package tui

import (
	"fmt"
	"io"
	"sort"
	"strings"
)

const (
	ListHelpDescription = "list all sessions, including endpoints that failed to report; use --clean to omit failed endpoints; diagnostics still go to stderr"
	// commandPrefixHelp documents the optional command-word prefix once, so the
	// operator learns that "/send" and "send" are the same command.
	commandPrefixHelp = "Command prefix: a leading / on the command word is optional, so /send and send are the same command; it never changes argument text, and cd / still means the workspace root."
)

type commandHelp struct {
	syntax      string
	description string
	parameters  []string
	examples    []string
}

var fieldHelp = []string{
	"NO: display row number from the most recently rendered list; use cd <no> to enter that session.",
	"SESSION_STATUS: provider-reported lifecycle state, such as running, stopped, or failed; the column is shown only when colour is disabled, because an enabled table colours the whole data row by that state.",
	"SESSION_NAME: session display name; empty when the provider did not report one.",
	"SESSION_ID: provider-native session ID; empty when the provider did not report one.",
	"ENDPOINT: endpoint hostname, falling back to its display name or ID.",
	"DATA_STATUS: collection result plus freshness qualifiers; base values are ok, failed, partial, unknown, or unrecognized, optionally followed by /stale, /unknown, or /unknown+stale; a trailing parenthesised local-time stamp such as ok (11:58:36) reports the latest successful collection, not the failure start time, and is omitted when no success has been recorded.",
}

