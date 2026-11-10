package tui

import (
	"context"
	"errors"
	"sort"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// refreshStub adds forced collection to the shared interactive stub, so a test
// can prove refresh asks the Endpoint for a fresh collection instead of reading
// the cached Server projection. Forced collections run concurrently, so the
// recorded calls and the served reports are guarded by a mutex.
type refreshStub struct {
	interactiveStub
	mu            sync.Mutex
	refreshCalls  []string
	refreshErrors map[string]error
	// fresh replaces the served report, so a test can prove the rendered table
	// shows the newly collected data rather than the previous projection.
	fresh map[string]protocol.InventoryReport
}

func (s *refreshStub) RefreshInventory(_ context.Context, endpointID string) (protocol.InventoryReport, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.refreshCalls = append(s.refreshCalls, endpointID)
	if err := s.refreshErrors[endpointID]; err != nil {
		return protocol.InventoryReport{}, err
	}
	if report, ok := s.fresh[endpointID]; ok {
		s.reports[endpointID] = report
	}
	return s.reports[endpointID], nil
}

// GetInventory serializes projection reads with forced collections, because a
// failed collection reads the last committed document from a worker goroutine.
func (s *refreshStub) GetInventory(ctx context.Context, endpointID string) (protocol.InventoryReport, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.interactiveStub.GetInventory(ctx, endpointID)
}

// forcedCollections returns the recorded Endpoint IDs in a stable order, because
// concurrent collection makes completion order non-deterministic.
func (s *refreshStub) forcedCollections() []string {
	s.mu.Lock()
	defer s.mu.Unlock()
	calls := append([]string(nil), s.refreshCalls...)
	sort.Strings(calls)
	return calls
}

// refreshScopeStub serves two endpoints and records forced collections.
func refreshScopeStub() *refreshStub {
	base := scopeStub()
	return &refreshStub{
		interactiveStub: *base,
		refreshErrors:   make(map[string]error),
		fresh:           make(map[string]protocol.InventoryReport),
	}
}

// TestRefreshForcesEveryEndpointInWorkspaceScope proves a workspace refresh asks
// every Endpoint for a fresh collection before rendering. Collections run
// concurrently, so the assertion compares the recorded set rather than the
// completion order.
func TestRefreshForcesEveryEndpointInWorkspaceScope(t *testing.T) {
	stub := refreshScopeStub()
	output, diagnostics := runScope(t, stub, "refresh\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if calls := stub.forcedCollections(); len(calls) != 2 || calls[0] != "endpoint-1" || calls[1] != "endpoint-2" {
		t.Fatalf("forced collections=%v, want one per endpoint", calls)
	}
	if !strings.Contains(output, "host-one") || !strings.Contains(output, "host-two") {
		t.Fatalf("workspace refresh did not render every endpoint: %q", output)
	}
}

// TestRefreshRendersTheFreshlyCollectedDocument proves the rendered table comes
// from the forced collection, so the operator sees fresh data after refresh.
func TestRefreshRendersTheFreshlyCollectedDocument(t *testing.T) {
	stub := refreshScopeStub()
	previous := stub.reports["endpoint-1"]
	previous.Sessions[0].ProviderDisplayName = "previous work"
	stub.reports["endpoint-1"] = previous
	fresh := scopeInventory("fresh-session", "fresh-generation")
	fresh.Sessions[0].ProviderDisplayName = "fresh work"
	stub.fresh["endpoint-1"] = fresh
	output, diagnostics := runScope(t, stub, "refresh\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	// The startup inventory legitimately shows the previous projection, so the
	// assertion is scoped to the segment the refresh command rendered.
	scoped := segmentBeforePrompt(output, "workspace> ")
	// The interactive table hides SESSION_ID, so each row is identified by its
	// display name, which the table still renders.
	if !strings.Contains(scoped, "fresh work") {
		t.Fatalf("refresh did not render the freshly collected session: %q", scoped)
	}
	if strings.Contains(scoped, "previous work") {
		t.Fatalf("refresh rendered the stale projection: %q", scoped)
	}
}

// TestRefreshNarrowsForcedCollectionToCurrentEndpoint proves endpoint scope
// forces only the current Endpoint.
func TestRefreshNarrowsForcedCollectionToCurrentEndpoint(t *testing.T) {
	stub := refreshScopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nrefresh\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 1 || stub.refreshCalls[0] != "endpoint-1" {
		t.Fatalf("forced collections=%v, want only endpoint-1", stub.refreshCalls)
	}
	scoped := segmentBeforePrompt(output, "endpoint[host-one/endpoint-1]> ")
	if strings.Contains(scoped, "host-two") {
		t.Fatalf("endpoint refresh leaked another endpoint: %q", scoped)
	}
}

// TestRefreshEndpointScopeFailsHard proves an endpoint-scoped refresh reports the
// forced-collection failure instead of silently rendering cached data.
func TestRefreshEndpointScopeFailsHard(t *testing.T) {
	stub := refreshScopeStub()
	stub.refreshErrors["endpoint-1"] = errors.New("forced collection failed")
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nrefresh\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: forced collection failed")
}

// TestRefreshWorkspaceScopeDegrades proves one failing Endpoint does not hide the
// Endpoints that did collect fresh data.
func TestRefreshWorkspaceScopeDegrades(t *testing.T) {
	stub := refreshScopeStub()
	stub.refreshErrors["endpoint-2"] = errors.New("forced collection failed")
	output, diagnostics := runScope(t, stub, "refresh\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "endpoint endpoint-2 unavailable: forced collection failed") {
		t.Fatalf("missing per-endpoint failure diagnostic: %q", diagnostics)
	}
	if !strings.Contains(output, "host-one") {
		t.Fatalf("a failing endpoint hid the healthy one: %q", output)
	}
}

// TestRefreshSessionScopeForcesThenRenders proves a session refresh forces a
// collection and renders the committed endpoint table, so the operator sees the
// reloaded rows instead of only a confirmation line.
func TestRefreshSessionScopeForcesThenRenders(t *testing.T) {
	stub := refreshScopeStub()
	report := stub.reports["endpoint-1"]
	report.Sessions[0].ProviderDisplayName = "reloaded work"
	stub.reports["endpoint-1"] = report
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nrefresh\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 1 || stub.refreshCalls[0] != "endpoint-1" {
		t.Fatalf("forced collections=%v, want only endpoint-1", stub.refreshCalls)
	}
	scoped := segmentBeforePrompt(output, "session[host-one/provider-res-1]> ")
	if !strings.Contains(scoped, "DATA_STATUS") || !strings.Contains(scoped, "reloaded work") {
		t.Fatalf("session refresh did not render the endpoint table: %q", scoped)
	}
	if strings.Contains(scoped, "host-two") {
		t.Fatalf("session refresh leaked another endpoint: %q", scoped)
	}
}

// TestRefreshSessionScopeReportsForcedCollectionFailure proves a session refresh
// surfaces the forced-collection failure instead of revalidating cached data.
func TestRefreshSessionScopeReportsForcedCollectionFailure(t *testing.T) {
	stub := refreshScopeStub()
	stub.refreshErrors["endpoint-1"] = errors.New("forced collection failed")
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nrefresh\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: forced collection failed")
}

// TestRefreshWithoutSeamStaysReadOnly proves a client without forced collection
// keeps the previous read-only behaviour instead of failing.
func TestRefreshWithoutSeamStaysReadOnly(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "refresh\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "host-one") || !strings.Contains(output, "host-two") {
		t.Fatalf("read-only refresh did not render the inventory: %q", output)
	}
}

// TestListNeverForcesCollection proves list keeps its read-only contract.
func TestListNeverForcesCollection(t *testing.T) {
	stub := refreshScopeStub()
	_, diagnostics := runScope(t, stub, "list\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.refreshCalls) != 0 {
		t.Fatalf("list forced %d collections", len(stub.refreshCalls))
	}
}
