//! Headless decoder: `cwdecode <file.wav | --demo> [--offset HZ] [--seconds N] [--center HZ]`

use cwskimmer::skimmer::{Event, Skimmer, NR_BINS, SAMPLE_RATE};
use cwskimmer::source::{IqSource, SynthSource, WavSource};
use rustfft::num_complex::Complex32;

fn main() {
    let mut args = std::env::args().skip(1);
    let (mut path, mut offset, mut seconds, mut center) = (None, 0.0f64, 60.0f64, 14_030_000.0f64);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--demo" => path = None,
            "--offset" => offset = args.next().and_then(|v| v.parse().ok()).unwrap_or(0.0),
            "--seconds" => seconds = args.next().and_then(|v| v.parse().ok()).unwrap_or(60.0),
            "--center" => center = args.next().and_then(|v| v.parse().ok()).unwrap_or(center),
            "-h" | "--help" => {
                eprintln!("usage: cwdecode [file.wav | --demo] [--offset HZ] [--seconds N] [--center HZ]");
                return;
            }
            p => path = Some(p.to_string()),
        }
    }
    let mut source: Box<dyn IqSource> = match path {
        Some(p) => Box::new(WavSource::open(&p, center, false).unwrap_or_else(|e| {
            eprintln!("{e}");
            std::process::exit(1)
        })),
        None => Box::new(SynthSource::new(center, 1)),
    };
    let mut sk = Skimmer::new();
    sk.set_bins(NR_BINS / 2, NR_BINS);
    sk.set_offset_hz(offset);
    let mut text = vec![String::new(); NR_BINS];
    let mut wpm = vec![0; NR_BINS];
    let mut buf = vec![Complex32::new(0.0, 0.0); 3840];
    let mut done = 0.0;
    let mut events = Vec::new();
    while done < seconds {
        let n = source.read(&mut buf);
        if n == 0 {
            break;
        }
        done += n as f64 / SAMPLE_RATE as f64;
        events.clear();
        sk.push(&buf[..n], &mut events);
        for e in &events {
            if let Event::Char { channel, wpm: w, ch } = e {
                text[*channel].push(*ch);
                wpm[*channel] = *w;
            }
        }
    }
    let tuned = source.center_hz() + offset;
    for k in 0..NR_BINS {
        if !text[k].is_empty() {
            let f = tuned + Skimmer::bin_offset_hz(k);
            println!("{:10.3} kHz  {:2} wpm  {}", f / 1000.0, wpm[k], text[k]);
        }
    }
}