var commandHelpCatalog = map[string]commandHelp{
	"list":      {"list [endpoint] [--clean]", ListHelpDescription + "; JSON output (--json/-json) is available only in the standalone non-interactive command", []string{"endpoint: optional endpoint ID filter", "--clean: omit endpoints that failed to report; diagnostics still go to stderr"}, []string{"list", "list endpoint-1", "list --clean"}},
	"cd":        {"cd [target]", "navigate between workspace, endpoint, and session scopes; bare cd returns to workspace", []string{"target: latest displayed row number, hostname, hostname/endpoint-id, session, hostname/endpoint-id/session, .., or /", "a bare ASCII number is shorthand for cd <number>; leading zeros are accepted and the number is temporary; a valid replacement list that fails during loading, rendering, or diagnostics invalidates the previous row numbers; invalid syntax or an invalid scoped filter preserves them", "failed-endpoint placeholders are displayed but cannot be selected; session scope rejects numeric row navigation", "after a valid replacement begins, a load, render, or diagnostic failure leaves no selectable row bindings; invalid syntax or an invalid scoped filter is rejected before replacement begins and preserves the previous bindings", "a hostname shared by several endpoints prompts for a numbered choice, a hostname/endpoint-id answer, or cancel", "entering session scope immediately renders one bounded output snapshot for the selected session, using the generation the transition validated; a failed read is reported as a diagnostic and does not change the selected session"}, []string{"cd", "cd 1", "cd /", "cd ..", "cd ai-dev", "cd ai-dev/endpoint-1", "cd res_abc", "cd ai-dev/endpoint-1/res_abc"}},
	"show":      {"show [endpoint-or-session]", "show detailed information for an endpoint or session; defaults to the current scope target", []string{"endpoint-or-session: optional endpoint ID, session/resource ID, provider session ID, or a bare list row number", "a bare ASCII number selects the session shown at that row of the most recently rendered list; a numeric token that is not a row number is retried as a provider session ID"}, []string{"show", "show 1", "show endpoint-1"}},
	"start":     {"start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>] [--task <text>]", "start an agent through the selected endpoint; interactive mode executes directly and does not support --json", []string{"endpoint: endpoint ID", "resource: compatibility resource identifier", "--profile: launch profile ID (required)", "--profile-revision: launch profile revision (required)", "--folder: optional working folder; empty value is treated as omitted", "--task: optional literal initial task text; no JSON is required", "--json: rejected in interactive mode"}, []string{"start", "start endpoint-1 ignored-resource --profile topsailai-main --profile-revision topsailai-v1", `start endpoint-1 ignored-resource --profile topsailai-main --profile-revision topsailai-v1 --task "summarize the open issues"`}},
	"resume":    {"resume", "resume the selected session", []string{"--json: rejected in interactive mode"}, []string{"resume"}},
	"stop":      {"stop [session]", "stop a session after confirmation; session scope stops the selected session", []string{"session: optional session/resource ID, provider session ID, or a bare list row number; required outside session scope and rejected inside it", "a bare ASCII number selects the session shown at that row of the most recently rendered list; a numeric token that is not a row number is retried as a provider session ID", "workspace scope resolves the row's own endpoint; a token matching sessions on several endpoints is rejected", "--json: rejected in interactive mode"}, []string{"stop", "stop 1", "stop res_abc"}},
	"inject":    {"inject <text>", "inject context into the selected session", []string{"text: literal context text; no JSON is required", "--json: rejected in interactive mode"}, []string{"inject the deployment notes are in docs/", `inject {"text":"context"}`}},
	"interrupt": {"interrupt [soft|hard] [message]", "request a soft or hard execution interrupt for the selected session", []string{"soft: soft interrupt, optionally followed by a literal message; empty input prompts for the action", "hard: hard interrupt; accepts no message", "--json: rejected in interactive mode"}, []string{"interrupt", "interrupt soft stop and summarize now", "interrupt hard"}},
	"drive":     {"drive [start|stop|status]", "manage the resident driver of the selected session; a driver injects input on the operator's behalf and is not the agent, so drive stop leaves the agent running", []string{"start: start a driver for the selected session; the driver runs autonomously and needs explicit confirmation", "stop: stop only the driver controller; the agent keeps running", "status: report the standard drive state from the persisted inventory; it never probes the provider", "an omitted action reports status", "--json: rejected in interactive mode"}, []string{"drive", "drive status", "drive start", "drive stop"}},
	"logs":      {"logs [-n <lines>] [session]", "show bounded output for a session in the current endpoint", []string{"-n, --lines: maximum number of trailing output lines to show; defaults to 0100", "session: optional session/resource ID, provider session ID, or a bare list row number; defaults to the current session", "a bare ASCII number selects the session shown at that row of the most recently rendered list; a numeric token that is not a row number is retried as a provider session ID"}, []string{"logs", "logs -n 0250", "logs 1", "logs res_abc"}},
	"send":      {"send <text>", "send a message to the selected session", []string{"text: message text, or a JSON object with a text field"}, []string{`send hello world`, `send {"text":"hello"}`}},
	"endpoints": {"endpoints [endpoint-id]", "list every registered endpoint with its connection state, observation time and capability revision; JSON output (--json) is available only in the standalone non-interactive command", []string{"endpoint-id: optional endpoint ID filter; an unknown filter renders an empty table", "read-only: it never forces provider discovery and never changes the list row numbers"}, []string{"endpoints", "endpoints endpoint-1"}},
	"status":    {"status <command-id>", "show the durable result of a command", []string{"command-id: submitted command identifier"}, []string{"status cmd_123"}},
	"refresh":   {"refresh", "force a fresh Endpoint collection and wait for it to be committed, then render the committed inventory", nil, []string{"refresh"}},
	"help":      {"help [command]", "show the command overview or detailed help for one command", []string{"command: optional command name, or scope for the scope model"}, []string{"help", "help list", "help scope"}},
	"quit":      {"quit", "leave interactive mode", nil, []string{"quit"}},
}

var commandHelpOrder = registeredCommandNames()

// registeredCommandNames derives help ordering from the command registration matrix.
func registeredCommandNames() []string {
	names := make([]string, 0, len(commandScopeMatrix))
	for _, rule := range commandScopeMatrix {
		names = append(names, rule.Name)
	}
	return names
}

// scopeHelpOrder is the fixed group order used by the scope-grouped overview.
var scopeHelpOrder = []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession}

