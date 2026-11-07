// Package security provides boundary authentication and authorization helpers.
package security

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"net/http"
	"strings"
)

// BearerAuthenticator validates one pre-provisioned management credential.
type BearerAuthenticator struct {
	Token  string
	Scopes ScopeSet
}

// Authenticate verifies the Authorization header and returns a stable request identity.
func (a BearerAuthenticator) Authenticate(r *http.Request) (string, bool) {
	identity, _, ok := a.AuthenticateScopes(r)
	return identity, ok
}

// AuthenticateScopes verifies the Authorization header and returns the request
// identity together with the scopes granted to that credential. An empty scope
// set means the credential is unrestricted.
func (a BearerAuthenticator) AuthenticateScopes(r *http.Request) (string, ScopeSet, bool) {
	if a.Token == "" {
		return "", nil, false
	}
	value := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if !strings.HasPrefix(value, prefix) || value[len(prefix):] != a.Token {
		return "", nil, false
	}
	return "operator", a.Scopes, true
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

// NewRequestID returns an opaque identifier for request correlation.
func NewRequestID() string {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "req_unknown"
	}
	return "req_" + hex.EncodeToString(raw[:])
}
