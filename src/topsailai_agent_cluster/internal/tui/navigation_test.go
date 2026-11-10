package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// navStub serves a fixed endpoint inventory for navigation tests.
type navStub struct {
	interactiveStub
	endpoints []protocol.Endpoint
	reports   map[string]protocol.InventoryReport
}

func (s *navStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return s.endpoints, nil
}

func (s *navStub) GetInventory(_ context.Context, id string) (protocol.InventoryReport, error) {
	if s.inventoryErr != nil {
		return protocol.InventoryReport{}, s.inventoryErr
	}
	report, ok := s.reports[id]
	if !ok {
		return protocol.InventoryReport{}, errNavMissingInventory
	}
	return report, nil
}

// errNavMissingInventory marks an endpoint without a report.
var errNavMissingInventory = navMissingInventoryError{}

type navMissingInventoryError struct{}

func (navMissingInventoryError) Error() string { return "missing inventory" }

// navInventory builds a complete report holding one fresh session.
func navInventory(sessionID, generation string) protocol.InventoryReport {
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

// singleHostStub serves one endpoint carrying a hostname.
func singleHostStub() *navStub {
	return &navStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", Hostname: "ai-dev", DisplayName: "host-a"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": navInventory("res-1", "generation-1")},
	}
}

// conflictStub serves two endpoints sharing the same hostname.
func conflictStub() *navStub {
	return &navStub{
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-2", Hostname: "ai-dev", DisplayName: "host-b"},
			{EndpointID: "endpoint-1", Hostname: "ai-dev", DisplayName: "host-a"},
		},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": navInventory("res-1", "generation-1"),
			"endpoint-2": navInventory("res-2", "generation-2"),
		},
	}
}

// runNav executes an interactive scenario and returns both streams.
func runNav(t *testing.T, stub InteractiveAPI, input string) (string, string) {
	t.Helper()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	return output.String(), diagnostics.String()
}

// lastPrompt returns the final prompt line of the captured output.
func lastPrompt(output string) string {
	trimmed := strings.TrimSuffix(output, " ")
	index := -1
	for _, prefix := range []string{"workspace>", "endpoint[", "session["} {
		if candidate := strings.LastIndex(trimmed, prefix); candidate > index {
			index = candidate
		}
	}
	if index < 0 {
		return ""
	}
	return trimmed[index:]
}

func TestCDRowNumberUsesMostRecentList(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runNav(t, stub, "list\ncd 1\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "session[host-one/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want first session", got)
	}
}

func TestCDRowNumberRejectsInvalidAndSessionScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "zero", input: "list\ncd 0\nexit\n", want: "error: row 0 is out of range; valid rows are 1-2\n"},
		{name: "out of range", input: "list\ncd 99\nexit\n", want: "error: row 99 is out of range; valid rows are 1-2\n"},
		{name: "session scope", input: "list\ncd 1\ncd 1\nexit\n", want: "error: row-number navigation is unavailable in session scope; use cd .. or cd <session>\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, diagnostics := runNav(t, scopeStub(), testCase.input)
			assertActionableError(t, diagnostics, strings.TrimSuffix(testCase.want, "\n"))
		})
	}
}

func TestCDWithoutArgumentsReturnsToWorkspace(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "from session", input: "cd ai-dev/endpoint-1/res-1\ncd\nexit\n"},
		{name: "from endpoint", input: "cd ai-dev/endpoint-1\ncd\nexit\n"},
		{name: "from workspace", input: "cd\nexit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			output, diagnostics := runNav(t, singleHostStub(), testCase.input)
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if got := lastPrompt(output); got != "workspace>" {
				t.Fatalf("final prompt = %q, want workspace prompt", got)
			}
		})
	}
}

func TestCDSlashReturnsToWorkspaceFromAnyScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "from session", input: "cd ai-dev/endpoint-1/res-1\ncd /\nexit\n"},
		{name: "from endpoint", input: "cd ai-dev/endpoint-1\ncd /\nexit\n"},
		{name: "from workspace", input: "cd /\nexit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			output, diagnostics := runNav(t, singleHostStub(), testCase.input)
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if got := lastPrompt(output); got != "workspace>" {
				t.Fatalf("final prompt = %q, want workspace prompt", got)
			}
		})
	}
}

