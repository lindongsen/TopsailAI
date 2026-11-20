package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// scopeInventory builds a complete report holding one fresh session.
func scopeInventory(sessionID, generation string) protocol.InventoryReport {
	return protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{{
			ClusterSessionID:   sessionID,
			ProviderSessionID:  "provider-" + sessionID,
			AdapterID:          "adapter-1",
			ProviderGeneration: generation,
			State:              "running",
			CollectionStatus:   protocol.CollectionSucceeded,
		}},
	}
}

// scopeStub serves two endpoints with distinct hostnames and one session each.
func scopeStub() *interactiveStub {
	return &interactiveStub{
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-1", Hostname: "host-one", DisplayName: "one"},
			{EndpointID: "endpoint-2", Hostname: "host-two", DisplayName: "two"},
		},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": scopeInventory("res-1", "generation-1"),
			"endpoint-2": scopeInventory("res-2", "generation-2"),
		},
	}
}

// siblingStub serves two sessions on the first endpoint to prove sibling listing.
func siblingStub() *interactiveStub {
	report := scopeInventory("res-1", "generation-1")
	report.Sessions = append(report.Sessions, protocol.Session{
		ClusterSessionID:    "res-1b",
		ProviderSessionID:   "provider-1b",
		ProviderDisplayName: "sibling work",
		AdapterID:           "adapter-1",
		ProviderGeneration:  "generation-1b",
		State:               "stopped",
		CollectionStatus:    protocol.CollectionSucceeded,
	})
	return &interactiveStub{
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-1", Hostname: "host-one"},
			{EndpointID: "endpoint-2", Hostname: "host-two"},
		},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": report,
			"endpoint-2": scopeInventory("res-2", "generation-2"),
		},
	}
}

// segmentBeforePrompt returns the output written between the second-to-last
// and the last occurrence of marker, which is the command output for the
// current scope. The startup inventory is excluded by construction.
func segmentBeforePrompt(output, marker string) string {
	last := strings.LastIndex(output, marker)
	if last < 0 {
		return output
	}
	previous := strings.LastIndex(output[:last], marker)
	if previous < 0 {
		return output[:last]
	}
	return output[previous+len(marker) : last]
}

// runScope executes one interactive scenario and returns both streams.
func runScope(t *testing.T, stub InteractiveAPI, input string, color ColorPolicy) (string, string) {
	t.Helper()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &diagnostics, InteractiveOptions{Color: color}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	return output.String(), diagnostics.String()
}

func TestSendIsUnavailableOutsideSessionScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{
			name:  "workspace",
			input: "send {\"text\":\"hi\"}\nexit\n",
			want:  "error: command \"send\" is unavailable in workspace scope; available commands: list, endpoints, cd, show, info, start, resume, stop, clean, drive, logs, status, refresh, watch, history, project, messages, model, help, quit, exit\n",
		},
		{
			name:  "endpoint",
			input: "cd host-one/endpoint-1\nsend {\"text\":\"hi\"}\nexit\n",
			want:  "error: command \"send\" is unavailable in endpoint scope; available commands: list, cd, show, info, start, resume, stop, clean, drive, logs, status, refresh, watch, history, project, messages, model, help, quit, exit\n",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := scopeStub()
			_, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			assertActionableError(t, diagnostics, strings.TrimSuffix(testCase.want, "\n"))
			if stub.admit != 0 {
				t.Fatalf("rejected send admitted %d commands", stub.admit)
			}
		})
	}
}

func TestSendWorksInSessionScope(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if !strings.Contains(output, "command submitted:") {
		t.Fatalf("missing submission evidence: %q", output)
	}
}

// TestLogsIsAvailableInWorkspaceScope proves the read needs no cd first: the
// workspace table numbers every endpoint's sessions in one sequence and each row
// carries its own endpoint, so a row number already names one machine.
//
// The assertion reads the recorded request rather than the rendered output,
// because the stub returns an empty snapshot: a text assertion would pass on the
// echoed command line and prove nothing about which session was addressed.
func TestLogsIsAvailableInWorkspaceScope(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, "logs 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("output requests = %d, want 1", len(stub.outputRequests))
	}
	request := stub.outputRequests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-1" {
		t.Fatalf("workspace logs addressed %s/%s, want endpoint-1/res-1", request.endpointID, request.resourceID)
	}
}

