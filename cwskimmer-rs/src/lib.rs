//! cwskimmer – multi-channel CW decoder.
//!
//! Rust port of the decoding engine of JvanKatwijk/cwskimmer (GPL-2.0+).
//! 192 kHz IQ goes in; every 2 ms a 2048-point spectrum is computed and 48
//! bins (~94 Hz apart, ~4.5 kHz total) around the tuned frequency are fed to
//! independent on/off-keying decoders.

pub mod decoder;
pub mod engine;
pub mod morse;
pub mod skimmer;
pub mod source;

#[cfg(feature = "gui")]
pub mod gui;
