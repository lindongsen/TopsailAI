package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// refreshTestServer records forced-collection calls and serves a document that
// differs from the cached projection, so a test can prove the rendered rows came
// from the forced collection rather than from the previous inventory.
type refreshTestServer struct {
	mu        sync.Mutex
	refreshed []string
	server    *httptest.Server
}

func newRefreshTestServer(t *testing.T) *refreshTestServer {
	t.Helper()
	fixture := &refreshTestServer{}
	fixture.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer test-token" {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		switch {
		case r.URL.Path == "/api/v1/endpoints":
			writeListTestEnvelope(w, http.StatusOK, "success", []protocol.Endpoint{
				{EndpointID: "endpoint-1", DisplayName: "endpoint-1", ConnectionState: "online"},
				{EndpointID: "endpoint-2", DisplayName: "endpoint-2", ConnectionState: "online"},
			})
		case r.URL.Path == "/api/v1/endpoints/endpoint-1/session-state/refresh" && r.Method == http.MethodPost:
			fixture.record("endpoint-1")
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory("fresh-1"))
		case r.URL.Path == "/api/v1/endpoints/endpoint-2/session-state/refresh" && r.Method == http.MethodPost:
			fixture.record("endpoint-2")
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory("fresh-2"))
		case r.URL.Path == "/api/v1/endpoints/endpoint-1/session-state":
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory("fresh-1"))
		case r.URL.Path == "/api/v1/endpoints/endpoint-2/session-state":
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory("fresh-2"))
		default:
			writeListTestEnvelope(w, http.StatusNotFound, "not found", nil)
		}
	}))
	t.Cleanup(fixture.server.Close)
	return fixture
}

// record appends one forced-collection call under the mutex.
func (f *refreshTestServer) record(endpointID string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.refreshed = append(f.refreshed, endpointID)
}

// calls returns the recorded forced-collection order.
func (f *refreshTestServer) calls() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.refreshed...)
}

// TestRefreshHelpAndDispatchContract proves the advertised syntax is executable
// and that the command forces a collection instead of reading the projection.
func TestRefreshHelpAndDispatchContract(t *testing.T) {
	var helpOut, helpDiagnostics strings.Builder
	if err := runWithIO([]string{"help", "refresh"}, strings.NewReader(""), &helpOut, &helpDiagnostics, false, nil); err != nil {
		t.Fatal(err)
	}
	const syntax = "agent-cluster-cli [options] [--endpoint <id>] refresh [endpoint] [-a|--all]"
	if !strings.Contains(helpOut.String(), syntax) {
		t.Fatalf("help=%q missing executable syntax %q", helpOut.String(), syntax)
	}
	fixture := newRefreshTestServer(t)
	var output, diagnostics strings.Builder
	args := []string{"--server-url", fixture.server.URL, "--token", "test-token", "refresh"}
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("advertised syntax failed: %v diagnostics=%q", err, diagnostics.String())
	}
	// Endpoints are collected concurrently, so the call order is not part of the
	// contract: the design stores results by Endpoint index and the rendered order
	// never depends on completion order. Assert the set and the exactly-once rule
	// instead of an order the worker pool does not promise.
	if calls := fixture.calls(); !sameStringSet(calls, []string{"endpoint-1", "endpoint-2"}) || len(calls) != 2 {
		t.Fatalf("forced collection calls=%q want each of endpoint-1,endpoint-2 exactly once", calls)
	}
	if !sameStringSet(listSessionIDs(output.String()), []string{"fresh-1", "fresh-2"}) {
		t.Fatalf("rendered rows=%q", output.String())
	}
}

// TestRefreshNarrowsForcedCollectionToFilteredEndpoint proves --endpoint forces
// only the selected endpoint, so a filtered refresh cannot amplify discovery.
func TestRefreshNarrowsForcedCollectionToFilteredEndpoint(t *testing.T) {
	fixture := newRefreshTestServer(t)
	var output, diagnostics strings.Builder
	args := []string{"--server-url", fixture.server.URL, "--token", "test-token", "--endpoint", "endpoint-2", "refresh"}
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("filtered refresh failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if got, want := strings.Join(fixture.calls(), ","), "endpoint-2"; got != want {
		t.Fatalf("forced collection=%q want=%q", got, want)
	}
	if !sameStringSet(listSessionIDs(output.String()), []string{"fresh-2"}) {
		t.Fatalf("rendered rows=%q", output.String())
	}
}

