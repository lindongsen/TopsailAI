package security

import (
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"fmt"
	"strings"
)

// Secret is a shared secret compared as a whole value. It is a string so a
// caller cannot accidentally treat it as a number, and it has no accessor that
// returns the value for logging: the only way to use it is to compare it.
//
// A Secret is never persisted, never logged and never stored in a struct field
// that outlives the request being forwarded. The Server holds its own two
// secrets in configuration and holds a Node's secret only for the duration of
// one forwarded request.
type Secret string

// ErrSecretMismatch reports a secret that did not match. Every failure produces
// this one error: a wrong secret, a missing secret and a malformed secret are
// indistinguishable to the caller, because distinguishing them tells an attacker
// whether a guess was close.
var ErrSecretMismatch = errors.New("secret mismatch")

// MinSecretLength is the shortest secret accepted at startup. A short secret is
// a guessable secret, and a guessable secret is the whole model's failure mode
// because no secret expires.
const MinSecretLength = 16

// Equal reports whether two secrets are the same value, in time independent of
// where the first difference is.
//
// Both values are hashed first, so the comparison always runs over 32 bytes.
// Comparing the raw bytes would return early when the lengths differ, which
// leaks the length of the configured secret and lets an attacker skip every
// candidate of the wrong size.
//
// The digest is computed per comparison and never stored. A stored digest is a
// stored credential index: it would let the Server recognise a secret later,
// which is exactly what "the Server never stores a Node token" forbids.
//
// An empty value on either side is a mismatch, including empty against empty.
// Hashing makes two empty values compare equal, so without this guard an unset
// configured secret would authenticate an absent header. The startup check
// already refuses an empty configured secret; this guard is the second line,
// because the first line is a check that can be skipped.
func (s Secret) Equal(candidate Secret) bool {
	if s == "" || candidate == "" {
		return false
	}
	left := sha256.Sum256([]byte(s))
	right := sha256.Sum256([]byte(candidate))
	return subtle.ConstantTimeCompare(left[:], right[:]) == 1
}

// Validate checks that a configured secret is usable. It is called once at
// startup, never per request, because a per-request check would be a check that
// can be skipped.
//
// An empty secret is a startup failure rather than an "authentication disabled"
// mode: an unset environment variable is the most likely way to accidentally
// disable authentication, so it must stop the process instead of opening it.
func (s Secret) Validate(name string) error {
	value := string(s)
	if value == "" {
		return fmt.Errorf("%s is empty; an empty secret is a startup failure, not a disabled check", name)
	}
	if strings.TrimSpace(value) != value {
		return fmt.Errorf("%s has leading or trailing whitespace; a trailing newline from a shell export would make every comparison fail", name)
	}
	if len(value) < MinSecretLength {
		return fmt.Errorf("%s is %d bytes, want at least %d", name, len(value), MinSecretLength)
	}
	return nil
}

// Redacted is the only representation of a secret that may be printed. It
// reports the length so an operator can tell two secrets apart without either
// value reaching a log.
func (s Secret) Redacted() string {
	if s == "" {
		return "<empty>"
	}
	return fmt.Sprintf("<secret:%d bytes>", len(s))
}
