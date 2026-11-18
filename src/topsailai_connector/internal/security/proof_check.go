package security

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
)

// Validate checks a proof value that arrived as structured data rather than as a
// header string.
//
// The Node receives a proof the Server already parsed, so it cannot re-parse the
// original header. It must still check every field, because the Server is not the
// authority for the Node's credential: a Server that forwarded a proof with a
// wrong scheme, an unknown version or a malformed nonce would otherwise hand the
// Node a value it never validated. The checks mirror ParseProof exactly, so a
// proof that would have been refused as a header is refused here too.
func (p Proof) Validate(expectedScheme string) error {
	if p.Scheme != expectedScheme {
		return fmt.Errorf("%w: scheme %q is not %q", ErrMalformedProof, p.Scheme, expectedScheme)
	}
	if p.Version != ProofVersion {
		return fmt.Errorf("%w: version %d is not supported; this build understands %d", ErrMalformedProof, p.Version, ProofVersion)
	}
	if err := ValidateKeyID(p.KeyID); err != nil {
		return fmt.Errorf("%w: %v", ErrMalformedProof, err)
	}
	if p.TimestampMS < 0 {
		return fmt.Errorf("%w: timestamp_ms is negative", ErrMalformedProof)
	}
	if err := validateLowerHex(p.Nonce, NonceHexLength, "nonce"); err != nil {
		return fmt.Errorf("%w: %v", ErrMalformedProof, err)
	}
	if err := validateLowerHex(p.Signature, SignatureHexLength, "signature"); err != nil {
		return fmt.Errorf("%w: %v", ErrMalformedProof, err)
	}
	return nil
}

// MaxRequestIDLength bounds a caller correlation id.
//
// The id is signed by both proofs and echoed in every log line, so an unbounded
// value is a caller deciding how much of the Server's log it occupies. The bound
// is generous for a UUID and small enough that a log line stays readable.
const MaxRequestIDLength = 128

// ValidateRequestID checks that a correlation id is usable.
//
// The id is not a credential and is not trusted for anything except correlation,
// but it is signed, so it must be a value both sides can reproduce byte for byte.
// Whitespace and control characters are refused because they would make a log line
// ambiguous, and a value that is ambiguous in a log is a value an operator cannot
// search for.
func ValidateRequestID(value string) error {
	if value == "" {
		return fmt.Errorf("request id is empty")
	}
	if len(value) > MaxRequestIDLength {
		return fmt.Errorf("request id is %d bytes, want at most %d", len(value), MaxRequestIDLength)
	}
	for _, character := range value {
		switch {
		case character >= 'a' && character <= 'z':
		case character >= 'A' && character <= 'Z':
		case character >= '0' && character <= '9':
		case character == '-', character == '_', character == '.', character == ':':
		default:
			return fmt.Errorf("request id contains %q, which is not a letter, a digit, '-', '_', '.' or ':'", character)
		}
	}
	return nil
}

// NewRequestID returns a fresh correlation id.
//
// One implementation is shared by the CLI and the Server, because the id is signed
// by the client proof: two generators that disagreed about the shape would produce
// an id the other side refuses, and the failure would look like an authentication
// error rather than a formatting one.
func NewRequestID() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate request id: %w", err)
	}
	return "req_" + hex.EncodeToString(buffer), nil
}
