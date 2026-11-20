package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// modelRegistryRequester records the Endpoint credential the Server forwarded and
// returns one configured result.
type modelRegistryRequester struct {
	token  string
	code   string
	result protocol.ModelRegistry
}

// RequestOutput satisfies the output seam so the handler can be built without a
// second stub.
func (r *modelRegistryRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// RequestModelRegistry returns the configured registry and records the forwarded
// Endpoint credential.
func (r *modelRegistryRequester) RequestModelRegistry(ctx context.Context, endpointID string, _ protocol.ModelRegistryQuery) (protocol.ModelRegistry, error) {
	r.token = security.EndpointCredentialFrom(ctx).Token
	result := r.result
	result.ErrorCode = r.code
	if result.Entries == nil {
		result.Entries = []protocol.ModelRegistryEntry{{ModelProfileID: "mp-1", ProviderDisplayName: endpointID, Available: true}}
	}
	if result.CurrentSource == "" {
		result.CurrentSource = protocol.ModelSourceWorkspace
	}
	return result, nil
}

// TestModelRegistryHTTPClient verifies the real route, the encoded endpoint and the
// typed result.
//
// The route takes only endpoint_id. A resource_id is deliberately not accepted,
// because a registry describes the machine rather than one session.
func TestModelRegistryHTTPClient(t *testing.T) {
	requester := &modelRegistryRequester{}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: requester}
	server := httptest.NewServer(h)
	defer server.Close()
	api := newBearerAPIClient(server.URL, "test")
	result, err := api.GetModelRegistry(context.Background(), "e /1")
	if err != nil || len(result.Entries) != 1 || result.Entries[0].ProviderDisplayName != "e /1" {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	for _, item := range []struct {
		method string
		path   string
		token  string
		status int
	}{
		{http.MethodGet, "/api/v1/model-registry?endpoint_id=e", "", http.StatusUnauthorized},
		{http.MethodPost, "/api/v1/model-registry?endpoint_id=e", "test", http.StatusMethodNotAllowed},
		{http.MethodGet, "/api/v1/model-registry", "test", http.StatusBadRequest},
	} {
		req := httptest.NewRequest(item.method, item.path, nil)
		req.Header.Set("Authorization", "Bearer "+item.token)
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("%s %s status=%d want=%d body=%s", item.method, item.path, out.Code, item.status, out.Body.String())
		}
	}
}

// TestModelRegistryForwardsEndpointToken proves Endpoint authority remains local:
// the Server forwards the credential and never decides what it permits.
func TestModelRegistryForwardsEndpointToken(t *testing.T) {
	requester := &modelRegistryRequester{}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: requester}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/model-registry?endpoint_id=e", nil)
	req.Header.Set("Authorization", "Bearer test")
	req.Header.Set(endpointTokenHeader, "endpoint-secret")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusOK || requester.token != "endpoint-secret" {
		t.Fatalf("status=%d token=%q body=%s", out.Code, requester.token, out.Body.String())
	}
}

// TestModelRegistryMapsEndpointRefusals preserves the credential and policy
// boundaries, and keeps a capability gap distinguishable from a provider failure.
func TestModelRegistryMapsEndpointRefusals(t *testing.T) {
	for _, item := range []struct {
		code   string
		status int
	}{
		{protocol.ModelRegistryUnsupported, http.StatusNotImplemented},
		{protocol.ModelRegistryTooLarge, http.StatusBadGateway},
		{protocol.ModelRegistrySelectionInvalid, http.StatusConflict},
		{protocol.PolicyDenied, http.StatusForbidden},
		{protocol.CredentialRejected, http.StatusUnauthorized},
		{protocol.AdapterBusy, http.StatusServiceUnavailable},
		{"endpoint_unavailable", http.StatusServiceUnavailable},
		{protocol.ModelRegistryProviderError, http.StatusBadGateway},
	} {
		h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: &modelRegistryRequester{code: item.code}}
		req := httptest.NewRequest(http.MethodGet, "/api/v1/model-registry?endpoint_id=e", nil)
		req.Header.Set("Authorization", "Bearer test")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("code=%s status=%d want=%d body=%s", item.code, out.Code, item.status, out.Body.String())
		}
	}
}

// TestModelRegistryReportsAnEmptyRegistryAsSuccess proves an Endpoint that answers
// "no model configured" is a successful read, not an error. Reporting it as a
// failure would tell an operator to investigate a machine that answered correctly.
func TestModelRegistryReportsAnEmptyRegistryAsSuccess(t *testing.T) {
	requester := &modelRegistryRequester{result: protocol.ModelRegistry{
		Entries:       []protocol.ModelRegistryEntry{},
		CurrentSource: protocol.ModelSourceInherited,
		ObservedAtMS:  1,
	}}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: requester}
	req := httptest.NewRequest(http.MethodGet, "/api/v1/model-registry?endpoint_id=e", nil)
	req.Header.Set("Authorization", "Bearer test")
	out := httptest.NewRecorder()
	h.ServeHTTP(out, req)
	if out.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", out.Code, out.Body.String())
	}
}
