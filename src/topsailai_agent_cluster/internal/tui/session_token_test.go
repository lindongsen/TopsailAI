package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// providerIDStub serves sessions whose provider identifiers are numeric strings,
// which is what a live adapter reports and what the list displays in SESSION_ID.
func providerIDStub() *interactiveStub {
	report := protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{
			{
				SessionID:         "res-1",
				ProviderSessionID: "20261027152208",
				AdapterID:         "adapter-1",
				Generation:        "generation-1",
				State:             "running",
				CollectionStatus:  protocol.CollectionSucceeded,
			},
			{
				SessionID:         "res-2",
				ProviderSessionID: "20261027152209",
				AdapterID:         "adapter-1",
				Generation:        "generation-2",
				State:             "running",
				CollectionStatus:  protocol.CollectionSucceeded,
			},
		},
	}
	return &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": report},
	}
}

// TestShowAcceptsTheDisplayedProviderSessionID proves the identifier an operator
// reads in the SESSION_ID column is usable as input.
func TestShowAcceptsTheDisplayedProviderSessionID(t *testing.T) {
	output, diagnostics := runScope(t, providerIDStub(), "list\nshow 20261027152208\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session: res-1 ") {
		t.Fatalf("show did not resolve the provider identifier to res-1: %q", output)
	}
}

// TestLogsAcceptsTheDisplayedProviderSessionID proves logs resolves the same way.
func TestLogsAcceptsTheDisplayedProviderSessionID(t *testing.T) {
	stub := providerIDStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nlist\nlogs 20261027152209\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "observed_at_ms:") {
		t.Fatalf("missing snapshot evidence: %q", output)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("output requests=%+v", stub.outputRequests)
	}
	request := stub.outputRequests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-2" || request.generation != "generation-2" {
		t.Fatalf("wrong output identity tuple: %+v", request)
	}
}

// TestLogsProviderSessionIDWithoutListStillResolves proves the identifier path
// works before any list has been rendered, because the inventory is authoritative.
func TestLogsProviderSessionIDWithoutListStillResolves(t *testing.T) {
	stub := providerIDStub()
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"})
	output, diagnostics := runLine(t, stub, state, "logs 20261027152208")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "observed_at_ms:") {
		t.Fatalf("missing snapshot evidence: %q", output)
	}
	if len(stub.outputRequests) != 1 || stub.outputRequests[0].resourceID != "res-1" {
		t.Fatalf("output requests=%+v", stub.outputRequests)
	}
}

// TestRowNumberWinsOverAProviderSessionID proves the documented shorthand keeps
// precedence when a provider identifier happens to look like a row number.
func TestRowNumberWinsOverAProviderSessionID(t *testing.T) {
	report := protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{
			{SessionID: "res-1", ProviderSessionID: "1", AdapterID: "adapter-1", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded},
			{SessionID: "res-2", ProviderSessionID: "2", AdapterID: "adapter-1", Generation: "generation-2", State: "running", CollectionStatus: protocol.CollectionSucceeded},
		},
	}
	stub := &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": report},
	}
	output, diagnostics := runScope(t, stub, "list\nshow 2\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session: res-2 ") {
		t.Fatalf("row number did not win over the provider identifier: %q", output)
	}
}

// TestNumericTokenBeyondTheRowsFallsBackToTheProviderSessionID proves a numeric
// token that is not a row number is retried as a provider identifier instead of
// being rejected with a misleading range error.
func TestNumericTokenBeyondTheRowsFallsBackToTheProviderSessionID(t *testing.T) {
	report := protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{
			{SessionID: "res-1", ProviderSessionID: "7", AdapterID: "adapter-1", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded},
		},
	}
	stub := &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": report},
	}
	output, diagnostics := runScope(t, stub, "list\nshow 7\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session: res-1 ") {
		t.Fatalf("provider identifier fallback did not resolve: %q", output)
	}
}

// TestUnknownNumericTokenKeepsTheRowRangeError proves an unresolvable numeric
// token still reports the actionable range instead of a bare not-found.
func TestUnknownNumericTokenKeepsTheRowRangeError(t *testing.T) {
	_, diagnostics := runScope(t, providerIDStub(), "list\nshow 99\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: row 99 is out of range; valid rows are 1-2")
}

// TestFindSessionAcceptsTheProviderSessionID proves the shared lookup accepts the
// displayed identifier, which every command that resolves a target relies on.
func TestFindSessionAcceptsTheProviderSessionID(t *testing.T) {
	endpoints := []protocol.Endpoint{{EndpointID: "e1"}}
	reports := map[string]protocol.InventoryReport{"e1": {Sessions: []protocol.Session{
		{SessionID: "res-1", ProviderSessionID: "20261027152208"},
	}}}
	_, _, session, err := FindSession("20261027152208", endpoints, reports)
	if err != nil || session == nil || session.SessionID != "res-1" {
		t.Fatalf("session=%#v err=%v", session, err)
	}
}