func TestCDParentMovesOneLevelUp(t *testing.T) {
	t.Run("session to endpoint", func(t *testing.T) {
		output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1/res-1\ncd ..\nexit\n")
		if diagnostics != "" {
			t.Fatalf("unexpected diagnostics: %q", diagnostics)
		}
		if got := lastPrompt(output); got != "endpoint[ai-dev/endpoint-1]>" {
			t.Fatalf("final prompt = %q, want endpoint prompt with hostname", got)
		}
	})
	t.Run("endpoint to workspace", func(t *testing.T) {
		output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1\ncd ..\nexit\n")
		if diagnostics != "" {
			t.Fatalf("unexpected diagnostics: %q", diagnostics)
		}
		if got := lastPrompt(output); got != "workspace>" {
			t.Fatalf("final prompt = %q, want workspace prompt", got)
		}
	})
	t.Run("workspace stays workspace", func(t *testing.T) {
		output, diagnostics := runNav(t, singleHostStub(), "cd ..\nexit\n")
		if diagnostics != "" {
			t.Fatalf("unexpected diagnostics: %q", diagnostics)
		}
		if !strings.Contains(output, "already at workspace scope\n") {
			t.Fatalf("missing workspace notice: %q", output)
		}
		if got := lastPrompt(output); got != "workspace>" {
			t.Fatalf("final prompt = %q, want workspace prompt", got)
		}
	})
}

func TestCDHostnameEntersUniqueEndpoint(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "endpoint[ai-dev/endpoint-1]>" {
		t.Fatalf("final prompt = %q, want endpoint prompt", got)
	}
}

func TestCDHostnameConflictListsStableCandidates(t *testing.T) {
	output, diagnostics := runNav(t, conflictStub(), "cd ai-dev\ncancel\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	want := "multiple endpoints match hostname \"ai-dev\":\n" +
		"  1. ai-dev / endpoint-1 / host-a\n" +
		"  2. ai-dev / endpoint-2 / host-b\n" +
		"select endpoint [1-2] or 'cancel': "
	if !strings.Contains(output, want) {
		t.Fatalf("conflict prompt = %q, want %q", output, want)
	}
}

func TestCDHostnameConflictSelectsNumberedCandidate(t *testing.T) {
	output, diagnostics := runNav(t, conflictStub(), "cd ai-dev\n2\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "endpoint[ai-dev/endpoint-2]>" {
		t.Fatalf("final prompt = %q, want second candidate endpoint", got)
	}
}

func TestCDHostnameConflictAcceptsFullPath(t *testing.T) {
	output, diagnostics := runNav(t, conflictStub(), "cd ai-dev\nai-dev/endpoint-2\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "endpoint[ai-dev/endpoint-2]>" {
		t.Fatalf("final prompt = %q, want second candidate endpoint", got)
	}
}

func TestCDHostnameConflictCancelKeepsScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "cancel", input: "cd ai-dev\ncancel\nexit\n", want: "scope transition cancelled\n"},
		{name: "empty answer", input: "cd ai-dev\n\nexit\n", want: "scope transition cancelled\n"},
		{name: "invalid index", input: "cd ai-dev\n9\nexit\n", want: "invalid selection; scope transition cancelled\n"},
		{name: "invalid text", input: "cd ai-dev\nnope\nexit\n", want: "invalid selection; scope transition cancelled\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			output, diagnostics := runNav(t, conflictStub(), testCase.input)
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if !strings.Contains(output, testCase.want) {
				t.Fatalf("output = %q, want %q", output, testCase.want)
			}
			if got := lastPrompt(output); got != "workspace>" {
				t.Fatalf("final prompt = %q, want unchanged workspace prompt", got)
			}
		})
	}
}

func TestCDHostnameConflictEOFKeepsScope(t *testing.T) {
	output, diagnostics := runNav(t, conflictStub(), "cd ai-dev\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "scope transition cancelled\n") {
		t.Fatalf("output = %q, want cancellation notice", output)
	}
	if got := lastPrompt(output); got != "workspace>" {
		t.Fatalf("final prompt = %q, want unchanged workspace prompt", got)
	}
}

func TestCDHostnameEndpointPathEntersEndpoint(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "endpoint[ai-dev/endpoint-1]>" {
		t.Fatalf("final prompt = %q, want endpoint prompt", got)
	}
}

