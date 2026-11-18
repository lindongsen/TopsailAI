// Package security holds the authorization and authentication primitives shared
// by the Server and the Node.
//
// Everything here is pure data and pure functions, except the replay cache, which
// is in-memory state owned by one verifier. Nothing here performs network or
// filesystem IO, so both binaries can compile it and neither can disagree about the
// contract.
package security

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
)

// SchemeClient is the fixed authentication scheme name of the CLI-to-Server proof.
//
// The scheme is part of the signed bytes, so a proof built for one domain cannot be
// replayed into the other even when both use the same HMAC construction.
const SchemeClient = "CONNECTOR-CLIENT-HMAC-SHA256"

// SchemeNode is the fixed authentication scheme name of the CLI-to-Node proof.
const SchemeNode = "CONNECTOR-NODE-HMAC-SHA256"

// ProofVersion is the only proof format version this build understands. It is
// signed, so a future format change is detectable instead of being read as if it
// were the current one.
const ProofVersion = 1

// NonceHexLength is the number of hexadecimal characters in a nonce. 32 characters
// encode 128 random bits, which is enough that two nonces never collide by
// accident and a guessed nonce is not a way to bypass replay detection.
const NonceHexLength = 32

// SignatureHexLength is the number of hexadecimal characters in an HMAC-SHA256
// signature.
const SignatureHexLength = sha256.Size * 2

// MaxProofHeaderBytes bounds one proof header value.
//
// The bound exists because the header is parsed before it is verified, so an
// unbounded header is the peer deciding how much memory the verifier spends. The
// accepted grammar is far smaller than this, so the bound only ever refuses a value
// that was already malformed.
const MaxProofHeaderBytes = 512

// ErrMalformedProof reports a proof header that does not match the accepted
// grammar. Every malformed form produces this one error, because a caller that can
// tell which field was wrong learns the shape of a valid proof.
var ErrMalformedProof = errors.New("malformed authentication proof")

// ErrProofMismatch reports a proof whose signature did not verify. It is distinct
// from ErrMalformedProof internally so an operator log can tell a bad guess from a
// broken client, but both map to the same caller-visible refusal.
var ErrProofMismatch = errors.New("authentication proof does not verify")

// Proof is one parsed authentication proof.
//
// It carries no secret: the signature is derived from a secret, and the key
// identifier is public. A Proof is therefore safe to keep for the duration of one
// request and safe to describe in a log by its key identifier.
type Proof struct {
	// Scheme is the fixed scheme name the proof was built for.
	Scheme string `json:"scheme"`
	// Version is the proof format version.
	Version int `json:"version"`
	// KeyID selects the secret the verifier must use.
	KeyID string `json:"key_id"`
	// TimestampMS is the signer's clock reading in milliseconds since the epoch.
	TimestampMS int64 `json:"timestamp_ms"`
	// Nonce is the one-time value the verifier records to detect replay.
	Nonce string `json:"nonce"`
	// Signature is the lowercase hexadecimal HMAC-SHA256 value.
	Signature string `json:"signature"`
}

