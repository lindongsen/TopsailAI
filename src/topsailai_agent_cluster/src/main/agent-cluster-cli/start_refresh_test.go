package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// startRefreshServer serves the minimum surface a non-interactive start needs:
// capabilities, command admission, terminal command evidence, the committed
// projection and the forced collection. It records forced collections so a test
// can prove the refresh happened exactly once for the started Endpoint.
type startRefreshServer struct {
	mu        sync.Mutex
	refreshed []string
	// fresh replaces the projection served after a forced collection, so a test
	// can model a collection that does or does not contain the launched session.
	fresh []string
	// current is the committed projection. A forced collection replaces it, because
	// the Server re-reads the committed document instead of trusting the reply.
	current []string
	// refreshStatus lets a test fail the forced collection.
	refreshStatus int
	server        *httptest.Server
}

func newStartRefreshServer(t *testing.T) *startRefreshServer {
	t.Helper()
	fixture := &startRefreshServer{fresh: []string{"res-1"}, current: []string{"res-1"}}
	fixture.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer test-token" {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		switch {
		case r.URL.Path == "/api/v1/endpoints/endpoint-1/capabilities":
			writeListTestEnvelope(w, http.StatusOK, "success", protocol.CapabilityDescriptor{
				Revision: "rev-1",
				Capabilities: []protocol.Capability{
					{Name: protocol.OperationAgentStart, Version: "v1"},
					{Name: protocol.OperationMessageSend, Version: "v1"},
				},
			})
		case r.URL.Path == "/api/v1/commands" && r.Method == http.MethodPost:
			var intent protocol.ImmutableIntent
			_ = json.NewDecoder(r.Body).Decode(&intent)
			writeListTestEnvelope(w, http.StatusAccepted, "accepted", map[string]any{
				"command_id": intent.CommandID,
				"status":     string(protocol.StatusDispatched),
			})
		case strings.HasPrefix(r.URL.Path, "/api/v1/commands/"):
			writeListTestEnvelope(w, http.StatusOK, "success", map[string]any{
				"command_id":       strings.TrimPrefix(r.URL.Path, "/api/v1/commands/"),
				"status":           string(protocol.StatusFinished),
				"effect_certainty": string(protocol.EffectAcknowledged),
			})
		case r.URL.Path == "/api/v1/endpoints/endpoint-1/session-state/refresh" && r.Method == http.MethodPost:
			fixture.record("endpoint-1")
			if fixture.refreshStatus != 0 {
				writeListTestEnvelope(w, fixture.refreshStatus, "endpoint_unavailable", nil)
				return
			}
			fixture.commit()
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory(fixture.committed()...))
		case r.URL.Path == "/api/v1/endpoints/endpoint-1/session-state":
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory(fixture.committed()...))
		case r.URL.Path == "/api/v1/endpoints":
			writeListTestEnvelope(w, http.StatusOK, "success", []protocol.Endpoint{
				{EndpointID: "endpoint-1", DisplayName: "endpoint-1", ConnectionState: "online"},
			})
		default:
			writeListTestEnvelope(w, http.StatusNotFound, "not found", nil)
		}
	}))
	t.Cleanup(fixture.server.Close)
	return fixture
}

// record appends one forced-collection call under the mutex.
func (f *startRefreshServer) record(endpointID string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.refreshed = append(f.refreshed, endpointID)
}

// commit replaces the committed projection with the freshly collected one.
func (f *startRefreshServer) commit() {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.current = append([]string(nil), f.fresh...)
}

// committed returns the committed projection.
func (f *startRefreshServer) committed() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.current...)
}

// calls returns the recorded forced-collection order.
func (f *startRefreshServer) calls() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.refreshed...)
}

// startArgs builds the documented non-interactive start invocation.
func startArgs(serverURL string, extra ...string) []string {
	args := []string{"--server-url", serverURL, "--token", "test-token", "--yes", "--profile", "p", "--profile-revision", "r"}
	return append(args, extra...)
}

