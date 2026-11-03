package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// helpText renders one help target and returns the raw text.
func helpText(t *testing.T, target string) string {
	t.Helper()
	var out strings.Builder
	if err := PrintCommandHelp(&out, target); err != nil {
		t.Fatalf("PrintCommandHelp(%q): %v", target, err)
	}
	return out.String()
}

// scopeGroup returns the command lines of one scope group in the overview.
func scopeGroup(t *testing.T, overview, scope string) []string {
	t.Helper()
	marker := "\n" + scope + ":\n"
	index := strings.Index(overview, marker)
	if index < 0 {
		t.Fatalf("overview missing %q group: %q", scope, overview)
	}
	rest := overview[index+len(marker):]
	lines := make([]string, 0)
	for _, line := range strings.Split(rest, "\n") {
		if strings.TrimSpace(line) == "" {
			break
		}
		lines = append(lines, strings.TrimSpace(line))
	}
	return lines
}

// groupCommandNames extracts the leading command name of each group line.
func groupCommandNames(lines []string) []string {
	names := make([]string, 0, len(lines))
	for _, line := range lines {
		fields := strings.Fields(line)
		if len(fields) == 0 {
			continue
		}
		names = append(names, fields[0])
	}
	return names
}

func TestHelpOverviewGroupsEveryScope(t *testing.T) {
	overview := helpText(t, "")
	if !strings.Contains(overview, "Commands by scope:") {
		t.Fatalf("overview missing heading: %q", overview)
	}
	for _, scope := range []string{"workspace", "endpoint", "session"} {
		if !strings.Contains(overview, "\n"+scope+":\n") {
			t.Fatalf("overview missing %q group: %q", scope, overview)
		}
	}
}

func TestHelpOverviewKeepsGroupOrder(t *testing.T) {
	overview := helpText(t, "")
	workspace := strings.Index(overview, "\nworkspace:\n")
	endpoint := strings.Index(overview, "\nendpoint:\n")
	session := strings.Index(overview, "\nsession:\n")
	if workspace < 0 || endpoint < 0 || session < 0 {
		t.Fatalf("overview groups missing: %q", overview)
	}
	if !(workspace < endpoint && endpoint < session) {
		t.Fatalf("group order is not workspace, endpoint, session: %q", overview)
	}
}

func TestHelpOverviewFollowsMatrixOrder(t *testing.T) {
	overview := helpText(t, "")
	for _, kind := range scopeHelpOrder {
		got := groupCommandNames(scopeGroup(t, overview, kind.String()))
		want := availableCommands(kind)
		if strings.Join(got, ",") != strings.Join(want, ",") {
			t.Fatalf("%s group order = %v, want %v", kind, got, want)
		}
	}
}

func TestHelpOverviewDerivesAvailabilityFromMatrix(t *testing.T) {
	overview := helpText(t, "")
	workspace := groupCommandNames(scopeGroup(t, overview, "workspace"))
	endpoint := groupCommandNames(scopeGroup(t, overview, "endpoint"))
	session := groupCommandNames(scopeGroup(t, overview, "session"))
	for _, name := range []string{"send", "logs"} {
		if containsName(workspace, name) {
			t.Fatalf("workspace group must not list %q: %v", name, workspace)
		}
	}
	if containsName(endpoint, "send") {
		t.Fatalf("endpoint group must not list send: %v", endpoint)
	}
	if !containsName(endpoint, "logs") {
		t.Fatalf("endpoint group must list logs: %v", endpoint)
	}
	if !containsName(session, "send") {
		t.Fatalf("session group must list send: %v", session)
	}
}

// containsName reports whether names holds the given command name.
func containsName(names []string, name string) bool {
	for _, candidate := range names {
		if candidate == name {
			return true
		}
	}
	return false
}

func TestHelpCommandReportsAvailableScopes(t *testing.T) {
	cases := []struct {
		target string
		want   string
	}{
		{"send", "Available in: session"},
		{"logs", "Available in: endpoint, session"},
		{"list", "Available in: workspace, endpoint, session"},
		{"cd", "Available in: workspace, endpoint, session"},
	}
	for _, testCase := range cases {
		text := helpText(t, testCase.target)
		if !strings.Contains(text, testCase.want+"\n") {
			t.Fatalf("help %s missing %q: %q", testCase.target, testCase.want, text)
		}
	}
}

func TestHelpCommandPlacesAvailableInAfterSyntax(t *testing.T) {
	text := helpText(t, "send")
	syntax := strings.Index(text, "Syntax: ")
	available := strings.Index(text, "Available in: ")
	description := strings.Index(text, "Description: ")
	if syntax < 0 || available < 0 || description < 0 {
		t.Fatalf("help send missing sections: %q", text)
	}
	if !(syntax < available && available < description) {
		t.Fatalf("section order is not syntax, available, description: %q", text)
	}
}

