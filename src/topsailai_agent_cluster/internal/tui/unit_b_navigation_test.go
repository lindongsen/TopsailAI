package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestUnitBBareNumberMatchesExplicitCD(t *testing.T) {
	bareOutput, bareDiagnostics := runNav(t, scopeStub(), "1\nquit\n")
	cdOutput, cdDiagnostics := runNav(t, scopeStub(), "cd 1\nquit\n")
	if bareDiagnostics != cdDiagnostics {
		t.Fatalf("diagnostics differ: bare=%q cd=%q", bareDiagnostics, cdDiagnostics)
	}
	if lastPrompt(bareOutput) != lastPrompt(cdOutput) {
		t.Fatalf("final prompts differ: bare=%q cd=%q", lastPrompt(bareOutput), lastPrompt(cdOutput))
	}
	if !strings.Contains(bareOutput, "session[host-one/provider-res-1]>") {
		t.Fatalf("bare number did not select session: %q", bareOutput)
	}
}

func TestUnitBNavigationSpellingsMatchFullStateAndCalls(t *testing.T) {
	run := func(input string) (interactiveState, *interactiveStub) {
		stub := scopeStub()
		state := interactiveState{}
		var out, diagnostics strings.Builder
		for _, line := range []string{"list", input} {
			quit, err := executeInteractiveLine(context.Background(), stub, &state, line, nil, &out, &out, &diagnostics, InteractiveOptions{})
			if err != nil || quit {
				t.Fatalf("execute %q: quit=%t err=%v diagnostics=%q", line, quit, err, diagnostics.String())
			}
		}
		return state, stub
	}
	bare, bareAPI := run("1")
	explicit, explicitAPI := run("cd 1")
	if bare.Scope != explicit.Scope || bare.EndpointID != explicit.EndpointID || bare.SessionID != explicit.SessionID || bare.Scope.ProviderSessionID != explicit.Scope.ProviderSessionID || bare.Scope.SessionName != explicit.Scope.SessionName || bare.Generation != explicit.Generation || bare.Invalidated != explicit.Invalidated || bare.InvalidReason != explicit.InvalidReason {
		t.Fatalf("navigation state differs: bare=%+v explicit=%+v", bare, explicit)
	}
	if bare.Scope != explicit.Scope || bare.Scope.EndpointID != explicit.Scope.EndpointID || bare.Scope.SessionID != explicit.Scope.SessionID || bare.Scope.Generation != explicit.Scope.Generation {
		t.Fatalf("selected scope identity differs: bare=%+v explicit=%+v", bare.Scope, explicit.Scope)
	}
	if bare.Invalidated != explicit.Invalidated || bare.InvalidReason != explicit.InvalidReason {
		t.Fatalf("invalidated state differs: bare=%+v explicit=%+v", bare, explicit)
	}
	if bareAPI.listCalls != 2 || explicitAPI.listCalls != 2 || bareAPI.inventoryCalls != 3 || explicitAPI.inventoryCalls != 3 {
		t.Fatalf("unexpected incremental calls: bare list=%d inventory=%d explicit list=%d inventory=%d", bareAPI.listCalls, bareAPI.inventoryCalls, explicitAPI.listCalls, explicitAPI.inventoryCalls)
	}
	for id, count := range bareAPI.inventoryByID {
		want := 1
		if id == "endpoint-1" {
			want = 2
		}
		if count != want || explicitAPI.inventoryByID[id] != count {
			t.Fatalf("inventory calls for %s: bare=%d explicit=%d want=%d", id, count, explicitAPI.inventoryByID[id], want)
		}
	}
	if bareAPI.outputCalls != 0 || explicitAPI.outputCalls != 0 || bareAPI.admit != 0 || explicitAPI.admit != 0 {
		t.Fatalf("navigation performed side effects: bare output=%d admit=%d explicit output=%d admit=%d", bareAPI.outputCalls, bareAPI.admit, explicitAPI.outputCalls, explicitAPI.admit)
	}
}

type unitBFailAfterWriter struct {
	remaining int
}

func (w *unitBFailAfterWriter) Write(data []byte) (int, error) {
	if w.remaining <= 0 {
		return 0, errUnitBWriter
	}
	w.remaining--
	return len(data), nil
}

type unitBObservingWriter struct {
	state   *interactiveState
	sawRows bool
}

func (w *unitBObservingWriter) Write([]byte) (int, error) {
	if len(w.state.Rows) != 0 {
		w.sawRows = true
	}
	return 0, errUnitBWriter
}