// ParseProof parses one proof header value for the expected scheme.
//
// The grammar is fixed and every deviation is a refusal:
//
//	<scheme> version=1,key_id=<key-id>,timestamp_ms=<decimal>,nonce=<32 hex>,signature=<64 hex>
//
// Fields must appear in that order, exactly once, with no optional whitespace. A
// permissive parser would accept two spellings of one proof, and two spellings is
// one spelling too many for a value that is compared byte for byte.
func ParseProof(value string, expectedScheme string) (Proof, error) {
	if value == "" {
		return Proof{}, fmt.Errorf("%w: value is empty", ErrMalformedProof)
	}
	if len(value) > MaxProofHeaderBytes {
		return Proof{}, fmt.Errorf("%w: value is %d bytes, want at most %d", ErrMalformedProof, len(value), MaxProofHeaderBytes)
	}
	if strings.TrimSpace(value) != value {
		return Proof{}, fmt.Errorf("%w: value has leading or trailing whitespace", ErrMalformedProof)
	}

	space := strings.IndexByte(value, ' ')
	if space < 0 {
		return Proof{}, fmt.Errorf("%w: no space after the scheme", ErrMalformedProof)
	}
	scheme := value[:space]
	if scheme != expectedScheme {
		return Proof{}, fmt.Errorf("%w: scheme %q is not %q", ErrMalformedProof, scheme, expectedScheme)
	}

	fields := strings.Split(value[space+1:], ",")
	if len(fields) != 5 {
		return Proof{}, fmt.Errorf("%w: got %d fields, want 5", ErrMalformedProof, len(fields))
	}

	version, err := parseProofField(fields[0], "version")
	if err != nil {
		return Proof{}, err
	}
	parsedVersion, err := strconv.Atoi(version)
	if err != nil {
		return Proof{}, fmt.Errorf("%w: version %q is not a decimal number", ErrMalformedProof, version)
	}
	if parsedVersion != ProofVersion {
		return Proof{}, fmt.Errorf("%w: version %d is not supported; this build understands %d", ErrMalformedProof, parsedVersion, ProofVersion)
	}

	keyID, err := parseProofField(fields[1], "key_id")
	if err != nil {
		return Proof{}, err
	}
	if err := ValidateKeyID(keyID); err != nil {
		return Proof{}, fmt.Errorf("%w: %v", ErrMalformedProof, err)
	}

	timestamp, err := parseProofField(fields[2], "timestamp_ms")
	if err != nil {
		return Proof{}, err
	}
	timestampMS, err := parseCanonicalDecimal(timestamp)
	if err != nil {
		return Proof{}, fmt.Errorf("%w: timestamp_ms %q is not a canonical non-negative decimal", ErrMalformedProof, timestamp)
	}

	nonce, err := parseProofField(fields[3], "nonce")
	if err != nil {
		return Proof{}, err
	}
	if err := validateLowerHex(nonce, NonceHexLength, "nonce"); err != nil {
		return Proof{}, fmt.Errorf("%w: %v", ErrMalformedProof, err)
	}

	signature, err := parseProofField(fields[4], "signature")
	if err != nil {
		return Proof{}, err
	}
	if err := validateLowerHex(signature, SignatureHexLength, "signature"); err != nil {
		return Proof{}, fmt.Errorf("%w: %v", ErrMalformedProof, err)
	}

	return Proof{
		Scheme:      scheme,
		Version:     parsedVersion,
		KeyID:       keyID,
		TimestampMS: timestampMS,
		Nonce:       nonce,
		Signature:   signature,
	}, nil
}

// parseProofField splits one `name=value` field and checks the name.
func parseProofField(field string, name string) (string, error) {
	prefix := name + "="
	if !strings.HasPrefix(field, prefix) {
		return "", fmt.Errorf("%w: field %q is not %q", ErrMalformedProof, field, prefix)
	}
	value := strings.TrimPrefix(field, prefix)
	if value == "" {
		return "", fmt.Errorf("%w: field %q is empty", ErrMalformedProof, name)
	}
	return value, nil
}

// parseCanonicalDecimal parses a non-negative decimal with no sign, no prefix and no
// leading zeros except the single value "0".
//
// The canonical spelling matters because the value is signed as text: accepting
// "007" and "7" as the same number would let one proof be re-spelled into another.
func parseCanonicalDecimal(value string) (int64, error) {
	if value == "" {
		return 0, errors.New("value is empty")
	}
	if len(value) > 1 && value[0] == '0' {
		return 0, errors.New("value has a leading zero")
	}
	for _, character := range value {
		if character < '0' || character > '9' {
			return 0, errors.New("value is not a decimal number")
		}
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil {
		return 0, err
	}
	if parsed < 0 {
		return 0, errors.New("value is negative")
	}
	return parsed, nil
}

// validateLowerHex checks that a value is lowercase hexadecimal of an exact length.
//
// Uppercase is refused rather than folded, because folding would accept two
// spellings of one nonce and the nonce is the replay identity.
func validateLowerHex(value string, length int, name string) error {
	if len(value) != length {
		return fmt.Errorf("%s is %d characters, want %d", name, len(value), length)
	}
	for _, character := range value {
		switch {
		case character >= '0' && character <= '9':
		case character >= 'a' && character <= 'f':
		default:
			return fmt.Errorf("%s contains %q, which is not a lowercase hexadecimal digit", name, character)
		}
	}
	return nil
}

// FormatProof renders a proof in the accepted header grammar.
//
// It exists so the CLI and a test build the header the same way. A second
// implementation of the grammar would be a second definition of a valid proof.
func FormatProof(proof Proof) string {
	return fmt.Sprintf("%s version=%d,key_id=%s,timestamp_ms=%d,nonce=%s,signature=%s",
		proof.Scheme, proof.Version, proof.KeyID, proof.TimestampMS, proof.Nonce, proof.Signature)
}

// NewNonce returns a fresh 128-bit nonce as 32 lowercase hexadecimal characters.
func NewNonce() (string, error) {
	buffer := make([]byte, NonceHexLength/2)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate nonce: %w", err)
	}
	return hex.EncodeToString(buffer), nil
}

