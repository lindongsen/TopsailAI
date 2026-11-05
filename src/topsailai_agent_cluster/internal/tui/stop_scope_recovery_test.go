package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// stopScopeStub serves one endpoint whose single session disappears from the inventory
// once the stop receipt has been rendered.
func stopScopeStub() *interactiveStub {
	return &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "host-one"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": scopeInventory("res-1", "generation-1")},
		// startup list, cd, stop preflight, stop revalidation, post-submit reconciliation.
		sessionPresenceSequence: []bool{true, true, true, true, false},
	}
}

// TestStopLeavesTheRemovedSessionScope proves an acknowledged stop returns the operator to
// the endpoint scope with an explicit notice instead of leaving a dead selection behind.
func TestStopLeavesTheRemovedSessionScope(t *testing.T) {
	stub := stopScopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if !strings.Contains(output, "session res-1 is no longer reported by endpoint endpoint-1; returned to endpoint scope") {
		t.Fatalf("missing scope notice: %q", output)
	}
	if got := lastPrompt(output); got != "endpoint[host-one/endpoint-1]>" {
		t.Fatalf("final prompt = %q, want endpoint prompt", got)
	}
}

// TestStopScopeRecoveryKeepsTheNextCommandUsable proves the operator no longer learns about
// the removal from a later inventory-backed command.
func TestStopScopeRecoveryKeepsTheNextCommandUsable(t *testing.T) {
	stub := stopScopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\ny\nrefresh\nquit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "was not found") {
		t.Fatalf("refresh still reported the removed session: %q", diagnostics)
	}
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session res-1 is no longer reported by endpoint endpoint-1; returned to endpoint scope") {
		t.Fatalf("missing scope notice: %q", output)
	}
}

// TestStopScopeRecoveryKeepsTheCommandIDQueryable proves the durable receipt stays reachable
// after the scope moved, because the command identifier is not part of the selection.
func TestStopScopeRecoveryKeepsTheCommandIDQueryable(t *testing.T) {
	stub := stopScopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\ny\nstatus\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "CommandID: cmd-1") {
		t.Fatalf("missing receipt: %q", output)
	}
	if !strings.Contains(output, "finished") {
		t.Fatalf("status did not report the durable state: %q", output)
	}
}

// TestCancelledStopKeepsTheSessionScope proves a declined confirmation never moves the
// operator out of a session that was not stopped.
func TestCancelledStopKeepsTheSessionScope(t *testing.T) {
	stub := stopScopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\nn\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("cancelled stop admitted %d commands", stub.admit)
	}
	if strings.Contains(output, "returned to endpoint scope") {
		t.Fatalf("cancelled stop moved the scope: %q", output)
	}
	if got := lastPrompt(output); got != "session[host-one/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want session prompt", got)
	}
}

// TestStopScopeRecoveryKeepsTheScopeWhenInventoryIsUnavailable proves an unprovable removal
// never fabricates a scope change and never turns an acknowledged stop into an error.
func TestStopScopeRecoveryKeepsTheScopeWhenInventoryIsUnavailable(t *testing.T) {
	stub := stopScopeStub()
	state := interactiveState{}
	state.enterEndpoint(stub.endpoints[0])
	state.enterSession(stub.endpoints[0], "res-1", "generation-1")
	stub.inventoryErr = errors.New("inventory unavailable")
	var out strings.Builder
	if err := reconcileStoppedSelection(context.Background(), stub, &state, "res-1", &out); err != nil {
		t.Fatalf("reconciliation returned an error: %v", err)
	}
	if state.Scope.Kind != ScopeSession || state.SessionID != "res-1" {
		t.Fatalf("scope changed without proof: %+v", state.Scope)
	}
	if !strings.Contains(out.String(), "use cd .. to leave the session scope") {
		t.Fatalf("missing recovery guidance: %q", out.String())
	}
}

// TestStopScopeRecoveryKeepsTheScopeWhenTheSessionIsStillReported proves a session that the
// endpoint still reports keeps its scope, so a stop that did not remove the resource never
// silently drops the operator's selection.
func TestStopScopeRecoveryKeepsTheScopeWhenTheSessionIsStillReported(t *testing.T) {
	stub := stopScopeStub()
	stub.sessionPresenceSequence = nil
	state := interactiveState{}
	state.enterEndpoint(stub.endpoints[0])
	state.enterSession(stub.endpoints[0], "res-1", "generation-1")
	var out strings.Builder
	if err := reconcileStoppedSelection(context.Background(), stub, &state, "res-1", &out); err != nil {
		t.Fatalf("reconciliation returned an error: %v", err)
	}
	if state.Scope.Kind != ScopeSession || state.SessionID != "res-1" {
		t.Fatalf("scope changed while the session was still reported: %+v", state.Scope)
	}
	if out.String() != "" {
		t.Fatalf("unexpected notice: %q", out.String())
	}
}

// TestNonRemovingOperationsKeepTheSessionScope proves only the operation that removes the
// selected resource reconciles the scope.
func TestNonRemovingOperationsKeepTheSessionScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "resume", input: "cd host-one/endpoint-1/res-1\nresume\ny\nquit\n"},
		{name: "inject", input: "cd host-one/endpoint-1/res-1\ninject {\"text\":\"hi\"}\ny\nquit\n"},
		{name: "interrupt", input: "cd host-one/endpoint-1/res-1\ninterrupt {\"action\":\"soft_interrupt\"}\ny\nquit\n"},
		{name: "send", input: "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\ny\nquit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := stopScopeStub()
			if testCase.name == "resume" {
				// resume requires an authoritative absence before and after confirmation.
				stub.sessionPresenceSequence = []bool{true, true, false, false, false}
			}
			output, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if strings.Contains(output, "returned to endpoint scope") {
				t.Fatalf("%s reconciled the scope: %q", testCase.name, output)
			}
			if got := lastPrompt(output); got != "session[host-one/provider-res-1]>" {
				t.Fatalf("final prompt = %q, want session prompt", got)
			}
		})
	}
}
