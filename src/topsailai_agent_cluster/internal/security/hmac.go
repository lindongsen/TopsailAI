package security

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"
)

// HMACScheme is the authentication scheme token used in the credential header.
//
// It is part of the signed string as well as the header, so a signature produced
// for one scheme cannot be replayed under another. The value is fixed rather than
// configurable because it identifies the algorithm, and an algorithm chosen by a
// caller is an algorithm an attacker can downgrade.
const HMACScheme = "AC-HMAC-SHA256"

// AuthMode selects how a credential is proven to a verifier.
//
// Exactly one mode is in force at a boundary. The two modes are never accepted
// together, because accepting both would let a caller bypass the stronger mode by
// sending the weaker syntax.
type AuthMode string

const (
	// ModeHMAC proves possession of the secret without transmitting it.
	ModeHMAC AuthMode = "hmac"
	// ModeBearer transmits the token itself. It exists only as an explicitly
	// selected compatibility mode.
	ModeBearer AuthMode = "bearer"
)

// DefaultAuthMode is the mode a boundary uses when nothing is configured.
//
// HMAC is the default because the plaintext path must be a deliberate choice
// rather than something a deployment keeps by accident.
const DefaultAuthMode = ModeHMAC

// DefaultSignatureWindow is how far a signature timestamp may differ from the
// verifier's clock.
const DefaultSignatureWindow = 60 * time.Second

// MaxSignatureWindow bounds a configured window.
//
// The bound exists because the window is the only thing that makes a captured
// signature expire. A typo that produced an effectively unlimited window would
// turn every captured signature into a permanent credential, so an excessive
// value is rejected instead of clamped: silently narrowing an operator's stated
// intent would hide the mistake.
const MaxSignatureWindow = 15 * time.Minute

// maxNonceBytes bounds a nonce so a caller cannot force the verifier to retain an
// arbitrarily large key.
const maxNonceBytes = 128

// maxKeyIDBytes bounds a key identifier for the same reason.
const maxKeyIDBytes = 128

// Errors returned by credential parsing and verification.
//
// They are distinct values rather than one generic failure because the operator's
// next action differs: a clock problem is fixed by correcting the clock, a
// configuration problem by editing a file, and a wrong secret by rotating a
// credential. Collapsing them into "authentication failed" would send every one
// of those investigations to the same place.
var (
	// ErrMalformedToken reports a token that is not exactly one key_id.secret pair.
	ErrMalformedToken = errors.New("token must be exactly one key_id.secret pair")
	// ErrMalformedSignature reports a credential header that cannot be parsed.
	ErrMalformedSignature = errors.New("credential header is malformed")
	// ErrUnknownKeyID reports a key identifier the verifier does not hold.
	ErrUnknownKeyID = errors.New("credential key_id is not configured")
	// ErrClockSkew reports a timestamp outside the configured window.
	ErrClockSkew = errors.New("credential timestamp is outside the accepted window")
	// ErrReplayedNonce reports a nonce already used inside the window.
	ErrReplayedNonce = errors.New("credential nonce was already used")
	// ErrBadSignature reports a signature that does not match the request.
	ErrBadSignature = errors.New("credential signature does not match the request")
	// ErrUnsupportedMode reports an authentication mode outside the vocabulary.
	ErrUnsupportedMode = errors.New("authentication mode must be hmac or bearer")
	// ErrInvalidWindow reports a signature window that is unusable.
	ErrInvalidWindow = errors.New("signature window must be positive and at most 15m")
)

// Token is one parsed credential.
//
// KeyID is public: it travels in every request and may be written to an audit log.
// Secret is the only part that provides secrecy, and it never leaves the caller or
// the verifier.
type Token struct {
	KeyID  string
	Secret string
}