// TestStartForcesOneCollectionForTheStartedEndpoint proves the non-interactive
// start refreshes the Endpoint that accepted it, so the next list already contains
// the launched session instead of waiting for the periodic collection.
func TestStartForcesOneCollectionForTheStartedEndpoint(t *testing.T) {
	fixture := newStartRefreshServer(t)
	var output, diagnostics strings.Builder
	args := startArgs(fixture.server.URL, "start", "endpoint-1", "res-1", "do the work")
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("start failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if got, want := strings.Join(fixture.calls(), ","), "endpoint-1"; got != want {
		t.Fatalf("forced collections=%q want=%q", got, want)
	}
}

// TestStartRendersTheFreshlyCollectedSession proves the rendered table comes from
// the forced collection, so the operator sees the launched session immediately.
func TestStartRendersTheFreshlyCollectedSession(t *testing.T) {
	fixture := newStartRefreshServer(t)
	fixture.fresh = []string{"res-1", "res-new"}
	var output, diagnostics strings.Builder
	args := startArgs(fixture.server.URL, "start", "endpoint-1", "res-1", "do the work")
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("start failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if !strings.Contains(output.String(), "res-new") {
		t.Fatalf("post-start table did not show the launched session: %q", output.String())
	}
}

// TestStartReportsSessionNotYetVisible proves a collection that omits the launched
// session is reported as pending visibility on stderr, not as a failure. The
// provider reports a background launch as submitted, and a session only becomes
// routable once its process is observed holding the output file, so an immediate
// collection can legitimately miss it.
func TestStartReportsSessionNotYetVisible(t *testing.T) {
	fixture := newStartRefreshServer(t)
	var output, diagnostics strings.Builder
	args := startArgs(fixture.server.URL, "start", "endpoint-1", "res-1", "do the work")
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("pending visibility must not fail the command: %v", err)
	}
	if !strings.Contains(diagnostics.String(), "session submitted but not yet visible") {
		t.Fatalf("missing pending-visibility notice: %q", diagnostics.String())
	}
	if strings.Contains(diagnostics.String(), "refresh after start failed") {
		t.Fatalf("pending visibility was reported as a refresh failure: %q", diagnostics.String())
	}
}

// TestStartRefreshFailureKeepsExitStatus proves a failed forced collection is a
// diagnostic, not a command failure, because the admission already succeeded.
func TestStartRefreshFailureKeepsExitStatus(t *testing.T) {
	fixture := newStartRefreshServer(t)
	fixture.refreshStatus = http.StatusServiceUnavailable
	var output, diagnostics strings.Builder
	args := startArgs(fixture.server.URL, "start", "endpoint-1", "res-1", "do the work")
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("refresh failure must not fail the command: %v", err)
	}
	if !strings.Contains(diagnostics.String(), "refresh after start failed") {
		t.Fatalf("refresh failure was not reported: %q", diagnostics.String())
	}
}

// TestStartJSONKeepsMachineReadableOutput proves --json still emits exactly one
// JSON document. Appending a rendered table would corrupt the machine-readable
// surface that automation parses.
func TestStartJSONKeepsMachineReadableOutput(t *testing.T) {
	fixture := newStartRefreshServer(t)
	var output, diagnostics strings.Builder
	args := startArgs(fixture.server.URL, "--json", "start", "endpoint-1", "res-1", "do the work")
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("start --json failed: %v diagnostics=%q", err, diagnostics.String())
	}
	var decoded map[string]any
	if err := json.Unmarshal([]byte(output.String()), &decoded); err != nil {
		t.Fatalf("start --json emitted a non-JSON document: %v output=%q", err, output.String())
	}
	if strings.Contains(output.String(), "SESSION_ID") {
		t.Fatalf("start --json appended a rendered table: %q", output.String())
	}
	if got, want := strings.Join(fixture.calls(), ","), "endpoint-1"; got != want {
		t.Fatalf("forced collections=%q want=%q", got, want)
	}
}

// TestNonStartActionsNeverForceCollection proves the refresh stays scoped to start,
// so send and stop do not add provider discovery cost.
func TestNonStartActionsNeverForceCollection(t *testing.T) {
	fixture := newStartRefreshServer(t)
	var output, diagnostics strings.Builder
	args := startArgs(fixture.server.URL, "send", "endpoint-1", "res-1", "hello", "gen-1")
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("send failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if calls := fixture.calls(); len(calls) != 0 {
		t.Fatalf("send forced %v, want no collection", calls)
	}
}
