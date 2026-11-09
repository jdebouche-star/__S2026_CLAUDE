//! egui front-end: spectrum + waterfall views, decoded-channel cards, spots.

mod waterfall;

use crate::engine::{Command, Engine};
use crate::skimmer::{Event, Skimmer, BIN_HZ, NR_BINS, SAMPLE_RATE, WIDE_POINTS};
use crate::source::IqSource;
use eframe::egui::{
    self, pos2, vec2, Align2, Color32, CornerRadius, FontId, Mesh, Rect, RichText, Sense, Shape,
    Stroke, StrokeKind,
};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use waterfall::{colormap, Waterfall};

const BG: Color32 = Color32::from_rgb(11, 14, 22);
const PANEL: Color32 = Color32::from_rgb(18, 23, 35);
const CARD: Color32 = Color32::from_rgb(22, 28, 42);
const AMBER: Color32 = Color32::from_rgb(255, 184, 64);
const CYAN: Color32 = Color32::from_rgb(70, 200, 240);
const GREEN: Color32 = Color32::from_rgb(110, 230, 140);
const DIM: Color32 = Color32::from_rgb(130, 142, 165);
const TEXT: Color32 = Color32::from_rgb(214, 222, 238);
const WATERFALL_ROWS: usize = 160;
/// Largest tuning offset from the stream centre that keeps all 48 bins inside the passband.
const MAX_OFFSET_HZ: f64 = SAMPLE_RATE as f64 / 2.0 - 3000.0;

#[derive(Default, Clone)]
struct Channel {
    text: String,
    wpm: i32,
    keyed: bool,
    level_db: f32,
    last_char: Option<Instant>,
}

struct Spot {
    call: String,
    freq_hz: f64,
    wpm: i32,
    utc: String,
}

pub struct SkimmerApp {
    engine: Engine,
    source_name: String,
    center_hz: f64,
    offset_hz: f64,
    step_hz: f64,
    bin_center: usize,
    bin_width: usize,
    min_snr: f32,
    paused: bool,
    hide_idle: bool,

    wide_db: Vec<f32>,
    wide_wf: Waterfall,
    wide_floor: f32,
    wide_range: f32,
    narrow_db: Vec<f32>,
    narrow_wf: Waterfall,
    narrow_lo: f32,
    narrow_hi: f32,
    channels: Vec<Channel>,
    spots: Vec<Spot>,
}

impl SkimmerApp {
    pub fn new(cc: &eframe::CreationContext<'_>, source: Box<dyn IqSource>, offset_hz: f64) -> Self {
        apply_theme(&cc.egui_ctx);
        let ctx = cc.egui_ctx.clone();
        let center_hz = source.center_hz();
        let source_name = source.name();
        let engine = Engine::spawn(source, offset_hz, move || ctx.request_repaint());
        engine.send(Command::SetBins { center: NR_BINS / 2, width: 7 });
        Self {
            engine,
            source_name,
            center_hz,
            offset_hz,
            step_hz: 100.0,
            bin_center: NR_BINS / 2,
            bin_width: 7,
            min_snr: 2.5,
            paused: false,
            hide_idle: true,
            wide_db: vec![-120.0; WIDE_POINTS],
            wide_wf: Waterfall::new("wide", WIDE_POINTS, WATERFALL_ROWS),
            wide_floor: -64.0,
            wide_range: 42.0,
            narrow_db: vec![-120.0; NR_BINS],
            narrow_wf: Waterfall::new("narrow", NR_BINS, WATERFALL_ROWS),
            narrow_lo: -60.0,
            narrow_hi: -20.0,
            channels: vec![Channel::default(); NR_BINS],
            spots: Vec::new(),
        }
    }

    fn tuned_hz(&self) -> f64 {
        self.center_hz + self.offset_hz
    }

    fn bin_freq(&self, k: usize) -> f64 {
        self.tuned_hz() + Skimmer::bin_offset_hz(k)
    }