type unitBDiagnosticAPI struct {
	*interactiveStub
}

func (s *unitBDiagnosticAPI) GetInventory(ctx context.Context, id string) (protocol.InventoryReport, error) {
	if id == "endpoint-2" {
		return protocol.InventoryReport{}, errors.New("diagnostic fixture failure")
	}
	return s.interactiveStub.GetInventory(ctx, id)
}

// TestUnitBNumericDiagnosticsUseCDForSpaceAndTabSurplus checks the whole-line recognizer.
func TestUnitBNumericDiagnosticsUseCDForSpaceAndTabSurplus(t *testing.T) {
	for _, input := range []string{"1 foo\nquit\n", "1\tfoo\nquit\n"} {
		t.Run(strings.ReplaceAll(input, "\t", "tab"), func(t *testing.T) {
			_, diagnostics := runNav(t, scopeStub(), input)
			want := "error: invalid arguments\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"
			if diagnostics != want {
				t.Fatalf("diagnostics=%q want=%q", diagnostics, want)
			}
		})
	}
}

// TestUnitBOverflowDoesNotFallBackToEndpointName verifies numeric classification precedes conversion.
func TestUnitBOverflowDoesNotFallBackToEndpointName(t *testing.T) {
	_, diagnostics := runNav(t, scopeStub(), strings.Repeat("9", 64)+"\nquit\n")
	want := "error: row number exceeds the supported integer range\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"
	if diagnostics != want {
		t.Fatalf("diagnostics=%q want=%q", diagnostics, want)
	}
}

// TestUnitBGenerationAndDuplicateIdentityRejectWithoutMutation verifies S1 and uniqueness.
func TestUnitBGenerationAndDuplicateIdentityRejectWithoutMutation(t *testing.T) {
	stub := singleHostStub()
	state := interactiveState{}
	rows := ListRows(stub.endpoints, stub.reports, "")
	assignRowNumbers(rows)
	state.setRows(rows)
	before := state
	stub.reports["endpoint-1"] = navInventory("res-1", "generation-2")
	if err := cdRowNumber(&state, stub, context.Background(), 1); err == nil || !strings.Contains(err.Error(), "generation changed") {
		t.Fatalf("generation error=%v", err)
	}
	if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.SessionID != before.SessionID {
		t.Fatalf("state changed after generation rejection: before=%+v after=%+v", before, state)
	}

	report := navInventory("res-1", "generation-1")
	report.Sessions = append(report.Sessions, report.Sessions[0])
	stub.reports["endpoint-1"] = report
	if err := cdRowNumber(&state, stub, context.Background(), 1); err == nil || !strings.Contains(err.Error(), "multiple sessions") {
		t.Fatalf("duplicate error=%v", err)
	}
	if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.SessionID != before.SessionID {
		t.Fatalf("state changed after duplicate rejection: before=%+v after=%+v", before, state)
	}
}

// TestUnitBFailedListClearsOldRows verifies failed replacement cannot retain stale numbers.
func TestUnitBFailedListClearsOldRows(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	state.setRows([]SessionRow{{No: 1, EndpointID: "old", SessionID: "old", Generation: "old"}})
	stub.failList = true
	var output, diagnostics strings.Builder
	err := interactiveList(context.Background(), stub, &state, "", false, &output, &diagnostics, ColorPolicy{})
	if err == nil {
		t.Fatal("expected list failure")
	}
	if len(state.Rows) != 0 {
		t.Fatalf("stale rows retained after failed list: %+v", state.Rows)
	}
	if _, ok := state.Rows[1]; ok {
		t.Fatal("old row remained selectable")
	}
}

// TestUnitBWriterFailureLeavesRowsEmpty verifies staged publication on render failure.
func TestUnitBWriterFailureLeavesRowsEmpty(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	state.setRows([]SessionRow{{No: 1, EndpointID: "old", SessionID: "old", Generation: "old"}})
	output := &unitBFailingWriter{}
	err := interactiveList(context.Background(), stub, &state, "", false, output, output, ColorPolicy{})
	if err == nil || !errors.Is(err, errUnitBWriter) {
		t.Fatalf("interactiveList error=%v", err)
	}
	if len(state.Rows) != 0 {
		t.Fatalf("rows published after render failure: %+v", state.Rows)
	}
}

// unitBFailingWriter fails after receiving the first output chunk.
type unitBFailingWriter struct{}

var errUnitBWriter = errors.New("unit B writer failure")

