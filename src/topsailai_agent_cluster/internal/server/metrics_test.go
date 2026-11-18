package server

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// metricsRequesterStub answers one message-count read with a fixed result or
// error, and records what the handler forwarded so the request shape is asserted
// rather than assumed.
type metricsRequesterStub struct {
	result       protocol.SessionMetrics
	err          error
	calls        int
	lastEndpoint string
	lastQuery    protocol.SessionMetricsQuery
}

// RequestOutput preserves the output seam the Handler field requires.
func (s *metricsRequesterStub) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// RequestMetrics records the forwarded query and answers with the fixed result.
func (s *metricsRequesterStub) RequestMetrics(_ context.Context, endpointID string, query protocol.SessionMetricsQuery) (protocol.SessionMetrics, error) {
	s.calls++
	s.lastEndpoint = endpointID
	s.lastQuery = query
	if s.err != nil {
		return protocol.SessionMetrics{}, s.err
	}
	return s.result, nil
}

// outputOnlyRequester implements the output seam and nothing else, so the
// metrics capability assertion must fail and the route must report that the
// channel is unavailable instead of pretending the read succeeded.
type outputOnlyRequester struct{}

// RequestOutput satisfies OutputRequester only.
func (outputOnlyRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// metricsHandler builds a handler whose output seam is the supplied requester.
// Both metrics routes share it because they share the same seam.
func metricsHandler(output OutputRequester) *Handler {
	return &Handler{Authenticator: security.BearerAuthenticator{Token: "test"}, Output: output}
}

// metricsCall issues one authenticated metrics request and returns the recorder.
func metricsCall(t *testing.T, handler http.Handler, method, path, token string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

// TestMetricsHTTPClient proves the happy path through the real HTTP and client
// boundary, so the request shape is verified end to end rather than by calling
// the handler directly.
func TestMetricsHTTPClient(t *testing.T) {
	stub := &metricsRequesterStub{result: protocol.SessionMetrics{
		ProviderSessionID: "s 1",
		Messages:          protocol.MessageCounts{Inbound: 3, Outbound: 5},
		ObservedAtMS:      1000,
	}}
	server := httptest.NewServer(metricsHandler(stub))
	defer server.Close()
	api := newBearerAPIClient(server.URL, "test")
	got, err := api.GetMetrics(context.Background(), "e /1", "s 1")
	if err != nil {
		t.Fatalf("GetMetrics: %v", err)
	}
	if got.Messages.Inbound != 3 || got.Messages.Outbound != 5 {
		t.Fatalf("counts = %+v, want inbound=3 outbound=5", got.Messages)
	}
	if got.ProviderSessionID != "s 1" {
		t.Fatalf("session id = %q, want %q", got.ProviderSessionID, "s 1")
	}
	if stub.calls != 1 {
		t.Fatalf("forwarded calls = %d, want 1", stub.calls)
	}
	if stub.lastEndpoint != "e /1" {
		t.Fatalf("forwarded endpoint = %q, want %q", stub.lastEndpoint, "e /1")
	}
	if stub.lastQuery.ProviderSessionID != "s 1" {
		t.Fatalf("forwarded session = %q, want %q", stub.lastQuery.ProviderSessionID, "s 1")
	}
}

// TestMetricsRequestValidation covers every rejection that happens before the
// Endpoint is reached, and proves none of them forwards a query.
func TestMetricsRequestValidation(t *testing.T) {
	stub := &metricsRequesterStub{}
	handler := metricsHandler(stub)
	for _, item := range []struct {
		name, method, path, token string
		status                    int
		wantCode                  string
	}{
		{"missing token", http.MethodGet, "/api/v1/metrics?endpoint_id=e&session_id=s", "", 401, ""},
		{"wrong method", http.MethodPost, "/api/v1/metrics?endpoint_id=e&session_id=s", "test", 405, "method_not_allowed"},
		{"missing endpoint", http.MethodGet, "/api/v1/metrics?session_id=s", "test", 400, "invalid_target"},
		{"missing session", http.MethodGet, "/api/v1/metrics?endpoint_id=e", "test", 400, "invalid_target"},
	} {
		t.Run(item.name, func(t *testing.T) {
			rec := metricsCall(t, handler, item.method, item.path, item.token)
			if rec.Code != item.status {
				t.Fatalf("status = %d, want %d, body = %s", rec.Code, item.status, rec.Body.String())
			}
			if item.wantCode != "" && !strings.Contains(rec.Body.String(), item.wantCode) {
				t.Fatalf("body = %s, want code %q", rec.Body.String(), item.wantCode)
			}
		})
	}
	if stub.calls != 0 {
		t.Fatalf("forwarded calls = %d, want 0: a rejected request must not reach the Endpoint", stub.calls)
	}
}

// TestMetricsReportsUnavailableChannel proves a handler without the metrics seam
// reports the missing capability instead of answering with an empty result.
func TestMetricsReportsUnavailableChannel(t *testing.T) {
	rec := metricsCall(t, metricsHandler(outputOnlyRequester{}), http.MethodGet, "/api/v1/metrics?endpoint_id=e&session_id=s", "test")
	if rec.Code != 503 {
		t.Fatalf("status = %d, want 503, body = %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "unavailable") {
		t.Fatalf("body = %s, want code %q", rec.Body.String(), "unavailable")
	}
}

// TestMetricsResultClassification covers every branch of the result mapper.
//
// Each outcome keeps its own status because they are different facts: an
// unsupported adapter is not an outage, an unmeasurable session is not a
// provider fault, and a refused caller was never forwarded. Collapsing any of
// them into the provider default would send the operator to investigate a
// provider that was never invoked.
//
// The rejected-identity branch is covered by
// TestMetricsRejectedIdentityIsACallerError in request_identity_test.go, which
// also proves the outcome is not reported as a provider failure, so it is not
// repeated here.
func TestMetricsResultClassification(t *testing.T) {
	for _, item := range []struct {
		name, errorCode, wantCode string
		status                    int
	}{
		{"unsupported adapter", protocol.MetricsUnsupported, protocol.MetricsUnsupported, 501},
		{"unknown session", protocol.MetricsSessionNotFound, protocol.MetricsSessionNotFound, 404},
		{"no live process", protocol.MetricsUnavailable, protocol.MetricsUnavailable, 409},
		{"endpoint offline", "endpoint_unavailable", "endpoint_unavailable", 503},
		{"credential rejected", protocol.CredentialRejected, protocol.CredentialRejected, 401},
		{"policy refused", protocol.PolicyDenied, protocol.PolicyDenied, 403},
		{"adapter busy", protocol.AdapterBusy, protocol.AdapterBusy, 503},
		{"provider fault", "provider_failed", protocol.MetricsProviderError, 502},
	} {
		t.Run(item.name, func(t *testing.T) {
			stub := &metricsRequesterStub{result: protocol.SessionMetrics{ProviderSessionID: "s1", ErrorCode: item.errorCode}}
			rec := metricsCall(t, metricsHandler(stub), http.MethodGet, "/api/v1/metrics?endpoint_id=e&session_id=s1", "test")
			if rec.Code != item.status {
				t.Fatalf("status = %d, want %d, body = %s", rec.Code, item.status, rec.Body.String())
			}
			if !strings.Contains(rec.Body.String(), item.wantCode) {
				t.Fatalf("body = %s, want code %q", rec.Body.String(), item.wantCode)
			}
		})
	}
}

// TestMetricsDistinguishesUnknownEndpointFromOffline proves a typo is not
// reported as an outage. The distinction needs a real store, because it is the
// store lookup that separates "no such address" from "address unreachable".
func TestMetricsDistinguishesUnknownEndpointFromOffline(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	handler := metricsHandler(&metricsRequesterStub{err: errors.New("endpoint is offline")})
	handler.Store = store
	for _, item := range []struct {
		name, endpoint, wantCode string
		status                   int
	}{
		{"registered but offline", "e1", "endpoint_unavailable", 503},
		{"never registered", "e-typo", "endpoint_not_found", 404},
	} {
		t.Run(item.name, func(t *testing.T) {
			rec := metricsCall(t, handler, http.MethodGet, "/api/v1/metrics?endpoint_id="+item.endpoint+"&session_id=s1", "test")
			if rec.Code != item.status {
				t.Fatalf("status = %d, want %d, body = %s", rec.Code, item.status, rec.Body.String())
			}
			if !strings.Contains(rec.Body.String(), item.wantCode) {
				t.Fatalf("body = %s, want code %q", rec.Body.String(), item.wantCode)
			}
		})
	}
}
