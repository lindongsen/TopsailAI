package tui

import (
	"context"
	"errors"
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

// scopeGroup returns the command lines of one scope group in the overview. The
// leading indent is preserved, so a hung description line stays distinguishable
// from a command line.
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
		lines = append(lines, strings.TrimRight(line, " "))
	}
	return lines
}

// groupCommandNames extracts the leading command name of each group line. A
// command line starts at the block indent; a hung description line is indented to
// the description column, so it is skipped instead of being read as a command.
func groupCommandNames(lines []string) []string {
	names := make([]string, 0, len(lines))
	for _, line := range lines {
		if !strings.HasPrefix(line, helpLineIndent) {
			continue
		}
		rest := strings.TrimPrefix(line, helpLineIndent)
		if rest == "" || strings.HasPrefix(rest, " ") {
			continue
		}
		fields := strings.Fields(rest)
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
		"session    entered with cd <session> or cd <hostname>/<endpoint-id>/<session>; entering renders one bounded output snapshot",
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

// TestCommandHelpLinesStayNonInteractiveCompatible verifies that every command
// line keeps its syntax and description and that all descriptions in the block
// start at one column, so the interactive list stays readable and never leaks
// scope grouping.
func TestCommandHelpLinesStayNonInteractiveCompatible(t *testing.T) {
	lines := CommandHelpLines()
	if len(lines) != len(commandHelpOrder) {
		t.Fatalf("CommandHelpLines returned %d lines, want %d", len(lines), len(commandHelpOrder))
	}
	column := -1
	for index, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		line := lines[index]
		if !strings.HasPrefix(line, helpLineIndent+entry.syntax) {
			t.Fatalf("line %d = %q, want syntax prefix %q", index, line, helpLineIndent+entry.syntax)
		}
		descriptionLine := line
		if strings.Contains(line, "\n") {
			parts := strings.SplitN(line, "\n", 2)
			descriptionLine = parts[1]
		}
		start := strings.Index(descriptionLine, entry.description)
		if start < 0 {
			t.Fatalf("line %d = %q, want description %q", index, line, entry.description)
		}
		if column < 0 {
			column = start
			continue
		}
		if start != column {
			t.Fatalf("line %d description starts at column %d, want %d: %q", index, start, column, line)
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
		{"workspace", ScopeState{Kind: ScopeWorkspace}, ansiBoldGreen + "workspace>" + ansiReset + " "},
		{"endpoint", ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1", Hostname: "ai-dev"}, ansiBoldGreen + "endpoint[ai-dev/endpoint-1]>" + ansiReset + " "},
		{"session", ScopeState{Kind: ScopeSession, EndpointID: "endpoint-1", Hostname: "ai-dev", ProviderSessionID: "20261027152208", SessionID: "res-1"}, ansiBoldGreen + "session[ai-dev/20261027152208]>" + ansiReset + " "},
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
	if !strings.Contains(diagnostics, `command "send" is unavailable in workspace scope; available commands: list, endpoints, cd, show, info, start, stop, status, refresh, watch, help, quit`) {
		t.Fatalf("scope restriction lost: %q", diagnostics)
	}
	if strings.Contains(output, "admitted") {
		t.Fatalf("restricted command executed: %q", output)
	}
}

func TestStartupInventoryRunsOncePerSession(t *testing.T) {
	stub := startupStub()
	output, _ := runStartup(t, stub, "quit\n", InteractiveOptions{})
	if got := strings.Count(output, "DATA_STATUS"); got != 1 {
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
	startupTable := segmentBeforePrompt(output, "workspace> ")
	manualTable := segmentBeforePrompt(manual, "workspace> ")
	startupTable = strings.TrimSuffix(startupTable, "list: view sessions | <n> or cd <n>: select | start: launch agent | help: commands | q: quit\n")
	if startupTable != manualTable {
		t.Fatalf("startup table %q differs from manual list %q", startupTable, manualTable)
	}
}

func TestHelpListOmitsRemovedTimestampColumns(t *testing.T) {
	text := helpText(t, "list")
	if !strings.Contains(text, "DATA_STATUS") {
		t.Fatalf("help list missing DATA_STATUS: %q", text)
	}
	if strings.Contains(text, "LAST_SUCCESS") {
		t.Fatalf("help list still contains LAST_SUCCESS: %q", text)
	}
	if strings.Contains(text, "GENERATION") {
		t.Fatalf("help list still contains GENERATION: %q", text)
	}
	if strings.Contains(text, "LAST_SUCCESS_MS") {
		t.Fatalf("help list still contains LAST_SUCCESS_MS: %q", text)
	}
}

// cancelledStub counts inventory calls so pre-cancelled parents can prove no API access.
type cancelledStub struct {
	interactiveStub
	inventoryCalls int
}

func (s *cancelledStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	s.inventoryCalls++
	return nil, errors.New("inventory must not be called")
}

func TestPreCancelledParentStopsBeforeStartupInventory(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	stub := &cancelledStub{}
	var output, diagnostics strings.Builder
	err := RunInteractive(ctx, stub, strings.NewReader("quit\n"), &output, &diagnostics, InteractiveOptions{})
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("RunInteractive error=%v, want context.Canceled", err)
	}
	if stub.inventoryCalls != 0 {
		t.Fatalf("pre-cancelled parent made %d inventory calls", stub.inventoryCalls)
	}
	if output.Len() != 0 || diagnostics.Len() != 0 {
		t.Fatalf("pre-cancelled parent wrote output=%q diagnostics=%q", output.String(), diagnostics.String())
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
		"agent-cluster-cli [options] [--endpoint <id>] refresh",
		"agent-cluster-cli [options] show <endpoint-or-session>",
		"agent-cluster-cli [options] [--lines <lines>] logs <endpoint> <session>",
		"agent-cluster-cli [options] status <command-id>",
		"agent-cluster-cli [options] send <endpoint> <resource> [text] [generation]",
		"agent-cluster-cli [options] btw <endpoint> <resource> [text] [generation]",
		"agent-cluster-cli [options] control <endpoint> <resource> [text] [generation]",
		"agent-cluster-cli [options] start <endpoint> <resource> [text] [generation]",
		"agent-cluster-cli [options] resume <endpoint> <resource> [text] [generation]",
		"agent-cluster-cli [options] stop <endpoint> <resource> <generation>",
		"agent-cluster-cli help [command]",
	} {
		if !strings.Contains(joined, want) {
			t.Fatalf("standalone help missing %q: %q", want, joined)
		}
	}
	for _, line := range lines {
		name := strings.Fields(line)[2]
		for _, forbidden := range []string{"inject", "interrupt", "cd", "quit"} {
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
	out.Reset()
	if err := PrintNonInteractiveCommandHelp(&out, "inject"); err != nil {
		t.Fatalf("accepted alias help failed: %v", err)
	}
	if !strings.Contains(out.String(), "Syntax: agent-cluster-cli [options] btw <endpoint> <resource> [text] [generation]") || !strings.Contains(out.String(), `Alias of: btw`) {
		t.Fatalf("alias help=%q", out.String())
	}
	if err := PrintNonInteractiveCommandHelp(&out, "interrupt"); err == nil || !strings.Contains(err.Error(), "unknown help command") {
		t.Fatalf("unknown help error=%v", err)
	}
	if !containsCommand(nonInteractiveHelpOrder, "start") || containsCommand(nonInteractiveHelpOrder, "inject") {
		t.Fatal("standalone command membership is inconsistent")
	}
}

// TestContextHelpExampleMatchesScope keeps examples executable in the current scope.
func TestContextHelpExampleMatchesScope(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession} {
		t.Run(kind.String(), func(t *testing.T) {
			var out strings.Builder
			if err := PrintScopedCommandHelp(&out, "", kind); err != nil {
				t.Fatal(err)
			}
			start := strings.Contains(out.String(), "Start example:")
			session := strings.Contains(out.String(), "Session example: show or logs;")
			if start != (kind != ScopeSession) || session != (kind == ScopeSession) {
				t.Fatalf("scope=%s startExample=%t sessionExample=%t output=%q", kind, start, session, out.String())
			}
		})
	}
}

// exampleFailureWriter fails only on the contextual example, after the command list.
type exampleFailureWriter struct{ err error }

// Write preserves the injected error identity at the changed footer boundary.
func (w exampleFailureWriter) Write(data []byte) (int, error) {
	if strings.Contains(string(data), "example:") {
		return 0, w.err
	}
	return len(data), nil
}

// TestContextHelpExampleWriteFailure propagates a failed footer in every scope.
func TestContextHelpExampleWriteFailure(t *testing.T) {
	sentinel := errors.New("context help example write failed")
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession} {
		if err := PrintScopedCommandHelp(exampleFailureWriter{err: sentinel}, "", kind); err != sentinel {
			t.Fatalf("scope=%s error=%v, want original sentinel", kind, err)
		}
	}
}

// TestContextHelpDefersRowBindingDetails keeps the first-use overview concise.
func TestContextHelpDefersRowBindingDetails(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession} {
		var out strings.Builder
		if err := PrintScopedCommandHelp(&out, "", kind); err != nil {
			t.Fatal(err)
		}
		if strings.Contains(out.String(), "invalid scoped filter") || strings.Contains(out.String(), "diagnostics invalidates") {
			t.Fatalf("verbose overview: %q", out.String())
		}
		if kind != ScopeSession && !strings.Contains(out.String(), "Run help list for row selection rules.") {
			t.Fatalf("missing detail pointer: %q", out.String())
		}
	}
	var detail strings.Builder
	if err := PrintScopedCommandHelp(&detail, "list", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	for _, rule := range []string{"invalid scoped filter preserves row bindings", "loading, rendering, or diagnostics invalidates them", "Run list or refresh"} {
		if !strings.Contains(detail.String(), rule) {
			t.Fatalf("missing %q: %q", rule, detail.String())
		}
	}
}

// rowRuleFailureWriter isolates the interactive-only list footer boundary.
type rowRuleFailureWriter struct{}

// Write preserves the original failure after all canonical details succeeded.
func (rowRuleFailureWriter) Write(data []byte) (int, error) {
	if strings.HasPrefix(string(data), "Row selection:") {
		return 0, errTableFixture
	}
	return len(data), nil
}

// TestInteractiveRowRuleWriteFailure preserves footer error identity.
func TestInteractiveRowRuleWriteFailure(t *testing.T) {
	if err := PrintScopedCommandHelp(rowRuleFailureWriter{}, "list", ScopeWorkspace); err != errTableFixture {
		t.Fatalf("error=%v", err)
	}
}