func (*unitBFailingWriter) Write([]byte) (int, error) { return 0, errUnitBWriter }

// TestUnitBNumericRecognizerRejectsSigns verifies only ASCII decimal tokens are shorthand.
func TestUnitBNumericRecognizerRejectsSigns(t *testing.T) {
	for _, input := range []string{"-1", "+1", "1.0", "１２", "\"1\"", "1/2"} {
		if candidate, _, _ := numericInput(input); candidate {
			t.Fatalf("input %q unexpectedly classified as numeric shorthand", input)
		}
	}
	if candidate, token, surplus := numericInput("  001\t "); !candidate || token != "001" || surplus {
		t.Fatalf("single token classification = candidate %v token %q surplus %v", candidate, token, surplus)
	}
}

type unitBSuccessfulObservingWriter struct {
	state   *interactiveState
	sawRows bool
}

func (w *unitBSuccessfulObservingWriter) Write(data []byte) (int, error) {
	if len(w.state.Rows) != 0 {
		w.sawRows = true
	}
	return len(data), nil
}

// TestUnitBB1LeadingZeroReorderAndRemovalKeepsPinnedIdentity verifies that displayed
// row numbers use cached identity rather than fresh inventory order.
func TestUnitBB1LeadingZeroReorderAndRemovalKeepsPinnedIdentity(t *testing.T) {
	stub := singleHostStub()
	state := interactiveState{}
	rows := []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}}
	state.setRows(rows)
	before := state
	if err := cdRowNumber(&state, stub, context.Background(), 1); err != nil {
		t.Fatalf("initial row selection: %v", err)
	}
	if state.SessionID != "res-1" || state.Generation != "generation-1" {
		t.Fatalf("initial identity = %q/%q", state.SessionID, state.Generation)
	}
	state = before
	reordered := stub.reports["endpoint-1"]
	reordered.Sessions = append([]protocol.Session{{SessionID: "other", AdapterID: "adapter-1", Generation: "other-generation", CollectionStatus: protocol.CollectionSucceeded}}, reordered.Sessions...)
	stub.reports["endpoint-1"] = reordered
	if err := cdRowNumber(&state, stub, context.Background(), 1); err != nil {
		t.Fatalf("reordered row selection: %v", err)
	}
	if state.SessionID != "res-1" {
		t.Fatalf("reordered inventory retargeted row: %q", state.SessionID)
	}
	state = before
	stub.reports["endpoint-1"] = protocol.InventoryReport{ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}}}
	if err := cdRowNumber(&state, stub, context.Background(), 1); err == nil || !strings.Contains(err.Error(), "no longer identifies") {
		t.Fatalf("removed row error = %v", err)
	}
	if state.Scope != before.Scope || state.SessionID != before.SessionID {
		t.Fatalf("removal mutated state: before=%+v after=%+v", before, state)
	}
	if candidate, token, surplus := numericInput("  001  "); !candidate || token != "001" || surplus {
		t.Fatalf("leading-zero classification = %v/%q/%v", candidate, token, surplus)
	}
}

// TestUnitBB2RejectionsKeepStateAndCalls verifies local rejection precedence and
// complete state/API invariants for representative rejected inputs.
func TestUnitBB2RejectionsKeepStateAndCalls(t *testing.T) {
	cases := []string{"0", "99", "1 foo", "1\tfoo", "-1", "1.0", "1/2"}
	for _, input := range cases {
		t.Run(strings.ReplaceAll(input, "\t", "tab"), func(t *testing.T) {
			stub := scopeStub()
			state := interactiveState{}
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
			before := state
			listCalls, inventoryCalls := stub.listCalls, stub.inventoryCalls
			var output, diagnostics strings.Builder
			_, err := executeInteractiveLine(context.Background(), stub, &state, input, nil, &output, &output, &diagnostics, InteractiveOptions{})
			if err == nil {
				t.Fatal("expected rejected input")
			}
			if state.Scope != before.Scope || state.SessionID != before.SessionID || state.Generation != before.Generation || state.Invalidated != before.Invalidated || state.InvalidReason != before.InvalidReason {
				t.Fatalf("rejection mutated state: before=%+v after=%+v", before, state)
			}
			if stub.listCalls != listCalls || stub.inventoryCalls != inventoryCalls {
				t.Fatalf("rejection performed API calls: list=%d inventory=%d", stub.listCalls, stub.inventoryCalls)
			}
		})
	}
}

