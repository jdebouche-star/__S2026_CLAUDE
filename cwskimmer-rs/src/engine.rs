//! Background thread that pulls IQ from a source, runs the skimmer and
//! publishes [`Event`]s.

use crate::skimmer::{Event, Skimmer, FRAME_SAMPLES, SAMPLE_RATE};
use crate::source::IqSource;
use rustfft::num_complex::Complex32;
use std::sync::mpsc::{channel, Receiver, Sender, TryRecvError};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

pub enum Command {
    /// Tune to an offset (Hz) from the stream centre frequency.
    SetOffset(f64),
    SetBins { center: usize, width: usize },
    SetMinSnr(f32),
    Reset,
    Pause(bool),
    Quit,
}

pub struct Engine {
    pub commands: Sender<Command>,
    pub events: Receiver<Vec<Event>>,
    handle: Option<JoinHandle<()>>,
}

impl Engine {
    /// Start the engine. `wake` is called whenever new events are available
    /// (e.g. to request a UI repaint).
    pub fn spawn(
        mut source: Box<dyn IqSource>,
        offset_hz: f64,
        wake: impl Fn() + Send + 'static,
    ) -> Engine {
        let (ctx, crx) = channel();
        let (etx, erx) = channel();
        let handle = thread::spawn(move || {
            let mut skimmer = Skimmer::new();
            skimmer.set_offset_hz(offset_hz);
            let realtime = source.realtime();
            let chunk = FRAME_SAMPLES * 5; // 10 ms
            let mut buf = vec![Complex32::new(0.0, 0.0); chunk];
            let mut paused = false;
            let start = Instant::now();
            let mut produced: u64 = 0;
            loop {
                loop {
                    match crx.try_recv() {
                        Ok(Command::SetOffset(hz)) => skimmer.set_offset_hz(hz),
                        Ok(Command::SetBins { center, width }) => skimmer.set_bins(center, width),
                        Ok(Command::SetMinSnr(s)) => skimmer.set_min_snr(s),
                        Ok(Command::Reset) => skimmer.reset(),
                        Ok(Command::Pause(p)) => paused = p,
                        Ok(Command::Quit) | Err(TryRecvError::Disconnected) => return,
                        Err(TryRecvError::Empty) => break,
                    }
                }
                if paused {
                    thread::sleep(Duration::from_millis(20));
                    // keep the real-time clock from "catching up" afterwards
                    produced = (start.elapsed().as_secs_f64() * SAMPLE_RATE as f64) as u64;
                    continue;
                }
                let n = source.read(&mut buf);
                if n == 0 {
                    return;
                }
                let mut events = Vec::new();
                skimmer.push(&buf[..n], &mut events);
                if !events.is_empty() && etx.send(events).is_ok() {
                    wake();
                }
                produced += n as u64;
                if realtime {
                    let due = Duration::from_secs_f64(produced as f64 / SAMPLE_RATE as f64);
                    if let Some(wait) = due.checked_sub(start.elapsed()) {
                        thread::sleep(wait);
                    }
                }
            }
        });
        Engine { commands: ctx, events: erx, handle: Some(handle) }
    }

    pub fn send(&self, c: Command) {
        let _ = self.commands.send(c);
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        let _ = self.commands.send(Command::Quit);
        if let Some(h) = self.handle.take() {
            let _ = h.join();
        }
    }
}