func TestHelpScopeDescribesScopeModel(t *testing.T) {
	text := helpText(t, "scope")
	for _, want := range []string{
		"Scope model:",
		"workspace  the root scope; shows all endpoints and sessions",
		"endpoint   entered with cd <hostname> or cd <hostname>/<endpoint-id>",
		"session    entered with cd <session> or cd <hostname>/<endpoint-id>/<session>",
		"Navigation:",
		"Commands differ by scope; run help to see the commands available in each scope.",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("help scope missing %q: %q", want, text)
		}
	}
}

func TestHelpScopesAliasMatchesScopeHelp(t *testing.T) {
	if helpText(t, "scopes") != helpText(t, "scope") {
		t.Fatal("help scopes alias differs from help scope")
	}
}

func TestHelpCDListsEveryNavigationForm(t *testing.T) {
	text := helpText(t, "cd")
	for _, want := range []string{
		"  cd\n",
		"  cd /\n",
		"  cd ..\n",
		"  cd ai-dev\n",
		"  cd ai-dev/endpoint-1\n",
		"  cd res_abc\n",
		"  cd ai-dev/endpoint-1/res_abc\n",
	} {
		if !strings.Contains(text, want) {
			t.Fatalf("help cd missing %q: %q", want, text)
		}
	}
	if !strings.Contains(text, "cancel") {
		t.Fatalf("help cd missing conflict cancellation: %q", text)
	}
}

func TestCommandHelpLinesStayNonInteractiveCompatible(t *testing.T) {
	lines := CommandHelpLines()
	if len(lines) != len(commandHelpOrder) {
		t.Fatalf("CommandHelpLines returned %d lines, want %d", len(lines), len(commandHelpOrder))
	}
	for index, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		want := entry.syntax + "   " + entry.description
		if lines[index] != want {
			t.Fatalf("line %d = %q, want %q", index, lines[index], want)
		}
	}
	for _, line := range lines {
		if strings.Contains(line, "Available in:") || strings.Contains(line, "Commands by scope:") {
			t.Fatalf("non-interactive help line leaked scope grouping: %q", line)
		}
	}
}

func TestHelpOverviewKeepsTableAndStateColors(t *testing.T) {
	output, _ := runScope(t, scopeStub(), "list\nquit\n", ColorPolicy{Enabled: true})
	if !strings.Contains(output, ansiBoldCyan+"NO") {
		t.Fatalf("table header lost bold cyan: %q", output)
	}
	if !strings.Contains(output, ansiGreen+"running") {
		t.Fatalf("running state lost green: %q", output)
	}
}

