package tui

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

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
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if !strings.Contains(output, "session (provider-res-1) is no longer reported by endpoint endpoint-1; returned to endpoint scope") {
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
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\ny\nrefresh\nexit\n", ColorPolicy{})
	if strings.Contains(diagnostics, "was not found") {
		t.Fatalf("refresh still reported the removed session: %q", diagnostics)
	}
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session (provider-res-1) is no longer reported by endpoint endpoint-1; returned to endpoint scope") {
		t.Fatalf("missing scope notice: %q", output)
	}
}

// TestStopScopeRecoveryKeepsTheCommandIDQueryable proves the durable receipt stays reachable
// after the scope moved, because the command identifier is not part of the selection.
func TestStopScopeRecoveryKeepsTheCommandIDQueryable(t *testing.T) {
	stub := stopScopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\ny\nstatus\nexit\n", ColorPolicy{})
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
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\nn\nexit\n", ColorPolicy{})
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
	if state.Scope.Kind != ScopeSession || state.ClusterSessionID != "res-1" {
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
	if state.Scope.Kind != ScopeSession || state.ClusterSessionID != "res-1" {
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
		{name: "btw", input: "cd host-one/endpoint-1/res-1\nbtw {\"text\":\"hi\"}\ny\nexit\n"},
		{name: "interrupt", input: "cd host-one/endpoint-1/res-1\ninterrupt {\"action\":\"soft_interrupt\"}\ny\nexit\n"},
		{name: "send", input: "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\nexit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := stopScopeStub()
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

// postSubmitBudgetStub records the command context and the context used by the
// post-submit reconciliation so the test can prove they are not the same budget.
type postSubmitBudgetStub struct {
	*interactiveStub
	commandCtx      context.Context
	reconcileCtx    context.Context
	reconcileErr    error
	reconcileBudget time.Duration
}

func (s *postSubmitBudgetStub) AdmitCommand(ctx context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.commandCtx = ctx
	return s.interactiveStub.AdmitCommand(ctx, intent)
}

func (s *postSubmitBudgetStub) GetInventory(ctx context.Context, id string) (protocol.InventoryReport, error) {
	// Inventory reads before admission belong to the preflight; every later read is the
	// post-submit reconciliation, which must not reuse the command budget.
	if s.commandCtx != nil {
		s.reconcileCtx = ctx
		s.reconcileErr = ctx.Err()
		if deadline, ok := ctx.Deadline(); ok {
			s.reconcileBudget = time.Until(deadline)
		}
	}
	return s.interactiveStub.GetInventory(ctx, id)
}

// TestStopScopeRecoveryUsesItsOwnBudget proves the reconciliation after the durable receipt
// runs on a fresh bounded context: the local wait may already have exhausted the command
// deadline, and reusing it would report an unavailable inventory for a healthy endpoint.
func TestStopScopeRecoveryUsesItsOwnBudget(t *testing.T) {
	stub := &postSubmitBudgetStub{interactiveStub: stopScopeStub()}
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nstop\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.reconcileCtx == nil {
		t.Fatal("reconciliation never read the inventory")
	}
	if stub.reconcileCtx == stub.commandCtx {
		t.Fatal("reconciliation reused the command context")
	}
	if stub.reconcileErr != nil {
		t.Fatalf("reconciliation context already failed when it read the inventory: %v", stub.reconcileErr)
	}
	if stub.reconcileBudget <= 0 {
		t.Fatalf("reconciliation budget = %v, want a fresh bounded budget", stub.reconcileBudget)
	}
	if !strings.Contains(output, "session (provider-res-1) is no longer reported by endpoint endpoint-1; returned to endpoint scope") {
		t.Fatalf("reconciliation did not converge the scope: %q", output)
	}
	if got := lastPrompt(output); got != "endpoint[host-one/endpoint-1]>" {
		t.Fatalf("final prompt = %q, want endpoint prompt", got)
	}
}

// TestFindSelectedNamesTheSessionIdentityWhenTheSessionIsGone proves the message the
// human named as the example expresses the session as the canonical identity
// expression, ({provider_session_name}) ({provider_session_id}), instead of the
// opaque cluster resource ID. The pinned scope carries the identity, so the message
// can name the session the operator selected even though the endpoint no longer
// reports it.
func TestFindSelectedNamesTheSessionIdentityWhenTheSessionIsGone(t *testing.T) {
	state := interactiveState{}
	endpoint := protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one", ConnectionState: "online"}
	state.enterSessionDetails(endpoint, "res-1", "provider-res-1", "Daily work", "adapter-1", "generation-1")
	loaded := reportLoad{
		endpoints: []protocol.Endpoint{endpoint},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": {ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded},
		},
	}
	_, _, _, err := findSelectedIn(loaded, &state)
	if err == nil {
		t.Fatal("expected the missing session to be reported")
	}
	const want = `selected session (Daily work) (provider-res-1) was not found; use cd .. to leave the session scope`
	if err.Error() != want {
		t.Fatalf("message = %q, want %q", err.Error(), want)
	}
	// The opaque resource ID must not appear as its own parenthesised token, because
	// the canonical expression replaces it rather than accompanying it.
	if strings.Contains(err.Error(), " (res-1)") {
		t.Fatalf("message still names the opaque resource ID: %q", err.Error())
	}
}