// ParseToken splits a credential into its public identifier and its secret.
//
// The format is exactly one dot. A token with no dot has no identifier, and a
// token with several dots is ambiguous: both are rejected rather than guessed,
// because a guess would silently pick one of two possible identifiers and the
// resulting refusal would look like a wrong secret.
func ParseToken(raw string) (Token, error) {
	keyID, secret, found := strings.Cut(raw, ".")
	if !found || keyID == "" || secret == "" {
		return Token{}, ErrMalformedToken
	}
	if strings.Contains(secret, ".") {
		return Token{}, ErrMalformedToken
	}
	if len(keyID) > maxKeyIDBytes {
		return Token{}, ErrMalformedToken
	}
	if strings.ContainsAny(keyID, " \t\r\n,") {
		return Token{}, ErrMalformedToken
	}
	return Token{KeyID: keyID, Secret: secret}, nil
}

// ParseAuthMode validates a configured authentication mode.
//
// An empty value selects the default. Any other unrecognised value is rejected,
// because falling back to a default on a typo would silently change how a
// deployment authenticates.
func ParseAuthMode(raw string) (AuthMode, error) {
	switch AuthMode(strings.ToLower(strings.TrimSpace(raw))) {
	case "":
		return DefaultAuthMode, nil
	case ModeHMAC:
		return ModeHMAC, nil
	case ModeBearer:
		return ModeBearer, nil
	default:
		return "", ErrUnsupportedMode
	}
}

// ParseSignatureWindow validates a configured signature window.
func ParseSignatureWindow(raw string) (time.Duration, error) {
	if strings.TrimSpace(raw) == "" {
		return DefaultSignatureWindow, nil
	}
	window, err := time.ParseDuration(strings.TrimSpace(raw))
	if err != nil {
		return 0, ErrInvalidWindow
	}
	if window <= 0 || window > MaxSignatureWindow {
		return 0, ErrInvalidWindow
	}
	return window, nil
}

// Signature is one parsed credential header.
type Signature struct {
	KeyID       string
	TimestampMS int64
	Nonce       string
	Signature   string
}

// Header renders the credential header value.
func (s Signature) Header() string {
	return fmt.Sprintf("%s key_id=%s, ts=%d, nonce=%s, sig=%s", HMACScheme, s.KeyID, s.TimestampMS, s.Nonce, s.Signature)
}

// ParseSignatureHeader parses a credential header value.
//
// Every field is required and no unknown field is accepted. A permissive parser
// would let a caller add a field the verifier ignores, and the ignored field would
// then look signed while contributing nothing.
func ParseSignatureHeader(value string) (Signature, error) {
	scheme, rest, found := strings.Cut(strings.TrimSpace(value), " ")
	if !found || scheme != HMACScheme {
		return Signature{}, ErrMalformedSignature
	}
	fields := map[string]string{}
	for _, part := range strings.Split(rest, ",") {
		name, raw, ok := strings.Cut(strings.TrimSpace(part), "=")
		if !ok {
			return Signature{}, ErrMalformedSignature
		}
		name = strings.TrimSpace(name)
		if _, duplicate := fields[name]; duplicate {
			return Signature{}, ErrMalformedSignature
		}
		fields[name] = strings.TrimSpace(raw)
	}
	for _, required := range []string{"key_id", "ts", "nonce", "sig"} {
		if fields[required] == "" {
			return Signature{}, ErrMalformedSignature
		}
	}
	if len(fields) != 4 {
		return Signature{}, ErrMalformedSignature
	}
	timestamp, err := strconv.ParseInt(fields["ts"], 10, 64)
	if err != nil || timestamp <= 0 {
		return Signature{}, ErrMalformedSignature
	}
	if len(fields["key_id"]) > maxKeyIDBytes || len(fields["nonce"]) > maxNonceBytes {
		return Signature{}, ErrMalformedSignature
	}
	if _, err := hex.DecodeString(fields["nonce"]); err != nil {
		return Signature{}, ErrMalformedSignature
	}
	if _, err := hex.DecodeString(fields["sig"]); err != nil {
		return Signature{}, ErrMalformedSignature
	}
	return Signature{KeyID: fields["key_id"], TimestampMS: timestamp, Nonce: fields["nonce"], Signature: fields["sig"]}, nil
}