// BodyDigest returns the lowercase SHA-256 hex of raw body bytes.
//
// A missing body is represented by the literal "-" rather than by the digest of
// zero bytes, so "no body" and "a present zero-byte body" are different requests.
// Collapsing them would let one proof be replayed against the other.
func BodyDigest(body []byte, present bool) string {
	if !present {
		return "-"
	}
	sum := sha256.Sum256(body)
	return hex.EncodeToString(sum[:])
}

// BytesDigest returns the lowercase SHA-256 hex of a byte slice that is always
// present, which is how a required header value is bound.
func BytesDigest(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

// CanonicalClientRequest builds the exact bytes a client proof signs.
//
// The order is fixed and every field occupies one line. The Node proof header digest
// is included so an attacker cannot keep a valid client proof and replace the Node
// proof it travels with.
func CanonicalClientRequest(method string, requestTarget string, bodyDigest string, nodeProofDigest string, requestID string, timestampMS int64, nonce string) string {
	return strings.Join([]string{
		SchemeClient,
		strconv.Itoa(ProofVersion),
		method,
		requestTarget,
		bodyDigest,
		nodeProofDigest,
		requestID,
		strconv.FormatInt(timestampMS, 10),
		nonce,
	}, "\n")
}

// CanonicalNodeOperation builds the exact bytes a Node proof signs.
//
// The Node receives a reconstructed channel request rather than the original HTTP
// serialization, so the proof signs the logical operation instead of raw bytes. Every
// field occupies one line, including an empty path and zero numeric values, so the
// CLI and the Node cannot disagree about a missing field.
func CanonicalNodeOperation(nodeID string, keyID string, operation string, scope string, path string, offset int64, length int64, requestID string, timestampMS int64, nonce string) string {
	return strings.Join([]string{
		SchemeNode,
		strconv.Itoa(ProofVersion),
		nodeID,
		keyID,
		operation,
		scope,
		path,
		strconv.FormatInt(offset, 10),
		strconv.FormatInt(length, 10),
		requestID,
		strconv.FormatInt(timestampMS, 10),
		nonce,
	}, "\n")
}

// Sign returns the lowercase hexadecimal HMAC-SHA256 of a canonical input.
func Sign(secret Secret, canonical string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(canonical))
	return hex.EncodeToString(mac.Sum(nil))
}

// VerifySignature compares a presented signature with the expected one in constant
// time.
//
// Both values are decoded from hexadecimal first, so the comparison runs over the
// same number of bytes regardless of where the first difference is. A malformed
// signature is a mismatch rather than an error, because the caller must not be able
// to tell a bad guess from a broken encoding.
func VerifySignature(secret Secret, canonical string, presented string) error {
	expected := Sign(secret, canonical)
	if len(expected) != len(presented) {
		return ErrProofMismatch
	}
	if !hmac.Equal([]byte(expected), []byte(presented)) {
		return ErrProofMismatch
	}
	return nil
}

// TimestampWithinWindow reports whether a proof timestamp is inside the verifier's
// window.
//
// The verifier owns the window: a request cannot choose or widen it. A zero or
// negative window is a configuration failure, not a value to clamp, because a
// clamped window would silently accept a proof the operator meant to refuse.
func TimestampWithinWindow(nowMS int64, proofMS int64, windowMS int64) bool {
	if windowMS <= 0 {
		return false
	}
	difference := nowMS - proofMS
	if difference < 0 {
		difference = -difference
	}
	return difference <= windowMS
}
