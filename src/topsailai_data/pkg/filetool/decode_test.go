package filetool

import (
	"bytes"
	"testing"
)

// TestDetectEncodingIsDeterministic locks the tie-breaking rule.
//
// chardet collects recognizer results from concurrent goroutines and sorts them
// with an unstable sort, so DetectBest returned different charsets for identical
// bytes when confidences tied. That made file reads non-deterministic. The
// detector now applies an explicit total order, so repeated detection over the
// same sample must always agree.
func TestDetectEncodingIsDeterministic(t *testing.T) {
	sample := bytes.Repeat([]byte{0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07}, 4096)

	first := detectEncoding(sample)
	for i := 0; i < 40; i++ {
		if got := detectEncoding(sample); got != first {
			t.Fatalf("detectEncoding is not deterministic: run %d returned %q, first run returned %q", i, got, first)
		}
	}
}

// TestDetectEncodingEmptySample verifies an empty sample yields no charset.
func TestDetectEncodingEmptySample(t *testing.T) {
	if got := detectEncoding(nil); got != "" {
		t.Fatalf("expected empty charset for nil sample, got %q", got)
	}
	if got := detectEncoding([]byte{}); got != "" {
		t.Fatalf("expected empty charset for empty sample, got %q", got)
	}
}

// TestDecodeBytesIsDeterministic verifies decoded output is stable.
//
// The byte sample below is the one that previously alternated between Big5 and
// GB-18030, which produced different decoded lengths for the same input.
func TestDecodeBytesIsDeterministic(t *testing.T) {
	data := make([]byte, 0, 51200)
	for i := 0; i < 200; i++ {
		for b := 0; b < 256; b++ {
			data = append(data, byte(b))
		}
	}

	first := decodeBytes(data)
	for i := 0; i < 20; i++ {
		got := decodeBytes(data)
		if got != first {
			t.Fatalf("decodeBytes is not deterministic: run %d produced %d bytes, first run produced %d bytes", i, len(got), len(first))
		}
	}
}

// TestDecodeBytesKeepsValidUTF8 verifies plain UTF-8 text is returned unchanged.
func TestDecodeBytesKeepsValidUTF8(t *testing.T) {
	const text = "plain ascii and 中文 text\n"
	if got := decodeBytes([]byte(text)); got != text {
		t.Fatalf("expected %q, got %q", text, got)
	}
}

// TestDecodeBytesEmptyInput verifies an empty payload decodes to an empty string.
func TestDecodeBytesEmptyInput(t *testing.T) {
	if got := decodeBytes(nil); got != "" {
		t.Fatalf("expected empty string, got %q", got)
	}
}
