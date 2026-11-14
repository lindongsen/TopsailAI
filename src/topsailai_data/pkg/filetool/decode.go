package filetool

import (
	"strings"
	"unicode/utf8"

	"github.com/saintfish/chardet"
	"golang.org/x/text/encoding"
	"golang.org/x/text/encoding/ianaindex"
	"golang.org/x/text/transform"
)

// encodingSampleSize is the number of leading bytes used for encoding
// detection. A bounded sample keeps detection cheap for large files.
const encodingSampleSize = 32768

// detectEncoding returns the IANA charset name detected from a byte sample.
// It returns an empty string when detection fails or yields nothing.
//
// chardet's DetectBest gathers recognizer results from concurrent goroutines and
// orders them with an unstable sort, so two runs over identical bytes can return
// different charsets when confidences tie. That made file reads
// non-deterministic: the same command returned different content and lengths.
// DetectAll is used instead and the winner is chosen by an explicit total order
// (confidence descending, then charset name ascending) so identical input always
// produces identical output.
func detectEncoding(sample []byte) string {
	if len(sample) == 0 {
		return ""
	}
	results, err := chardet.NewTextDetector().DetectAll(sample)
	if err != nil || len(results) == 0 {
		return ""
	}
	best := results[0]
	for _, candidate := range results[1:] {
		if candidate.Confidence > best.Confidence {
			best = candidate
			continue
		}
		if candidate.Confidence == best.Confidence && candidate.Charset < best.Charset {
			best = candidate
		}
	}
	return best.Charset
}

// lookupEncoding resolves an IANA charset name to a decoder.
func lookupEncoding(name string) encoding.Encoding {
	if name == "" {
		return nil
	}
	enc, err := ianaindex.IANA.Encoding(name)
	if err != nil || enc == nil {
		return nil
	}
	return enc
}

// isAsciiOnly reports whether every byte in the sample is ASCII.
//
// An ASCII-only sample is compatible with every ASCII-superset encoding, so it
// carries no evidence about which one applies. Detection over such a sample
// returns several candidates at equal confidence and the winner is arbitrary.
func isAsciiOnly(sample []byte) bool {
	for _, value := range sample {
		if value >= utf8.RuneSelf {
			return false
		}
	}
	return true
}

// decodeBytes converts raw file bytes to text.
//
// Valid UTF-8 is returned unchanged before detection runs, because detection
// samples only the leading bytes and a pure-ASCII prefix says nothing about
// later content. When the sample is ASCII-only the detected charset would be
// arbitrary, so the buffer is decoded as UTF-8 with replacement instead: valid
// runs survive and only genuinely invalid bytes become U+FFFD. A sample that
// carries real non-ASCII evidence still reaches the detected decoder.
func decodeBytes(data []byte) string {
	if len(data) == 0 {
		return ""
	}

	if utf8.Valid(data) {
		return string(data)
	}

	sample := data
	if len(sample) > encodingSampleSize {
		sample = sample[:encodingSampleSize]
	}

	if isAsciiOnly(sample) {
		return strings.ToValidUTF8(string(data), "\uFFFD")
	}

	if enc := lookupEncoding(detectEncoding(sample)); enc != nil {
		decoded, _, err := transform.Bytes(enc.NewDecoder(), data)
		if err == nil {
			return string(decoded)
		}
	}

	return strings.ToValidUTF8(string(data), "\uFFFD")
}
