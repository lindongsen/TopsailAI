package server

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/client"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
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

// launchFailureRequester fails every launch query, so the handler must classify it.
type launchFailureRequester struct{ launchRequester }

// RequestLaunchOptions always fails, standing in for an offline endpoint.
func (launchFailureRequester) RequestLaunchOptions(context.Context, string, protocol.LaunchQuery) (protocol.LaunchOptions, error) {
	return protocol.LaunchOptions{}, errors.New("endpoint is offline")
}

// TestLaunchOptionsDistinguishesUnknownEndpointFromOffline proves a typo is no
// longer reported as an availability failure.
func TestLaunchOptionsDistinguishesUnknownEndpointFromOffline(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "known", InstanceID: "known-1", DisplayName: "known", Hostname: "host-known", ConnectionState: "online", CapabilityRevision: "v1"}, 1000); err != nil {
		t.Fatal(err)
	}
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: launchFailureRequester{}, Store: store}
	for _, item := range []struct {
		endpointID string
		status     int
		code       string
	}{
		{endpointID: "missing", status: http.StatusNotFound, code: "endpoint_not_found"},
		{endpointID: "known", status: http.StatusServiceUnavailable, code: "endpoint_unavailable"},
	} {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/launch-options?endpoint_id="+item.endpointID, nil)
		req.Header.Set("Authorization", "Bearer test")
		out := httptest.NewRecorder()
		h.ServeHTTP(out, req)
		if out.Code != item.status {
			t.Fatalf("endpoint %q status=%d want=%d body=%s", item.endpointID, out.Code, item.status, out.Body.String())
		}
		if !strings.Contains(out.Body.String(), `"`+item.code+`"`) {
			t.Fatalf("endpoint %q body=%s want code %q", item.endpointID, out.Body.String(), item.code)
		}
	}
}