// NewNonce returns a fresh random nonce.
func NewNonce() string {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		// A nonce that cannot be random cannot protect against replay, so the
		// caller must not proceed. Returning an empty string makes the signing
		// path fail closed instead of emitting a predictable value.
		return ""
	}
	return hex.EncodeToString(raw[:])
}

// Sign returns the lower-case hex HMAC-SHA256 of message under secret.
func Sign(secret, message string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(message))
	return hex.EncodeToString(mac.Sum(nil))
}

// VerifySignature reports whether signature is the HMAC of message under secret.
//
// hmac.Equal compares in constant time, so a wrong signature cannot be discovered
// byte by byte from response timing.
func VerifySignature(secret, message, signature string) bool {
	expected := Sign(secret, message)
	return hmac.Equal([]byte(expected), []byte(signature))
}

// ConstantTimeEqual compares two strings without leaking their common prefix.
//
// The bearer path needs this because it compares a presented token with a stored
// one. A short-circuiting comparison would let an attacker recover the token one
// byte at a time.
func ConstantTimeEqual(left, right string) bool {
	return subtle.ConstantTimeCompare([]byte(left), []byte(right)) == 1
}

// BodyDigest returns the digest of a request body, or "-" when there is none.
//
// The literal "-" is used instead of the digest of an empty string so an absent
// body and an empty body are distinguishable in the signed string. They are
// different requests, and a signature that covered both identically would let one
// be replayed as the other.
func BodyDigest(body []byte) string {
	if len(body) == 0 {
		return "-"
	}
	sum := sha256.Sum256(body)
	return hex.EncodeToString(sum[:])
}

// CanonicalHTTPRequest builds the signed string for one HTTP request.
//
// The fields are newline separated with a fixed order and no optional entries, so
// one request has exactly one encoding. The path includes the query string because
// the query selects the target: signing only the path would let an attacker
// redirect a read to a different resource while keeping a valid signature.
func CanonicalHTTPRequest(method, path string, body []byte, timestampMS int64, nonce string) string {
	return strings.Join([]string{
		HMACScheme,
		method,
		path,
		BodyDigest(body),
		strconv.FormatInt(timestampMS, 10),
		nonce,
	}, "\n")
}

// CanonicalFrameRequest builds the signed string for one channel frame.
//
// A frame has no HTTP method or path, so its logical identity is signed instead.
//
// The request ID is deliberately absent. The Server mints every frame request ID
// after the caller's request has already been authenticated
// (internal/server/commands.go:259 and internal/channel/server.go:710), so the
// signer cannot compute the value it would have to sign. A field the signer cannot
// compute is not a stronger signature, it is an unimplementable one.
//
// The property the request ID was meant to provide is provided by the payload
// digest instead. Because the digest covers the whole request content, a captured
// signature cannot be moved to a different target: a different resource produces a
// different digest and the signature fails. That is why payloadDigest must cover
// the request rather than only the operation name.
func CanonicalFrameRequest(frameType, operation, endpointID, payloadDigest string, timestampMS int64, nonce string) string {
	if payloadDigest == "" {
		payloadDigest = "-"
	}
	return strings.Join([]string{
		HMACScheme,
		frameType,
		operation,
		endpointID,
		payloadDigest,
		strconv.FormatInt(timestampMS, 10),
		nonce,
	}, "\n")
}

// NonceCache remembers nonces used inside the signature window.
//
// It is bounded and in memory. A nonce only matters while its timestamp is still
// inside the window, so a durable store would retain values that can no longer be
// replayed.
type NonceCache struct {
	mu      sync.Mutex
	limit   int
	window  time.Duration
	entries map[string]time.Time
}

