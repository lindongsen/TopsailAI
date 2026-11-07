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
			SessionID:         sessionID,
			ProviderSessionID: "provider-" + sessionID,
			AdapterID:         "adapter-1",
			Generation:        generation,
			State:             "running",
			CollectionStatus:  protocol.CollectionSucceeded,
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
		SessionID:         "res-1b",
		ProviderSessionID: "provider-1b",
		AdapterID:         "adapter-1",
		Generation:        "generation-1b",
		State:             "stopped",
		CollectionStatus:  protocol.CollectionSucceeded,
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
			input: "send {\"text\":\"hi\"}\nquit\n",
			want:  "error: command \"send\" is unavailable in workspace scope; available commands: list, endpoints, cd, show, start, stop, status, refresh, watch, help, quit\n",
		},
		{
			name:  "endpoint",
			input: "cd host-one/endpoint-1\nsend {\"text\":\"hi\"}\nquit\n",
			want:  "error: command \"send\" is unavailable in endpoint scope; available commands: list, cd, show, start, stop, logs, status, refresh, watch, help, quit\n",
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
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nsend {\"text\":\"hi\"}\ny\nquit\n", ColorPolicy{})
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

func TestLogsIsUnavailableInWorkspaceScope(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "logs\nquit\n", ColorPolicy{})
	want := "error: command \"logs\" is unavailable in workspace scope; available commands: list, endpoints, cd, show, start, stop, status, refresh, watch, help, quit\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestLogsRequiresSessionInEndpointScope(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nlogs\nquit\n", ColorPolicy{})
	want := "error: no session selected; use cd <number> to select a session row, or cd <hostname>/<endpoint-id>/<session>\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestLogsAcceptsSessionArgumentInEndpointScope(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nlogs res-1\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "observed_at_ms:") || !strings.Contains(output, "truncated: false") {
		t.Fatalf("missing snapshot evidence: %q", output)
	}
}

func TestLogsUsesCurrentSessionInSessionScope(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1/res-1\nlogs\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "observed_at_ms:") {
		t.Fatalf("missing snapshot evidence: %q", output)
	}
}

func TestListNarrowsToCurrentEndpoint(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nlist\nquit\n", ColorPolicy{})
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
	output, diagnostics := runScope(t, siblingStub(), "cd host-one/endpoint-1/res-1\nlist\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	scoped := segmentBeforePrompt(output, "session[host-one/provider-res-1]> ")
	if !strings.Contains(scoped, "provider-1b") {
		t.Fatalf("missing sibling session: %q", scoped)
	}
	if strings.Contains(scoped, "res-2") {
		t.Fatalf("list leaked another endpoint: %q", scoped)
	}
}

func TestListRejectsMismatchingFilterOutsideWorkspace(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nlist endpoint-2\nquit\n", ColorPolicy{})
	want := "error: list filter \"endpoint-2\" does not match the current endpoint \"endpoint-1\"\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestShowRequiresTargetInWorkspaceScope(t *testing.T) {
	_, diagnostics := runScope(t, scopeStub(), "show\nquit\n", ColorPolicy{})
	want := "error: show requires an endpoint or session in workspace scope; use show <number> for a session row or show <endpoint-id>\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestShowDefaultsToCurrentEndpoint(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nshow\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "endpoint: endpoint-1 (") {
		t.Fatalf("missing endpoint detail: %q", output)
	}
}

func TestShowDefaultsToCurrentSession(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1/res-1\nshow\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	want := "session: res-1 adapter=adapter-1 generation=generation-1 state=running"
	if !strings.Contains(output, want) {
		t.Fatalf("missing session detail %q in %q", want, output)
	}
}

func TestRefreshCoversWorkspaceScope(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "refresh\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "host-one") || !strings.Contains(output, "host-two") {
		t.Fatalf("workspace refresh did not cover every endpoint: %q", output)
	}
}

func TestRefreshNarrowsToCurrentEndpoint(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1\nrefresh\nquit\n", ColorPolicy{})
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
	output, diagnostics := runScope(t, scopeStub(), "cd host-one/endpoint-1/res-1\nrefresh\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	scoped := segmentBeforePrompt(output, "session[host-one/provider-res-1]> ")
	if !strings.Contains(scoped, "SESSION_ID") || !strings.Contains(scoped, "provider-res-1") {
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
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nrefresh\nquit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: selected session generation changed; use the session again")
	if got := strings.Count(output, "SESSION_ID"); got != 1 {
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
		{name: "workspace", input: "status cmd-1\nquit\n"},
		{name: "endpoint", input: "cd host-one/endpoint-1\nstatus cmd-1\nquit\n"},
		{name: "session", input: "cd host-one/endpoint-1/res-1\nstatus cmd-1\nquit\n"},
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
	_, diagnostics := runScope(t, scopeStub(), "status\nquit\n", ColorPolicy{})
	want := "error: no command has been submitted in this CLI yet; run an action such as start, then run status without an argument\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestHelpAndQuitRemainAvailableInEveryScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "workspace", input: "help\nquit\n"},
		{name: "endpoint", input: "cd host-one/endpoint-1\nhelp\nquit\n"},
		{name: "session", input: "cd host-one/endpoint-1/res-1\nhelp\nquit\n"},
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

func TestAvailableCommandsUseStableOrder(t *testing.T) {
	cases := []struct {
		kind ScopeKind
		want string
	}{
		{kind: ScopeWorkspace, want: "list, endpoints, cd, show, start, stop, status, refresh, watch, help, quit"},
		{kind: ScopeEndpoint, want: "list, cd, show, start, stop, logs, status, refresh, watch, help, quit"},
		{kind: ScopeSession, want: "list, cd, show, resume, stop, inject, interrupt, ctl, drive, logs, send, status, refresh, help, quit"},
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
	_, diagnostics := runScope(t, scopeStub(), "bogus\nquit\n", ColorPolicy{})
	want := "error: unknown command \"bogus\" (try help)\n"
	assertActionableError(t, diagnostics, strings.TrimSuffix(want, "\n"))
}

func TestRemovedCommandsKeepTheirDiagnostics(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "table", input: "table\nquit\n", want: "error: \"table\" has been removed; use \"list --clean\" for the previous behavior\n"},
		{name: "use", input: "use 1\nquit\n", want: "error: \"use\" has been removed; use \"cd\" to navigate\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, diagnostics := runScope(t, scopeStub(), testCase.input, ColorPolicy{})
			assertActionableError(t, diagnostics, strings.TrimSuffix(testCase.want, "\n"))
		})
	}
}

func TestScopeMatrixKeepsTableHeaderAndStateColors(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "list\nquit\n", ColorPolicy{Enabled: true})
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
		{name: "workspace", input: "quit\n", want: ansiBoldGreen + "workspace>" + ansiReset + " "},
		{name: "endpoint", input: "cd host-one/endpoint-1\nquit\n", want: ansiBoldGreen + "endpoint[host-one/endpoint-1]>" + ansiReset + " "},
		{name: "session", input: "cd host-one/endpoint-1/res-1\nquit\n", want: ansiBoldGreen + "session[host-one/provider-res-1]>" + ansiReset + " "},
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
