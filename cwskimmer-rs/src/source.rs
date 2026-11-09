//! IQ sample sources: WAV recordings and a synthetic CW band.
//!
//! Real SDR back-ends can be added by implementing [`IqSource`].

use crate::morse;
use crate::skimmer::SAMPLE_RATE;
use rand::{rngs::StdRng, Rng, SeedableRng};
use rustfft::num_complex::Complex32;

pub trait IqSource: Send {
    /// Fill `out` with samples; returns how many were written (0 = end).
    fn read(&mut self, out: &mut [Complex32]) -> usize;
    /// Short description for the UI.
    fn name(&self) -> String;
    /// Centre frequency of the stream in Hz.
    fn center_hz(&self) -> f64;
    /// Whether the engine should pace reads to real time.
    fn realtime(&self) -> bool {
        true
    }
}

// ---------------------------------------------------------------- WAV file

/// Stereo (I/Q) WAV file at 192 kHz, 16-bit int or 32-bit float.
pub struct WavSource {
    samples: Vec<Complex32>,
    pos: usize,
    center: f64,
    name: String,
    looping: bool,
}

impl WavSource {
    pub fn open(path: &str, center_hz: f64, looping: bool) -> Result<Self, String> {
        let mut reader = hound::WavReader::open(path).map_err(|e| format!("{path}: {e}"))?;
        let spec = reader.spec();
        if spec.channels != 2 {
            return Err(format!("{path}: need a 2-channel (I/Q) WAV, got {} channel(s)", spec.channels));
        }
        if spec.sample_rate != SAMPLE_RATE {
            return Err(format!("{path}: need {SAMPLE_RATE} Hz, got {} Hz", spec.sample_rate));
        }
        let flat: Vec<f32> = match spec.sample_format {
            hound::SampleFormat::Float => {
                reader.samples::<f32>().collect::<Result<_, _>>().map_err(|e| e.to_string())?
            }
            hound::SampleFormat::Int => {
                let scale = 1.0 / (1u64 << (spec.bits_per_sample - 1)) as f32;
                reader
                    .samples::<i32>()
                    .map(|s| s.map(|v| v as f32 * scale))
                    .collect::<Result<_, _>>()
                    .map_err(|e| e.to_string())?
            }
        };
        let samples = flat.chunks_exact(2).map(|c| Complex32::new(c[0], c[1])).collect();
        Ok(Self {
            samples,
            pos: 0,
            center: center_hz,
            name: path.rsplit('/').next().unwrap_or(path).to_string(),
            looping,
        })
    }
}

impl IqSource for WavSource {
    fn read(&mut self, out: &mut [Complex32]) -> usize {
        let mut n = 0;
        while n < out.len() {
            if self.pos >= self.samples.len() {
                if self.looping && !self.samples.is_empty() {
                    self.pos = 0;
                } else {
                    break;
                }
            }
            let take = (out.len() - n).min(self.samples.len() - self.pos);
            out[n..n + take].copy_from_slice(&self.samples[self.pos..self.pos + take]);
            self.pos += take;
            n += take;
        }
        n
    }
    fn name(&self) -> String {
        format!("file: {}", self.name)
    }
    fn center_hz(&self) -> f64 {
        self.center
    }
}

// ------------------------------------------------------------ synthetic band

/// A keyed carrier sending a repeating message.
struct Station {
    offset_hz: f64,
    amp: f32,
    wpm: f32,
    phase: f64,
    /// Remaining on/off segments, in samples; `true` = key down.
    plan: Vec<(bool, usize)>,
    idx: usize,
    left: usize,
    env: f32,
    qsb_phase: f32,
    qsb_rate: f32,
    messages: Vec<String>,
    next_msg: usize,
}

const CALLS: &[&str] = &[
    "DL1ABC", "K1XYZ", "G4DEF", "JA1QRP", "F5GHI", "OH2BH", "VK3ABC", "SM5ZZ", "PA3XYZ", "EA8TT",
    "I2WIN", "W7UT", "UA9CC", "HB9AA", "ON4KST",
];

impl Station {
    fn new(rng: &mut StdRng, offset_hz: f64, amp: f32, wpm: f32) -> Self {
        let mut messages = Vec::new();
        for _ in 0..4 {
            let a = CALLS[rng.gen_range(0..CALLS.len())];
            let b = CALLS[rng.gen_range(0..CALLS.len())];
            messages.push(match rng.gen_range(0..3) {
                0 => format!("CQ CQ CQ DE {a} {a} K"),
                1 => format!("{b} DE {a} 599 5NN TU"),
                _ => format!("CQ TEST DE {a} {a} TEST"),
            });
        }
        let mut s = Self {
            offset_hz,
            amp,
            wpm,
            phase: rng.gen::<f64>() * std::f64::consts::TAU,
            plan: Vec::new(),
            idx: 0,
            left: 0,
            env: 0.0,
            qsb_phase: rng.gen::<f32>() * 6.28,
            qsb_rate: rng.gen_range(0.05..0.3),
            messages,
            next_msg: rng.gen_range(0..4),
        };
        s.load_message();
        s
    }