// scopeCommandDescriptions holds per-scope wording only. Availability always
// comes from commandScopeMatrix so the two can never disagree.
var scopeCommandDescriptions = map[ScopeKind]map[string]string{
	ScopeWorkspace: {
		"list":      "list sessions across all endpoints",
		"endpoints": "list every registered endpoint with its connection state and freshness",
		"cd":        "navigate to an endpoint or session",
		"show":      "show endpoint or session details",
		"stop":      "stop a session by row number or session ID",
		"status":    "show command result",
		"refresh":   "refresh inventories",
		"help":      "show help",
		"quit":      "exit",
	},
	ScopeEndpoint: {
		"list":    "list sessions in the current endpoint",
		"cd":      "navigate to a session or back to workspace",
		"show":    "show endpoint or session details",
		"logs":    "show session logs",
		"stop":    "stop a session in this endpoint by row number or session ID",
		"status":  "show command result",
		"refresh": "refresh the current endpoint",
		"help":    "show help",
		"quit":    "exit",
	},
	ScopeSession: {
		"list":      "list sessions in the current endpoint; an explicit endpoint must match it",
		"cd":        "bare cd or cd /: workspace; cd ..: endpoint; cd <target>: navigate",
		"show":      "show the current session, or an explicit endpoint/session target",
		"logs":      "show current session output, or another session in this endpoint; -n <lines> bounds the trailing lines",
		"send":      "send a message to the current session after confirmation",
		"resume":    "resume the current session",
		"stop":      "stop the current session",
		"inject":    "inject context into the current session",
		"interrupt": "interrupt the current session",
		"drive":     "manage the current session driver; drive stop leaves the agent running",
		"status":    "explicit ID: command result; omitted: last submitted command, otherwise current session state",
		"refresh":   "reload the current endpoint table and revalidate the current session",
		"help":      "show help",
		"quit":      "exit",
	},
}

// CommandHelpLines returns the interactive command descriptions in registration order.
func CommandHelpLines() []string {
	lines := make([]string, 0, len(commandHelpOrder))
	for _, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		lines = append(lines, entry.syntax+"   "+entry.description)
	}
	return lines
}

var nonInteractiveHelpOrder = []string{"list", "refresh", "endpoints", "show", "logs", "status", "send", "btw", "control", "start", "resume", "stop", "drive", "help"}

// nonInteractiveHelpAliases maps accepted standalone spellings to the advertised
// command. The advertised list keeps one spelling per surface, while an accepted
// alias still resolves to the same detailed help.
var nonInteractiveHelpAliases = map[string]string{"inject": "btw"}

// NonInteractiveCommandHelpLines returns only commands dispatched by the standalone CLI.
func NonInteractiveCommandHelpLines() []string {
	lines := make([]string, 0, len(nonInteractiveHelpOrder))
	for _, name := range nonInteractiveHelpOrder {
		entry := nonInteractiveHelpEntry(name)
		lines = append(lines, entry.syntax+"   "+entry.description)
	}
	return lines
}

// PrintNonInteractiveCommandHelp renders help matching standalone CLI dispatch and flag placement.
func PrintNonInteractiveCommandHelp(out io.Writer, target string) error {
	target = strings.ToLower(strings.TrimSpace(target))
	if target == "" {
		for _, line := range NonInteractiveCommandHelpLines() {
			if _, err := fmt.Fprintln(out, line); err != nil {
				return err
			}
		}
		return nil
	}
	advertised := target
	if alias, ok := nonInteractiveHelpAliases[target]; ok {
		advertised = alias
	}
	if !containsCommand(nonInteractiveHelpOrder, advertised) {
		return fmt.Errorf("unknown help command %q; available commands: %s", target, strings.Join(nonInteractiveHelpOrder, ", "))
	}
	entry := nonInteractiveHelpEntry(advertised)
	if _, err := fmt.Fprintf(out, "%s\n\nSyntax: %s\nDescription: %s\n", advertised, entry.syntax, entry.description); err != nil {
		return err
	}
	if advertised != target {
		_, err := fmt.Fprintf(out, "Alias of: %s (accepted spelling %q)\n", advertised, target)
		return err
	}
	return nil
}

func containsCommand(names []string, target string) bool {
	for _, name := range names {
		if name == target {
			return true
		}
	}
	return false
}