func TestCDSessionInsideEndpointScope(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1\ncd res-1\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "session[ai-dev/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want session prompt", got)
	}
}

func TestCDFullPathEntersSession(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1/res-1\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "session[ai-dev/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want session prompt", got)
	}
}

func TestCDUnknownTargetsReportExactErrors(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "unknown endpoint", input: "cd nope\nexit\n", want: "error: endpoint \"nope\" was not found\n"},
		{name: "unknown endpoint path", input: "cd ai-dev/nope\nexit\n", want: "error: endpoint \"ai-dev/nope\" was not found\n"},
		{name: "unknown session", input: "cd ai-dev/endpoint-1/nope\nexit\n", want: "error: session \"nope\" was not found on endpoint \"endpoint-1\"\n"},
		{name: "unknown session in endpoint scope", input: "cd ai-dev/endpoint-1\ncd nope\nexit\n", want: "error: session \"nope\" was not found on endpoint \"endpoint-1\"\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, diagnostics := runNav(t, singleHostStub(), testCase.input)
			assertActionableError(t, diagnostics, strings.TrimSuffix(testCase.want, "\n"))
		})
	}
}

func TestCDFailureKeepsCurrentScope(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1\ncd nope\nexit\n")
	if !strings.Contains(diagnostics, "was not found") {
		t.Fatalf("missing failure diagnostic: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "endpoint[ai-dev/endpoint-1]>" {
		t.Fatalf("final prompt = %q, want unchanged endpoint prompt", got)
	}
}

func TestCDFailureKeepsSessionScope(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "cd ai-dev/endpoint-1/res-1\ncd ai-dev/endpoint-1/nope\nexit\n")
	if !strings.Contains(diagnostics, "was not found") {
		t.Fatalf("missing failure diagnostic: %q", diagnostics)
	}
	if got := lastPrompt(output); got != "session[ai-dev/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want unchanged session prompt", got)
	}
}

func TestUseCommandReportsRemoval(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "use 1\nexit\n")
	assertActionableError(t, diagnostics, `error: "use" has been removed; use "cd" to navigate`)
	if got := lastPrompt(output); got != "workspace>" {
		t.Fatalf("final prompt = %q, want unchanged workspace prompt", got)
	}
}

func TestCDPromptFillsHostnameThroughRealListPath(t *testing.T) {
	output, diagnostics := runNav(t, singleHostStub(), "list\ncd ai-dev/endpoint-1/res-1\nexit\n")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "ai-dev") {
		t.Fatalf("list did not render the endpoint hostname: %q", output)
	}
	if got := lastPrompt(output); got != "session[ai-dev/provider-res-1]>" {
		t.Fatalf("final prompt = %q, want hostname in session prompt", got)
	}
}

func TestCDPromptFillsHostnameFromListRows(t *testing.T) {
	stub := singleHostStub()
	rows := ListRows(stub.endpoints, stub.reports, "")
	assignRowNumbers(rows)
	state := interactiveState{}
	state.setRows(rows)
	if len(state.Rows) != 1 {
		t.Fatalf("rows = %d, want 1", len(state.Rows))
	}
	row := state.Rows[1]
	if row.EndpointID != "endpoint-1" || row.ClusterSessionID != "res-1" || row.ProviderGeneration != "generation-1" {
		t.Fatalf("row identity = %+v", row)
	}
	state.enterSessionDetails(stub.endpoints[0], row.ClusterSessionID, row.ProviderSessionID, row.ProviderDisplayName, row.AdapterID, row.ProviderGeneration)
	var prompt strings.Builder
	if err := RenderPrompt(&prompt, state.Scope, false, ColorPolicy{}); err != nil {
		t.Fatal(err)
	}
	if got, want := prompt.String(), "session[ai-dev/provider-res-1]> "; got != want {
		t.Fatalf("prompt = %q, want %q", got, want)
	}
}

