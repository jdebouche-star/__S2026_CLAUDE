use cwskimmer::decoder::ChannelDecoder;
use cwskimmer::morse;
use cwskimmer::skimmer::{Event, Skimmer, NR_BINS, SAMPLE_RATE};
use cwskimmer::source::{IqSource, SynthSource};
use rustfft::num_complex::Complex32;

/// Ideal key envelope at 500 frames/s -> decoder.
#[test]
fn decoder_reads_clean_keying() {
    let wpm: f32 = 20.0;
    let unit = (1.2 / wpm * 500.0).round() as usize; // frames per dit
    let msg = "CQ CQ DE K1ABC K1ABC TEST K K K K K";
    let mut env: Vec<f32> = vec![0.0; 300];
    for (wi, w) in msg.split(' ').enumerate() {
        if wi > 0 { env.extend(vec![0.0; 7 * unit]); }
        for (ci, c) in w.chars().enumerate() {
            if ci > 0 { env.extend(vec![0.0; 3 * unit]); }
            for (ei, e) in morse::pattern(c).unwrap().chars().enumerate() {
                if ei > 0 { env.extend(vec![0.0; unit]); }
                env.extend(vec![1.0; if e == '.' { unit } else { 3 * unit }]);
            }
        }
    }
    env.extend(vec![0.0; 40 * unit]);
    let mut d = ChannelDecoder::new();
    let mut out = Vec::new();
    for v in env { d.process(v + 0.01, 0.01, &mut out); }
    let text: String = out.into_iter().collect();
    assert!(text.contains("K1ABC"), "decoded: {text:?}");
    assert!(text.contains("TEST"), "decoded: {text:?}");
    assert_eq!(d.wpm(), 20);
}

/// Full chain: synthetic IQ -> mixer -> FFT -> bins -> text.
#[test]
fn skimmer_decodes_synthetic_band_and_follows_tuning() {
    let mut src = SynthSource::new(14_030_000.0, 1);
    let mut sk = Skimmer::new();
    sk.set_bins(NR_BINS / 2, NR_BINS);
    sk.set_offset_hz(350.0); // station at +350 Hz must land on the centre bin
    let mut text = vec![String::new(); NR_BINS];
    let mut buf = vec![Complex32::new(0.0, 0.0); 3840];
    let mut ev = Vec::new();
    for _ in 0..(40 * SAMPLE_RATE as usize / buf.len()) {
        src.read(&mut buf);
        ev.clear();
        sk.push(&buf, &mut ev);
        for e in &ev {
            if let Event::Char { channel, ch, .. } = e { text[*channel].push(*ch); }
        }
    }
    let centre = &text[NR_BINS / 2];
    assert!(centre.contains("DE") && centre.contains("VK3ABC") || centre.contains("DL1ABC"),
            "centre bin decoded {centre:?}");
}
