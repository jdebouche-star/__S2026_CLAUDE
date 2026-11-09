//! Spectrum front-end: slices 192 kHz IQ into 2 ms frames, takes a 2048-point
//! FFT of each and feeds 48 bins around the tuned frequency to the decoders.

use crate::decoder::ChannelDecoder;
use rustfft::{num_complex::Complex32, Fft, FftPlanner};
use std::f64::consts::TAU;
use std::sync::Arc;

pub const SAMPLE_RATE: u32 = 192_000;
pub const FFT_SIZE: usize = 2048;
pub const NR_BINS: usize = 48;
/// New samples consumed per frame (2 ms => 500 frames/s).
pub const FRAME_SAMPLES: usize = 384;
/// Spacing between decoder bins in Hz.
pub const BIN_HZ: f64 = SAMPLE_RATE as f64 / FFT_SIZE as f64;
/// Wide spectrum is refreshed every this many frames (20 ms).
const WIDE_EVERY: u32 = 10;
/// Narrow spectrum is refreshed every this many frames (100 ms).
const NARROW_EVERY: u32 = 50;
/// Number of points in the wide spectrum event.
pub const WIDE_POINTS: usize = FFT_SIZE / 2;

/// Something the engine tells the outside world.
#[derive(Clone, Debug)]
pub enum Event {
    /// Wide (full 192 kHz) spectrum in dB, left = -96 kHz, right = +96 kHz,
    /// relative to the device centre frequency.
    Wide(Vec<f32>),
    /// The 48 decoder bins in dB plus which of them are currently keyed.
    Narrow { db: Vec<f32>, keyed: Vec<bool> },
    /// A character decoded on `channel`.
    Char { channel: usize, wpm: i32, ch: char },
}

pub struct Skimmer {
    fft: Arc<dyn Fft<f32>>,
    scratch: Vec<Complex32>,
    pending: Vec<Complex32>,
    history: Vec<Complex32>, // last FFT_SIZE raw samples, for the wide view
    hist_pos: usize,
    hann: Vec<f32>,
    phase: f64,
    offset_hz: f64,
    decoders: Vec<ChannelDecoder>,
    low: usize,
    high: usize, // inclusive
    center_bin: usize,
    width: usize,
    noise: f32,
    frames: u32,
    last_mags: [f32; NR_BINS],
    min_snr: f32,
}

impl Default for Skimmer {
    fn default() -> Self {
        Self::new()
    }
}

impl Skimmer {
    pub fn new() -> Self {
        let mut planner = FftPlanner::new();
        let fft = planner.plan_fft_forward(FFT_SIZE);
        let hann = (0..FFT_SIZE)
            .map(|i| 0.5 - 0.5 * (std::f32::consts::TAU * i as f32 / FFT_SIZE as f32).cos())
            .collect();
        let mut s = Self {
            scratch: vec![Complex32::new(0.0, 0.0); fft.get_inplace_scratch_len()],
            fft,
            pending: Vec::with_capacity(FRAME_SAMPLES * 4),
            history: vec![Complex32::new(0.0, 0.0); FFT_SIZE],
            hist_pos: 0,
            hann,
            phase: 0.0,
            offset_hz: 0.0,
            decoders: vec![ChannelDecoder::new(); NR_BINS],
            low: 0,
            high: 0,
            center_bin: NR_BINS / 2,
            width: 5,
            noise: 0.0,
            frames: 0,
            last_mags: [0.0; NR_BINS],
            min_snr: 2.5,
        };
        s.set_bins(NR_BINS / 2, 5);
        s.set_min_snr(2.5);
        s
    }

    /// Choose which bins are decoded: `width` bins around `center`.
    pub fn set_bins(&mut self, center: usize, width: usize) {
        let width = width.clamp(1, NR_BINS);
        let center = center.clamp(0, NR_BINS - 1);
        let low = center.saturating_sub(width / 2);
        let high = if width % 2 == 1 { center + width / 2 } else { center + width / 2 - 1 }
            .min(NR_BINS - 1);
        for i in self.low..=self.high {
            if i < low || i > high {
                self.decoders[i].reset();
            }
        }
        self.center_bin = center;
        self.width = width;
        self.low = low;
        self.high = high;
    }

    pub fn bins(&self) -> (usize, usize) {
        (self.center_bin, self.width)
    }

    /// Decoded bin range (inclusive).
    pub fn active_range(&self) -> (usize, usize) {
        (self.low, self.high)
    }

    /// Squelch: tones must be this many times above the noise floor (0 = off).
    pub fn set_min_snr(&mut self, snr: f32) {
        self.min_snr = snr;
        for d in &mut self.decoders {
            d.min_snr = snr;
        }
    }

