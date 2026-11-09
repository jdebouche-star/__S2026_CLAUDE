//! Morse code table. Patterns use '.' for dit and '_' for dah.

const TABLE: &[(char, &str)] = &[
    ('A', "._"), ('B', "_..."), ('C', "_._."), ('D', "_.."), ('E', "."),
    ('F', ".._."), ('G', "__."), ('H', "...."), ('I', ".."), ('J', ".___"),
    ('K', "_._"), ('L', "._.."), ('M', "__"), ('N', "_."), ('O', "___"),
    ('P', ".__."), ('Q', "__._"), ('R', "._."), ('S', "..."), ('T', "_"),
    ('U', ".._"), ('V', "..._"), ('W', ".__"), ('X', "_.._"), ('Y', "_.__"),
    ('Z', "__.."),
    ('0', "_____"), ('1', ".____"), ('2', "..___"), ('3', "...__"),
    ('4', "...._"), ('5', "....."), ('6', "_...."), ('7', "__..."),
    ('8', "___.."), ('9', "____."),
    ('.', "._._._"), (',', "__..__"), ('?', "..__.."),
    ('/', "_.._."), ('=', "_..._"),
];

/// Decode a dit/dah pattern; `None` if it is not a known character.
pub fn lookup(pattern: &str) -> Option<char> {
    TABLE.iter().find(|(_, p)| *p == pattern).map(|(c, _)| *c)
}

/// Dit/dah pattern for a character (case-insensitive), if known.
pub fn pattern(c: char) -> Option<&'static str> {
    let c = c.to_ascii_uppercase();
    TABLE.iter().find(|(ch, _)| *ch == c).map(|(_, p)| *p)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip() {
        for (c, p) in TABLE {
            assert_eq!(lookup(p), Some(*c));
            assert_eq!(pattern(*c), Some(*p));
        }
        assert_eq!(lookup("........"), None);
    }
}