func nonInteractiveHelpEntry(name string) commandHelp {
	canonical := canonicalCommandName(name)
	entry := commandHelpCatalog[canonical]
	switch name {
	case "start", "resume":
		entry.syntax = "agent-cluster-cli [options] " + name + " <endpoint> <resource> [text] [generation]"
	case "stop":
		entry.syntax = "agent-cluster-cli [options] stop <endpoint> <resource> <generation>"
	case "drive":
		entry.syntax = "agent-cluster-cli [options] drive <start|stop|status> <endpoint> <session> [generation]"
	case "logs":
		entry.syntax = "agent-cluster-cli [options] [--lines <lines>] logs <endpoint> <session>"
	case "show":
		entry.syntax = "agent-cluster-cli [options] show <endpoint-or-session>"
	case "status":
		entry.syntax = "agent-cluster-cli [options] status <command-id>"
	case "list":
		entry.syntax = "agent-cluster-cli [options] [--endpoint <id>] list [--clean]"
	case "refresh":
		entry.syntax = "agent-cluster-cli [options] [--endpoint <id>] refresh"
	case "endpoints":
		entry.syntax = "agent-cluster-cli [options] [--endpoint <id>] endpoints [endpoint-id]"
	case "send", "btw", "control":
		entry.syntax = "agent-cluster-cli [options] " + name + " <endpoint> <resource> [text] [generation]"
	case "help":
		entry.syntax = "agent-cluster-cli help [command]"
	}
	return entry
}

// scopeCommandLines derives one scope group from the availability matrix.
func scopeCommandLines(kind ScopeKind) []string {
	names := availableCommands(kind)
	lines := make([]string, 0, len(names))
	for _, name := range names {
		entry := scopedHelpEntry(name, kind)
		description := scopeCommandDescriptions[kind][name]
		if description == "" {
			description = entry.description
		}
		lines = append(lines, entry.syntax+"   "+description)
	}
	return lines
}

// commandScopes lists the scopes that may run one command, in stable order.
func commandScopes(name string) []string {
	scopes := make([]string, 0, len(scopeHelpOrder))
	for _, kind := range scopeHelpOrder {
		if commandAllowed(name, kind) {
			scopes = append(scopes, kind.String())
		}
	}
	return scopes
}

// helpTarget normalizes one help argument: case, surrounding space, and the
// optional command prefix. The prefix is a form, so "help /send" must resolve
// exactly like "help send".
func helpTarget(target string) string {
	return canonicalCommandName(trimCommandPrefix(strings.ToLower(strings.TrimSpace(target))))
}

// PrintCommandHelp renders overview or detailed help without ANSI styling.
func PrintCommandHelp(out io.Writer, target string) error {
	target = helpTarget(target)
	if target == "" {
		return printScopeHelpOverview(out)
	}
	if target == "scope" || target == "scopes" {
		return printScopeModelHelp(out)
	}
	entry, ok := commandHelpCatalog[target]
	if !ok {
		return fmt.Errorf("unknown help command %q; available commands: %s", target, strings.Join(commandHelpOrder, ", "))
	}
	return printCommandDetail(out, target, entry)
}

// PrintScopedCommandHelp renders context help or complete canonical help.
func PrintScopedCommandHelp(out io.Writer, target string, kind ScopeKind) error {
	target = helpTarget(target)
	if target == "" {
		return printContextHelp(out, kind)
	}
	if target == "all" {
		return printAllCommandHelp(out)
	}
	if target == "scope" || target == "scopes" {
		return printScopeModelHelp(out)
	}
	entry, ok := commandHelpCatalog[target]
	if !ok {
		return fmt.Errorf("unknown help command %q; next: run help all", target)
	}
	entry = interactiveHelpEntry(target, kind)
	if target == "start" {
		return printInteractiveStartHelp(out, entry)
	}
	if err := printCommandDetail(out, target, entry); err != nil {
		return err
	}
	if target == "list" {
		_, err := fmt.Fprintln(out, "Row selection: invalid syntax or an invalid scoped filter preserves row bindings; a valid replacement that fails during loading, rendering, or diagnostics invalidates them. Run list or refresh before selecting a new row number.")
		return err
	}
	return nil
}