    /// Tuned frequency as an offset from the IQ stream's centre frequency.
    pub fn set_offset_hz(&mut self, hz: f64) {
        self.offset_hz = hz;
        self.reset();
    }

    pub fn offset_hz(&self) -> f64 {
        self.offset_hz
    }

    /// Clear all decoders.
    pub fn reset(&mut self) {
        for d in &mut self.decoders {
            d.reset();
        }
    }

    /// Frequency offset (Hz, relative to the tuned frequency) of bin `k`.
    pub fn bin_offset_hz(k: usize) -> f64 {
        (k as f64 - (NR_BINS / 2) as f64) * BIN_HZ
    }

    /// Estimated speed of the decoder behind bin `k`.
    pub fn wpm(&self, k: usize) -> i32 {
        self.decoders[k].wpm()
    }

    /// Feed IQ samples; events are appended to `events`.
    pub fn push(&mut self, samples: &[Complex32], events: &mut Vec<Event>) {
        // Raw copy for the wide spectrum.
        for &s in samples {
            self.history[self.hist_pos] = s;
            self.hist_pos = (self.hist_pos + 1) % FFT_SIZE;
        }
        // Mix the tuned frequency down to DC.
        let step = -TAU * self.offset_hz / SAMPLE_RATE as f64;
        for &s in samples {
            let (sin, cos) = self.phase.sin_cos();
            self.pending.push(s * Complex32::new(cos as f32, sin as f32));
            self.phase += step;
            if self.phase > TAU || self.phase < -TAU {
                self.phase %= TAU;
            }
        }
        let mut consumed = 0;
        while self.pending.len() - consumed >= FRAME_SAMPLES {
            let frame: Vec<Complex32> = self.pending[consumed..consumed + FRAME_SAMPLES].to_vec();
            consumed += FRAME_SAMPLES;
            self.frame(&frame, events);
        }
        self.pending.drain(..consumed);
    }

    fn frame(&mut self, frame: &[Complex32], events: &mut Vec<Event>) {
        let mut buf = vec![Complex32::new(0.0, 0.0); FFT_SIZE];
        buf[..FRAME_SAMPLES].copy_from_slice(frame);
        self.fft.process_with_scratch(&mut buf, &mut self.scratch);

        // 48 bins centred on DC.
        let mut mags = [0.0f32; NR_BINS];
        for (k, m) in mags.iter_mut().enumerate() {
            *m = buf[(FFT_SIZE - NR_BINS / 2 + k) % FFT_SIZE].norm();
        }
        self.last_mags = mags;

        // Noise floor = median of the bins (signals occupy a minority).
        let mut sorted = mags;
        sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let median = sorted[NR_BINS / 2];
        self.noise = 0.99 * self.noise + 0.01 * median;

        let mut chars = Vec::new();
        for k in self.low..=self.high {
            chars.clear();
            self.decoders[k].process(mags[k], self.noise, &mut chars);
            let wpm = self.decoders[k].wpm();
            for &ch in &chars {
                events.push(Event::Char { channel: k, wpm, ch });
            }
        }

        self.frames += 1;
        if self.frames % WIDE_EVERY == 0 {
            events.push(Event::Wide(self.wide_spectrum()));
        }
        if self.frames % NARROW_EVERY == 0 {
            let db = mags.iter().map(|&m| to_db(m / FRAME_SAMPLES as f32)).collect();
            let keyed = (0..NR_BINS)
                .map(|k| k >= self.low && k <= self.high && self.decoders[k].keyed())
                .collect();
            events.push(Event::Narrow { db, keyed });
        }
    }

    /// Windowed full-resolution spectrum of the last 2048 raw samples.
    fn wide_spectrum(&mut self) -> Vec<f32> {
        let mut buf: Vec<Complex32> = (0..FFT_SIZE)
            .map(|i| self.history[(self.hist_pos + i) % FFT_SIZE] * self.hann[i])
            .collect();
        self.fft.process_with_scratch(&mut buf, &mut self.scratch);
        let norm = FFT_SIZE as f32 / 2.0;
        // fftshift, then max-pool pairs down to WIDE_POINTS.
        let shifted = |i: usize| buf[(i + FFT_SIZE / 2) % FFT_SIZE].norm() / norm;
        (0..WIDE_POINTS)
            .map(|i| to_db(shifted(2 * i).max(shifted(2 * i + 1))))
            .collect()
    }
}

pub fn to_db(x: f32) -> f32 {
    20.0 * (x + 1e-9).log10()
}