    fn set_offset(&mut self, hz: f64) {
        self.offset_hz = hz.clamp(-MAX_OFFSET_HZ, MAX_OFFSET_HZ);
        self.engine.send(Command::SetOffset(self.offset_hz));
        self.clear_channels();
    }

    fn set_bins(&mut self, center: usize, width: usize) {
        self.bin_width = width.clamp(1, NR_BINS);
        self.bin_center = center.clamp(0, NR_BINS - 1);
        self.engine.send(Command::SetBins { center: self.bin_center, width: self.bin_width });
        let (lo, hi) = self.active_range();
        for (k, c) in self.channels.iter_mut().enumerate() {
            if k < lo || k > hi {
                *c = Channel::default();
            }
        }
    }

    fn active_range(&self) -> (usize, usize) {
        let w = self.bin_width;
        let lo = self.bin_center.saturating_sub(w / 2);
        let hi = if w % 2 == 1 { self.bin_center + w / 2 } else { self.bin_center + w / 2 - 1 };
        (lo, hi.min(NR_BINS - 1))
    }

    fn clear_channels(&mut self) {
        self.channels.iter_mut().for_each(|c| *c = Channel::default());
    }

    fn drain_events(&mut self) {
        while let Ok(batch) = self.engine.events.try_recv() {
            for ev in batch {
                match ev {
                    Event::Wide(db) => {
                        self.wide_db = db.clone();
                        self.wide_wf.push(db);
                    }
                    Event::Narrow { db, keyed } => {
                        let (mut lo, mut hi) = (f32::MAX, f32::MIN);
                        for &d in &db {
                            lo = lo.min(d);
                            hi = hi.max(d);
                        }
                        self.narrow_lo += 0.1 * (lo - self.narrow_lo);
                        self.narrow_hi += 0.1 * (hi - self.narrow_hi);
                        for (k, c) in self.channels.iter_mut().enumerate() {
                            c.level_db += 0.5 * (db[k] - c.level_db);
                            c.keyed = keyed[k];
                        }
                        self.narrow_wf.push(db.clone());
                        self.narrow_db = db;
                    }
                    Event::Char { channel, wpm, ch } => {
                        let c = &mut self.channels[channel];
                        c.wpm = wpm;
                        c.last_char = Some(Instant::now());
                        c.text.push(ch);
                        if c.text.len() > crate::decoder::TEXT_LENGTH {
                            c.text.remove(0);
                        }
                        if ch == ' ' {
                            // Only trust a call after "DE" or when it is sent twice in a row.
                            let mut toks = c.text.trim_end().rsplit(' ');
                            if let (Some(tok), prev) = (toks.next(), toks.next()) {
                                if looks_like_call(tok) && (prev == Some("DE") || prev == Some(tok)) {
                                    let tok = tok.to_string();
                                    self.add_spot(tok, channel, wpm);
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    fn add_spot(&mut self, call: String, channel: usize, wpm: i32) {
        let freq = self.bin_freq(channel);
        let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) % 86400;
        let utc = format!("{:02}:{:02}:{:02}", secs / 3600, secs / 60 % 60, secs % 60);
        if let Some(s) = self.spots.iter_mut().find(|s| s.call == call && (s.freq_hz - freq).abs() < 1000.0) {
            s.freq_hz = freq;
            s.utc = utc;
            s.wpm = wpm;
        } else {
            self.spots.insert(0, Spot { call, freq_hz: freq, wpm, utc });
            self.spots.truncate(200);
        }
    }

    // ------------------------------------------------------------------ UI

    fn header(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_centered(|ui| {
            ui.add_space(6.0);
            ui.label(RichText::new("CW SKIMMER").strong().size(15.0).color(CYAN));
            ui.add_space(14.0);
            let big = format!("{:.3}", self.tuned_hz() / 1000.0);
            ui.label(RichText::new(format!("{big} kHz")).monospace().size(26.0).color(AMBER));
            ui.add_space(8.0);
            if ui.button("−").clicked() {
                self.set_offset(self.offset_hz - self.step_hz);
            }
            if ui.button("+").clicked() {
                self.set_offset(self.offset_hz + self.step_hz);
            }
            egui::ComboBox::from_id_salt("step")
                .selected_text(format!("step {} Hz", self.step_hz))
                .show_ui(ui, |ui| {
                    for s in [10.0, 100.0, 500.0, 1000.0, 5000.0] {
                        ui.selectable_value(&mut self.step_hz, s, format!("{s} Hz"));
                    }
                });
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                ui.add_space(8.0);
                let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) % 86400;
                ui.label(
                    RichText::new(format!("{:02}:{:02}:{:02} UTC", secs / 3600, secs / 60 % 60, secs % 60))
                        .monospace()
                        .color(DIM),
                );
                ui.add_space(10.0);
                if ui.button("Clear").clicked() {
                    self.engine.send(Command::Reset);
                    self.clear_channels();
                    self.spots.clear();
                }
                let label = if self.paused { "▶ Resume" } else { "⏸ Pause" };
                if ui.button(label).clicked() {
                    self.paused = !self.paused;
                    self.engine.send(Command::Pause(self.paused));
                }
                ui.add_space(10.0);
                ui.label(RichText::new(&self.source_name).color(DIM));
            });
        });
    }

    /// 192 kHz view: spectrum on top of a waterfall. Click/drag to tune.
    fn wide_view(&mut self, ui: &mut egui::Ui, height: f32) {
        let (rect, resp) =
            ui.allocate_exact_size(vec2(ui.available_width(), height), Sense::click_and_drag());
        let painter = ui.painter_at(rect);
        painter.rect_filled(rect, CornerRadius::same(6), PANEL);
        let plot = Rect::from_min_max(rect.min + vec2(0.0, 0.0), pos2(rect.max.x, rect.min.y + height * 0.38));
        let wf = Rect::from_min_max(pos2(rect.min.x, plot.max.y), rect.max);

        let x_of = |hz: f64| rect.min.x + ((hz / SAMPLE_RATE as f64) + 0.5) as f32 * rect.width();
        let (floor, range) = (self.wide_floor, self.wide_range);
        // waterfall
        let tex = self.wide_wf.texture(ui.ctx(), floor, range);
        painter.image(tex, wf, Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)), Color32::WHITE);
        // spectrum
        draw_spectrum(&painter, plot, &self.wide_db, floor, floor + range, CYAN);
        // frequency grid (every 10 kHz)
        for k in -9..=9 {
            let hz = k as f64 * 10_000.0;
            let x = x_of(hz);
            painter.line_segment([pos2(x, plot.max.y - 5.0), pos2(x, plot.max.y)], Stroke::new(1.0_f32, DIM));
            if k % 2 == 0 {
                painter.text(
                    pos2(x + 2.0, plot.min.y + 2.0),
                    Align2::LEFT_TOP,
                    format!("{:.2}", (self.center_hz + hz) / 1e6),
                    FontId::monospace(10.0),
                    DIM,
                );
            }
        }
        // decoding band + cursor
        let (lo, hi) = self.active_range();
        let x0 = x_of(self.offset_hz + Skimmer::bin_offset_hz(lo) - BIN_HZ / 2.0);
        let x1 = x_of(self.offset_hz + Skimmer::bin_offset_hz(hi) + BIN_HZ / 2.0);
        let band = Rect::from_min_max(pos2(x0, rect.min.y), pos2(x1.max(x0 + 2.0), rect.max.y));
        painter.rect_filled(band, 0, Color32::from_rgba_unmultiplied(255, 184, 64, 36));
        let cx = x_of(self.offset_hz);
        painter.line_segment([pos2(cx, rect.min.y), pos2(cx, rect.max.y)], Stroke::new(1.5_f32, AMBER));

        if let Some(p) = resp.interact_pointer_pos() {
            if resp.clicked() || resp.dragged() {
                let hz = ((p.x - rect.min.x) / rect.width()) as f64 * SAMPLE_RATE as f64 - SAMPLE_RATE as f64 / 2.0;
                self.set_offset(hz);
            }
        }
        if resp.hovered() {
            let scroll = ui.input(|i| i.smooth_scroll_delta.y);
            if scroll != 0.0 {
                self.set_offset(self.offset_hz + self.step_hz * scroll.signum() as f64);
            }
            if let Some(p) = resp.hover_pos() {
                let hz = ((p.x - rect.min.x) / rect.width()) as f64 * SAMPLE_RATE as f64 - SAMPLE_RATE as f64 / 2.0;
                painter.text(
                    pos2(rect.max.x - 8.0, rect.max.y - 6.0),
                    Align2::RIGHT_BOTTOM,
                    format!("{:.3} kHz", (self.center_hz + hz) / 1000.0),
                    FontId::monospace(12.0),
                    TEXT,
                );
            }
        }
        painter.rect_stroke(rect, CornerRadius::same(6), Stroke::new(1.0_f32, Color32::from_gray(45)), StrokeKind::Inside);
    }

    /// 48-bin decoder view. Click to move the decoding window, scroll to resize it.
    fn narrow_view(&mut self, ui: &mut egui::Ui, height: f32) {
        let (rect, resp) =
            ui.allocate_exact_size(vec2(ui.available_width(), height), Sense::click_and_drag());
        let painter = ui.painter_at(rect);
        painter.rect_filled(rect, CornerRadius::same(6), PANEL);
        let bars = Rect::from_min_max(rect.min, pos2(rect.max.x, rect.min.y + height * 0.45));
        let wf = Rect::from_min_max(pos2(rect.min.x, bars.max.y), rect.max);
        let bw = rect.width() / NR_BINS as f32;
        let (lo_db, hi_db) = (self.narrow_lo + 3.0, self.narrow_hi.max(self.narrow_lo + 15.0));
        let tex = self.narrow_wf.texture(ui.ctx(), lo_db, hi_db - lo_db);
        painter.image(tex, wf, Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)), Color32::WHITE);

        let (lo, hi) = self.active_range();
        for k in 0..NR_BINS {
            let x = rect.min.x + k as f32 * bw;
            let active = k >= lo && k <= hi;
            let v = ((self.narrow_db.get(k).copied().unwrap_or(-120.0) - lo_db) / (hi_db - lo_db)).clamp(0.0, 1.0);
            let h = (bars.height() - 14.0) * v;
            let colour = if self.channels[k].keyed {
                AMBER
            } else if active {
                CYAN
            } else {
                Color32::from_gray(70)
            };
            let bar = Rect::from_min_max(pos2(x + 1.5, bars.max.y - h), pos2(x + bw - 1.5, bars.max.y));
            painter.rect_filled(bar, CornerRadius::same(2), colour);
            if active {
                painter.rect_filled(
                    Rect::from_min_max(pos2(x, bars.min.y), pos2(x + bw, bars.max.y)),
                    0,
                    Color32::from_rgba_unmultiplied(70, 200, 240, 14),
                );
            }
            if k % 6 == 0 {
                painter.text(
                    pos2(x + 2.0, bars.min.y + 2.0),
                    Align2::LEFT_TOP,
                    format!("{:.2}", self.bin_freq(k) / 1000.0),
                    FontId::monospace(10.0),
                    DIM,
                );
            }
        }
        // window markers on waterfall
        let x0 = rect.min.x + lo as f32 * bw;
        let x1 = rect.min.x + (hi + 1) as f32 * bw;
        painter.rect_stroke(
            Rect::from_min_max(pos2(x0, rect.min.y), pos2(x1, rect.max.y)),
            0,
            Stroke::new(1.0_f32, AMBER.gamma_multiply(0.7)),
            StrokeKind::Inside,
        );
        if resp.clicked() || resp.dragged() {
            if let Some(p) = resp.interact_pointer_pos() {
                let k = ((p.x - rect.min.x) / bw) as usize;
                self.set_bins(k.min(NR_BINS - 1), self.bin_width);
            }
        }
        if resp.hovered() {
            let scroll = ui.input(|i| i.smooth_scroll_delta.y);
            if scroll > 0.0 {
                self.set_bins(self.bin_center, self.bin_width + 1);
            } else if scroll < 0.0 {
                self.set_bins(self.bin_center, self.bin_width.saturating_sub(1).max(1));
            }
        }
        painter.rect_stroke(rect, CornerRadius::same(6), Stroke::new(1.0_f32, Color32::from_gray(45)), StrokeKind::Inside);
    }

