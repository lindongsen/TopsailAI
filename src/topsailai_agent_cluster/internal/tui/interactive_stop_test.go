package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestStopAcceptsRowNumberInWorkspaceScope proves the operator types a row number
// from the fleet list and the stop reaches the endpoint that owns that row.
func TestStopAcceptsRowNumberInWorkspaceScope(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "list\nstop 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationAgentStop || intent.EndpointID != "endpoint-1" {
		t.Fatalf("wrong stop intent: %+v", intent)
	}
	if intent.Target == nil || intent.Target.ResourceID != "res-1" || intent.Target.Generation != "generation-1" {
		t.Fatalf("wrong stop target: %+v", intent.Target)
	}
	if !strings.Contains(output, "row numbers are stale after stop; run list to refresh") {
		t.Fatalf("missing row invalidation notice: %q", output)
	}
}

// TestStopAcceptsRowNumberInEndpointScope proves the endpoint list numbering is
// reused and the row must belong to the current endpoint.
func TestStopAcceptsRowNumberInEndpointScope(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nlist\nstop 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d", stub.admit)
	}
	intent := stub.intents[0]
	if intent.EndpointID != "endpoint-1" {
		t.Fatalf("wrong stop endpoint: %+v", intent)
	}
	if intent.Target == nil || intent.Target.ResourceID != "res-1" || intent.Target.Generation != "generation-1" {
		t.Fatalf("wrong stop target: %+v", intent.Target)
	}
}

// TestStopRejectsForeignRowInEndpointScope proves a number rendered for another
// endpoint is never silently retargeted.
func TestStopRejectsForeignRowInEndpointScope(t *testing.T) {
	stub := scopeStub()
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"})
	state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-2", SessionID: "res-2", Generation: "generation-2"}})
	_, diagnostics := runLine(t, stub, state, "stop 1")
	assertActionableError(t, diagnostics, `error: row 1 belongs to endpoint "endpoint-2", not the current endpoint "endpoint-1"; run list in that endpoint first`)
	if stub.admit != 0 {
		t.Fatalf("foreign row admitted %d commands", stub.admit)
	}
}

// TestStopResolvesSessionIDAcrossEndpoints proves a literal identifier works in
// workspace scope without a rendered list.
func TestStopResolvesSessionIDAcrossEndpoints(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, "stop res-2\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d", stub.admit)
	}
	intent := stub.intents[0]
	if intent.EndpointID != "endpoint-2" {
		t.Fatalf("wrong stop endpoint: %+v", intent)
	}
	if intent.Target == nil || intent.Target.ResourceID != "res-2" || intent.Target.Generation != "generation-2" {
		t.Fatalf("wrong stop target: %+v", intent.Target)
	}
}

// TestStopRejectsAmbiguousSessionIDAcrossEndpoints proves a token matching several
// endpoints is rejected, because the operator named no endpoint.
func TestStopRejectsAmbiguousSessionIDAcrossEndpoints(t *testing.T) {
	stub := &interactiveStub{
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-1", Hostname: "host-one"},
			{EndpointID: "endpoint-2", Hostname: "host-two"},
		},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": scopeInventory("res-shared", "generation-1"),
			"endpoint-2": scopeInventory("res-shared", "generation-2"),
		},
	}
	_, diagnostics := runScope(t, stub, "stop res-shared\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: multiple sessions match "res-shared"; use stop <number> with a row from list`)
	if stub.admit != 0 {
		t.Fatalf("ambiguous target admitted %d commands", stub.admit)
	}
}