// TestLogsRequiresTargetInWorkspaceScope proves a bare logs still demands an
// explicit target there, so it can never fall back to a stale pinned selection.
func TestLogsRequiresTargetInWorkspaceScope(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "logs\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: logs requires a session in workspace scope; use logs <number> for a session row or logs <session-id>")
}

// TestLogsResolvesProviderSessionIDInWorkspaceScope proves a literal provider
// session ID is resolved across every endpoint, so the identifier an operator
// copies from the table works without entering the endpoint first.
func TestLogsResolvesProviderSessionIDInWorkspaceScope(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, "logs provider-res-1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("output requests = %d, want 1", len(stub.outputRequests))
	}
	request := stub.outputRequests[0]
	if request.endpointID != "endpoint-1" || request.resourceID != "res-1" {
		t.Fatalf("provider session ID resolved to %s/%s, want endpoint-1/res-1", request.endpointID, request.resourceID)
	}
}

// TestLogsRejectsAmbiguousProviderSessionIDInWorkspaceScope proves a token that
// names sessions on several endpoints is refused instead of guessed, because a
// silent choice would read the wrong machine's output.
func TestLogsRejectsAmbiguousProviderSessionIDInWorkspaceScope(t *testing.T) {
	stub := scopeStub()
	shared := scopeInventory("res-2", "generation-2")
	shared.Sessions[0].ProviderSessionID = "provider-res-1"
	stub.reports["endpoint-2"] = shared
	_, diagnostics := runScope(t, stub, "logs provider-res-1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "multiple sessions match provider session ID") {
		t.Fatalf("ambiguous token was not refused: %q", diagnostics)
	}
	if len(stub.outputRequests) != 0 {
		t.Fatalf("ambiguous token still issued %d output requests", len(stub.outputRequests))
	}
}

// TestLogsRejectsEndpointTokenInWorkspaceScope proves an endpoint identifier is
// refused with the real reason, because logs addresses a session and never an
// endpoint.
func TestLogsRejectsEndpointTokenInWorkspaceScope(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "logs endpoint-1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "names an endpoint, not a session") {
		t.Fatalf("endpoint token was not refused with the real reason: %q", diagnostics)
	}
}

// TestLogsFollowIsAvailableInWorkspaceScope proves the follow form works without
// entering an endpoint. The stub must implement the streaming seam and the REPL
// must be driven through the keypress-capable reader, because armFollowStream only
// arms the intent: a plain reader never opens the stream, so the test would pass
// while proving nothing about which session was addressed.
func TestLogsFollowIsAvailableInWorkspaceScope(t *testing.T) {
	stub := &followStub{interactiveStub: *scopeStub(), blockOpen: true}
	_, diagnostics, _ := runWatchREPL(t, stub, []string{"logs -f 1", "quit"}, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	requests := waitFollowRequests(t, stub, 1)
	if requests[0].endpointID != "endpoint-1" || requests[0].resourceID != "res-1" {
		t.Fatalf("logs -f addressed %s/%s, want endpoint-1/res-1", requests[0].endpointID, requests[0].resourceID)
	}
}

// TestLogsHonoursLineBudgetInWorkspaceScope proves the -n argument keeps working
// after the scope is widened, because the user asked for the same arguments to
// behave the same way. A test that only proved the command was accepted would
// pass even if the budget were dropped on the workspace path, and the operator
// would silently receive the default number of lines instead of the requested
// one.
func TestLogsHonoursLineBudgetInWorkspaceScope(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, "logs -n 7 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.outputRequests) != 1 {
		t.Fatalf("output requests = %d, want 1", len(stub.outputRequests))
	}
	if got := stub.outputRequests[0].maxLines; got != 7 {
		t.Fatalf("maxLines = %d, want 7", got)
	}
}

