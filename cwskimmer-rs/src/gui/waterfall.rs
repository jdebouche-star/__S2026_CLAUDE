//! Scrolling waterfall rendered into an egui texture.

use eframe::egui::{self, Color32, ColorImage, TextureHandle, TextureOptions};
use std::collections::VecDeque;

pub struct Waterfall {
    name: &'static str,
    width: usize,
    height: usize,
    rows: VecDeque<Vec<f32>>, // newest first, values in dB
    texture: Option<TextureHandle>,
    dirty: bool,
}

/// Dark-blue -> cyan -> yellow -> red -> white colour ramp for t in 0..=1.
pub fn colormap(t: f32) -> Color32 {
    const STOPS: [(f32, [u8; 3]); 6] = [
        (0.00, [4, 6, 20]),
        (0.20, [14, 30, 110]),
        (0.45, [0, 150, 200]),
        (0.65, [90, 220, 140]),
        (0.82, [255, 220, 60]),
        (1.00, [255, 70, 40]),
    ];
    let t = t.clamp(0.0, 1.0);
    for w in STOPS.windows(2) {
        let (t0, c0) = w[0];
        let (t1, c1) = w[1];
        if t <= t1 {
            let f = (t - t0) / (t1 - t0);
            let l = |a: u8, b: u8| (a as f32 + (b as f32 - a as f32) * f) as u8;
            return Color32::from_rgb(l(c0[0], c1[0]), l(c0[1], c1[1]), l(c0[2], c1[2]));
        }
    }
    Color32::WHITE
}

impl Waterfall {
    pub fn new(name: &'static str, width: usize, height: usize) -> Self {
        Self { name, width, height, rows: VecDeque::new(), texture: None, dirty: true }
    }

    pub fn push(&mut self, row: Vec<f32>) {
        self.rows.push_front(row);
        self.rows.truncate(self.height);
        self.dirty = true;
    }

    /// Mark for re-render (e.g. after the level sliders changed).
    pub fn invalidate(&mut self) {
        self.dirty = true;
    }

    pub fn texture(&mut self, ctx: &egui::Context, floor: f32, range: f32) -> egui::TextureId {
        if self.dirty || self.texture.is_none() {
            let mut img = ColorImage::new([self.width, self.height], Color32::from_rgb(4, 6, 20));
            for (y, row) in self.rows.iter().enumerate() {
                for (x, &v) in row.iter().take(self.width).enumerate() {
                    img.pixels[y * self.width + x] = colormap((v - floor) / range);
                }
            }
            match &mut self.texture {
                Some(t) => t.set(img, TextureOptions::LINEAR),
                None => self.texture = Some(ctx.load_texture(self.name, img, TextureOptions::LINEAR)),
            }
            self.dirty = false;
        }
        self.texture.as_ref().unwrap().id()
    }
}