    fn channel_cards(&mut self, ui: &mut egui::Ui) {
        let (lo, hi) = self.active_range();
        let groups = self.group_channels(lo, hi);
        if groups.is_empty() {
            ui.add_space(30.0);
            ui.vertical_centered(|ui| {
                ui.label(RichText::new("Listening… decoded stations appear here").color(DIM).size(15.0));
            });
            return;
        }
        let norm = |db: f32| ((db - (self.narrow_lo - 3.0)) / (self.narrow_hi - self.narrow_lo + 3.0).max(6.0)).clamp(0.0, 1.0);
        for (k, extra) in groups {
            let c = &self.channels[k];
            let fresh = c.last_char.map_or(false, |t| t.elapsed() < Duration::from_secs(6));
            egui::Frame::new()
                .fill(CARD)
                .corner_radius(CornerRadius::same(6))
                .inner_margin(egui::Margin::symmetric(10, 6))
                .stroke(Stroke::new(1.0_f32, if c.keyed { AMBER } else if fresh { CYAN.gamma_multiply(0.5) } else { Color32::from_gray(40) }))
                .show(ui, |ui| {
                    ui.set_width(ui.available_width());
                    ui.horizontal(|ui| {
                        let dot = if c.keyed { AMBER } else { Color32::from_gray(60) };
                        let (r, _) = ui.allocate_exact_size(vec2(10.0, 10.0), Sense::hover());
                        ui.painter().circle_filled(r.center(), 4.5, dot);
                        ui.label(RichText::new(format!("{:.2}", self.bin_freq(k) / 1000.0)).monospace().size(16.0).color(AMBER));
                        ui.label(RichText::new(format!("{:>2} wpm", c.wpm)).monospace().color(CYAN));
                        let (r, _) = ui.allocate_exact_size(vec2(48.0, 8.0), Sense::hover());
                        ui.painter().rect_filled(r, CornerRadius::same(3), Color32::from_gray(40));
                        let fill = Rect::from_min_size(r.min, vec2(r.width() * norm(c.level_db), r.height()));
                        ui.painter().rect_filled(fill, CornerRadius::same(3), colormap(0.35 + 0.6 * norm(c.level_db)));
                        if extra > 0 {
                            ui.label(RichText::new(format!("+{extra} bins")).small().color(DIM));
                        }
                        ui.add(egui::Label::new(styled_text(&c.text, fresh)).wrap());
                    });
                });
            ui.add_space(3.0);
        }
    }