// printInteractiveStartHelp adds wizard guidance only to scoped interactive help.
func printInteractiveStartHelp(out io.Writer, entry commandHelp) error {
	if err := printCommandDetail(out, "start", entry); err != nil {
		return err
	}
	_, err := fmt.Fprintln(out, "Project launch: start [endpoint] selects a live adapter and project (or manual folder), then asks for the initial task. Without an endpoint argument it prints a numbered endpoint list and accepts a bare number, so no endpoint identifier has to be typed. Empty/cancel cancels. Legacy explicit --profile syntax and clients without launch queries use the endpoint/resource/profile/revision prompts; q quits, r refreshes, and help repeats guidance.")
	return err
}

// printCommandDetail renders one canonical command without changing non-interactive help.
func printCommandDetail(out io.Writer, target string, entry commandHelp) error {
	if _, err := fmt.Fprintf(out, "%s\n\nSyntax: %s\nAvailable in: %s\nDescription: %s\n", target, entry.syntax, strings.Join(commandScopes(target), ", "), entry.description); err != nil {
		return err
	}
	if len(entry.parameters) > 0 {
		if _, err := fmt.Fprintln(out, "Parameters:"); err != nil {
			return err
		}
		for _, parameter := range entry.parameters {
			if _, err := fmt.Fprintf(out, "  %s\n", parameter); err != nil {
				return err
			}
		}
	}
	if len(entry.examples) > 0 {
		if _, err := fmt.Fprintln(out, "Examples:"); err != nil {
			return err
		}
		for _, example := range entry.examples {
			if _, err := fmt.Fprintf(out, "  %s\n", example); err != nil {
				return err
			}
		}
	}
	if target == "list" {
		if _, err := fmt.Fprintln(out, "Fields:"); err != nil {
			return err
		}
		for _, field := range fieldHelp {
			if _, err := fmt.Fprintf(out, "  %s\n", field); err != nil {
				return err
			}
		}
	}
	return nil
}

// printContextHelp renders only canonical commands executable in the current scope.
func printContextHelp(out io.Writer, kind ScopeKind) error {
	if _, err := fmt.Fprintf(out, "Current scope: %s\n\nCommands:\n", kind); err != nil {
		return err
	}
	for _, name := range availableCommands(kind) {
		entry := interactiveHelpEntry(name, kind)
		description := scopeCommandDescriptions[kind][name]
		if description == "" {
			description = entry.description
		}
		if _, err := fmt.Fprintf(out, "  %s   %s\n", entry.syntax, description); err != nil {
			return err
		}
	}
	workflow := "Next: list -> <number> or cd <number> -> show/logs. Run help list for row selection rules."
	if kind == ScopeSession {
		workflow = "Bare cd or cd / returns to workspace; cd .. returns to endpoint. Numeric row navigation is unavailable in session scope.\n" +
			"Entering a session renders one bounded output snapshot immediately; run logs again to re-read it.\n" +
			"Session selectors use internal resource IDs or unique names, not necessarily the provider SESSION_ID shown in list.\n" +
			"Actions require adapter capability support and fresh session data; scope availability alone does not guarantee support."
	}
	example := "Start example: start <endpoint> <resource> --profile <id> --profile-revision <revision>"
	if kind == ScopeSession {
		example = "Session example: show or logs; use cd .. before starting another agent."
	}
	for _, line := range []string{"", workflow, example, commandPrefixHelp, "Run help all for every command and scope."} {
		if _, err := fmt.Fprintln(out, line); err != nil {
			return err
		}
	}
	return nil
}

