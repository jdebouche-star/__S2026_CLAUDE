//! Per-channel on/off-keying CW decoder (port of `elementHandler`).
//!
//! The decoder is fed one magnitude sample per spectrum frame (500/s, i.e.
//! 2 ms per sample). Tones and spaces are measured in frames, queued, and
//! once 14 elements are available the shortest space is taken as the dit
//! length and a letter is cut out at the first long space.

use crate::morse;

/// Frames per second delivered to each decoder.
pub const FRAME_RATE: f32 = 500.0;
const QUEUE_LENGTH: usize = 32;
const SEARCH_LENGTH: usize = 14;
/// A PARIS "bit" lasts 1.2 s at 1 wpm = 600 frames.
const PARIS_FRAMES: i32 = 600;
/// A gap longer than this many dits is a word break. (Upstream uses 3, which
/// equals a letter gap, so it inserts spurious spaces; 5 sits between 3 and 7.)
const WORD_GAP: f32 = 5.0;
/// Number of characters of text kept per channel.
pub const TEXT_LENGTH: usize = 75;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum State {
    Idle,
    Tone,
    Space,
}

/// Small moving-average filter.
#[derive(Clone)]
struct MovingAverage {
    buf: [f32; 5],
    pos: usize,
}

impl MovingAverage {
    fn new() -> Self {
        Self { buf: [0.0; 5], pos: 0 }
    }
    fn filter(&mut self, v: f32) -> f32 {
        self.buf[self.pos] = v;
        self.pos = (self.pos + 1) % self.buf.len();
        self.buf.iter().sum::<f32>() / self.buf.len() as f32
    }
}

fn decaying_average(old: f32, input: f32, weight: f32) -> f32 {
    if weight <= 1.0 {
        input
    } else {
        input / weight + old * (1.0 - 1.0 / weight)
    }
}

#[derive(Clone)]
pub struct ChannelDecoder {
    smooth: MovingAverage,
    agc_peak: f32,
    starter: u32,
    state: State,
    now: i32,
    start: i32,
    queue: [i32; QUEUE_LENGTH],
    filler: usize,
    empty: usize,
    wpm: i32,
    text: String,
    /// Minimum tone level relative to the noise floor (0 disables squelch).
    pub min_snr: f32,
}

impl Default for ChannelDecoder {
    fn default() -> Self {
        Self::new()
    }
}

impl ChannelDecoder {
    pub fn new() -> Self {
        Self {
            smooth: MovingAverage::new(),
            agc_peak: 0.0,
            starter: 0,
            state: State::Idle,
            now: 0,
            start: 0,
            queue: [0; QUEUE_LENGTH],
            filler: 0,
            empty: 0,
            wpm: 0,
            text: String::new(),
            min_snr: 0.0,
        }
    }

    /// Forget all timing state and decoded text.
    pub fn reset(&mut self) {
        let min_snr = self.min_snr;
        *self = Self::new();
        self.min_snr = min_snr;
    }

    /// Is a tone currently detected?
    pub fn keyed(&self) -> bool {
        self.state == State::Tone
    }

    /// Estimated speed in words per minute (0 if unknown).
    pub fn wpm(&self) -> i32 {
        self.wpm
    }

    /// Decoded text (last [`TEXT_LENGTH`] characters).
    pub fn text(&self) -> &str {
        &self.text
    }

    /// Feed one magnitude sample; decoded characters are appended to `out`.
    /// `noise` is the current noise-floor estimate used for squelch.
    pub fn process(&mut self, raw: f32, noise: f32, out: &mut Vec<char>) {
        if raw > self.agc_peak {
            self.agc_peak = decaying_average(self.agc_peak, raw, 50.0);
        } else {
            self.agc_peak = decaying_average(self.agc_peak, raw, 500.0);
        }
        let value = self.smooth.filter(raw);
        if self.starter < 100 {
            self.starter += 1;
            return;
        }
        self.now += 1;
        let squelched = self.min_snr > 0.0 && value < self.min_snr * noise;

        match self.state {
            State::Idle => {
                if value > 0.77 * self.agc_peak && !squelched {
                    self.start = self.now;
                    self.state = State::Tone;
                }
            }
            State::Tone => {
                if value < 0.43 * self.agc_peak {
                    let duration = self.now - self.start;
                    if duration < 3 {
                        return; // spike (stays in Tone, like the original)
                    }
                    self.state = State::Space;
                    self.start = self.now;
                    self.add(duration, true, out);
                }
            }
            State::Space => {
                if value > 0.67 * self.agc_peak && !squelched {
                    let duration = self.now - self.start;
                    if duration < 4 {
                        return; // noise
                    }
                    self.state = State::Tone;
                    self.start = self.now;
                    self.add(duration, false, out);
                }
            }
        }
    }

    fn at(&self, i: usize) -> i32 {
        self.queue[(self.empty + i) % QUEUE_LENGTH]
    }

    fn advance(&mut self, n: usize) {
        self.empty = (self.empty + n) % QUEUE_LENGTH;
    }

    /// Queue a tone (positive) or space (negative) duration and try to cut a
    /// letter out of the queue.
    fn add(&mut self, duration: i32, is_tone: bool, out: &mut Vec<char>) {
        self.queue[self.filler] = if is_tone { duration } else { -duration };
        self.filler = (self.filler + 1) % QUEUE_LENGTH;
        let elems = (self.filler + QUEUE_LENGTH - self.empty) % QUEUE_LENGTH;
        if elems < SEARCH_LENGTH {
            return;
        }

        // Guess the dit length from the shortest space.
        let (mut min_space, mut max_space) = (i32::MAX, 0);
        for i in 0..SEARCH_LENGTH {
            let v = self.at(i);
            if v < 0 {
                min_space = min_space.min(-v);
                max_space = max_space.max(-v);
            }
        }
        if max_space == 0 || 2 * min_space > max_space {
            self.advance(2);
            return;
        }
        self.wpm = PARIS_FRAMES / min_space;
        if !(5..=40).contains(&self.wpm) {
            self.advance(2);
            return;
        }

        // A symbol has at most 6 dit/dah elements; look for the long gap.
        for i in 0..6 {
            let space = -self.at(2 * i + 1);
            if space > 2 * min_space {
                let pattern: String = (0..=i)
                    .map(|j| {
                        if self.at(2 * j) as f32 > 1.5 * min_space as f32 {
                            '_'
                        } else {
                            '.'
                        }
                    })
                    .collect();
                self.push_char(morse::lookup(&pattern).unwrap_or('*'), out);
                if space as f32 > WORD_GAP * min_space as f32 {
                    self.push_char(' ', out);
                }
                self.advance(2 * i + 2);
                return;
            }
        }
        self.advance(2);
    }

    fn push_char(&mut self, c: char, out: &mut Vec<char>) {
        self.text.push(c);
        if self.text.len() > TEXT_LENGTH {
            self.text.remove(0);
        }
        out.push(c);
    }
}