    /// Collapse neighbouring bins that decode the same signal into one entry.
    fn group_channels(&self, lo: usize, hi: usize) -> Vec<(usize, usize)> {
        let mut groups: Vec<(usize, usize)> = Vec::new(); // (best bin, merged count)
        let mut last: Option<usize> = None;
        for k in lo..=hi {
            let c = &self.channels[k];
            if c.text.trim().is_empty() {
                if !self.hide_idle {
                    groups.push((k, 0));
                    last = None;
                }
                continue;
            }
            if let (Some(l), Some(g)) = (last, groups.last_mut()) {
                if k - l <= 2 && similar(&self.channels[g.0].text, &c.text) {
                    g.1 += 1;
                    if c.level_db > self.channels[g.0].level_db {
                        g.0 = k;
                    }
                    last = Some(k);
                    continue;
                }
            }
            groups.push((k, 0));
            last = Some(k);
        }
        groups
    }

    fn side_panel(&mut self, ui: &mut egui::Ui) {
        ui.add_space(6.0);
        ui.label(RichText::new("TUNING").strong().color(DIM).size(11.0));
        let mut khz = self.tuned_hz() / 1000.0;
        if ui
            .add(egui::DragValue::new(&mut khz).speed(0.05).fixed_decimals(3).suffix(" kHz"))
            .changed()
        {
            self.set_offset(khz * 1000.0 - self.center_hz);
        }
        ui.add_space(4.0);
        ui.label(RichText::new("DECODER").strong().color(DIM).size(11.0));
        let mut changed = false;
        let (mut centre, mut width) = (self.bin_center, self.bin_width);
        changed |= ui.add(egui::Slider::new(&mut centre, 0..=NR_BINS - 1).text("centre bin")).changed();
        changed |= ui.add(egui::Slider::new(&mut width, 1..=NR_BINS).text("width")).changed();
        if changed {
            self.set_bins(centre, width);
        }
        if ui.add(egui::Slider::new(&mut self.min_snr, 0.0..=8.0).text("squelch ×")).changed() {
            self.engine.send(Command::SetMinSnr(self.min_snr));
        }
        ui.checkbox(&mut self.hide_idle, "hide silent channels");
        ui.add_space(4.0);
        ui.label(RichText::new("DISPLAY").strong().color(DIM).size(11.0));
        let a = ui.add(egui::Slider::new(&mut self.wide_floor, -120.0..=-20.0).text("floor dB")).changed();
        let b = ui.add(egui::Slider::new(&mut self.wide_range, 20.0..=100.0).text("range dB")).changed();
        if a || b {
            self.wide_wf.invalidate();
        }
        ui.add_space(8.0);
        ui.separator();
        ui.label(RichText::new("SPOTS").strong().color(DIM).size(11.0));
        egui::ScrollArea::vertical().auto_shrink(false).show(ui, |ui| {
            let mut tune_to = None;
            for s in &self.spots {
                let r = ui
                    .horizontal(|ui| {
                        ui.label(RichText::new(&s.utc).monospace().size(11.0).color(DIM));
                        ui.label(RichText::new(&s.call).monospace().strong().color(GREEN));
                        ui.label(RichText::new(format!("{:.1}", s.freq_hz / 1000.0)).monospace().color(AMBER));
                    })
                    .response
                    .interact(Sense::click());
                if r.on_hover_text(format!("{} wpm — click to tune", s.wpm)).clicked() {
                    tune_to = Some(s.freq_hz);
                }
            }
            if let Some(f) = tune_to {
                self.set_offset(f - self.center_hz);
            }
            if self.spots.is_empty() {
                ui.label(RichText::new("callsigns will be listed here").color(DIM));
            }
        });
    }
}

