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
func detectEncoding(sample []byte) string {
	if len(sample) == 0 {
		return ""
	}
	result, err := chardet.NewTextDetector().DetectBest(sample)
	if err != nil || result == nil {
		return ""
	}
	return result.Charset
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

// decodeBytes converts raw file bytes to text.
//
// The leading bytes are sampled to detect the encoding; the detected decoder is
// applied to the whole buffer. Undecodable bytes are replaced so a partially
// corrupted file still yields readable text, matching the source tool's
// UTF-8-with-replacement fallback.
func decodeBytes(data []byte) string {
	if len(data) == 0 {
		return ""
	}

	sample := data
	if len(sample) > encodingSampleSize {
		sample = sample[:encodingSampleSize]
	}

	if enc := lookupEncoding(detectEncoding(sample)); enc != nil {
		decoded, _, err := transform.Bytes(enc.NewDecoder(), data)
		if err == nil {
			return string(decoded)
		}
	}

	if utf8.Valid(data) {
		return string(data)
	}
	return strings.ToValidUTF8(string(data), "\uFFFD")
}