// TestLogsRequiresSessionInEndpointScope proves endpoint scope still needs a
// session, because the endpoint alone does not name one.
func TestLogsRequiresSessionInEndpointScope(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nlogs\nexit\n", ColorPolicy{})
	want := "error: no session selected; use cd <number> to select a session row, or cd <hostname>/<endpoint-id>/<session>\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestLogsAcceptsSessionArgumentInEndpointScope(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nlogs res-1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "observed_at:") || !strings.Contains(output, "truncated: false") {
		t.Fatalf("missing snapshot evidence: %q", output)
	}
}

func TestLogsUsesCurrentSessionInSessionScope(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1/res-1\nlogs\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "observed_at:") {
		t.Fatalf("missing snapshot evidence: %q", output)
	}
}

func TestListNarrowsToCurrentEndpoint(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nlist\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	scoped := segmentBeforePrompt(output, "endpoint[host-one/endpoint-1]> ")
	if !strings.Contains(scoped, "host-one") {
		t.Fatalf("missing current endpoint row: %q", scoped)
	}
	if strings.Contains(scoped, "host-two") {
		t.Fatalf("list leaked another endpoint: %q", scoped)
	}
}

func TestListInSessionScopeShowsSiblingSessions(t *testing.T) {
	output, diagnostics := runScope(t, siblingStub(), "cd host-one/endpoint-1/res-1\nlist\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	scoped := segmentBeforePrompt(output, "session[host-one/provider-res-1]> ")
	if !strings.Contains(scoped, "sibling work") {
		t.Fatalf("missing sibling session: %q", scoped)
	}
	if strings.Contains(scoped, "res-2") {
		t.Fatalf("list leaked another endpoint: %q", scoped)
	}
}

func TestListRejectsMismatchingFilterOutsideWorkspace(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nlist endpoint-2\nexit\n", ColorPolicy{})
	want := "error: list filter \"endpoint-2\" does not match the current endpoint \"endpoint-1\"\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

// TestShowWithoutASelectorAsksInsteadOfRefusing proves the workspace refusal was
// replaced by the guided question. The old behaviour reported a usage line and sent
// the operator to a second command, which cost two commands for one decision.
//
// The answer is empty because this test is about the question, not the selection: an
// empty answer cancels, so the assertion cannot be satisfied by a detail render that
// happened for an unrelated reason.
func TestShowWithoutASelectorAsksInsteadOfRefusing(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "show\n\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("a bare show reported a diagnostic: %q", diagnostics)
	}
	if !strings.Contains(output, "select endpoint or session [1-2]") {
		t.Fatalf("a bare show did not ask which row to show: %q", output)
	}
	if strings.Contains(diagnostics, "show requires an endpoint or session") {
		t.Fatalf("the removed refusal is still reported: %q", diagnostics)
	}
}

func TestShowDefaultsToCurrentEndpoint(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nshow\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "endpoint: endpoint-1 (") {
		t.Fatalf("missing endpoint detail: %q", output)
	}
}

func TestShowDefaultsToCurrentSession(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1/res-1\nshow\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	want := "session: res-1 adapter=adapter-1 provider_generation=generation-1 state=running"
	if !strings.Contains(output, want) {
		t.Fatalf("missing session detail %q in %q", want, output)
	}
}

func TestRefreshCoversWorkspaceScope(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "refresh\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "host-one") || !strings.Contains(output, "host-two") {
		t.Fatalf("workspace refresh did not cover every endpoint: %q", output)
	}
}

func TestRefreshNarrowsToCurrentEndpoint(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nrefresh\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	scoped := segmentBeforePrompt(output, "endpoint[host-one/endpoint-1]> ")
	if !strings.Contains(scoped, "host-one") {
		t.Fatalf("missing current endpoint row: %q", scoped)
	}
	if strings.Contains(scoped, "host-two") {
		t.Fatalf("endpoint refresh leaked another endpoint: %q", scoped)
	}
}