// TestStopRejectsChangedGenerationBeforeConfirmation proves a replacement session is
// never stopped: the row was rendered for generation-1 and the inventory now reports
// generation-2. The rejection happens before the confirmation prompt, so no answer is
// queued for it.
func TestStopRejectsChangedGenerationBeforeConfirmation(t *testing.T) {
	stub := scopeStub()
	// Startup list and the explicit list read two endpoints each, so the stop
	// revalidation is the fifth inventory call; only that read reports a new
	// generation for the selected session.
	stub.generationSequence = []string{"generation-1", "generation-1", "generation-1", "generation-1", "generation-2"}
	_, diagnostics := runScope(t, stub, "list\nstop 1\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: session "res-1" generation changed; run list again`)
	if stub.admit != 0 {
		t.Fatalf("changed generation admitted %d commands", stub.admit)
	}
}

// TestStopRejectsOfflineEndpoint proves a stop is refused when the owning endpoint is
// not online, instead of being dispatched into a disconnected channel.
func TestStopRejectsOfflineEndpoint(t *testing.T) {
	stub := scopeStub()
	stub.endpoints[0].ConnectionState = "offline"
	_, diagnostics := runScope(t, stub, "list\nstop 1\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: endpoint "endpoint-1" is not online: connection_state=offline`)
	if stub.admit != 0 {
		t.Fatalf("offline endpoint admitted %d commands", stub.admit)
	}
}

// TestStopRejectsIncompleteInventory proves an incomplete report cannot authorize a
// stop, because an unavailable observation is unknown rather than empty.
func TestStopRejectsIncompleteInventory(t *testing.T) {
	stub := scopeStub()
	report := scopeInventory("res-1", "generation-1")
	report.ReportComplete = false
	stub.reports["endpoint-1"] = report
	_, diagnostics := runScope(t, stub, "stop res-1\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: endpoint "endpoint-1" inventory is unavailable`)
	if stub.admit != 0 {
		t.Fatalf("incomplete inventory admitted %d commands", stub.admit)
	}
}

// TestStopDeclinedConfirmationAdmitsNothing proves the confirmation gate still guards
// the new scope paths.
func TestStopDeclinedConfirmationAdmitsNothing(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "list\nstop 1\nn\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("declined stop admitted %d commands", stub.admit)
	}
	if !strings.Contains(output, "stop cancelled") {
		t.Fatalf("missing cancellation notice: %q", output)
	}
}

// TestStopKeepsRowBindingsWhenConfirmationIsDeclined proves the invalidation notice is
// tied to an executed stop, not to the prompt.
func TestStopKeepsRowBindingsWhenConfirmationIsDeclined(t *testing.T) {
	stub := scopeStub()
	state := &interactiveState{}
	var output, diagnostics strings.Builder
	lines := make(chan lineReadResult, 1)
	lines <- lineReadResult{line: "n"}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "list", nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("list: %v", err)
	}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "stop 1", lines, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("stop 1: %v", err)
	}
	if len(state.Rows) == 0 {
		t.Fatal("declined stop dropped the row bindings")
	}
	if strings.Contains(output.String(), "row numbers are stale after stop") {
		t.Fatalf("declined stop reported invalidation: %q", output.String())
	}
}

// TestStopReportsCommandIDForStatus proves the non-session-scope path records the
// command ID on the real state, so a following status can query the receipt.
func TestStopReportsCommandIDForStatus(t *testing.T) {
	stub := scopeStub()
	stub.admittedCommandID = "cmd-77"
	state := &interactiveState{}
	var output, diagnostics strings.Builder
	lines := make(chan lineReadResult, 1)
	lines <- lineReadResult{line: "y"}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "list", nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("list: %v", err)
	}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "stop 1", lines, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("stop 1: %v", err)
	}
	if state.commandID != "cmd-77" {
		t.Fatalf("state commandID=%q, want cmd-77", state.commandID)
	}
}

// TestStopConfirmationNamesProviderSessionIDFirst proves the workspace-scope stop
// question names the provider session identifier before the opaque cluster resource
// ID, so the operator can match the question against the SESSION_ID column of the
// rendered list before answering. The opaque ID stays available for status and info.
func TestStopConfirmationNamesProviderSessionIDFirst(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "list\nstop 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "stop session provider-res-1 (res-1)? Confirm stop?") {
		t.Fatalf("confirmation question does not name the provider session ID first: %q", output)
	}
	if strings.Index(output, "provider-res-1") > strings.Index(output, "stop session provider-res-1 (res-1)?") {
		t.Fatalf("provider session ID is not the first identifier in the question: %q", output)
	}
}

// TestStopConfirmationDeclinedAdmitsNothing proves the reworded question keeps the
// confirmation gate: a declined answer still admits no command.
func TestStopConfirmationDeclinedAdmitsNothing(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "list\nstop 1\nn\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("declined stop admitted %d commands", stub.admit)
	}
	if !strings.Contains(output, "stop cancelled") {
		t.Fatalf("missing cancellation notice: %q", output)
	}
}
