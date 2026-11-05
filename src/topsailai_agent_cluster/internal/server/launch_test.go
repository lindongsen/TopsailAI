package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"topsailai_agent_cluster/internal/client"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

type launchRequester struct{}

// RequestOutput preserves the existing constructor's output interface.
func (launchRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// RequestLaunchOptions supplies a test handler response through the real HTTP/client boundary.
func (launchRequester) RequestLaunchOptions(_ context.Context, endpoint string, query protocol.LaunchQuery) (protocol.LaunchOptions, error) {
	return protocol.LaunchOptions{Handlers: []protocol.LaunchHandler{{AdapterID: query.AdapterID, Revision: endpoint}}, Projects: []protocol.Project{{Name: "工程", Path: "/work/my app"}}}, nil
}

// TestLaunchHTTPClient verifies auth, method validation and encoded selectors.
func TestLaunchHTTPClient(t *testing.T) {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: launchRequester{}}
	server := httptest.NewServer(h)
	defer server.Close()
	api := client.NewAPIClient(server.URL, "test")
	result, err := api.GetLaunchOptions(context.Background(), "e /1", "a&1")
	if err != nil || result.Handlers[0].AdapterID != "a&1" || result.Handlers[0].Revision != "e /1" {
		t.Fatalf("%#v %v", result, err)
	}
	for _, item := range []struct {
		method, path, token string
		status              int
	}{
		{http.MethodGet, "/api/v1/launch-options?endpoint_id=e", "", 401},
		{http.MethodPost, "/api/v1/launch-options?endpoint_id=e", "test", 405},
		{http.MethodGet, "/api/v1/launch-options", "test", 400},
	} {
		req := httptest.NewRequest(item.method, item.path, nil)
		req.Header.Set("Authorization", "Bearer "+item.token)
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("%d want %d", out.Code, item.status)
		}
	}
}