impl eframe::App for SkimmerApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.drain_events();
        egui::TopBottomPanel::top("header")
            .exact_height(46.0)
            .frame(egui::Frame::new().fill(PANEL).inner_margin(egui::Margin::symmetric(6, 0)))
            .show(ctx, |ui| self.header(ui));
        egui::SidePanel::right("side")
            .exact_width(290.0)
            .frame(egui::Frame::new().fill(PANEL).inner_margin(egui::Margin::same(10)))
            .show(ctx, |ui| self.side_panel(ui));
        egui::CentralPanel::default()
            .frame(egui::Frame::new().fill(BG).inner_margin(egui::Margin::same(10)))
            .show(ctx, |ui| {
                let h = ui.available_height();
                self.wide_view(ui, (h * 0.30).clamp(150.0, 320.0));
                ui.add_space(8.0);
                self.narrow_view(ui, (h * 0.22).clamp(110.0, 220.0));
                ui.add_space(8.0);
                egui::ScrollArea::vertical().auto_shrink(false).show(ui, |ui| self.channel_cards(ui));
            });
        ctx.request_repaint_after(Duration::from_millis(250)); // clock + stale highlights
    }
}

// ----------------------------------------------------------------- helpers

fn apply_theme(ctx: &egui::Context) {
    let mut v = egui::Visuals::dark();
    v.panel_fill = BG;
    v.window_fill = PANEL;
    v.override_text_color = Some(TEXT);
    v.widgets.noninteractive.bg_stroke = Stroke::new(1.0_f32, Color32::from_gray(40));
    v.selection.bg_fill = CYAN.gamma_multiply(0.45);
    let r = CornerRadius::same(5);
    v.widgets.inactive.corner_radius = r;
    v.widgets.hovered.corner_radius = r;
    v.widgets.active.corner_radius = r;
    ctx.set_visuals(v);
    ctx.style_mut(|s| s.spacing.item_spacing = vec2(8.0, 5.0));
}

