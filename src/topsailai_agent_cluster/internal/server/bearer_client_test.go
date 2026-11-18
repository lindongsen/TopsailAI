package server

import (
	"topsailai_agent_cluster/internal/client"
	"topsailai_agent_cluster/internal/security"
)

// newBearerAPIClient constructs a client that presents a plain bearer token.
//
// These tests pair a BearerAuthenticator with a plain token, so they assert
// request plumbing rather than the authentication mode. HMAC is the default and
// requires a key_id.secret credential, so a plain token would make every
// assertion describe the signature instead of the token.
func newBearerAPIClient(baseURL, token string) *client.APIClient {
	api := client.NewAPIClient(baseURL, token)
	api.AuthMode = security.ModeBearer
	return api
}
