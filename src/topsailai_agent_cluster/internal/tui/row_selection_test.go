package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// rowSelectionState builds a state whose rows mirror a rendered list.
func rowSelectionState(rows ...SessionRow) *interactiveState {
	state := &interactiveState{}
	state.setRows(rows)
	return state
}

// TestResolveRowSelectionRejectsUnusableTokens proves every rejection stays local.
func TestResolveRowSelectionRejectsUnusableTokens(t *testing.T) {
	sessionRow := SessionRow{No: 1, EndpointID: "endpoint-1", ClusterSessionID: "res-1", ProviderGeneration: "generation-1"}
	placeholderRow := SessionRow{No: 2, EndpointID: "endpoint-2", State: "no sessions"}
	generationlessRow := SessionRow{No: 3, EndpointID: "endpoint-1", ClusterSessionID: "res-3"}
	cases := []struct {
		name  string
		state *interactiveState
		token string
		want  string
	}{
		{"overflow", rowSelectionState(sessionRow), strings.Repeat("9", 64), "row number exceeds the supported integer range"},
		{"no-list", rowSelectionState(), "1", "no list is available for row selection; run list first"},
		{"out-of-range", rowSelectionState(sessionRow), "2", "row 2 is out of range; valid rows are 1-1"},
		{"placeholder", rowSelectionState(placeholderRow), "2", "row 2 does not identify a session; choose a session row"},
		{"no-generation", rowSelectionState(generationlessRow), "3", "row 3 has no generation; run list again"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if _, err := resolveRowSelection(testCase.state, testCase.token); err == nil || err.Error() != testCase.want {
				t.Fatalf("err=%v want=%q", err, testCase.want)
			}
		})
	}
}

// TestResolveRowSelectionInEndpointRejectsForeignRow proves a number rendered for
// another endpoint is never silently retargeted.
func TestResolveRowSelectionInEndpointRejectsForeignRow(t *testing.T) {
	state := rowSelectionState(SessionRow{No: 1, EndpointID: "endpoint-2", ClusterSessionID: "res-2", ProviderGeneration: "generation-2"})
	_, err := resolveRowSelectionInEndpoint(state, "1", "endpoint-1")
	want := `row 1 belongs to endpoint "endpoint-2", not the current endpoint "endpoint-1"; run list in that endpoint first`
	if err == nil || err.Error() != want {
		t.Fatalf("err=%v want=%q", err, want)
	}
	row, err := resolveRowSelectionInEndpoint(state, "1", "endpoint-2")
	if err != nil || row.ClusterSessionID != "res-2" {
		t.Fatalf("row=%+v err=%v", row, err)
	}
}

// TestLogsAcceptsRowNumberInEndpointScope proves the operator types a number
// instead of a provider session identifier.
func TestLogsAcceptsRowNumberInEndpointScope(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nlist\nlogs 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "observed_at:") {
		t.Fatalf("missing snapshot evidence: %q", output)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("output requests=%+v", stub.outputRequests)
	}
	request := stub.outputRequests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-1" || request.generation != "generation-1" {
		t.Fatalf("wrong output identity tuple: %+v", request)
	}
}

// runLine executes one interactive line against an explicit state and renders the
// returned error the same way the REPL does, so diagnostics stay comparable.
func runLine(t *testing.T, stub InteractiveAPI, state *interactiveState, line string) (string, string) {
	t.Helper()
	var output, diagnostics strings.Builder
	if _, err := executeInteractiveLine(context.Background(), stub, state, line, nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
		if writeErr := writeInteractiveError(&diagnostics, line, err); writeErr != nil {
			t.Fatalf("writeInteractiveError: %v", writeErr)
		}
	}
	return output.String(), diagnostics.String()
}