// TestUnitBB3NumericNamedEndpointOverflowDoesNotQueryName verifies that overflow
// remains a local numeric range error even when an endpoint ID is numeric-looking.
func TestUnitBB3NumericNamedEndpointOverflowDoesNotQueryName(t *testing.T) {
	stub := scopeStub()
	stub.endpoints = append(stub.endpoints, protocol.Endpoint{EndpointID: strings.Repeat("9", 64), Hostname: "numeric"})
	stub.reports[strings.Repeat("9", 64)] = scopeInventory("numeric-session", "generation-numeric")
	state := interactiveState{}
	var output, diagnostics strings.Builder
	beforeList, beforeInventory := stub.listCalls, stub.inventoryCalls
	_, err := executeInteractiveLine(context.Background(), stub, &state, strings.Repeat("9", 64), nil, &output, &output, &diagnostics, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "supported integer range") {
		t.Fatalf("overflow error = %v", err)
	}
	if stub.listCalls != beforeList || stub.inventoryCalls != beforeInventory {
		t.Fatalf("overflow queried authority: list=%d inventory=%d", stub.listCalls, stub.inventoryCalls)
	}
}

// TestUnitBB5SessionScopeAndQualifiedPathsPreserveBaseline verifies numeric row
// rejection in session scope and the existing parent/root/qualified navigation.
func TestUnitBB5SessionScopeAndQualifiedPathsPreserveBaseline(t *testing.T) {
	_, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1/res-1\ncd 1\nquit\n")
	assertActionableError(t, diagnostics, "error: row-number navigation is unavailable in session scope; use cd .. or cd <session>")
	for _, input := range []string{"cd ai-dev/endpoint-1/res-1\ncd ..\nquit\n", "cd ai-dev/endpoint-1/res-1\ncd /\nquit\n", "cd ai-dev/endpoint-1\ncd res-1\nquit\n"} {
		output, diagnostics := runNav(t, singleHostStub(), input)
		if diagnostics != "" || !(strings.Contains(output, "endpoint[") || strings.Contains(output, "session[")) {
			t.Fatalf("baseline path failed for %q: output=%q diagnostics=%q", input, output, diagnostics)
		}
	}
	output, diagnostics := runNav(t, conflictStub(), "cd ai-dev\nai-dev/endpoint-2\nquit\n")
	if diagnostics != "" || !strings.Contains(output, "endpoint[ai-dev/endpoint-2]>") {
		t.Fatalf("hostname conflict path failed: output=%q diagnostics=%q", output, diagnostics)
	}
}

// TestUnitBB1ScopeMatrixAndLeadingZeroEquivalence verifies all list scopes and
// that a leading-zero row token preserves the same complete identity as its
// canonical spelling.
func TestUnitBB1ScopeMatrixAndLeadingZeroEquivalence(t *testing.T) {
	for _, tc := range []struct {
		name   string
		filter string
		want   int
	}{
		{name: "workspace", filter: "", want: 2},
		{name: "filtered", filter: "endpoint-1", want: 1},
		{name: "endpoint", filter: "endpoint-1", want: 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			stub := scopeStub()
			state := interactiveState{}
			if tc.name == "endpoint" {
				state.enterEndpoint(stub.endpoints[0])
			}
			var output, diagnostics strings.Builder
			if err := interactiveList(context.Background(), stub, &state, tc.filter, false, &output, &diagnostics, ColorPolicy{}); err != nil {
				t.Fatal(err)
			}
			if len(state.Rows) != tc.want {
				t.Fatalf("rows=%d want=%d", len(state.Rows), tc.want)
			}
		})
	}
	run := func(t *testing.T, input string) (interactiveState, *interactiveStub) {
		t.Helper()
		stub := scopeStub()
		state := interactiveState{}
		var output, diagnostics strings.Builder
		for _, line := range []string{"list", input} {
			quit, err := executeInteractiveLine(context.Background(), stub, &state, line, nil, &output, &output, &diagnostics, InteractiveOptions{})
			if quit || err != nil {
				t.Fatalf("input %q: quit=%t err=%v diagnostics=%q", input, quit, err, diagnostics.String())
			}
		}
		return state, stub
	}
	one, oneAPI := run(t, "1")
	leading, leadingAPI := run(t, "01")
	if one.Scope != leading.Scope || one.EndpointID != leading.EndpointID || one.SessionID != leading.SessionID || one.Generation != leading.Generation || one.Invalidated != leading.Invalidated || one.InvalidReason != leading.InvalidReason {
		t.Fatalf("leading-zero identity differs: one=%+v leading=%+v", one, leading)
	}
	if oneAPI.listCalls != leadingAPI.listCalls || oneAPI.inventoryCalls != leadingAPI.inventoryCalls || oneAPI.outputCalls != leadingAPI.outputCalls || oneAPI.admit != leadingAPI.admit {
		t.Fatalf("leading-zero API calls differ: one=%+v leading=%+v", oneAPI, leadingAPI)
	}
}