// NewNonceCache returns a cache holding at most limit nonces for window.
func NewNonceCache(limit int, window time.Duration) *NonceCache {
	if limit <= 0 {
		limit = 1024
	}
	if window <= 0 {
		window = DefaultSignatureWindow
	}
	return &NonceCache{limit: limit, window: window, entries: make(map[string]time.Time)}
}

// Accept records one nonce and reports whether it was unused.
//
// A nonce already present and unexpired is a replay, so it is refused. Expired
// entries are dropped on the way through, which keeps the map bounded without a
// background goroutine.
func (c *NonceCache) Accept(keyID, nonce string, now time.Time) bool {
	if c == nil {
		return true
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	key := keyID + "\x00" + nonce
	for existing, expiry := range c.entries {
		if !expiry.After(now) {
			delete(c.entries, existing)
		}
	}
	if expiry, seen := c.entries[key]; seen && expiry.After(now) {
		return false
	}
	if len(c.entries) >= c.limit {
		// The cache is full of live nonces. Refusing is the safe direction: it
		// fails closed instead of evicting a nonce that could still be replayed.
		return false
	}
	c.entries[key] = now.Add(c.window)
	return true
}

// Verifier checks HMAC-signed requests against the tokens it holds.
type Verifier struct {
	// Tokens is keyed by the public key identifier.
	Tokens map[string]Token
	// Window is how far a timestamp may differ from Now.
	Window time.Duration
	// Nonces remembers nonces used inside Window.
	Nonces *NonceCache
	// Now supplies the current time. A nil value uses time.Now.
	Now func() time.Time
}

// NewVerifier returns a verifier for tokens with the given window.
func NewVerifier(tokens map[string]Token, window time.Duration) *Verifier {
	if window <= 0 {
		window = DefaultSignatureWindow
	}
	return &Verifier{Tokens: tokens, Window: window, Nonces: NewNonceCache(0, window)}
}

func (v *Verifier) now() time.Time {
	if v.Now != nil {
		return v.Now()
	}
	return time.Now()
}

// Verify checks one signature against the canonical message it should cover.
//
// The order of checks is load-bearing. The token is looked up first because it is
// the cheapest rejection. The window is checked before the signature because an
// expired request is refused without any cryptographic work. The signature is
// verified before the nonce is recorded, so a forged request cannot consume a
// nonce slot and deny that nonce to the legitimate caller.
func (v *Verifier) Verify(message string, signature Signature) error {
	if v == nil {
		return ErrUnknownKeyID
	}
	token, known := v.Tokens[signature.KeyID]
	if !known {
		return ErrUnknownKeyID
	}
	now := v.now()
	skew := now.Sub(time.UnixMilli(signature.TimestampMS))
	if skew < 0 {
		skew = -skew
	}
	if skew > v.Window {
		return ErrClockSkew
	}
	if !VerifySignature(token.Secret, message, signature.Signature) {
		return ErrBadSignature
	}
	if !v.Nonces.Accept(signature.KeyID, signature.Nonce, now) {
		return ErrReplayedNonce
	}
	return nil
}

// SignRequest produces the credential header value for one request.
//
// The caller supplies a builder rather than a finished message because the
// timestamp and nonce are part of the signed string and are generated here. A
// caller that built the message first would have to invent its own timestamp and
// nonce, and the two would then be able to disagree with the header that carries
// them.
//
// It returns an error when a nonce cannot be generated, so the caller fails closed
// instead of sending a request with a predictable nonce.
func SignRequest(token Token, build func(timestampMS int64, nonce string) string) (Signature, error) {
	nonce := NewNonce()
	if nonce == "" {
		return Signature{}, errors.New("cannot generate a nonce")
	}
	timestamp := time.Now().UnixMilli()
	return Signature{
		KeyID:       token.KeyID,
		TimestampMS: timestamp,
		Nonce:       nonce,
		Signature:   Sign(token.Secret, build(timestamp, nonce)),
	}, nil
}
