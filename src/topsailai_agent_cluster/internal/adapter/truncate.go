package adapter

import "unicode/utf8"

// TruncateUTF8 returns at most limit bytes of data without splitting a rune, so
// a truncated payload stays valid UTF-8 instead of ending in half a character.
//
// A raw byte slice would cut a multi-byte character in half and leave the caller
// with bytes that no longer decode, which is why both the snapshot and the follow
// output paths share this helper instead of slicing directly.
//
// At most one rune's worth of bytes is removed, so data that is not UTF-8 at all
// is not wiped out. A non-positive limit yields no bytes, and data that already
// fits is returned unchanged so the common path never copies or shortens it.
func TruncateUTF8(data []byte, limit int) []byte {
	if limit <= 0 {
		return nil
	}
	if len(data) <= limit {
		return data
	}
	trimmed := data[:limit]
	for i := 0; i < utf8.UTFMax-1 && len(trimmed) > 0; i++ {
		r, size := utf8.DecodeLastRune(trimmed)
		if r != utf8.RuneError || size > 1 {
			return trimmed
		}
		trimmed = trimmed[:len(trimmed)-1]
	}
	return trimmed
}