// printAllCommandHelp renders all canonical commands and their scope restrictions.
func printAllCommandHelp(out io.Writer) error {
	if _, err := fmt.Fprintln(out, "All commands:"); err != nil {
		return err
	}
	if _, err := fmt.Fprintln(out, "Bare ASCII numbers are shorthand for cd <number> in workspace and endpoint scopes; session scope does not support numeric row navigation."); err != nil {
		return err
	}
	if _, err := fmt.Fprintln(out, commandPrefixHelp); err != nil {
		return err
	}
	for _, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		if _, err := fmt.Fprintf(out, "  %s   scopes: %s   %s\n", entry.syntax, strings.Join(commandScopes(name), ", "), entry.description); err != nil {
			return err
		}
	}
	if _, err := fmt.Fprintln(out, "\nAliases: "+commandAliasHelp()); err != nil {
		return err
	}
	return nil
}

// commandAliasHelp renders accepted aliases from the canonical alias registry.
func commandAliasHelp() string {
	aliases := make([]string, 0, len(commandAliases))
	for alias, canonical := range commandAliases {
		aliases = append(aliases, alias+"="+canonical)
	}
	sort.Strings(aliases)
	return strings.Join(aliases, ", ")
}

// printScopeHelpOverview renders one command group per scope.
func printScopeHelpOverview(out io.Writer) error {
	if _, err := fmt.Fprintln(out, "Commands by scope:"); err != nil {
		return err
	}
	for _, kind := range scopeHelpOrder {
		if _, err := fmt.Fprintf(out, "\n%s:\n", kind); err != nil {
			return err
		}
		for _, line := range scopeCommandLines(kind) {
			if _, err := fmt.Fprintf(out, "  %s\n", line); err != nil {
				return err
			}
		}
	}
	return nil
}

// printScopeModelHelp documents the scope model and every navigation form.
func printScopeModelHelp(out io.Writer) error {
	lines := []string{
		"Scope model:",
		"",
		"  workspace  the root scope; shows all endpoints and sessions",
		"  endpoint   entered with cd <hostname> or cd <hostname>/<endpoint-id>",
		"  session    entered with cd <session> or cd <hostname>/<endpoint-id>/<session>; entering renders one bounded output snapshot",
		"",
		"Navigation:",
		"  cd                    return to workspace scope",
		"  cd /                  return to workspace scope",
		"  cd ..                 go up one scope",
		"  cd <hostname>         enter an endpoint (prompts when the hostname is ambiguous)",
		"  cd <hostname>/<id>    enter a specific endpoint",
		"  cd <session>          enter a session inside the current endpoint",
		"  cd <hostname>/<id>/<session>  enter a session directly",
		"",
		"Commands differ by scope; run help to see the commands available in each scope.",
	}
	for _, line := range lines {
		if _, err := fmt.Fprintln(out, line); err != nil {
			return err
		}
	}
	return nil
}

// HelpCommandNames returns command names in stable display order.
func HelpCommandNames() []string {
	result := append([]string(nil), commandHelpOrder...)
	sort.Strings(result)
	return result
}

// scopedHelpEntry describes session status without changing standalone command help.
func scopedHelpEntry(name string, kind ScopeKind) commandHelp {
	entry := commandHelpCatalog[name]
	if name == "status" && kind == ScopeSession {
		entry.syntax = "status [command-id]"
		entry.description = "show an explicit command result; without an ID, use the last command submitted in this CLI, otherwise show current session state"
		entry.parameters = []string{"command-id: optional submitted command identifier", "without an ID: last submitted command takes precedence over current session state"}
		entry.examples = []string{"status", "status cmd_123"}
	}
	return entry
}

// interactiveHelpEntry extends scopedHelpEntry for the interactive REPL only.
// The REPL remembers the last command it submitted, so no interactive scope
// requires a command ID; the standalone CLI has no such memory and keeps the
// mandatory form.
func interactiveHelpEntry(name string, kind ScopeKind) commandHelp {
	entry := scopedHelpEntry(name, kind)
	if name != "status" || kind == ScopeSession {
		return entry
	}
	entry.syntax = "status [command-id]"
	entry.description = "show the durable result of a command; without an ID it reports the last command submitted in this CLI"
	entry.parameters = []string{"command-id: optional submitted command identifier; omit it to reuse the last command submitted in this CLI"}
	entry.examples = []string{"status", "status cmd_123"}
	return entry
}