func TestRefreshRendersTableInSessionScope(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1/res-1\nrefresh\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	scoped := segmentBeforePrompt(output, "session[host-one/provider-res-1]> ")
	if !strings.Contains(scoped, "DATA_STATUS") || !strings.Contains(scoped, "host-one") {
		t.Fatalf("session refresh did not render the endpoint table: %q", scoped)
	}
	if strings.Contains(scoped, "host-two") {
		t.Fatalf("session refresh leaked another endpoint: %q", scoped)
	}
	if got := lastPrompt(output); got != "session[host-one/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want session prompt", got)
	}
}

func TestRefreshInSessionScopeStillRevalidatesTheSelection(t *testing.T) {
	stub := scopeStub()
	// Startup list, cd, then refresh: the refresh read is the fifth inventory call,
	// so only that read reports a new generation for the pinned session.
	stub.generationSequence = []string{"generation-1", "generation-1", "generation-1", "generation-1", "generation-2"}
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nrefresh\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: selected session generation changed; use the session again")
	if got := strings.Count(output, "DATA_STATUS"); got != 1 {
		t.Fatalf("refresh rendered %d tables for an invalidated selection, want only the startup table: %q", got, output)
	}
	if got := lastPrompt(output); got != "session[host-one/provider-res-1!]>" {
		t.Fatalf("final prompt = %q, want invalidated session prompt", got)
	}
}

func TestStatusAcceptsExplicitCommandIDInEveryScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "workspace", input: "status cmd-1\nexit\n"},
		{name: "endpoint", input: "cd host-one/endpoint-1\nstatus cmd-1\nexit\n"},
		{name: "session", input: "cd host-one/endpoint-1/res-1\nstatus cmd-1\nexit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			output, diagnostics := runScope(t, scopeStub(), testCase.input, ColorPolicy{})
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			want := "CommandID: cmd-1\nStatus: finished\nDeliveryBoundary: \nEffectCertainty: \nErrorCode: \n"
			if !strings.Contains(output, want) {
				t.Fatalf("missing interactive status fields %q in output: %q", want, output)
			}
			if strings.Contains(output, "confirmed result") {
				t.Fatalf("interactive status used legacy semantic label: %q", output)
			}
		})
	}
}

func TestStatusWithoutCommandIDExplainsTheShortForm(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "status\nexit\n", ColorPolicy{})
	want := "error: no command has been submitted in this CLI yet; run an action such as start, then run status without an argument\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestHelpAndQuitRemainAvailableInEveryScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "workspace", input: "help\nexit\n"},
		{name: "endpoint", input: "cd host-one/endpoint-1\nhelp\nexit\n"},
		{name: "session", input: "cd host-one/endpoint-1/res-1\nhelp\nexit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			output, diagnostics := runScope(t, scopeStub(), testCase.input, ColorPolicy{})
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if !strings.Contains(output, "Current scope:") {
				t.Fatalf("help was not rendered: %q", output)
			}
		})
	}
}

// TestCompletableCommandsAddOnlyMultiCharacterAliases proves completion offers
// every canonical command plus each alias that is genuinely partial while it is
// typed. A one-character alias is already complete, so offering it would only
// turn a unique completion into a false ambiguity.
func TestCompletableCommandsAddOnlyMultiCharacterAliases(t *testing.T) {
	for _, testCase := range []struct {
		kind ScopeKind
		want string
	}{
		{ScopeWorkspace, "list, endpoints, cd, show, info, start, resume, stop, clean, drive, logs, status, refresh, watch, history, project, messages, model, help, quit, exit"},
		{ScopeEndpoint, "list, cd, show, info, start, resume, stop, clean, drive, logs, status, refresh, watch, history, project, messages, model, help, quit, exit"},
		{ScopeSession, "list, cd, show, info, stop, btw, interrupt, ctl, drive, logs, send, status, refresh, messages, model, help, quit, exit, control"},
	} {
		t.Run(testCase.kind.String(), func(t *testing.T) {
			if got := strings.Join(completableCommands(testCase.kind), ", "); got != testCase.want {
				t.Fatalf("completableCommands(%s)=%q want %q", testCase.kind, got, testCase.want)
			}
		})
	}
	// Every canonical command stays completable, so the alias set is additive.
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession} {
		completable := completableCommands(kind)
		for _, name := range availableCommands(kind) {
			if !containsCommand(completable, name) {
				t.Fatalf("scope=%s lost canonical command %q", kind, name)
			}
		}
	}
}

