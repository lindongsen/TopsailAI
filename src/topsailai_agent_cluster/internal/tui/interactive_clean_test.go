package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// cleanInteractiveStub exposes cleanup without changing the broad shared test
// fixture's capability surface.
type cleanInteractiveStub struct {
	*interactiveStub
}

// GetCapabilities advertises the standard cleanup operation for focused tests.
func (s cleanInteractiveStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{{Name: protocol.OperationWorkspaceClean}}}, nil
}

// expiredCleanStub returns a generationless provider row that remains a valid
// exact cleanup target even though no live process generation is available.
func expiredCleanStub() cleanInteractiveStub {
	stub := scopeStub()
	report := stub.reports["endpoint-1"]
	report.Sessions[0].ProviderGeneration = ""
	report.Sessions[0].State = "unknown"
	report.Sessions[0].StateReason = "liveness_unverified"
	stub.reports["endpoint-1"] = report
	return cleanInteractiveStub{interactiveStub: stub}
}

// TestCleanWorksInWorkspaceAndEndpointScopes proves both requested command
// surfaces submit the same provider-neutral operation to the row's owning
// Endpoint and preserve the generation when one exists.
func TestCleanWorksInWorkspaceAndEndpointScopes(t *testing.T) {
	tests := []struct {
		name  string
		input string
	}{
		{name: "workspace", input: "list\nclean 1\ny\nexit\n"},
		{name: "endpoint", input: "cd host-one/endpoint-1\nlist\nclean 1\ny\nexit\n"},
	}
	for _, testCase := range tests {
		t.Run(testCase.name, func(t *testing.T) {
			stub := cleanInteractiveStub{interactiveStub: scopeStub()}
			output, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if stub.admit != 1 {
				t.Fatalf("admitted=%d, want 1", stub.admit)
			}
			intent := stub.intents[0]
			if intent.Operation != protocol.OperationWorkspaceClean || intent.EndpointID != "endpoint-1" {
				t.Fatalf("wrong clean intent: %+v", intent)
			}
			if intent.Target == nil || intent.Target.ResourceID != "res-1" || intent.Target.ProviderGeneration != "generation-1" {
				t.Fatalf("wrong clean target: %+v", intent.Target)
			}
			if !strings.Contains(output, "row numbers are stale after clean; run list to refresh") {
				t.Fatalf("missing row invalidation notice: %q", output)
			}
		})
	}
}

// TestCleanIsUnavailableInSessionScope proves cleanup is deliberately excluded
// after entering one session, despite that scope already naming a target.
func TestCleanIsUnavailableInSessionScope(t *testing.T) {
	stub := cleanInteractiveStub{interactiveStub: scopeStub()}
	_, diagnostics := runScope(t, stub, "cd endpoint-1/res-1\nclean res-1\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: command "clean" is unavailable in session scope; available commands: list, cd, show, info, stop, btw, interrupt, ctl, drive, logs, send, status, refresh, messages, model, help, quit, exit`)
	if stub.admit != 0 {
		t.Fatalf("session-scope clean admitted %d commands", stub.admit)
	}
}

// TestCleanAcceptsGenerationlessExpiredRow proves cleanup does not apply the
// live-process generation requirement used by send and stop.
func TestCleanAcceptsGenerationlessExpiredRow(t *testing.T) {
	stub := expiredCleanStub()
	_, diagnostics := runScope(t, stub, "list\nclean 1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d, want 1", stub.admit)
	}
	if target := stub.intents[0].Target; target == nil || target.ProviderGeneration != "" || target.ResourceID != "res-1" {
		t.Fatalf("generationless target = %+v", target)
	}
}

// TestCleanRejectsAmbiguousIdentifierAcrossEndpoints proves workspace scope
// never chooses the first matching provider or cluster session identifier.
func TestCleanRejectsAmbiguousIdentifierAcrossEndpoints(t *testing.T) {
	stub := scopeStub()
	stub.reports["endpoint-1"] = scopeInventory("res-shared", "generation-1")
	stub.reports["endpoint-2"] = scopeInventory("res-shared", "generation-2")
	cleanStub := cleanInteractiveStub{interactiveStub: stub}
	_, diagnostics := runScope(t, cleanStub, "clean res-shared\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: multiple sessions match "res-shared"; use clean <number> with a row from list`)
	if cleanStub.admit != 0 {
		t.Fatalf("ambiguous clean admitted %d commands", cleanStub.admit)
	}
}

// TestCleanDeclinedConfirmationPreservesRows proves merely displaying the
// destructive confirmation changes neither provider state nor local bindings.
func TestCleanDeclinedConfirmationPreservesRows(t *testing.T) {
	stub := cleanInteractiveStub{interactiveStub: scopeStub()}
	state := &interactiveState{}
	var output, diagnostics strings.Builder
	lines := make(chan lineReadResult, 1)
	lines <- lineReadResult{line: "n"}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "list", nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("list: %v", err)
	}
	if _, err := executeInteractiveLine(context.Background(), stub, state, "clean 1", lines, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("clean: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("declined clean admitted %d commands", stub.admit)
	}
	if len(state.Rows) == 0 {
		t.Fatal("declined clean dropped row bindings")
	}
	if !strings.Contains(output.String(), "clean session (provider-res-1)? Confirm clean?") {
		t.Fatalf("missing exact-target confirmation: %q", output.String())
	}
	if strings.Contains(output.String(), "row numbers are stale after clean") {
		t.Fatalf("declined clean reported invalidation: %q", output.String())
	}
}

// TestCleanRejectsAmbiguousProviderIDOnOneEndpoint proves workspace lookup
// preserves the exact matcher's ambiguity result instead of treating it as absence.
func TestCleanRejectsAmbiguousProviderIDOnOneEndpoint(t *testing.T) {
	stub := scopeStub()
	report := stub.reports["endpoint-1"]
	duplicate := report.Sessions[0]
	duplicate.ClusterSessionID = "res-duplicate"
	duplicate.ProviderGeneration = "generation-duplicate"
	report.Sessions = append(report.Sessions, duplicate)
	stub.reports["endpoint-1"] = report
	cleanStub := cleanInteractiveStub{interactiveStub: stub}
	_, diagnostics := runScope(t, cleanStub, "clean provider-res-1\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: multiple sessions match provider session ID "provider-res-1" on endpoint "endpoint-1"; use the cluster session ID or a row number`)
	if cleanStub.admit != 0 {
		t.Fatalf("ambiguous clean admitted %d commands", cleanStub.admit)
	}
}