func TestCDPromptsUseExactAnsiSequences(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "workspace", input: "exit\n", want: ansiBoldGreen + "workspace>" + ansiReset + " "},
		{name: "endpoint", input: "cd ai-dev/endpoint-1\nexit\n", want: ansiBoldGreen + "endpoint[ai-dev/endpoint-1]>" + ansiReset + " "},
		{name: "session", input: "cd ai-dev/endpoint-1/res-1\nexit\n", want: ansiBoldGreen + "session[ai-dev/provider-res-1]>" + ansiReset + " "},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var output, diagnostics strings.Builder
			if err := RunInteractive(context.Background(), singleHostStub(), strings.NewReader(testCase.input), &output, &diagnostics, InteractiveOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
				t.Fatalf("RunInteractive: %v", err)
			}
			if !strings.Contains(output.String(), testCase.want) {
				t.Fatalf("output = %q, want prompt %q", output.String(), testCase.want)
			}
			if strings.Contains(testCase.want, ansiCyan) || strings.Contains(testCase.want, ansiBoldCyan) {
				t.Fatalf("prompt contains cyan styling: %q", testCase.want)
			}
		})
	}
}

func TestCDPromptHasNoAnsiWhenColorDisabled(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), singleHostStub(), strings.NewReader("cd ai-dev/endpoint-1/res-1\nexit\n"), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if strings.Contains(output.String(), "\x1b") {
		t.Fatalf("colorless output contains ANSI: %q", output.String())
	}
	if !strings.Contains(output.String(), "session[ai-dev/provider-res-1]> ") {
		t.Fatalf("missing plain prompt: %q", output.String())
	}
}

func TestListTableKeepsHeaderAndStateColors(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), singleHostStub(), strings.NewReader("list\nexit\n"), &output, &diagnostics, InteractiveOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	text := output.String()
	if !strings.Contains(text, ansiBoldCyan+"NO") {
		t.Fatalf("table header lost bold cyan styling: %q", text)
	}
	if !strings.Contains(text, ansiGreen+"running") {
		t.Fatalf("running state lost green styling: %q", text)
	}
}

func TestSessionPromptUsesProviderSessionIDAndSanitizesIt(t *testing.T) {
	cases := []struct {
		name  string
		scope ScopeState
		want  string
	}{
		{name: "provider session id", scope: ScopeState{Kind: ScopeSession, Hostname: "ai-dev", ProviderSessionID: "20261027152208", SessionName: "统一Agent管理方案"}, want: "session[ai-dev/20261027152208]> "},
		{name: "empty provider session id", scope: ScopeState{Kind: ScopeSession, Hostname: "ai-dev", ProviderSessionID: "", SessionName: "统一Agent管理方案", ClusterSessionID: "res_1234567890abcdef"}, want: "session[ai-dev/-]> "},
		{name: "slash in provider session id", scope: ScopeState{Kind: ScopeSession, Hostname: "ai-dev", ProviderSessionID: "provider/session"}, want: "session[ai-dev/provider∕session]> "},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var output strings.Builder
			if err := RenderPrompt(&output, testCase.scope, false, ColorPolicy{}); err != nil {
				t.Fatal(err)
			}
			if output.String() != testCase.want {
				t.Fatalf("prompt = %q, want %q", output.String(), testCase.want)
			}
			if strings.Contains(output.String(), "res_") || (testCase.scope.SessionName != "" && strings.Contains(output.String(), testCase.scope.SessionName)) {
				t.Fatalf("prompt leaked forbidden session identity: %q", output.String())
			}
		})
	}
}

func TestSessionPromptKeepsGreenBoldStyle(t *testing.T) {
	var output strings.Builder
	scope := ScopeState{Kind: ScopeSession, Hostname: "ai-dev", ProviderSessionID: "20261027152208"}
	if err := RenderPrompt(&output, scope, false, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	if got, want := output.String(), ansiBoldGreen+"session[ai-dev/20261027152208]>"+ansiReset+" "; got != want {
		t.Fatalf("prompt = %q, want %q", got, want)
	}
}

func TestSessionPromptDoesNotFallBackToDisplayNameOrResourceID(t *testing.T) {
	var output strings.Builder
	scope := ScopeState{Kind: ScopeSession, Hostname: "ai-dev", ClusterSessionID: "res_1234567890abcdef", SessionName: "display-name"}
	if err := RenderPrompt(&output, scope, false, ColorPolicy{}); err != nil {
		t.Fatal(err)
	}
	if got, want := output.String(), "session[ai-dev/-]> "; got != want {
		t.Fatalf("prompt = %q, want %q", got, want)
	}
}