// TestLogsRowNumberWithoutListExplainsTheShortForm proves the failure names the fix.
// The endpoint scope is entered directly because navigation renders a fresh list,
// so only an explicit state can prove the no-list branch. A numeric token is also a
// valid provider session identifier, so the failure keeps the identifier wording and
// appends the row-selection remedy instead of claiming the token was a row number.
func TestLogsRowNumberWithoutListExplainsTheShortForm(t *testing.T) {
	stub := scopeStub()
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"})
	_, diagnostics := runLine(t, stub, state, "logs 1")
	assertActionableError(t, diagnostics, `error: session "1" was not found on endpoint "endpoint-1"; run list to select a session by row number`)
	if len(stub.outputRequests) != 0 {
		t.Fatalf("rejected row selection reached the API: %+v", stub.outputRequests)
	}
}

// TestShowAcceptsRowNumberInWorkspaceScope proves show reuses the rendered numbering.
func TestShowAcceptsRowNumberInWorkspaceScope(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "list\nshow 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session: res-1 ") {
		t.Fatalf("show did not resolve row 1 to res-1: %q", output)
	}
}

// TestShowRowNumberWithoutListExplainsTheShortForm proves show rejects locally.
// A fresh state has no rendered list, which is the only way to reach this branch
// because the REPL renders the workspace inventory before the first prompt.
func TestShowRowNumberWithoutListExplainsTheShortForm(t *testing.T) {
	_, diagnostics := runLine(t, scopeStub(), &interactiveState{}, "show 1")
	assertActionableError(t, diagnostics, `error: endpoint or session "1" was not found; run list to select a session by row number`)
}

// TestShowRowNumberOutOfRangeReportsTheValidRange proves the range is actionable.
func TestShowRowNumberOutOfRangeReportsTheValidRange(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "list\nshow 99\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: row 99 is out of range; valid rows are 1-2")
}

// TestStatusWithoutArgumentReusesTheLastSubmittedCommand proves the operator never
// retypes an opaque command identifier.
func TestStatusWithoutArgumentReusesTheLastSubmittedCommand(t *testing.T) {
	stub := scopeStub()
	stub.admittedCommandID = "cmd-42"
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\nstatus\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d", stub.admit)
	}
	if !strings.Contains(output, "confirmed result") {
		t.Fatalf("status did not report the last command: %q", output)
	}
}

// TestInteractiveStatusHelpOmitsTheMandatoryID proves interactive help matches the
// short form while standalone help keeps the mandatory identifier.
func TestInteractiveStatusHelpOmitsTheMandatoryID(t *testing.T) {
	var interactive strings.Builder
	if err := PrintScopedCommandHelp(&interactive, "status", ScopeEndpoint); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(interactive.String(), "Syntax: status [command-id]") {
		t.Fatalf("interactive status help still demands an ID: %q", interactive.String())
	}
	var standalone strings.Builder
	if err := PrintCommandHelp(&standalone, "status"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(standalone.String(), "Syntax: status <command-id>") {
		t.Fatalf("standalone status help lost the mandatory ID: %q", standalone.String())
	}
}

// TestRowSelectionDoesNotAdmitCommands proves row selection is read-only.
func TestRowSelectionDoesNotAdmitCommands(t *testing.T) {
	stub := scopeStub()
	runScope(t, stub, "list\nshow 1\ncd host-one/endpoint-1\nlist\nlogs 1\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("row selection admitted %d commands", stub.admit)
	}
}

// TestRowSelectionUsesTheLatestRenderedList proves a refresh rebinds the numbers.
func TestRowSelectionUsesTheLatestRenderedList(t *testing.T) {
	stub := scopeStub()
	state := &interactiveState{}
	var output, diagnostics strings.Builder
	for _, line := range []string{"list", "show 1"} {
		if _, err := executeInteractiveLine(context.Background(), stub, state, line, nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("%q: %v", line, err)
		}
	}
	if diagnostics.Len() != 0 {
		t.Fatalf("unexpected diagnostics: %q", diagnostics.String())
	}
	if !strings.Contains(output.String(), "session: res-1 ") {
		t.Fatalf("row 1 did not resolve to res-1: %q", output.String())
	}
}