fn draw_spectrum(p: &egui::Painter, r: Rect, db: &[f32], lo: f32, hi: f32, colour: Color32) {
    if db.len() < 2 {
        return;
    }
    let n = db.len();
    let pts: Vec<_> = db
        .iter()
        .enumerate()
        .map(|(i, &v)| {
            let x = r.min.x + r.width() * i as f32 / (n - 1) as f32;
            let y = r.max.y - r.height() * ((v - lo) / (hi - lo)).clamp(0.0, 1.0);
            pos2(x, y)
        })
        .collect();
    let mut mesh = Mesh::default();
    let fill = colour.gamma_multiply(0.16);
    for (i, pt) in pts.iter().enumerate() {
        mesh.colored_vertex(*pt, fill);
        mesh.colored_vertex(pos2(pt.x, r.max.y), Color32::TRANSPARENT);
        if i > 0 {
            let b = (2 * i) as u32;
            mesh.add_triangle(b - 2, b - 1, b);
            mesh.add_triangle(b - 1, b + 1, b);
        }
    }
    p.add(Shape::mesh(mesh));
    p.add(Shape::line(pts, Stroke::new(1.2_f32, colour)));
}

/// Callsign-ish token: 1–3 alnum prefix ending in a digit, then 1–4 letters.
fn looks_like_call(tok: &str) -> bool {
    let b = tok.as_bytes();
    if b.len() < 4 || b.len() > 7 || !b.iter().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit()) {
        return false;
    }
    let Some(d) = b.iter().rposition(|c| c.is_ascii_digit()) else { return false };
    let tail = &b[d + 1..];
    d >= 1 && d <= 3 && (1..=4).contains(&tail.len()) && tail.iter().all(|c| c.is_ascii_uppercase())
}

