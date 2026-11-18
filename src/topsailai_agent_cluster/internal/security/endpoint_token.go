package security

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
)

// ErrEndpointCredentialNotSigned reports a credential that arrived in the bearer
// form while the Endpoint requires a signature.
//
// It is a distinct error rather than a generic authentication failure because the
// operator's next action differs: the credential form is wrong, so the caller must
// be reconfigured to sign, while a wrong secret means the secret must be rotated.
// Reporting one message for both would send every investigation to the same place.
var ErrEndpointCredentialNotSigned = errors.New("endpoint credential must be signed in hmac mode")

// EndpointAuthHeader carries the caller's Endpoint credential on an operator
// request.
//
// It is a header rather than a query parameter for the same reason the Server
// credential is: a URL is recorded by access logs, reverse proxies and shell
// history, while a header is not recorded by default. The Server forwards this
// value into the channel frame without interpreting it.
const EndpointAuthHeader = "X-Endpoint-Auth"

// endpointTokenContextKey is the private key type for the Endpoint token. A
// distinct unexported type keeps the value from colliding with any other
// context value, including the operator scope set.
type endpointTokenContextKey struct{}

// endpointKeyIDContextKey is the private key type for the verified Endpoint key
// identifier.
type endpointKeyIDContextKey struct{}

// EndpointCredential is the caller's Endpoint credential as it travels from the
// operator API to the Endpoint policy check.
//
// Exactly one of the two forms is populated, and which one is decided by the
// authentication mode in force at the Endpoint. The struct carries both forms
// rather than one opaque string because the Endpoint must be able to tell a
// bearer token from a signature: a single string field would force the Endpoint
// to guess, and a guess is how a caller downgrades a stronger mode by sending the
// weaker syntax.
//
// Token is the bearer form. It is the secret itself, which is why bearer mode is
// the compatibility mode rather than the default.
//
// KeyID, TimestampMS, Nonce and Signature are the HMAC form. KeyID is public and
// may be logged; the secret never appears here, because the whole point of the
// HMAC form is that the secret does not travel.
type EndpointCredential struct {
	Token       string `json:"token,omitempty"`
	KeyID       string `json:"key_id,omitempty"`
	TimestampMS int64  `json:"ts,omitempty"`
	Nonce       string `json:"nonce,omitempty"`
	Signature   string `json:"sig,omitempty"`
}

// IsZero reports whether the credential carries nothing.
//
// An absent credential is not the same as a wrong one, but both are refused by an
// Endpoint that enforces a policy. The distinction matters at the transport
// layer, where an absent credential must not be turned into an empty bearer token
// that a permissive default could accept.
func (c EndpointCredential) IsZero() bool {
	return c.Token == "" && c.Signature == ""
}

// Header renders the credential as the header value the operator API carries.
//
// The HMAC form reuses Signature.Header so one wire format serves both the Server
// credential and the Endpoint credential. A second spelling of the same scheme
// would be a second parser to keep in step, and the two would drift.
func (c EndpointCredential) Header() string {
	if c.Signature != "" {
		return Signature{
			KeyID:       c.KeyID,
			TimestampMS: c.TimestampMS,
			Nonce:       c.Nonce,
			Signature:   c.Signature,
		}.Header()
	}
	if c.Token != "" {
		return "Bearer " + c.Token
	}
	return ""
}

// ParseEndpointCredential parses an Endpoint credential header value.
//
// The two forms are distinguished by their scheme prefix, never by shape. A value
// that is neither form is rejected rather than treated as a bare bearer token,
// because accepting an unprefixed value would let a caller present a signature as
// if it were a token and have it compared as a secret.
func ParseEndpointCredential(raw string) (EndpointCredential, error) {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return EndpointCredential{}, nil
	}
	if token, found := strings.CutPrefix(trimmed, "Bearer "); found {
		if token == "" {
			return EndpointCredential{}, errors.New("endpoint bearer credential is empty")
		}
		return EndpointCredential{Token: token}, nil
	}
	signature, err := ParseSignatureHeader(trimmed)
	if err != nil {
		return EndpointCredential{}, fmt.Errorf("endpoint credential header: %w", err)
	}
	return EndpointCredential{
		KeyID:       signature.KeyID,
		TimestampMS: signature.TimestampMS,
		Nonce:       signature.Nonce,
		Signature:   signature.Signature,
	}, nil
}

// WithEndpointToken attaches the caller's Endpoint token to a request context.
//
// The token travels in the context rather than in a function parameter because
// every hop between the operator API and the channel frame builder already
// threads a context, while the token is a transport credential that no
// intermediate layer interprets. The operator identity crosses the Server the
// same way, so both credentials are carried by the context rather than by a
// parameter that every hop would have to repeat.
//
// The Server never validates this value. It only forwards it, because
// authorization belongs to the Endpoint that owns the machine.
func WithEndpointToken(ctx context.Context, token string) context.Context {
	return context.WithValue(ctx, endpointTokenContextKey{}, token)
}

// EndpointToken returns the Endpoint token attached by the operator API
// boundary. An absent token is the empty string, which the Endpoint refuses:
// a missing credential must never be weaker than a wrong one.
func EndpointToken(ctx context.Context) string {
	token, ok := ctx.Value(endpointTokenContextKey{}).(string)
	if !ok {
		return ""
	}
	return token
}

// WithEndpointCredential attaches a parsed Endpoint credential to a context.
func WithEndpointCredential(ctx context.Context, credential EndpointCredential) context.Context {
	return context.WithValue(ctx, endpointCredentialContextKey{}, credential)
}

// endpointCredentialContextKey is the private key type for the parsed credential.
type endpointCredentialContextKey struct{}