func TestHelpOverviewKeepsScopePrompts(t *testing.T) {
	cases := []struct {
		name  string
		scope ScopeState
		want  string
	}{
		{"workspace", ScopeState{Kind: ScopeWorkspace}, ansiBoldGreen + "cluster>" + ansiReset + " "},
		{"endpoint", ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1", Hostname: "ai-dev"}, ansiBoldGreen + "cluster[ai-dev/endpoint-1]>" + ansiReset + " "},
		{"session", ScopeState{Kind: ScopeSession, EndpointID: "endpoint-1", Hostname: "ai-dev", ProviderSessionID: "20261027152208", SessionID: "res-1"}, ansiBoldGreen + "cluster[ai-dev/20261027152208]>" + ansiReset + " "},
	}
	for _, testCase := range cases {
		var out strings.Builder
		if err := RenderPrompt(&out, testCase.scope, false, ColorPolicy{Enabled: true}); err != nil {
			t.Fatalf("RenderPrompt: %v", err)
		}
		if out.String() != testCase.want {
			t.Fatalf("%s prompt = %q, want %q", testCase.name, out.String(), testCase.want)
		}
	}
}

func TestHelpOverviewKeepsScopeRestrictions(t *testing.T) {
	output, diagnostics := runScope(t, scopeStub(), "send {}\nquit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, `command "send" is unavailable in workspace scope; available commands: list, cd, show, start, status, refresh, help, quit`) {
		t.Fatalf("scope restriction lost: %q", diagnostics)
	}
	if strings.Contains(output, "admitted") {
		t.Fatalf("restricted command executed: %q", output)
	}
}

func TestStartupInventoryRunsOncePerSession(t *testing.T) {
	stub := startupStub()
	output, _ := runStartup(t, stub, "quit\n", InteractiveOptions{})
	if got := strings.Count(output, "LAST_SUCCESS"); got != 1 {
		t.Fatalf("startup rendered %d inventories, want 1: %q", got, output)
	}
	if stub.inventoryCalls != 1 {
		t.Fatalf("startup fetched %d inventories, want 1", stub.inventoryCalls)
	}
}

func TestStartupInventoryUsesSharedListPath(t *testing.T) {
	stub := startupStub()
	output, _ := runStartup(t, stub, "quit\n", InteractiveOptions{})
	manual, _ := runScope(t, startupStub(), "list\nquit\n", ColorPolicy{})
	startupTable := segmentBeforePrompt(output, "cluster> ")
	manualTable := segmentBeforePrompt(manual, "cluster> ")
	startupTable = strings.TrimSuffix(startupTable, "list: view sessions | cd <n>: select | start: launch agent | help: commands | q: quit\n")
	if startupTable != manualTable {
		t.Fatalf("startup table %q differs from manual list %q", startupTable, manualTable)
	}
}

func TestHelpListOmitsRemovedTimestampColumns(t *testing.T) {
	text := helpText(t, "list")
	if !strings.Contains(text, "LAST_SUCCESS") {
		t.Fatalf("help list missing LAST_SUCCESS: %q", text)
	}
	if strings.Contains(text, "GENERATION") {
		t.Fatalf("help list still contains GENERATION: %q", text)
	}
	if strings.Contains(text, "LAST_SUCCESS_MS") {
		t.Fatalf("help list still contains LAST_SUCCESS_MS: %q", text)
	}
}

// cancelledStub reports the caller context error from ListEndpoints.
type cancelledStub struct {
	interactiveStub
}

func (s *cancelledStub) ListEndpoints(ctx context.Context) ([]protocol.Endpoint, error) {
	return nil, ctx.Err()
}

func TestStartupInventoryRespectsContextCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	var output, diagnostics strings.Builder
	err := RunInteractive(ctx, &cancelledStub{}, strings.NewReader("quit\n"), &output, &diagnostics, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(diagnostics.String(), "error:") {
		t.Fatalf("cancelled startup inventory was not reported: %q", diagnostics.String())
	}
	if !strings.Contains(output.String(), "cluster> ") {
		t.Fatalf("cancelled startup inventory aborted the repl: %q", output.String())
	}
}

// TestNonInteractiveHelpCatalogMatchesStandaloneDispatch pins command selection and syntax.
func TestNonInteractiveHelpCatalogMatchesStandaloneDispatch(t *testing.T) {
	lines := NonInteractiveCommandHelpLines()
	if len(lines) != len(nonInteractiveHelpOrder) {
		t.Fatalf("got %d lines, want %d", len(lines), len(nonInteractiveHelpOrder))
	}
	joined := strings.Join(lines, "\n")
	for _, want := range []string{
		"agent-cluster-cli [options] [--endpoint <id>] list [--clean]",
		"agent-cluster-cli [options] show <endpoint-or-session>",
		"agent-cluster-cli [options] logs <endpoint> <session>",
		"agent-cluster-cli [options] status <command-id>",
		"agent-cluster-cli [options] send <endpoint> <resource> [payload] [generation]",
		"agent-cluster-cli [options] btw <endpoint> <resource> [payload] [generation]",
		"agent-cluster-cli [options] control <endpoint> <resource> [payload] [generation]",
		"agent-cluster-cli [options] start <endpoint> <resource> [payload] [generation]",
		"agent-cluster-cli [options] resume <endpoint> <resource> [payload] [generation]",
		"agent-cluster-cli [options] stop <endpoint> <resource> <generation>",
		"agent-cluster-cli help [command]",
	} {
		if !strings.Contains(joined, want) {
			t.Fatalf("standalone help missing %q: %q", want, joined)
		}
	}
	for _, line := range lines {
		name := strings.Fields(line)[2]
		for _, forbidden := range []string{"inject", "interrupt", "cd", "refresh", "quit"} {
			if name == forbidden {
				t.Fatalf("standalone help leaked interactive command %q: %q", forbidden, joined)
			}
		}
	}
}

// TestPrintNonInteractiveCommandHelp covers overview, detail, and unknown commands.
func TestPrintNonInteractiveCommandHelp(t *testing.T) {
	var out strings.Builder
	if err := PrintNonInteractiveCommandHelp(&out, ""); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "agent-cluster-cli [options] start") {
		t.Fatalf("overview=%q", out.String())
	}
	for _, command := range nonInteractiveHelpOrder {
		out.Reset()
		if err := PrintNonInteractiveCommandHelp(&out, strings.ToUpper(command)); err != nil {
			t.Fatalf("help %s: %v", command, err)
		}
		if !strings.Contains(out.String(), "Syntax: agent-cluster-cli") {
			t.Fatalf("help %s=%q", command, out.String())
		}
	}
	if err := PrintNonInteractiveCommandHelp(&out, "inject"); err == nil || !strings.Contains(err.Error(), "unknown help command") {
		t.Fatalf("unknown help error=%v", err)
	}
	if !containsCommand(nonInteractiveHelpOrder, "start") || containsCommand(nonInteractiveHelpOrder, "inject") {
		t.Fatal("standalone command membership is inconsistent")
	}
}