/// Do two decoded strings look like the same transmission? True when the
/// tail of one shares an 8-character run with the other.
fn similar(a: &str, b: &str) -> bool {
    const RUN: usize = 8;
    if a.len() < RUN || b.len() < RUN {
        return false;
    }
    let tail = &a[a.len().saturating_sub(40)..];
    (0..=tail.len() - RUN).any(|i| tail.is_char_boundary(i) && tail.is_char_boundary(i + RUN) && b.contains(&tail[i..i + RUN]))
}

fn styled_text(text: &str, fresh: bool) -> egui::text::LayoutJob {
    use egui::text::{LayoutJob, TextFormat};
    let font = FontId::monospace(15.0);
    let base = if fresh { TEXT } else { DIM };
    let mut job = LayoutJob::default();
    let n = text.split(' ').count();
    for (i, tok) in text.split(' ').enumerate() {
        let colour = if looks_like_call(tok) {
            GREEN
        } else if matches!(tok, "CQ" | "DE" | "TEST" | "QRZ" | "K" | "TU" | "73") {
            CYAN
        } else {
            base
        };
        let fmt = TextFormat { font_id: font.clone(), color: colour, ..Default::default() };
        job.append(tok, 0.0, fmt.clone());
        if i + 1 < n {
            job.append(" ", 0.0, fmt);
        }
    }
    job
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn calls() {
        for c in ["K1ABC", "DL1ABC", "W7UT", "JA1QRP", "F5GHI", "OH2BH", "9A1A"] {
            assert!(looks_like_call(c), "{c}");
        }
        for c in ["5NN", "599", "CQ", "TEST", "TU", "DE", "1ABC"] {
            assert!(!looks_like_call(c), "{c}");
        }
    }
}