func TestAvailableCommandsUseStableOrder(t *testing.T) {
	cases := []struct {
		kind ScopeKind
		want string
	}{
		{kind: ScopeWorkspace, want: "list, endpoints, cd, show, info, start, resume, stop, clean, drive, logs, status, refresh, watch, history, project, messages, model, help, quit, exit"},
		{kind: ScopeEndpoint, want: "list, cd, show, info, start, resume, stop, clean, drive, logs, status, refresh, watch, history, project, messages, model, help, quit, exit"},
		{kind: ScopeSession, want: "list, cd, show, info, stop, btw, interrupt, ctl, drive, logs, send, status, refresh, messages, model, help, quit, exit"},
	}
	for _, testCase := range cases {
		t.Run(testCase.kind.String(), func(t *testing.T) {
			if got := strings.Join(availableCommands(testCase.kind), ", "); got != testCase.want {
				t.Fatalf("availableCommands(%s) = %q, want %q", testCase.kind, got, testCase.want)
			}
		})
	}
}

func TestCommandAllowedKeepsUnknownNamesPassThrough(t *testing.T) {
	if !commandAllowed("bogus", ScopeWorkspace) {
		t.Fatal("unknown command must reach the unknown-command diagnostic")
	}
	if commandAllowed("send", ScopeWorkspace) {
		t.Fatal("send must be rejected in workspace scope")
	}
	if !commandAllowed("help", ScopeWorkspace) || !commandAllowed("quit", ScopeSession) {
		t.Fatal("help and quit must always be allowed")
	}
}

func TestUnknownCommandDiagnosticIsPreserved(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "bogus\nexit\n", ColorPolicy{})
	want := "error: unknown command \"bogus\" (try help)\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestRemovedCommandsKeepTheirDiagnostics(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "table", input: "table\nexit\n", want: "error: \"table\" has been removed; use \"list --clean\" for the previous behavior\n"},
		{name: "use", input: "use 1\nexit\n", want: "error: \"use\" has been removed; use \"cd\" to navigate\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, diagnostics := runScope(t, scopeStub(), testCase.input, ColorPolicy{})
			assertActionableError(t, diagnostics, strings.TrimSuffix(testCase.want, "\n"))
		})
	}
}

func TestScopeMatrixKeepsTableHeaderAndStateColors(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "list\nexit\n", ColorPolicy{Enabled: true})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, ansiBoldCyan+"NO") {
		t.Fatalf("table header lost bold cyan styling: %q", output)
	}
	if !strings.Contains(output, ansiGreen+"running") {
		t.Fatalf("running state lost green styling: %q", output)
	}
}

func TestScopePromptsKeepExactAnsiSequences(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "workspace", input: "exit\n", want: ansiBoldGreen + "workspace>" + ansiReset + " "},
		{name: "endpoint", input: "cd host-one/endpoint-1\nexit\n", want: ansiBoldGreen + "endpoint[host-one/endpoint-1]>" + ansiReset + " "},
		{name: "session", input: "cd host-one/endpoint-1/res-1\nexit\n", want: ansiBoldGreen + "session[host-one/provider-res-1]>" + ansiReset + " "},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			output, _ := runScope(t, scopeStub(), testCase.input, ColorPolicy{Enabled: true})
			if !strings.Contains(output, testCase.want) {
				t.Fatalf("output = %q, want prompt %q", output, testCase.want)
			}
			if strings.Contains(testCase.want, ansiCyan) || strings.Contains(testCase.want, ansiBoldCyan) {
				t.Fatalf("prompt contains cyan styling: %q", testCase.want)
			}
		})
	}
}

func TestStartIsUnavailableInSessionScope(t *testing.T) {
	if err := requireCommandScope("start", ScopeSession); err == nil {
		t.Fatal("start unexpectedly allowed in session scope")
	}
}
