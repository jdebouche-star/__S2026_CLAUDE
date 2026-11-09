//! cwskimmer GUI: `cwskimmer [file.wav] [--center HZ] [--offset HZ] [--loop]` (no file = demo band)

use cwskimmer::gui::SkimmerApp;
use cwskimmer::source::{IqSource, SynthSource, WavSource};

fn main() -> eframe::Result {
    let mut args = std::env::args().skip(1);
    let (mut path, mut center, mut offset, mut looping) = (None, 14_030_000.0f64, 0.0f64, false);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--center" => center = args.next().and_then(|v| v.parse().ok()).unwrap_or(center),
            "--offset" => offset = args.next().and_then(|v| v.parse().ok()).unwrap_or(0.0),
            "--loop" => looping = true,
            "-h" | "--help" => {
                eprintln!("usage: cwskimmer [file.wav] [--center HZ] [--offset HZ] [--loop]\n\
                           file.wav: 192 kHz stereo I/Q recording; omit for a built-in demo band");
                return Ok(());
            }
            p => path = Some(p.to_string()),
        }
    }
    let source: Box<dyn IqSource> = match path {
        Some(p) => Box::new(WavSource::open(&p, center, looping).unwrap_or_else(|e| {
            eprintln!("{e}");
            std::process::exit(1)
        })),
        None => Box::new(SynthSource::new(center, 1)),
    };
    let options = eframe::NativeOptions {
        viewport: eframe::egui::ViewportBuilder::default()
            .with_title("CW Skimmer")
            .with_inner_size([1360.0, 860.0])
            .with_min_inner_size([900.0, 600.0]),
        ..Default::default()
    };
    eframe::run_native(
        "CW Skimmer",
        options,
        Box::new(move |cc| Ok(Box::new(SkimmerApp::new(cc, source, offset)))),
    )
}
