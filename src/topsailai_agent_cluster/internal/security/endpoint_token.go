package security

import "context"

// endpointTokenContextKey is the private key type for the Endpoint token. A
// distinct unexported type keeps the value from colliding with any other
// context value, including the operator scope set.
type endpointTokenContextKey struct{}

// WithEndpointToken attaches the caller's Endpoint token to a request context.
//
// The token travels in the context rather than in a function parameter because
// every hop between the operator API and the channel frame builder already
// threads a context, while the token is a transport credential that no
// intermediate layer interprets. This mirrors WithAuthenticatedScopes, so the
// two credentials that cross the Server are carried the same way.
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