// TestUnitBB2EveryRejectionPreservesStateAndCalls covers every local numeric
// rejection branch, including empty and whitespace-only input.
func TestUnitBB2EveryRejectionPreservesStateAndCalls(t *testing.T) {
	inputs := []string{"0", "99", "1 foo", "1\tfoo", "-1", "+1", "1.0", "１２", "\"1\"", "1/2", "", "   \t  "}
	for _, input := range inputs {
		t.Run(strings.ReplaceAll(strings.TrimSpace(input), "\t", "tab"), func(t *testing.T) {
			stub := scopeStub()
			state := interactiveState{Scope: ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1"}, interactiveSelection: interactiveSelection{EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1", InvalidReason: ""}}
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
			before := state
			beforeList, beforeInventory := stub.listCalls, stub.inventoryCalls
			var output, diagnostics strings.Builder
			_, err := executeInteractiveLine(context.Background(), stub, &state, input, nil, &output, &output, &diagnostics, InteractiveOptions{})
			if err == nil {
				t.Fatal("expected rejection")
			}
			if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.SessionID != before.SessionID || state.Generation != before.Generation || state.Invalidated != before.Invalidated || state.InvalidReason != before.InvalidReason {
				t.Fatalf("state changed for %q: before=%+v after=%+v", input, before, state)
			}
			if stub.listCalls != beforeList || stub.inventoryCalls != beforeInventory {
				t.Fatalf("API calls changed for %q: list=%d/%d inventory=%d/%d", input, beforeList, stub.listCalls, beforeInventory, stub.inventoryCalls)
			}
		})
	}
}

// TestUnitBB3ZeroQueryMatrixAcrossScopes verifies that local numeric parsing
// does not perform endpoint-name lookup before rejecting an overflow token.
func TestUnitBB3ZeroQueryMatrixAcrossScopes(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession} {
		t.Run(kind.String(), func(t *testing.T) {
			stub := scopeStub()
			state := interactiveState{Scope: ScopeState{Kind: kind, EndpointID: "endpoint-1", SessionID: "res-1"}}
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
			var output, diagnostics strings.Builder
			_, err := executeInteractiveLine(context.Background(), stub, &state, strings.Repeat("9", 64), nil, &output, &output, &diagnostics, InteractiveOptions{})
			if err == nil || !strings.Contains(err.Error(), "supported integer range") {
				t.Fatalf("error=%v", err)
			}
			if stub.listCalls != 0 || stub.inventoryCalls != 0 {
				t.Fatalf("overflow performed queries: list=%d inventory=%d", stub.listCalls, stub.inventoryCalls)
			}
		})
	}
}

// TestUnitBB5SessionScopeRejectsNumericNavigation is the independent session
// scope restriction assertion.
func TestUnitBB5SessionScopeRejectsNumericNavigation(t *testing.T) {
	_, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1/res-1\ncd 1\nquit\n")
	assertActionableError(t, diagnostics, "error: row-number navigation is unavailable in session scope; use cd .. or cd <session>")
}

// TestUnitBB5ParentAndRootNavigation are independent parent and root assertions.
func TestUnitBB5ParentAndRootNavigation(t *testing.T) {
	for _, tc := range []struct{ name, input, want string }{
		{"parent", "cd ai-dev/endpoint-1/res-1\ncd ..\nquit\n", "endpoint[ai-dev/endpoint-1]>"},
		{"root", "cd ai-dev/endpoint-1/res-1\ncd /\nquit\n", "workspace>"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			output, diagnostics := runNav(t, singleHostStub(), tc.input)
			if diagnostics != "" || lastPrompt(output) != tc.want {
				t.Fatalf("prompt=%q diagnostics=%q", lastPrompt(output), diagnostics)
			}
		})
	}
}