// TestRefreshJSONMatchesListJSON proves the machine-readable surface stays
// identical to list, so automation can switch commands without changing parsing.
func TestRefreshJSONMatchesListJSON(t *testing.T) {
	fixture := newRefreshTestServer(t)
	var refreshOut, refreshErr strings.Builder
	refreshArgs := []string{"--server-url", fixture.server.URL, "--token", "test-token", "--json", "refresh"}
	if err := runWithIO(refreshArgs, strings.NewReader(""), &refreshOut, &refreshErr, false, nil); err != nil {
		t.Fatalf("refresh --json failed: %v diagnostics=%q", err, refreshErr.String())
	}
	var listOut, listErr strings.Builder
	listArgs := []string{"--server-url", fixture.server.URL, "--token", "test-token", "--json", "list"}
	if err := runWithIO(listArgs, strings.NewReader(""), &listOut, &listErr, false, nil); err != nil {
		t.Fatalf("list --json failed: %v diagnostics=%q", err, listErr.String())
	}
	if refreshOut.String() != listOut.String() {
		t.Fatalf("refresh json=%q list json=%q", refreshOut.String(), listOut.String())
	}
}

// TestRefreshAcceptsPositionalEndpoint proves the standalone surface supports the
// same exact Endpoint selection as the interactive command.
func TestRefreshAcceptsPositionalEndpoint(t *testing.T) {
	fixture := newRefreshTestServer(t)
	var output, diagnostics strings.Builder
	args := []string{"--server-url", fixture.server.URL, "--token", "test-token", "refresh", "endpoint-1"}
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("positional refresh failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if got, want := strings.Join(fixture.calls(), ","), "endpoint-1"; got != want {
		t.Fatalf("forced collection=%q want=%q", got, want)
	}
	if !sameStringSet(listSessionIDs(output.String()), []string{"fresh-1"}) {
		t.Fatalf("rendered rows=%q", output.String())
	}
}

// TestRefreshRejectsConflictingSelectorsAndRepeatedAll proves two spellings
// cannot silently override each other or apply one option twice.
func TestRefreshRejectsConflictingSelectorsAndRepeatedAll(t *testing.T) {
	for _, args := range [][]string{
		{"--endpoint", "endpoint-1", "refresh", "endpoint-2"},
		{"refresh", "endpoint-1", "endpoint-2"},
		{"refresh", "-a", "--all"},
	} {
		fixture := newRefreshTestServer(t)
		fullArgs := append([]string{"--server-url", fixture.server.URL, "--token", "test-token"}, args...)
		var output, diagnostics strings.Builder
		err := runWithIO(fullArgs, strings.NewReader(""), &output, &diagnostics, false, nil)
		if err == nil || err.Error() != "usage: agent-cluster-cli [options] [--endpoint <id>] refresh [endpoint] [-a|--all]" {
			t.Fatalf("args=%v unexpected result: %v", args, err)
		}
		if calls := fixture.calls(); len(calls) != 0 {
			t.Fatalf("args=%v rejected command still forced collection: %v", args, calls)
		}
	}
}

// TestRefreshReportsForcedCollectionFailure proves a failed forced collection is
// an error rather than a silently cached projection.
func TestRefreshReportsForcedCollectionFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/endpoints" {
			writeListTestEnvelope(w, http.StatusOK, "success", []protocol.Endpoint{
				{EndpointID: "endpoint-1", DisplayName: "endpoint-1", ConnectionState: "online"},
			})
			return
		}
		if r.URL.Path == "/api/v1/endpoints/endpoint-1/session-state/refresh" {
			writeListTestEnvelope(w, http.StatusServiceUnavailable, "endpoint_unavailable", nil)
			return
		}
		writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory("cached-1"))
	}))
	defer server.Close()
	var output, diagnostics strings.Builder
	args := []string{"--server-url", server.URL, "--token", "test-token", "--endpoint", "endpoint-1", "refresh"}
	err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil {
		t.Fatalf("forced collection failure was swallowed: output=%q", output.String())
	}
	if strings.Contains(output.String(), "cached-1") {
		t.Fatalf("failed refresh rendered cached rows: %q", output.String())
	}
}