// EndpointCredentialFrom returns the parsed Endpoint credential attached by the
// operator API boundary.
//
// It falls back to the plain token carrier so a caller that only set a token
// still produces a bearer credential. The fallback is deliberate and narrow: it
// converts a token into the bearer form only, never into the HMAC form, because
// inventing a signature is impossible and pretending one exists would fail
// verification with a message that blames the caller's secret.
func EndpointCredentialFrom(ctx context.Context) EndpointCredential {
	if credential, ok := ctx.Value(endpointCredentialContextKey{}).(EndpointCredential); ok {
		return credential
	}
	if token := EndpointToken(ctx); token != "" {
		return EndpointCredential{Token: token}
	}
	return EndpointCredential{}
}

// WithEndpointKeyID records the key identifier a verified Endpoint credential
// proved.
//
// The value is public, so it may be logged and used as the policy lookup key. It
// is attached only after verification succeeds, so a handler that reads it can
// rely on the credential having been proven rather than merely presented.
func WithEndpointKeyID(ctx context.Context, keyID string) context.Context {
	return context.WithValue(ctx, endpointKeyIDContextKey{}, keyID)
}

// EndpointKeyID returns the verified Endpoint key identifier, or the empty
// string when no HMAC credential was verified.
func EndpointKeyID(ctx context.Context) string {
	keyID, ok := ctx.Value(endpointKeyIDContextKey{}).(string)
	if !ok {
		return ""
	}
	return keyID
}

// EndpointCredentialFor returns the credential to attach to a frame, or nil when
// the caller presented none.
//
// It returns a pointer so an absent credential is omitted from the frame rather
// than encoded as an empty object. The distinction matters: an Endpoint that
// enforces a policy refuses an absent credential, and it must be able to tell
// "nothing was presented" from "an empty credential was presented", because the
// second is a malformed request rather than a missing one.
func EndpointCredentialFor(ctx context.Context) *EndpointCredential {
	credential := EndpointCredentialFrom(ctx)
	if credential.IsZero() {
		return nil
	}
	return &credential
}

// AsSignature returns the HMAC form of the credential as a Signature.
//
// It exists so verification reuses the one Signature type and the one Verifier
// rather than growing a second parser for the same four fields. A credential that
// carries no signature returns the zero Signature, which the Verifier refuses as
// an unknown key identifier instead of accepting as an empty proof.
func (c EndpointCredential) AsSignature() Signature {
	return Signature{
		KeyID:       c.KeyID,
		TimestampMS: c.TimestampMS,
		Nonce:       c.Nonce,
		Signature:   c.Signature,
	}
}

// IsHMAC reports whether the credential carries the HMAC form.
func (c EndpointCredential) IsHMAC() bool {
	return c.Signature != ""
}

// IsBearer reports whether the credential carries the bearer form.
func (c EndpointCredential) IsBearer() bool {
	return c.Token != ""
}

// EndpointRequestDigest returns the digest that binds an Endpoint credential to
// one operator request.
//
// It covers the method, the request target including its query string, and the
// body, because those three are what select the work the Endpoint will perform.
// The Server computes it from the request it actually received and forwards it
// opaquely, so the digest describes the request that arrived rather than the
// request the caller claims to have sent. That is what stops a captured
// signature from being replayed against a different target.
//
// The digest deliberately covers the raw request target rather than the protocol
// struct the Server forwards. The Server normalizes query values before building
// that struct, so a digest over the struct could not be computed by the caller:
// an absent bound becomes a default and an oversized one is clamped, and the
// caller would have to duplicate that normalization to agree. The raw target is
// the only material both sides derive identically.
func EndpointRequestDigest(method, requestURI string, body []byte) string {
	sum := sha256.Sum256([]byte(method + "\n" + requestURI + "\n" + BodyDigest(body)))
	return hex.EncodeToString(sum[:])
}

// endpointRequestDigestContextKey is the private key type for the request digest.
type endpointRequestDigestContextKey struct{}

// WithEndpointRequestDigest attaches the digest of the operator request that
// carried this credential.
//
// The Server attaches it because the Server is the only party that sees the
// request as it arrived. The Endpoint reads it to verify the signature, and never
// recomputes it, because the Endpoint never sees the HTTP request.
func WithEndpointRequestDigest(ctx context.Context, digest string) context.Context {
	return context.WithValue(ctx, endpointRequestDigestContextKey{}, digest)
}

// EndpointRequestDigestFrom returns the request digest attached by the operator
// API boundary, or the empty string when the credential was not signed.
func EndpointRequestDigestFrom(ctx context.Context) string {
	digest, ok := ctx.Value(endpointRequestDigestContextKey{}).(string)
	if !ok {
		return ""
	}
	return digest
}

// VerifyEndpointCredential proves one Endpoint credential for one frame.
//
// The credential must be in the HMAC form. A bearer credential is refused rather
// than verified, because an Endpoint configured for HMAC mode must not accept the
// weaker syntax: accepting it would let any caller downgrade the mode by sending
// the secret in the clear, which is the exact exposure HMAC mode exists to remove.
// The refusal is an authentication error, never a policy decision, so the caller
// learns that its credential form was wrong instead of believing its grants were
// insufficient.
//
// The signed message covers the operation, the Endpoint identity and the request
// digest, so a credential captured for one operation on one machine cannot be
// replayed for a different operation, against a different machine, or against a
// different request. Replay of the identical request inside the window is refused
// by the nonce cache.
func VerifyEndpointCredential(verifier *Verifier, credential EndpointCredential, operation, endpointID, requestDigest string) error {
	if !credential.IsHMAC() {
		return ErrEndpointCredentialNotSigned
	}
	message := CanonicalFrameRequest(operation, endpointID, requestDigest, credential.TimestampMS, credential.Nonce)
	return verifier.Verify(message, credential.AsSignature())
}