// TestUnitBB5HostnameConflictAndEndpointIDSelection independently checks the
// conflict prompt and the qualified endpoint/session path.
func TestUnitBB5HostnameConflictAndEndpointIDSelection(t *testing.T) {
	output, diagnostics := runNav(t, conflictStub(), "cd ai-dev\nai-dev/endpoint-2\nquit\n")
	if diagnostics != "" || lastPrompt(output) != "endpoint[ai-dev/endpoint-2]>" {
		t.Fatalf("conflict selection prompt=%q diagnostics=%q", lastPrompt(output), diagnostics)
	}
	output, diagnostics = runNav(t, singleHostStub(), "cd endpoint-1/res-1\nquit\n")
	if diagnostics != "" || lastPrompt(output) != "session[ai-dev/provider-res-1]>" {
		t.Fatalf("endpoint-id path prompt=%q diagnostics=%q", lastPrompt(output), diagnostics)
	}
}

// Interrupt behavior is covered by interactive_interrupt_test.go, which injects
// an actual signal into RunInteractive and asserts watcher joining and the typed error.

// TestUnitBB1EndpointAndSessionLeadingZeroEquivalence extends leading-zero
// identity checks to endpoint and session scopes.
func TestUnitBB1EndpointAndSessionLeadingZeroEquivalence(t *testing.T) {
	selectEndpoint := func(input string) (interactiveState, *interactiveStub) {
		t.Helper()
		stub := scopeStub()
		state := interactiveState{}
		var output, diagnostics strings.Builder
		for _, line := range []string{"cd host-one/endpoint-1", "list", input} {
			quit, err := executeInteractiveLine(context.Background(), stub, &state, line, nil, &output, &output, &diagnostics, InteractiveOptions{})
			if quit || err != nil {
				t.Fatalf("endpoint input %q line %q: quit=%t err=%v diagnostics=%q", input, line, quit, err, diagnostics.String())
			}
		}
		return state, stub
	}
	one, oneAPI := selectEndpoint("1")
	leading, leadingAPI := selectEndpoint("01")
	assertUnitBSelectionEqual(t, one, leading)
	if oneAPI.listCalls != leadingAPI.listCalls || oneAPI.inventoryCalls != leadingAPI.inventoryCalls {
		t.Fatalf("endpoint leading-zero calls differ: one=%+v leading=%+v", oneAPI, leadingAPI)
	}

	selectSession := func(input string) (string, interactiveState, *interactiveStub) {
		t.Helper()
		stub := scopeStub()
		state := interactiveState{}
		var output, diagnostics strings.Builder
		for _, line := range []string{"cd host-one/endpoint-1/res-1", "list", input} {
			_, err := executeInteractiveLine(context.Background(), stub, &state, line, nil, &output, &output, &diagnostics, InteractiveOptions{})
			if line == input {
				return err.Error(), state, stub
			}
			if err != nil {
				t.Fatalf("session setup line %q: %v", line, err)
			}
		}
		return "", state, stub
	}
	errOne, sessionOne, apiOne := selectSession("1")
	errLeading, sessionLeading, apiLeading := selectSession("01")
	if errOne != errLeading || errOne != "row-number navigation is unavailable in session scope; use cd .. or cd <session>" {
		t.Fatalf("session leading-zero errors differ: one=%q leading=%q", errOne, errLeading)
	}
	assertUnitBSelectionEqual(t, sessionOne, sessionLeading)
	if apiOne.listCalls != apiLeading.listCalls || apiOne.inventoryCalls != apiLeading.inventoryCalls {
		t.Fatalf("session leading-zero calls differ: one=%+v leading=%+v", apiOne, apiLeading)
	}
}

func assertUnitBSelectionEqual(t *testing.T, left, right interactiveState) {
	t.Helper()
	if left.Scope != right.Scope || left.EndpointID != right.EndpointID || left.SessionID != right.SessionID || left.Generation != right.Generation || left.Invalidated != right.Invalidated || left.InvalidReason != right.InvalidReason {
		t.Fatalf("selection identity differs: left=%+v right=%+v", left, right)
	}
}

