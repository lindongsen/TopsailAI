// Package security provides boundary authentication and authorization helpers.
package security

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// RequestAuthenticator validates one inbound request credential.
//
// It is an interface rather than one concrete type because the Server accepts two
// authentication modes and must not know which one a deployment selected. A
// concrete field would force every caller to construct the mode-specific type and
// would make the mode a compile-time decision instead of a configuration decision.
type RequestAuthenticator interface {
	Authenticate(*http.Request) (string, bool)
}

// BearerAuthenticator validates one pre-provisioned management credential.
type BearerAuthenticator struct {
	Token string
}

// Authenticate verifies the Authorization header and returns a stable request identity.
//
// The Server authenticates a caller but does not decide what that caller may do on
// a machine: authorization belongs to the Endpoint that owns the machine.
func (a BearerAuthenticator) Authenticate(r *http.Request) (string, bool) {
	if a.Token == "" {
		return "", false
	}
	value := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if !strings.HasPrefix(value, prefix) {
		return "", false
	}
	// The comparison is constant time because a byte-wise early exit leaks how
	// many leading bytes matched, which lets an attacker recover the token one
	// byte at a time. Network jitter hides most of that signal, but a known
	// timing oracle must not be left in place beside a stronger scheme.
	if !ConstantTimeEqual(value[len(prefix):], a.Token) {
		return "", false
	}
	return "operator", true
}

// CredentialAuthenticator validates requests in the configured authentication mode.
//
// Exactly one mode is active at a time. A request that fails in the active mode is
// refused; it is never retried in the other mode, because a fallback would let an
// attacker downgrade a signed deployment to a plaintext credential by simply
// omitting the signature.
type CredentialAuthenticator struct {
	// Mode selects the active scheme. An empty value means ModeHMAC.
	Mode AuthMode
	// Bearer validates the plaintext credential when Mode is ModeBearer.
	Bearer BearerAuthenticator
	// Verifier validates signed credentials when Mode is ModeHMAC.
	Verifier *Verifier
}

// Authenticate validates the request in the configured mode.
func (a CredentialAuthenticator) Authenticate(r *http.Request) (string, bool) {
	mode := a.Mode
	if mode == "" {
		mode = DefaultAuthMode
	}
	switch mode {
	case ModeBearer:
		return a.Bearer.Authenticate(r)
	case ModeHMAC:
		return a.authenticateHMAC(r)
	default:
		// An unrecognised mode refuses every request rather than guessing. A
		// guess would silently authenticate in a scheme the operator did not
		// select, which is the one outcome a security boundary must never
		// produce.
		return "", false
	}
}

// authenticateHMAC verifies a signed request and returns the request identity.
//
// The identity stays "operator" in both modes because it is compared against the
// intent's IssuerID, which the client already sets to that value. The public
// key_id is attached separately for audit, so adding signed credentials does not
// change what an admitted command records as its issuer.
func (a CredentialAuthenticator) authenticateHMAC(r *http.Request) (string, bool) {
	if a.Verifier == nil {
		return "", false
	}
	signature, err := ParseSignatureHeader(r.Header.Get("Authorization"))
	if err != nil {
		return "", false
	}
	body, err := readAndRestoreBody(r)
	if err != nil {
		return "", false
	}
	// The signed path includes the query string because the query selects the
	// target. Signing only the path would let an attacker redirect a read to a
	// different resource while keeping a valid signature.
	message := CanonicalHTTPRequest(r.Method, r.URL.RequestURI(), body, signature.TimestampMS, signature.Nonce)
	if err := a.Verifier.Verify(message, signature); err != nil {
		return "", false
	}
	*r = *r.WithContext(WithCredentialKeyID(r.Context(), signature.KeyID))
	return "operator", true
}

// ReadAndRestoreBody returns the request body and leaves it readable for the
// handler.
//
// It is exported because the Server needs the same bytes twice for two different
// reasons: the authenticator verifies the Server credential over them, and the
// operator boundary digests them into the Endpoint credential binding. Both must
// see the identical bytes, so both use this one reader instead of each draining
// the stream in its own way.
func ReadAndRestoreBody(r *http.Request) ([]byte, error) {
	return readAndRestoreBody(r)
}

// readAndRestoreBody returns the request body and leaves it readable for the handler.
//
// The signature covers the body, so the authentication boundary has to read it
// before the handler decodes it. Restoring the bytes is what keeps the two from
// competing for one stream: without it the handler would decode an empty body and
// report a malformed request for a request that was correctly signed.
func readAndRestoreBody(r *http.Request) ([]byte, error) {
	if r.Body == nil {
		return nil, nil
	}
	body, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	if err := r.Body.Close(); err != nil {
		return nil, err
	}
	r.Body = io.NopCloser(bytes.NewReader(body))
	return body, nil
}

type identityContextKey struct{}

// WithAuthenticatedIdentity attaches the authenticated operator identity to a request context.
func WithAuthenticatedIdentity(ctx context.Context, identity string) context.Context {
	return context.WithValue(ctx, identityContextKey{}, identity)
}

// AuthenticatedIdentity returns the operator identity attached by the authentication boundary.
func AuthenticatedIdentity(ctx context.Context) (string, bool) {
	identity, ok := ctx.Value(identityContextKey{}).(string)
	return identity, ok && identity != ""
}

type credentialKeyIDContextKey struct{}

// WithCredentialKeyID attaches the public credential key identifier to a request context.
//
// The key identifier is not a secret, so recording it makes a refusal attributable
// to one caller without ever writing the credential itself to a log.
func WithCredentialKeyID(ctx context.Context, keyID string) context.Context {
	return context.WithValue(ctx, credentialKeyIDContextKey{}, keyID)
}

// CredentialKeyID returns the public credential key identifier, when one was presented.
func CredentialKeyID(ctx context.Context) (string, bool) {
	keyID, ok := ctx.Value(credentialKeyIDContextKey{}).(string)
	return keyID, ok && keyID != ""
}

// NewRequestID returns an opaque identifier for request correlation.
func NewRequestID() string {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "req_unknown"
	}
	return "req_" + hex.EncodeToString(raw[:])
}

// NewCredentialAuthenticator returns the authenticator for one configured mode.
//
// The credential is interpreted according to the mode, and the two modes accept
// different forms. In HMAC mode the credential must be a key_id.secret pair,
// because the verifier needs the secret to recompute the signature and the key
// identifier to select it. In bearer mode the credential is compared verbatim.
//
// A malformed credential is an error rather than an empty authenticator. An
// authenticator built from a credential that cannot be parsed would refuse every
// request, and the resulting 401 would describe the caller's credential instead
// of the deployment's configuration mistake.
func NewCredentialAuthenticator(mode AuthMode, credential string, window time.Duration) (RequestAuthenticator, error) {
	resolved, err := ParseAuthMode(string(mode))
	if err != nil {
		return nil, err
	}
	switch resolved {
	case ModeBearer:
		return CredentialAuthenticator{Mode: ModeBearer, Bearer: BearerAuthenticator{Token: credential}}, nil
	case ModeHMAC:
		token, err := ParseToken(credential)
		if err != nil {
			return nil, fmt.Errorf("hmac mode requires a key_id.secret credential: %w", err)
		}
		return CredentialAuthenticator{
			Mode:     ModeHMAC,
			Verifier: NewVerifier(map[string]Token{token.KeyID: token}, window),
		}, nil
	default:
		return nil, ErrUnsupportedMode
	}
}