    fn load_message(&mut self) {
        let unit = (1.2 / self.wpm as f64 * SAMPLE_RATE as f64) as usize;
        let text = self.messages[self.next_msg % self.messages.len()].clone();
        self.next_msg += 1;
        let mut plan = Vec::new();
        for (wi, word) in text.split(' ').enumerate() {
            if wi > 0 {
                plan.push((false, 7 * unit));
            }
            for (ci, c) in word.chars().enumerate() {
                if ci > 0 {
                    plan.push((false, 3 * unit));
                }
                let pat = morse::pattern(c).unwrap_or("");
                for (ei, e) in pat.chars().enumerate() {
                    if ei > 0 {
                        plan.push((false, unit));
                    }
                    plan.push((true, if e == '.' { unit } else { 3 * unit }));
                }
            }
        }
        plan.push((false, 20 * unit)); // pause between transmissions
        self.plan = plan;
        self.idx = 0;
        self.left = self.plan[0].1;
    }

    /// Advance one sample; returns the (real) key envelope.
    fn step(&mut self, alpha: f32) -> f32 {
        if self.left == 0 {
            self.idx += 1;
            if self.idx >= self.plan.len() {
                self.load_message();
            } else {
                self.left = self.plan[self.idx].1;
            }
        }
        self.left = self.left.saturating_sub(1);
        let target = if self.plan[self.idx].0 { 1.0 } else { 0.0 };
        self.env += (target - self.env) * alpha;
        self.env
    }
}

/// A fake 192 kHz slice of the CW band: several stations with noise and QSB.
pub struct SynthSource {
    rng: StdRng,
    stations: Vec<Station>,
    center: f64,
    noise: f32,
    alpha: f32,
    t: u64,
}

impl SynthSource {
    pub fn new(center_hz: f64, seed: u64) -> Self {
        let mut rng = StdRng::seed_from_u64(seed);
        // offsets relative to the centre; the first few sit inside the default
        // 4.5 kHz decoding window, the rest are spread over the 192 kHz view.
        let layout: &[(f64, f32, f32)] = &[
            (-1750.0, 0.22, 18.0),
            (-650.0, 0.12, 24.0),
            (350.0, 0.30, 21.0),
            (1450.0, 0.16, 15.0),
            (-9800.0, 0.25, 22.0),
            (-4300.0, 0.14, 26.0),
            (3900.0, 0.18, 17.0),
            (7300.0, 0.28, 20.0),
            (15200.0, 0.12, 19.0),
            (-23400.0, 0.20, 23.0),
            (41800.0, 0.35, 25.0),
            (-61000.0, 0.15, 16.0),
            (78500.0, 0.22, 28.0),
        ];
        let stations = layout
            .iter()
            .map(|&(o, a, w)| Station::new(&mut rng, o, a, w))
            .collect();
        Self {
            rng,
            stations,
            center: center_hz,
            noise: 0.05,
            alpha: 1.0 - (-1.0 / (0.002 * SAMPLE_RATE as f32)).exp(),
            t: 0,
        }
    }

    fn gauss(&mut self) -> f32 {
        let u1: f32 = self.rng.gen::<f32>().max(1e-12);
        let u2: f32 = self.rng.gen();
        (-2.0 * u1.ln()).sqrt() * (std::f32::consts::TAU * u2).cos()
    }
}

impl IqSource for SynthSource {
    fn read(&mut self, out: &mut [Complex32]) -> usize {
        let dt = 1.0 / SAMPLE_RATE as f32;
        for o in out.iter_mut() {
            let mut acc = Complex32::new(self.gauss() * self.noise, self.gauss() * self.noise);
            let tt = self.t as f32 * dt;
            for s in &mut self.stations {
                let env = s.step(self.alpha);
                if env < 1e-4 {
                    s.phase += std::f64::consts::TAU * s.offset_hz * dt as f64;
                    continue;
                }
                let qsb = 0.65 + 0.35 * (s.qsb_rate * tt * 6.28 + s.qsb_phase).sin();
                let a = s.amp * env * qsb;
                acc += Complex32::new(s.phase.cos() as f32, s.phase.sin() as f32) * a;
                s.phase += std::f64::consts::TAU * s.offset_hz * dt as f64;
                if s.phase > std::f64::consts::TAU {
                    s.phase -= std::f64::consts::TAU;
                }
            }
            *o = acc;
            self.t += 1;
        }
        out.len()
    }
    fn name(&self) -> String {
        "demo: synthetic CW band".into()
    }
    fn center_hz(&self) -> f64 {
        self.center
    }
}