// TestUnitBB3InteractiveCallCountMatrix measures calls through RunInteractive,
// subtracting the common startup inventory from each scenario.
func TestUnitBB3InteractiveCallCountMatrix(t *testing.T) {
	baseline := func(input string) *interactiveStub {
		stub := scopeStub()
		var output, diagnostics strings.Builder
		if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("RunInteractive %q: %v diagnostics=%q", input, err, diagnostics.String())
		}
		return stub
	}
	startup := baseline("quit\n")
	numeric := baseline("1\nquit\n")
	if numeric.listCalls-startup.listCalls != 1 || numeric.inventoryByID["endpoint-1"]-startup.inventoryByID["endpoint-1"] != 1 || numeric.inventoryByID["endpoint-2"] != startup.inventoryByID["endpoint-2"] || numeric.outputCalls != 0 || numeric.admit != 0 {
		t.Fatalf("numeric call counts unexpected: startup=%+v numeric=%+v", startup, numeric)
	}
	name := baseline("cd endpoint-1\nquit\n")
	if name.listCalls <= startup.listCalls || name.inventoryCalls <= startup.inventoryCalls || name.outputCalls != 0 || name.admit != 0 {
		t.Fatalf("name path call counts unexpected: startup=%+v name=%+v", startup, name)
	}
	local := baseline("0\nquit\n")
	if local.listCalls != startup.listCalls || local.inventoryCalls != startup.inventoryCalls || local.outputCalls != 0 || local.admit != 0 {
		t.Fatalf("local rejection performed incremental calls: startup=%+v local=%+v", startup, local)
	}
}

// TestUnitBB5NumericQualifiedEndpointPath verifies numeric endpoint and session
// path segments remain resolved by the explicit qualified path grammar.
func TestUnitBB5NumericQualifiedEndpointPath(t *testing.T) {
	stub := scopeStub()
	stub.endpoints = append([]protocol.Endpoint{{EndpointID: "1", Hostname: "numeric-host"}}, stub.endpoints...)
	stub.reports["1"] = scopeInventory("2", "generation-2")
	output, diagnostics := runNav(t, stub, "cd 1/2\nquit\n")
	if diagnostics != "" || !strings.Contains(output, "session[numeric-host/provider-2]>") {
		t.Fatalf("numeric qualified path failed: output=%q diagnostics=%q", output, diagnostics)
	}
}

// TestUnitBB5SessionListThenBareNumberRejects verifies list does not enable row
// navigation after entering session scope.
func TestUnitBB5SessionListThenBareNumberRejects(t *testing.T) {
	stub := scopeStub()
	state := interactiveState{}
	var output, diagnostics strings.Builder
	for _, line := range []string{"cd host-one/endpoint-1/res-1", "list"} {
		if _, err := executeInteractiveLine(context.Background(), stub, &state, line, nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
			t.Fatalf("setup %q: %v", line, err)
		}
	}
	before := state
	beforeList, beforeInventory := stub.listCalls, stub.inventoryCalls
	_, err := executeInteractiveLine(context.Background(), stub, &state, "1", nil, &output, &output, &diagnostics, InteractiveOptions{})
	if err == nil || err.Error() != "row-number navigation is unavailable in session scope; use cd .. or cd <session>" {
		t.Fatalf("session bare number error=%v", err)
	}
	if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.SessionID != before.SessionID || state.Generation != before.Generation || stub.listCalls != beforeList || stub.inventoryCalls != beforeInventory {
		t.Fatalf("session bare number changed state/calls: before=%+v after=%+v calls=%d/%d -> %d/%d", before, state, beforeList, beforeInventory, stub.listCalls, stub.inventoryCalls)
	}
}

// recordingOutputAPI returns identity-specific output while preserving the real
// interactive logs path and recording the request tuple sent to the endpoint.
type recordingOutputAPI struct {
	*interactiveStub
	outputs map[string]string
}

func (s *recordingOutputAPI) GetOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (protocol.OutputSnapshotResponse, error) {
	s.interactiveStub.outputCalls++
	s.interactiveStub.outputRequests = append(s.interactiveStub.outputRequests, outputRequest{endpointID: endpointID, resourceID: resourceID, generation: generation, maxBytes: maxBytes, maxLines: maxLines})
	return protocol.OutputSnapshotResponse{Data: s.outputs[resourceID]}, nil
}

// TestUnitBB1SessionLeadingZeroPreservesEachRejectedSnapshot compares each
// rejected spelling with its own pre-command snapshot, not only with its peer.
func TestUnitBB1SessionLeadingZeroPreservesEachRejectedSnapshot(t *testing.T) {
	for _, input := range []string{"1", "01"} {
		t.Run(input, func(t *testing.T) {
			stub := scopeStub()
			state := interactiveState{}
			var output, diagnostics strings.Builder
			for _, line := range []string{"cd host-one/endpoint-1/res-1", "list"} {
				if _, err := executeInteractiveLine(context.Background(), stub, &state, line, nil, &output, &output, &diagnostics, InteractiveOptions{}); err != nil {
					t.Fatalf("setup %q: %v", line, err)
				}
			}
			before := state
			beforeList, beforeInventory := stub.listCalls, stub.inventoryCalls
			_, err := executeInteractiveLine(context.Background(), stub, &state, input, nil, &output, &output, &diagnostics, InteractiveOptions{})
			if err == nil || err.Error() != "row-number navigation is unavailable in session scope; use cd .. or cd <session>" {
				t.Fatalf("input=%q error=%v", input, err)
			}
			if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.SessionID != before.SessionID || state.Generation != before.Generation || state.Invalidated != before.Invalidated || state.InvalidReason != before.InvalidReason {
				t.Fatalf("input=%q changed state: before=%+v after=%+v", input, before, state)
			}
			if stub.listCalls != beforeList || stub.inventoryCalls != beforeInventory {
				t.Fatalf("input=%q changed calls: before=%d/%d after=%d/%d", input, beforeList, beforeInventory, stub.listCalls, stub.inventoryCalls)
			}
		})
	}
}

