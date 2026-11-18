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
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// metricsBatchRequesterStub answers one set read with a fixed result or error,
// and records what the handler forwarded so the set is asserted rather than
// assumed.
type metricsBatchRequesterStub struct {
	result       protocol.SessionMetricsBatch
	err          error
	calls        int
	lastEndpoint string
	lastQuery    protocol.SessionMetricsBatchQuery
}

// RequestOutput preserves the output seam the Handler field requires.
func (s *metricsBatchRequesterStub) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// RequestMetricsBatch records the forwarded set and answers with the fixed result.
func (s *metricsBatchRequesterStub) RequestMetricsBatch(_ context.Context, endpointID string, query protocol.SessionMetricsBatchQuery) (protocol.SessionMetricsBatch, error) {
	s.calls++
	s.lastEndpoint = endpointID
	s.lastQuery = query
	if s.err != nil {
		return protocol.SessionMetricsBatch{}, s.err
	}
	return s.result, nil
}

// metricsBatchCall issues one authenticated batch request with an optional body.
func metricsBatchCall(t *testing.T, handler http.Handler, method, body, token string) *httptest.ResponseRecorder {
	t.Helper()
	var reader *strings.Reader
	if body == "" {
		reader = strings.NewReader("")
	} else {
		reader = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, "/api/v1/metrics/batch", reader)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

// TestMetricsBatchHTTPClient proves the happy path through the real HTTP and
// client boundary, so the set survives the round trip rather than being verified
// by a direct handler call.
func TestMetricsBatchHTTPClient(t *testing.T) {
	stub := &metricsBatchRequesterStub{result: protocol.SessionMetricsBatch{
		Results: []protocol.SessionMetrics{
			{ProviderSessionID: "s1", Messages: protocol.MessageCounts{Inbound: 1, Outbound: 2}, ObservedAtMS: 1000},
			{ProviderSessionID: "s2", Messages: protocol.MessageCounts{Inbound: 3, Outbound: 4}, ObservedAtMS: 1000},
		},
		ObservedAtMS: 1000,
	}}
	server := httptest.NewServer(metricsHandler(stub))
	defer server.Close()
	api := newBearerAPIClient(server.URL, "test")
	got, err := api.GetMetricsBatch(context.Background(), "e /1", []string{"s1", "s2"})
	if err != nil {
		t.Fatalf("GetMetricsBatch: %v", err)
	}
	if len(got.Results) != 2 {
		t.Fatalf("results = %d, want 2", len(got.Results))
	}
	if got.Results[1].Messages.Inbound != 3 || got.Results[1].Messages.Outbound != 4 {
		t.Fatalf("second member counts = %+v, want inbound=3 outbound=4", got.Results[1].Messages)
	}
	if stub.calls != 1 {
		t.Fatalf("forwarded calls = %d, want 1", stub.calls)
	}
	if stub.lastEndpoint != "e /1" {
		t.Fatalf("forwarded endpoint = %q, want %q", stub.lastEndpoint, "e /1")
	}
	if len(stub.lastQuery.ProviderSessionIDs) != 2 || stub.lastQuery.ProviderSessionIDs[0] != "s1" || stub.lastQuery.ProviderSessionIDs[1] != "s2" {
		t.Fatalf("forwarded set = %v, want [s1 s2]", stub.lastQuery.ProviderSessionIDs)
	}
}

// TestMetricsBatchPreservesPartialSuccess proves a set where one member was never
// answered still returns 200 and keeps the members that were measured.
//
// This is the property the route exists for: a member failure is not a
// whole-request failure, so classifying it as one would discard the measured
// members and turn one missing session into an empty column.
func TestMetricsBatchPreservesPartialSuccess(t *testing.T) {
	stub := &metricsBatchRequesterStub{result: protocol.SessionMetricsBatch{
		Results: []protocol.SessionMetrics{
			{ProviderSessionID: "s1", Messages: protocol.MessageCounts{Inbound: 7, Outbound: 8}, ObservedAtMS: 1000},
		},
		ObservedAtMS: 1000,
	}}
	server := httptest.NewServer(metricsHandler(stub))
	defer server.Close()
	api := newBearerAPIClient(server.URL, "test")
	got, err := api.GetMetricsBatch(context.Background(), "e1", []string{"s1", "s2", "s3"})
	if err != nil {
		t.Fatalf("GetMetricsBatch: %v", err)
	}
	if len(got.Results) != 1 {
		t.Fatalf("results = %d, want 1: the measured member must survive two unanswered ones", len(got.Results))
	}
	if got.Results[0].ProviderSessionID != "s1" || got.Results[0].Messages.Inbound != 7 {
		t.Fatalf("measured member = %+v, want s1 inbound=7", got.Results[0])
	}
}

// TestMetricsBatchRequestValidation covers every rejection that happens before
// the Endpoint is reached, and proves none of them forwards a query.
func TestMetricsBatchRequestValidation(t *testing.T) {
	overBound := make([]string, protocol.MaxMetricsBatchSessions+1)
	for i := range overBound {
		overBound[i] = "s"
	}
	overBoundBody := `{"endpoint_id":"e1","provider_session_ids":["` + strings.Join(overBound, `","`) + `"]}`
	stub := &metricsBatchRequesterStub{}
	handler := metricsHandler(stub)
	for _, item := range []struct {
		name, method, body, token string
		status                    int
		wantCode                  string
	}{
		{"missing token", http.MethodPost, `{"endpoint_id":"e1","provider_session_ids":["s1"]}`, "", 401, ""},
		{"wrong method", http.MethodGet, "", "test", 405, "method_not_allowed"},
		{"malformed body", http.MethodPost, `{"endpoint_id":`, "test", 400, "invalid_request"},
		{"unknown field", http.MethodPost, `{"endpoint_id":"e1","provider_session_ids":["s1"],"extra":1}`, "test", 400, "invalid_request"},
		{"missing endpoint", http.MethodPost, `{"provider_session_ids":["s1"]}`, "test", 400, "invalid_target"},
		{"empty set", http.MethodPost, `{"endpoint_id":"e1","provider_session_ids":[]}`, "test", 400, "invalid_target"},
		{"absent set", http.MethodPost, `{"endpoint_id":"e1"}`, "test", 400, "invalid_target"},
		{"over bound", http.MethodPost, overBoundBody, "test", 400, "invalid_target"},
	} {
		t.Run(item.name, func(t *testing.T) {
			rec := metricsBatchCall(t, handler, item.method, item.body, item.token)
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

// TestMetricsBatchAcceptsTheBoundExactly proves the bound is inclusive, so a set
// of exactly MaxMetricsBatchSessions is accepted rather than refused by an
// off-by-one.
func TestMetricsBatchAcceptsTheBoundExactly(t *testing.T) {
	atBound := make([]string, protocol.MaxMetricsBatchSessions)
	for i := range atBound {
		atBound[i] = "s"
	}
	body := `{"endpoint_id":"e1","provider_session_ids":["` + strings.Join(atBound, `","`) + `"]}`
	stub := &metricsBatchRequesterStub{}
	rec := metricsBatchCall(t, metricsHandler(stub), http.MethodPost, body, "test")
	if rec.Code != 200 {
		t.Fatalf("status = %d, want 200, body = %s", rec.Code, rec.Body.String())
	}
	if stub.calls != 1 {
		t.Fatalf("forwarded calls = %d, want 1", stub.calls)
	}
	if len(stub.lastQuery.ProviderSessionIDs) != protocol.MaxMetricsBatchSessions {
		t.Fatalf("forwarded set = %d, want %d", len(stub.lastQuery.ProviderSessionIDs), protocol.MaxMetricsBatchSessions)
	}
}

// TestMetricsBatchReportsUnavailableChannel proves a handler without the batch
// seam reports the missing capability instead of answering with an empty set.
func TestMetricsBatchReportsUnavailableChannel(t *testing.T) {
	rec := metricsBatchCall(t, metricsHandler(outputOnlyRequester{}), http.MethodPost, `{"endpoint_id":"e1","provider_session_ids":["s1"]}`, "test")
	if rec.Code != 503 {
		t.Fatalf("status = %d, want 503, body = %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "unavailable") {
		t.Fatalf("body = %s, want code %q", rec.Body.String(), "unavailable")
	}
}

// TestMetricsBatchResultClassification covers every branch of the batch result
// mapper.
//
// The top-level error code is reserved for a failure that applies to the whole
// request, so each branch must keep its own status. A refused caller was never
// forwarded and a busy adapter was never invoked, so neither may share the
// provider default.
func TestMetricsBatchResultClassification(t *testing.T) {
	for _, item := range []struct {
		name, errorCode, wantCode string
		status                    int
	}{
		{"unsupported adapter", protocol.MetricsUnsupported, protocol.MetricsUnsupported, 501},
		{"endpoint offline", "endpoint_unavailable", "endpoint_unavailable", 503},
		{"credential rejected", protocol.CredentialRejected, protocol.CredentialRejected, 401},
		{"policy refused", protocol.PolicyDenied, protocol.PolicyDenied, 403},
		{"adapter busy", protocol.AdapterBusy, protocol.AdapterBusy, 503},
		{"provider fault", "provider_failed", protocol.MetricsProviderError, 502},
	} {
		t.Run(item.name, func(t *testing.T) {
			stub := &metricsBatchRequesterStub{result: protocol.SessionMetricsBatch{ErrorCode: item.errorCode}}
			rec := metricsBatchCall(t, metricsHandler(stub), http.MethodPost, `{"endpoint_id":"e1","provider_session_ids":["s1"]}`, "test")
			if rec.Code != item.status {
				t.Fatalf("status = %d, want %d, body = %s", rec.Code, item.status, rec.Body.String())
			}
			if !strings.Contains(rec.Body.String(), item.wantCode) {
				t.Fatalf("body = %s, want code %q", rec.Body.String(), item.wantCode)
			}
		})
	}
}

// TestMetricsBatchDistinguishesUnknownEndpointFromOffline proves a typo is not
// reported as an outage. The distinction needs a real store, because it is the
// store lookup that separates "no such address" from "address unreachable".
func TestMetricsBatchDistinguishesUnknownEndpointFromOffline(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	handler := metricsHandler(&metricsBatchRequesterStub{err: errors.New("endpoint is offline")})
	handler.Store = store
	for _, item := range []struct {
		name, endpoint, wantCode string
		status                   int
	}{
		{"registered but offline", "e1", "endpoint_unavailable", 503},
		{"never registered", "e-typo", "endpoint_not_found", 404},
	} {
		t.Run(item.name, func(t *testing.T) {
			body := `{"endpoint_id":"` + item.endpoint + `","provider_session_ids":["s1"]}`
			rec := metricsBatchCall(t, handler, http.MethodPost, body, "test")
			if rec.Code != item.status {
				t.Fatalf("status = %d, want %d, body = %s", rec.Code, item.status, rec.Body.String())
			}
			if !strings.Contains(rec.Body.String(), item.wantCode) {
				t.Fatalf("body = %s, want code %q", rec.Body.String(), item.wantCode)
			}
		})
	}
}