// TestFindSessionPrefersTheResourceID proves the existing form keeps precedence
// when a provider identifier collides with another session's resource ID.
func TestFindSessionPrefersTheResourceID(t *testing.T) {
	endpoints := []protocol.Endpoint{{EndpointID: "e1"}}
	reports := map[string]protocol.InventoryReport{"e1": {Sessions: []protocol.Session{
		{SessionID: "res-1", ProviderSessionID: "res-2"},
		{SessionID: "res-2", ProviderSessionID: "provider-2"},
	}}}
	_, _, session, err := FindSession("res-2", endpoints, reports)
	if err != nil || session == nil || session.SessionID != "res-2" {
		t.Fatalf("session=%#v err=%v", session, err)
	}
}

// TestFindSessionInEndpointAcceptsTheProviderSessionID proves the scoped lookup
// used by logs accepts the displayed identifier too.
func TestFindSessionInEndpointAcceptsTheProviderSessionID(t *testing.T) {
	loaded := reportLoad{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports: map[string]protocol.InventoryReport{"endpoint-1": {
			ReportComplete: true,
			Sessions:       []protocol.Session{{SessionID: "res-1", ProviderSessionID: "20261027152208"}},
		}},
	}
	_, _, session, err := findSessionInEndpoint(loaded, "endpoint-1", "20261027152208")
	if err != nil || session.SessionID != "res-1" {
		t.Fatalf("session=%#v err=%v", session, err)
	}
}

// TestResolveSessionTokenLeavesNonNumericTokensToTheIdentifierPath proves the
// resolver never claims a token it cannot map from the rendered list.
func TestResolveSessionTokenLeavesNonNumericTokensToTheIdentifierPath(t *testing.T) {
	state := rowSelectionState(SessionRow{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", ProviderSessionID: "20261027152208", Generation: "generation-1"})
	if _, resolved, err := resolveSessionToken(state, "res-1"); err != nil || resolved {
		t.Fatalf("resolved=%v err=%v", resolved, err)
	}
	row, resolved, err := resolveSessionToken(state, "20261027152208")
	if err != nil || !resolved || row.SessionID != "res-1" {
		t.Fatalf("row=%+v resolved=%v err=%v", row, resolved, err)
	}
}

// TestResolveSessionTokenInEndpointRejectsAForeignProviderID proves a provider
// identifier rendered for another endpoint is never silently retargeted.
func TestResolveSessionTokenInEndpointRejectsAForeignProviderID(t *testing.T) {
	state := rowSelectionState(SessionRow{No: 1, EndpointID: "endpoint-2", SessionID: "res-2", ProviderSessionID: "20261027152208", Generation: "generation-2"})
	_, _, err := resolveSessionTokenInEndpoint(state, "20261027152208", "endpoint-1")
	want := `row 1 belongs to endpoint "endpoint-2", not the current endpoint "endpoint-1"; run list in that endpoint first`
	if err == nil || err.Error() != want {
		t.Fatalf("err=%v want=%q", err, want)
	}
}

// TestProviderSessionIDSelectionDoesNotAdmitCommands proves the new path is read-only.
func TestProviderSessionIDSelectionDoesNotAdmitCommands(t *testing.T) {
	stub := providerIDStub()
	runScope(t, stub, "list\nshow 20261027152208\ncd host-one/endpoint-1\nlist\nlogs 20261027152209\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("provider identifier selection admitted %d commands", stub.admit)
	}
}

// TestProviderSessionIDSelectionUsesTheLiveInventory proves the fallback reads the
// authoritative inventory rather than trusting a stale rendered list.
func TestProviderSessionIDSelectionUsesTheLiveInventory(t *testing.T) {
	stub := providerIDStub()
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"})
	before := stub.inventoryCalls
	if _, diagnostics := runLine(t, stub, state, "logs 20261027152208"); diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.inventoryCalls <= before {
		t.Fatalf("inventory was not read: before=%d after=%d", before, stub.inventoryCalls)
	}
}

// contextAwareStub fails every inventory read once the caller context is done,
// which is what a real client does. The shared stub ignores the context, so it
// cannot prove that the resolver runs under the caller context.
type contextAwareStub struct {
	*interactiveStub
}

func (s *contextAwareStub) GetInventory(ctx context.Context, id string) (protocol.InventoryReport, error) {
	if err := ctx.Err(); err != nil {
		return protocol.InventoryReport{}, err
	}
	return s.interactiveStub.GetInventory(ctx, id)
}

// TestProviderSessionIDContextIsPreserved proves the resolver runs under the
// caller context so a cancelled parent still aborts the lookup.
func TestProviderSessionIDContextIsPreserved(t *testing.T) {
	stub := &contextAwareStub{interactiveStub: providerIDStub()}
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := interactiveLogs(ctx, stub, state, "20261027152208", 4096, 4096, &strings.Builder{}, ColorPolicy{})
	// loadReports degrades a failed inventory read into an incomplete report, so
	// the observable contract is that the cancelled parent aborts before any
	// output request is issued.
	if err == nil {
		t.Fatal("cancelled context unexpectedly succeeded")
	}
	if len(stub.outputRequests) != 0 {
		t.Fatalf("cancelled context still requested output: %+v", stub.outputRequests)
	}
}