// TestUnitBB1ScopeRowsCarryExactCapturedIdentity verifies each supported list
// scope binds a displayed number to the exact endpoint/session/generation row.
func TestUnitBB1ScopeRowsCarryExactCapturedIdentity(t *testing.T) {
	for _, tc := range []struct {
		name   string
		setup  func(*interactiveState, *interactiveStub)
		filter string
		want   SessionRow
	}{
		{name: "workspace", filter: "", want: SessionRow{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}},
		{name: "filtered", filter: "endpoint-1", want: SessionRow{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}},
		{name: "endpoint", filter: "", setup: func(state *interactiveState, stub *interactiveStub) { state.enterEndpoint(stub.endpoints[0]) }, want: SessionRow{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			stub := scopeStub()
			state := interactiveState{}
			if tc.setup != nil {
				tc.setup(&state, stub)
			}
			var output, diagnostics strings.Builder
			if err := interactiveList(context.Background(), stub, &state, tc.filter, false, &output, &diagnostics, ColorPolicy{}); err != nil {
				t.Fatal(err)
			}
			row, ok := state.Rows[1]
			if !ok || row.EndpointID != tc.want.EndpointID || row.SessionID != tc.want.SessionID || row.Generation != tc.want.Generation {
				t.Fatalf("captured row=%+v exists=%t want=%+v", row, ok, tc.want)
			}
		})
	}
}

// TestUnitBB2SingleDecimalRejectionFixtures verifies each required local rejection
// with exact diagnostics, unchanged selection state, and zero API side effects.
func TestUnitBB2SingleDecimalRejectionFixtures(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "zero", input: "0", want: "error: row 0 is out of range; valid rows are 1-1\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
		{name: "out-of-range", input: "2", want: "error: row 2 is out of range; valid rows are 1-1\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
		{name: "overflow", input: strings.Repeat("9", 64), want: "error: row number exceeds the supported integer range\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
		{name: "surplus-space", input: "1 foo", want: "error: invalid arguments\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
		{name: "surplus-tab", input: "1\tfoo", want: "error: invalid arguments\nusage: cd [target]\nnext: Run help cd for valid syntax.\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			stub := scopeStub()
			state := interactiveState{}
			state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
			before := state
			beforeList, beforeInventory, beforeOutput, beforeAdmit := stub.listCalls, stub.inventoryCalls, stub.outputCalls, stub.admit
			var output, diagnostics strings.Builder
			_, err := executeInteractiveLine(context.Background(), stub, &state, tc.input, nil, &output, &output, &diagnostics, InteractiveOptions{})
			if err == nil {
				t.Fatal("expected local rejection")
			}
			if writeErr := writeInteractiveError(&diagnostics, "cd", err); writeErr != nil {
				t.Fatalf("write diagnostics: %v", writeErr)
			}
			if diagnostics.String() != tc.want {
				t.Fatalf("diagnostics=%q want=%q", diagnostics.String(), tc.want)
			}
			if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.SessionID != before.SessionID || state.Generation != before.Generation || state.Invalidated != before.Invalidated || state.InvalidReason != before.InvalidReason {
				t.Fatalf("state changed: before=%+v after=%+v", before, state)
			}
			if stub.listCalls != beforeList || stub.inventoryCalls != beforeInventory || stub.outputCalls != beforeOutput || stub.admit != beforeAdmit {
				t.Fatalf("API calls changed: before=%d/%d/%d/%d after=%d/%d/%d/%d", beforeList, beforeInventory, beforeOutput, beforeAdmit, stub.listCalls, stub.inventoryCalls, stub.outputCalls, stub.admit)
			}
		})
	}
}
