package filetool

import (
	"bytes"
	"strings"
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

// asciiWithInsertion builds a buffer of ASCII filler with one string inserted
// at a byte offset. It lets a test place a non-ASCII character beyond the
// encoding detection sample without a huge literal.
func asciiWithInsertion(t *testing.T, total int, insertion string, offset int) []byte {
	t.Helper()
	payload := []byte(insertion)
	if offset+len(payload) > total {
		t.Fatalf("insertion of %d bytes at offset %d exceeds a %d-byte buffer", len(payload), offset, total)
	}
	data := bytes.Repeat([]byte{'a'}, total)
	copy(data[offset:], payload)
	return data
}

// TestDecodeBytesKeepsUTF8BeyondSampleBoundary locks the fix for a defect where
// a non-ASCII character after the 32768-byte sample was corrupted.
//
// A pure-ASCII sample carries no encoding evidence, so the detected charset was
// arbitrary and applying it to the whole buffer destroyed later UTF-8. The
// boundary is asserted on both sides so a fix that merely changes the sample
// size is caught.
func TestDecodeBytesKeepsUTF8BeyondSampleBoundary(t *testing.T) {
	for _, offset := range []int{32765, 32766, 32767, 40000} {
		data := asciiWithInsertion(t, 66000, "\u2502", offset)
		if got := decodeBytes(data); got != string(data) {
			t.Fatalf("offset %d: decodeBytes returned %d bytes, want %d", offset, len(got), len(data))
		}
	}
}

// TestDecodeBytesKeepsCJKBeyondSampleBoundary verifies a multi-byte sequence
// survives, so the fix is not tuned to one character.
func TestDecodeBytesKeepsCJKBeyondSampleBoundary(t *testing.T) {
	data := asciiWithInsertion(t, 66000, "\u4e2d\u6587\u6d4b\u8bd5", 40000)
	if got := decodeBytes(data); got != string(data) {
		t.Fatalf("decodeBytes returned %d bytes, want %d", len(got), len(data))
	}
}

// TestDecodeBytesKeepsValidRunsAroundInvalidByte verifies a stray invalid byte
// does not destroy surrounding UTF-8.
//
// A whole-buffer validity check alone cannot rescue this input, because the
// buffer is not valid UTF-8. Only the valid runs must survive and the stray
// byte must become a replacement character.
func TestDecodeBytesKeepsValidRunsAroundInvalidByte(t *testing.T) {
	data := asciiWithInsertion(t, 66000, "\u2502", 40000)
	data[50000] = 0xFF

	got := decodeBytes(data)
	if !strings.Contains(got, "\u2502") {
		t.Fatalf("decodeBytes lost the box-drawing character: %q", got[:80])
	}
	if !strings.Contains(got, "\uFFFD") {
		t.Fatalf("decodeBytes did not replace the invalid byte")
	}
	// The stray byte becomes one 3-byte replacement character, so the result is
	// exactly two bytes longer and nothing else may change.
	if want := len(data) + 2; len(got) != want {
		t.Fatalf("decodeBytes returned %d bytes, want %d", len(got), want)
	}
	if n := strings.Count(got, "\uFFFD"); n != 1 {
		t.Fatalf("decodeBytes produced %d replacement characters, want 1", n)
	}
}

// TestDecodeBytesStillUsesDetectedDecoder verifies a sample carrying real
// non-UTF-8 evidence still reaches the detected decoder.
//
// Latin-1 text is not valid UTF-8, so the UTF-8 fast path must not swallow it.
func TestDecodeBytesStillUsesDetectedDecoder(t *testing.T) {
	latin1 := []byte("Le caf\xe9 est tr\xe8s bon. Voil\xe0 la cr\xe8me br\xfbl\xe9e. Le caf\xe9 est tr\xe8s bon.")
	got := decodeBytes(latin1)
	if !strings.Contains(got, "caf\u00e9") {
		t.Fatalf("decodeBytes did not decode Latin-1: %q", got)
	}
}

// TestDecodeBytesPureAsciiUnchanged verifies plain ASCII is returned unchanged.
func TestDecodeBytesPureAsciiUnchanged(t *testing.T) {
	data := bytes.Repeat([]byte{'a'}, 66000)
	if got := decodeBytes(data); got != string(data) {
		t.Fatalf("decodeBytes returned %d bytes, want %d", len(got), len(data))
	}
}
