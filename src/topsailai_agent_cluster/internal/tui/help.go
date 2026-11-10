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
	"SESSION_ID: provider-native session ID; empty when the provider did not report one. The interactive table hides this column because the value is long and opaque, so select a session by its row number or name; the standalone list command still prints it, and logs, stop, drive and the standalone show command still accept it as a selector.",
	"DRIVER: controller state reported by the provider: running, unverified, stale, exited, failed, none, or unknown; a dash means the provider reported no driver observation, which is not proof that no controller exists. A controller injects input on the operator's behalf; it is not the agent, so stopping it leaves the agent running. The column is a read projection of the persisted inventory and never probes the provider. When colour is enabled, a verified running controller is shown in bold green in this cell only, so it stands out without recolouring the row: the row colour still reports the session state, and only a verified running controller is emphasised, so unverified, stale, exited, failed, none and unknown stay distinguishable.",
	"PROJECT_WORKSPACE: workspace the session is working on, as reported by the provider; empty when the provider did not report one. It is descriptive report data only and never selects a route, capability, or permission.",
	"ENDPOINT: endpoint hostname, falling back to its display name or ID.",
	"DATA_STATUS: collection result plus freshness qualifiers; base values are ok, failed, partial, unknown, or unrecognized, optionally followed by /stale, /unknown, or /unknown+stale; a trailing parenthesised local-time stamp such as ok (11:58:36) reports the latest successful collection, not the failure start time, and is omitted when no success has been recorded.",
}

var commandHelpCatalog = map[string]commandHelp{
	"list":      {"list [endpoint] [--clean] [--full]", ListHelpDescription + "; JSON output (--json/-json) is available only in the standalone non-interactive command", []string{"endpoint: optional endpoint ID filter", "--clean: omit endpoints that failed to report; diagnostics still go to stderr", "--full: disable truncation; a narrow terminal wraps long cells instead of clipping them", "lf: shorthand for list --full"}, []string{"list", "list endpoint-1", "list --clean", "list --full", "lf"}},
	"cd":        {"cd [target]", "navigate between workspace, endpoint, and session scopes; bare cd returns to workspace", []string{"target: latest displayed row number, hostname, hostname/endpoint-id, session, hostname/endpoint-id/session, .., or /", "a bare ASCII number is shorthand for cd <number> in workspace and endpoint scope; leading zeros are accepted and the number is temporary; a valid replacement list that fails during loading, rendering, or diagnostics invalidates the previous row numbers; invalid syntax or an invalid scoped filter preserves them", "failed-endpoint placeholders are displayed but cannot be selected; session scope rejects the explicit cd <number> form, and a bare number typed there is message text offered as a send", "after a valid replacement begins, a load, render, or diagnostic failure leaves no selectable row bindings; invalid syntax or an invalid scoped filter is rejected before replacement begins and preserves the previous bindings", "a hostname shared by several endpoints prompts for a numbered choice, a hostname/endpoint-id answer, or cancel", "entering session scope immediately renders one bounded output snapshot for the selected session, using the generation the transition validated; a failed read is reported as a diagnostic and does not change the selected session"}, []string{"cd", "cd 1", "cd /", "cd ..", "cd ai-dev", "cd ai-dev/endpoint-1", "cd res_abc", "cd ai-dev/endpoint-1/res_abc"}},
	"show":      {"show [endpoint-or-session]", "show detailed information for an endpoint or session; defaults to the current scope target", []string{"endpoint-or-session: optional endpoint ID, session/resource ID, provider session ID, or a bare list row number", "a bare ASCII number selects the session shown at that row of the most recently rendered list; a numeric token that is not a row number is retried as a provider session ID"}, []string{"show", "show 1", "show endpoint-1"}},
	"info":      {"info [session]", "show session detail for one session, including its provider session PID, driver state and controller PID; defaults to the current session", []string{"session: optional session/resource ID, provider session ID, or a bare list row number; required in workspace scope and rejected when it names an endpoint", "a bare ASCII number selects the session shown at that row of the most recently rendered list; a numeric token that is not a row number is retried as a provider session ID", "read-only: it never changes the selected session, the list row numbers, or any provider state", "provider_pid is the process identity the provider reported for the session; it is display evidence only, so it is never a routing identity, never a generation and never a signal authority, and a provider that reported no PID leaves provider_pid empty instead of printing 0", "the drive fields are the same fields drive status prints, so the two surfaces cannot disagree; an absent observation is reported as drive_state: not_reported, which is not proof that no controller exists", "--json: rejected in interactive mode"}, []string{"info", "info 1", "info res_abc"}},
	"start":     {"start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>] [--task <text>]", "start an agent through the selected endpoint; interactive mode executes directly and does not support --json", []string{"endpoint: endpoint ID", "resource: compatibility resource identifier", "--profile: launch profile ID (required)", "--profile-revision: launch profile revision (required)", "--folder: optional working folder; empty value is treated as omitted", "--task: optional literal initial task text; no JSON is required", "without --task and without a positional task: read a multi-line task and finish it with a standalone EOF line or Ctrl+D; the terminator is never part of the task, and the accepted task is echoed verbatim with colour so it can be verified before submission", "an empty multi-line task is rejected instead of submitting nothing", "after a completed start: force one collection for the selected endpoint, then start the same live tail as logs -f for the session that appeared, so the new session is watched without typing logf; the tail is armed after the collection because the launched session generation is minted by it, and any key stops it", "no tail is armed when no session appeared yet, when more than one appeared, when the generation is unverified, or when the client cannot stream; the reason is reported as a diagnostic, and a client that cannot stop a tail renders one bounded snapshot instead", "--json: rejected in interactive mode"}, []string{"start", "start endpoint-1 ignored-resource --profile topsailai-main --profile-revision topsailai-v1", `start endpoint-1 ignored-resource --profile topsailai-main --profile-revision topsailai-v1 --task "summarize the open issues"`}},
	"resume":    {"resume [row]", "resume a stopped session selected from the history table; the endpoint must prove from a complete fresh inventory that the session has no live generation", []string{"row: bare history row number from the most recently rendered history table; required, because resume authorizes on a proven absence rather than on a live generation", "a live row is rejected instead of resumed; run history again to refresh the row numbers", "a read-only row, or a row the adapter reports as non-resumable, is rejected with the adapter's reason", "--json: rejected in interactive mode"}, []string{"resume 3"}},
	"stop":      {"stop [session]", "stop a session after confirmation; session scope stops the selected session", []string{"session: optional session/resource ID, provider session ID, or a bare list row number; required outside session scope and rejected inside it", "a bare ASCII number selects the session shown at that row of the most recently rendered list; a numeric token that is not a row number is retried as a provider session ID", "workspace scope resolves the row's own endpoint; a token matching sessions on several endpoints is rejected", "--json: rejected in interactive mode"}, []string{"stop", "stop 1", "stop res_abc"}},
	"btw":       {"btw [text]", "inject context into the selected session; a bare btw reads a multi-line context block", []string{"text: literal context text; no JSON is required", "without text: read a multi-line context block and finish it with a standalone EOF line or Ctrl+D; the terminator is never part of the context", "an empty multi-line context block is rejected instead of submitting nothing", "--json: rejected in interactive mode"}, []string{"btw the deployment notes are in docs/", `btw {"text":"context"}`}},
	"interrupt": {"interrupt [soft|hard] [message]", "request a soft or hard execution interrupt for the selected session", []string{"soft: soft interrupt, optionally followed by a literal message", "hard: hard interrupt; accepts no message; this is the default when no action word is given", "--json: rejected in interactive mode"}, []string{"interrupt", "interrupt soft stop and summarize now", "interrupt hard"}},
	"ctl":       {"ctl [action] [key=value ...] | ctl.<action> [key=value ...]", "send one provider control action to the selected session; the action list is rendered from the capabilities the endpoint advertises, so an unsupported action is never offered", []string{"action: advertised control action name, or its number in the rendered list; empty prompts for the action", "ctl.<action>: dotted spelling that names the action in the command word, so the action prompt is skipped", "key=value: optional parameters separated by spaces; empty sends no parameters, and a bare word without = is rejected", "a value is read as a JSON scalar when it is one, so 300 is a number and true is a boolean; wrap it in double quotes to send the literal text", "when no parameter is supplied the prompt asks for them, so no JSON document is ever typed in interactive mode", "the action is a mutating request and needs explicit confirmation", "--json: rejected in interactive mode"}, []string{"ctl", "ctl heartbeat", "ctl.heartbeat", "ctl pause reason=maintenance", `ctl.pause reason=maintenance timeout_seconds=300`}},
	"drive":     {"drive [start|stop|status] [session]", "manage the resident driver of one session; a driver injects input on the operator's behalf and is not the agent, so drive stop leaves the agent running", []string{"start: start a driver for the target session; the driver runs autonomously and needs explicit confirmation", "stop: stop only the driver controller; the agent keeps running", "status: report the standard drive state from the persisted inventory; it never probes the provider", "an omitted action reports status, so a bare drive never mutates anything", "session: optional session/resource ID, provider session ID, or a bare list row number; required outside session scope and rejected inside it", "a bare ASCII number selects the session shown at that row of the most recently rendered list; a numeric token that is not a row number is retried as a provider session ID", "workspace scope resolves the row's own endpoint; a token matching sessions on several endpoints is rejected", "--json: rejected in interactive mode"}, []string{"drive", "drive 1", "drive res_abc", "drive status 1", "drive start 1", "drive stop res_abc"}},
	"logs":      {"logs [-n <lines>] [-f|--follow] [session]", "show bounded output for a session in the current endpoint, or stream it until a key is pressed", []string{"-n, --lines: maximum number of trailing output lines to show; defaults to the REPL budget, which is 0300 unless the startup --lines option set 0100-1000", "-f, --follow: stream new output records until any key is pressed; the stream is bound to the session generation resolved now, so a replaced session is never followed", "session: optional session/resource ID, provider session ID, or a bare list row number; defaults to the current session", "a bare ASCII number selects the session shown at that row of the most recently rendered list; a numeric token that is not a row number is retried as a provider session ID", "logf: shorthand for logs -f, so follow is implied and needs no flag; every other argument is accepted unchanged, and a repeated follow flag is still rejected"}, []string{"logs", "logs -n 0250", "logs 1", "logs res_abc", "logs -f", "logs --follow 1", "logf", "logf -n 0250"}},
	"history":   {"history [endpoint]", "read bounded provider session history for one endpoint and render it as a numbered table; the result is a live provider read, never a persisted projection", []string{"endpoint: optional endpoint ID or hostname; defaults to the current endpoint, and workspace scope requires it", "a hostname shared by several endpoints is rejected with the candidate list", "history row numbers are a separate namespace from list row numbers, and a history render replaces the list row numbers", "a row that the inventory join could not resolve to a live resource and generation cannot be entered with cd; it is reported instead of fabricating a generation", "--json: rejected in interactive mode"}, []string{"history", "history endpoint-1", "history ai-dev"}},
	"messages":  {"messages [session]", "read one session's conversation; messages are persisted provider data, so a stopped session can still be read", []string{"session: optional provider session ID or a bare history row number; defaults to the current session, and workspace scope requires it", "a bare ASCII number selects the row shown at that row of the most recently rendered history table; a numeric token that is not a row number is retried as a provider session ID", "workspace scope resolves the row's own endpoint; a token matching sessions on several endpoints is rejected", "unlike cd and resume, this command reads both live and stopped sessions, because it addresses persisted provider data rather than a live process", "read-only: it never changes the selected session, the list row numbers, or the history row numbers, so several rows can be read in sequence", "a bounded window is always labelled; a shortened conversation is never presented as complete", "--json: rejected in interactive mode"}, []string{"messages", "messages 3", "messages 20261013131753"}},
	"send":      {"send [text]", "send a message to the selected session; an explicit text submits directly, and only a bare send reads a multi-line message and asks for confirmation", []string{"text: message text, or a JSON object with a text field; an explicit text is submitted without a confirmation question, because the command word and the payload are already stated", "without text: read a multi-line message and finish it with a standalone EOF line or Ctrl+D; the terminator is never part of the message", "a bare send asks Confirm send? before submitting, because the assembled block was never shown as a whole; an empty multi-line message is rejected instead of submitting nothing", "after a completed send: start the same live tail as logs -f, then force one collection for the selected endpoint and revalidate only the selected session, so a later list reads a newer document; the tail opens on the next prompt and any key stops it, and both steps are reported as diagnostics and never turn the accepted send into a failure", "when the client cannot stream or the input mode cannot observe a keypress, the tail degrades to one bounded output snapshot and says so, because a live tail that cannot be stopped is worse than a snapshot"}, []string{`send hello world`, `send {"text":"hello"}`}},
	"endpoints": {"endpoints [endpoint-id]", "list every registered endpoint with its connection state, observation time and capability revision; JSON output (--json) is available only in the standalone non-interactive command", []string{"endpoint-id: optional endpoint ID filter; an unknown filter renders an empty table", "read-only: it never forces provider discovery and never changes the list row numbers"}, []string{"endpoints", "endpoints endpoint-1"}},
	"status":    {"status <command-id>", "show the durable result of a command", []string{"command-id: submitted command identifier"}, []string{"status cmd_123"}},
	"refresh":   {"refresh", "force a fresh Endpoint collection and wait for it to be committed, then render the committed inventory", nil, []string{"refresh"}},
	"watch":     {"watch [interval] [--force]", "re-render the list on a timer until any key is pressed; it collects once immediately on start, the default re-reads the persisted inventory every 5s, and --force performs a forced collection with a 10s floor", []string{"interval: optional positive duration, such as 5s or 500ms; the projection mode requires at least 1s", "--force: perform a forced Endpoint collection on every tick instead of re-reading the persisted inventory; requires at least 10s because each tick launches one provider discovery per endpoint", "the first table is printed immediately, before the first tick, so the current inventory appears at once", "the table layout is re-read on every render, so resizing the terminal during the loop is honoured on the next tick", "any keypress stops the loop before the key is applied", "a refresh that changes the row set prints one rebinding diagnostic, so a row number never changes silently", "unavailable in session scope, because a forced refresh can invalidate the pinned session", "--json: rejected in interactive mode"}, []string{"watch", "watch 2s", "watch --force", "watch 10s --force"}},
	"help":      {"help [command]", "show the command overview or detailed help for one command", []string{"command: optional command name, or scope for the scope model"}, []string{"help", "help list", "help scope"}},
	"quit":      {"quit", "leave interactive mode; outside workspace scope it returns to workspace scope instead", nil, []string{"quit", "q"}},
	"exit":      {"exit", "leave interactive mode from every scope", nil, []string{"exit"}},
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
		"info":      "show session detail by row number or session ID",
		"history":   "read provider session history for one endpoint and number its rows",
		"messages":  "read one session's conversation by history row number or session ID",
		"resume":    "resume a stopped session by history row number",
		"stop":      "stop a session by row number or session ID",
		"drive":     "manage a session driver by row number or session ID; drive stop leaves the agent running",
		"status":    "show command result",
		"refresh":   "refresh inventories",
		"watch":     "re-render the list on a timer until any key is pressed",
		"help":      "show help",
		"quit":      "leave interactive mode",
	},
	ScopeEndpoint: {
		"list":     "list sessions in the current endpoint",
		"cd":       "navigate to a session or back to workspace",
		"show":     "show endpoint or session details",
		"info":     "show session detail in this endpoint by row number or session ID",
		"logs":     "show session logs",
		"history":  "read provider session history for the current endpoint and number its rows",
		"messages": "read one session's conversation in this endpoint by history row number or session ID",
		"resume":   "resume a stopped session by history row number",
		"stop":     "stop a session in this endpoint by row number or session ID",
		"drive":    "manage a session driver in this endpoint by row number or session ID; drive stop leaves the agent running",
		"status":   "show command result",
		"refresh":  "refresh the current endpoint",
		"watch":    "re-render the endpoint table on a timer until any key is pressed",
		"help":     "show help",
		"quit":     "q: same command; outside workspace scope both return to workspace scope",
		"exit":     "leave interactive mode from every scope",
	},
	ScopeSession: {
		"list":      "list sessions in the current endpoint; an explicit endpoint must match it",
		"cd":        "bare cd or cd /: workspace; cd ..: endpoint; cd <target>: navigate",
		"show":      "show the current session, or an explicit endpoint/session target",
		"info":      "show the current session detail, or another session in this endpoint",
		"logs":      "show current session output, or another session in this endpoint; -n <lines> bounds the trailing lines and -f streams until a key is pressed",
		"messages":  "read the current session's conversation; messages are persisted provider data, so a stopped session can still be read",
		"send":      "send a message to the current session; an explicit text submits directly, and a bare send asks for confirmation; unrecognized text offers this action",
		"stop":      "stop the current session",
		"btw":       "inject context into the current session",
		"interrupt": "interrupt the current session",
		"drive":     "manage the current session driver; drive stop leaves the agent running",
		"status":    "explicit ID: command result; omitted: last submitted command, otherwise current session state",
		"refresh":   "reload the current endpoint table and revalidate the current session",
		"help":      "show help",
		"quit":      "q: same command; outside workspace scope both return to workspace scope",
		"exit":      "leave interactive mode from every scope",
	},
}

const (
	// helpLineIndent is the leading indent of one command line in a help block.
	helpLineIndent = "  "
	// helpDescriptionGap separates the syntax cell from its description.
	helpDescriptionGap = "   "
	// helpSyntaxColumn caps the aligned description column, so one long syntax
	// never pushes every other description far to the right.
	helpSyntaxColumn = 40
)

// helpColumnWidth returns the description column for one block. A cell wider than
// the cap hangs its description on the next line, so it never widens the column.
// Hanging is only worth it when the over-cap cells are a minority: when most cells
// exceed the cap, hanging would double the block height without aligning anything,
// so the widest cell wins and every description stays inline.
func helpColumnWidth(cells []string) int {
	width := 0
	widest := 0
	overCap := 0
	for _, cell := range cells {
		cellWidth := displayWidth(cell)
		if cellWidth > widest {
			widest = cellWidth
		}
		if cellWidth > helpSyntaxColumn {
			overCap++
			continue
		}
		if cellWidth > width {
			width = cellWidth
		}
	}
	if width == 0 || overCap*2 > len(cells) {
		width = widest
	}
	return width
}

// formatHelpLine renders one aligned help line. A cell that fits the block column
// keeps its description on the same line. A cell wider than the cap keeps the
// description on the next line, indented to the same description column, so one
// long syntax never pushes every other description to the right and every
// description in the block still starts at one column.
func formatHelpLine(cell, description string, width int) string {
	column := helpLineIndent + strings.Repeat(" ", width) + helpDescriptionGap
	if displayWidth(cell) <= width {
		return helpLineIndent + cell + strings.Repeat(" ", width-displayWidth(cell)) + helpDescriptionGap + description
	}
	return helpLineIndent + cell + "\n" + column + description
}

// formatHelpBlock renders one aligned block from parallel cell and description
// slices, so every help surface shares the same column policy.
func formatHelpBlock(cells, descriptions []string) []string {
	return formatHelpBlockAt(cells, descriptions, helpColumnWidth(cells))
}

// formatHelpBlockAt renders one aligned block at an explicit description column,
// so several blocks printed together can share one column instead of each
// choosing its own.
func formatHelpBlockAt(cells, descriptions []string, width int) []string {
	lines := make([]string, 0, len(cells))
	for index, cell := range cells {
		lines = append(lines, formatHelpLine(cell, descriptions[index], width))
	}
	return lines
}

// formatHelpBlockColumns renders one aligned block with an optional middle column,
// such as the scope list in help all. The middle column is padded to its own shared
// width, so the trailing description starts at one column on every line instead of
// shifting with the length of the scope list.
func formatHelpBlockColumns(cells, middles, descriptions []string) []string {
	width := helpColumnWidth(cells)
	middleWidth := 0
	for _, middle := range middles {
		if middleWidth < displayWidth(middle) {
			middleWidth = displayWidth(middle)
		}
	}
	lines := make([]string, 0, len(cells))
	for index, cell := range cells {
		description := descriptions[index]
		if middles[index] != "" {
			description = middles[index] + strings.Repeat(" ", middleWidth-displayWidth(middles[index])) + helpDescriptionGap + description
		}
		lines = append(lines, formatHelpLine(cell, description, width))
	}
	return lines
}

// CommandHelpLines returns the interactive command descriptions in registration order.
func CommandHelpLines() []string {
	cells := make([]string, 0, len(commandHelpOrder))
	descriptions := make([]string, 0, len(commandHelpOrder))
	for _, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		cells = append(cells, entry.syntax)
		descriptions = append(descriptions, entry.description)
	}
	return formatHelpBlock(cells, descriptions)
}

var nonInteractiveHelpOrder = []string{"list", "refresh", "history", "messages", "endpoints", "show", "info", "logs", "status", "send", "btw", "interrupt", "ctl", "exec", "start", "resume", "stop", "drive", "help", "interactive"}

// nonInteractiveHelpAliases maps accepted standalone spellings to the advertised
// command. The advertised list keeps one spelling per surface, while an accepted
// alias still resolves to the same detailed help.
var nonInteractiveHelpAliases = map[string]string{"control": "ctl", logsFollowAlias: "logs", listFullAlias: "list"}

// NonInteractiveCommandHelpLines returns only commands dispatched by the standalone CLI.
func NonInteractiveCommandHelpLines() []string {
	cells := make([]string, 0, len(nonInteractiveHelpOrder))
	descriptions := make([]string, 0, len(nonInteractiveHelpOrder))
	for _, name := range nonInteractiveHelpOrder {
		entry := nonInteractiveHelpEntry(name)
		cells = append(cells, entry.syntax)
		descriptions = append(descriptions, entry.description)
	}
	return formatHelpBlock(cells, descriptions)
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
	// The standalone surface shares the canonical renderer so a command's help
	// cannot drift between the two surfaces. The scope line is suppressed
	// because the standalone CLI has no scope model. The heading is the spelling
	// the operator typed, so an alias never answers with a name they did not use.
	if err := printCommandDetail(out, target, advertised, entry, false); err != nil {
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
	case "start":
		entry.syntax = "agent-cluster-cli [options] " + name + " <endpoint> <resource> [text] [generation]"
	case "resume":
		// resume exists on both surfaces, but the standalone form addresses the
		// session by resource ID because it has no rendered history table, so the
		// syntax and parameters differ from the interactive row-number form.
		entry.syntax = "agent-cluster-cli [options] resume <endpoint> <resource> [text] [generation]"
		entry.description = "resume a stopped session identified by resource ID; the endpoint must prove from a complete fresh inventory that the session has no live generation"
		entry.parameters = []string{"endpoint: endpoint ID", "resource: session/resource ID of the stopped session", "text: optional literal initial task text", "generation: optional expected generation; a live generation is rejected instead of resumed", "--json: write the structured receipt instead of the rendered one"}
		entry.examples = []string{"resume endpoint-1 res_abc", "resume endpoint-1 res_abc gen-1"}
	case "stop":
		entry.syntax = "agent-cluster-cli [options] stop <endpoint> <resource> <generation>"
	case "drive":
		entry.syntax = "agent-cluster-cli [options] drive <start|stop|status> <endpoint> <session> [generation]"
	case "logs":
		entry.syntax = "agent-cluster-cli [options] [--lines <lines>] [--follow] logs <endpoint> <session>"
	case "show":
		entry.syntax = "agent-cluster-cli [options] show <endpoint-or-session>"
	case "info":
		entry.syntax = "agent-cluster-cli [options] info <session-id>"
		// The standalone surface has no rendered list and no current session, so
		// the interactive default must not be advertised here.
		entry.description = "show session detail for one session identified by resource ID or provider session ID"
	case "status":
		entry.syntax = "agent-cluster-cli [options] status <command-id>"
	case "list":
		entry.syntax = "agent-cluster-cli [options] [--endpoint <id>] list [--clean] [--full]"
	case "refresh":
		entry.syntax = "agent-cluster-cli [options] [--endpoint <id>] refresh"
	case "history":
		// history exists on both surfaces, but the standalone form has no current
		// endpoint and no rendered table, so it states the mandatory endpoint
		// argument and writes the joined document instead of a numbered table.
		entry.syntax = "agent-cluster-cli [options] history <endpoint-id-or-hostname>"
		entry.description = "read bounded provider session history for one endpoint; the result is a live provider read, never a persisted projection"
		entry.parameters = []string{"endpoint-id-or-hostname: endpoint to query; a hostname shared by several endpoints is rejected with the candidate list", "--limit: maximum number of history rows returned; 0 keeps the provider's own window and a positive value never raises it", "--json: write the joined history document instead of the rendered table"}
		entry.examples = []string{"history endpoint-1", "history ai-dev"}
	case "messages":
		// The standalone form has no current endpoint and no rendered history
		// table, so it states both mandatory arguments and never accepts a row
		// number: a row number only exists after an interactive render.
		entry.syntax = "agent-cluster-cli [options] messages <endpoint-id-or-hostname> <session-id>"
		entry.description = "read one session's conversation; messages are persisted provider data, so a stopped session can still be read"
		entry.parameters = []string{"endpoint-id-or-hostname: endpoint to query; a hostname shared by several endpoints is rejected with the candidate list", "session-id: provider session ID; a cluster resource ID is not accepted, because a stopped session has none", "--max-chars: maximum characters per message; 0 keeps the adapter default and a positive value never raises it", "--json: write the conversation document instead of the rendered blocks"}
		entry.examples = []string{"messages endpoint-1 20261013131753", "messages ai-dev 20261013131753 --max-chars 2000"}
	case "endpoints":
		entry.syntax = "agent-cluster-cli [options] [--endpoint <id>] endpoints [endpoint-id]"
	case "send":
		// The standalone entry replaces the interactive parameter list instead of
		// appending to it. The catalog entry rejects --json because the REPL has no
		// machine output, and appending would also repeat the "without text"
		// parameter that the catalog already states.
		entry.syntax = "agent-cluster-cli [options] send <endpoint> <resource> [text] [generation]"
		entry.description = "send a message to one session; without text it reads a multi-line message from stdin"
		entry.parameters = []string{"endpoint: endpoint ID", "resource: session/resource ID", "text: message text, or a JSON object with a text field; an explicit text is submitted without a confirmation question", "without text: read a multi-line message from stdin and finish it with a standalone EOF line or Ctrl+D; the terminator is never part of the message", "generation: optional expected generation", "--json: write the structured receipt instead of the rendered one"}
	case "btw":
		// btw is the only spelling of context injection, so the standalone entry
		// replaces the interactive parameter list instead of appending to it. The
		// catalog entry rejects --json because the REPL has no machine output, and
		// appending would also repeat the "without text" parameter that the
		// catalog already states.
		entry.syntax = "agent-cluster-cli [options] " + name + " <endpoint> <resource> [text] [generation]"
		entry.parameters = []string{"endpoint: endpoint ID", "resource: session/resource ID", "text: literal context text; no JSON is required", "without text: read a multi-line context block from stdin and finish it with a standalone EOF line or Ctrl+D; the terminator is never part of the context", "generation: optional expected generation", "--json: write the structured receipt instead of the rendered one"}
		entry.examples = []string{"btw endpoint-1 res_abc the deployment notes are in docs/", `btw endpoint-1 res_abc {"text":"context"}`}
	case "interrupt":
		// interrupt is the only spelling of execution interruption, so the
		// standalone entry replaces the interactive parameter list instead of
		// appending to it. The catalog entry rejects --json because the REPL has
		// no machine output, while the standalone surface accepts it.
		entry.syntax = "agent-cluster-cli [options] " + name + " <endpoint> <resource> [text] [generation]"
		entry.parameters = []string{"endpoint: endpoint ID", "resource: session/resource ID", "text: optional action word soft or hard, optionally followed by a literal message; hard accepts no message and is the default when no action word is given", "generation: optional expected generation", "--yes: confirm the interrupt, which is required because it cannot be undone", "--json: write the structured receipt instead of the rendered one"}
		entry.examples = []string{"interrupt endpoint-1 res_abc", "interrupt endpoint-1 res_abc soft", "interrupt endpoint-1 res_abc soft stop and summarize now", "interrupt endpoint-1 res_abc hard"}
	case "ctl":
		entry.syntax = "agent-cluster-cli [options] ctl <endpoint> <resource> <action> [json] [generation]"
		// The catalog entry is the interactive spelling, so its parameters
		// describe the REPL form and reject --json. The standalone surface
		// separates the payload by argv position and accepts --json, so both
		// lists are replaced instead of inherited.
		entry.parameters = []string{"endpoint: endpoint ID", "resource: session/resource ID", "action: advertised control action name", "json: optional JSON object payload; empty sends no parameters", "generation: optional expected generation", "--yes: confirm the control action, which is required because it mutates the session", "--json: write the structured receipt instead of the rendered one"}
		entry.examples = []string{"ctl endpoint-1 res_abc heartbeat", `ctl endpoint-1 res_abc pause {"reason":"maintenance"}`}
	case "exec":
		// exec is a standalone-only spelling: it has no interactive command word
		// because the interactive form is the "!" input prefix. It therefore has
		// no scope-matrix entry, and its description is supplied here instead of
		// in the catalog, which must stay one-to-one with the matrix.
		entry.syntax = "agent-cluster-cli [options] exec <endpoint> <resource> <generation> -- <argv...>"
		entry.description = "run one allowlisted command in the session working directory; the argv array is taken from the shell's own word splitting and is never re-tokenized, and the allowlist decision is made by the endpoint"
		entry.parameters = []string{"endpoint: endpoint ID", "resource: session/resource ID", "generation: target generation", "--: separates the target from the argv array", "argv: program and arguments; the program must be allowlisted by the endpoint", "--json: write the structured receipt instead of the rendered one"}
		entry.examples = []string{"exec endpoint-1 res_abc gen-1 -- git status", "exec endpoint-1 res_abc gen-1 -- ls -la"}
	case "help":
		entry.syntax = "agent-cluster-cli help [command]"
	case "interactive":
		// interactive is a standalone-only spelling: it has no interactive
		// command word because it is the REPL itself. It therefore has no
		// scope-matrix entry, and its description is supplied here instead of
		// in the catalog, which must stay one-to-one with the matrix.
		entry.syntax = "agent-cluster-cli [options] interactive"
		entry.description = "start the interactive REPL; equivalent to -i, and it requires a terminal on stdin"
		entry.parameters = []string{"-i: the same selection written as a global option", "--json, --yes: rejected, because the REPL renders its own output"}
		entry.examples = []string{"interactive", "agent-cluster-cli -i"}
	}
	return entry
}

// scopeCommandCells derives one scope group's syntax cells and descriptions from
// the availability matrix, so several groups can share one description column.
func scopeCommandCells(kind ScopeKind) ([]string, []string) {
	names := availableCommands(kind)
	cells := make([]string, 0, len(names))
	descriptions := make([]string, 0, len(names))
	for _, name := range names {
		entry := scopedHelpEntry(name, kind)
		description := scopeCommandDescriptions[kind][name]
		if description == "" {
			description = entry.description
		}
		cells = append(cells, entry.syntax)
		descriptions = append(descriptions, description)
	}
	return cells, descriptions
}

// scopeCommandLines derives one scope group from the availability matrix.
func scopeCommandLines(kind ScopeKind) []string {
	cells, descriptions := scopeCommandCells(kind)
	return formatHelpBlock(cells, descriptions)
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
// exactly like "help send". The dotted control spelling is a form of ctl too, so
// "help ctl.heartbeat" resolves like "help ctl" instead of reporting an unknown
// command for a spelling the dispatcher accepts.
func helpTarget(target string) string {
	normalized := canonicalCommandName(trimCommandPrefix(strings.ToLower(strings.TrimSpace(target))))
	if _, dotted := ctlDottedAction(normalized); dotted {
		return "ctl"
	}
	// The logf shorthand is a form rather than an alias entry, so it is resolved
	// here for the same reason the dotted ctl form is: the dispatcher accepts the
	// spelling, so help must answer it instead of reporting an unknown command.
	if normalized == logsFollowAlias {
		return "logs"
	}
	// The lf shorthand is a form rather than an alias entry, so it is resolved
	// here for the same reason: the dispatcher accepts the spelling, so help must
	// answer it instead of reporting an unknown command.
	if normalized == listFullAlias {
		return "list"
	}
	return normalized
}

// helpSpelling returns the spelling the operator typed, normalized the same way
// helpTarget normalizes it but without alias canonicalization. An alias must
// answer with the name the operator used, so "help btw" is headed "btw" rather
// than the canonical command it resolves to.
func helpSpelling(target string) string {
	return trimCommandPrefix(strings.ToLower(strings.TrimSpace(target)))
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
	return printCommandDetail(out, target, target, entry, true)
}

// PrintScopedCommandHelp renders context help or complete canonical help.
func PrintScopedCommandHelp(out io.Writer, target string, kind ScopeKind) error {
	spelling := helpSpelling(target)
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
	if err := printCommandDetail(out, spelling, target, entry, true); err != nil {
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
	if err := printCommandDetail(out, "start", "start", entry, true); err != nil {
		return err
	}
	_, err := fmt.Fprintln(out, "Project launch: start [endpoint] selects a live adapter and project (or manual folder), then asks for the initial task. Without an endpoint argument it prints a numbered endpoint list and accepts a bare number, so no endpoint identifier has to be typed. An empty task answer enters multi-line task mode: type the task, then finish it with a standalone EOF line or Ctrl+D, and the accepted task is echoed verbatim with colour so it can be verified before submission. Empty/cancel cancels. Legacy explicit --profile syntax and clients without launch queries use the endpoint/resource/profile/revision prompts; q quits, r refreshes, and help repeats guidance.")
	return err
}

// printCommandDetail renders one canonical command. The heading is the spelling
// the operator asked for, while target stays canonical so the scope line and the
// field list are looked up by the command that actually owns them. The scope line
// is optional because the standalone surface has no scope model: printing
// "Available in:" there would advertise an interactive concept the caller cannot
// use. Both surfaces share this renderer so a command's help cannot drift between
// them.
func printCommandDetail(out io.Writer, heading, target string, entry commandHelp, withScopes bool) error {
	if withScopes {
		if _, err := fmt.Fprintf(out, "%s\n\nSyntax: %s\nAvailable in: %s\nDescription: %s\n", heading, entry.syntax, strings.Join(commandScopes(target), ", "), entry.description); err != nil {
			return err
		}
	} else if _, err := fmt.Fprintf(out, "%s\n\nSyntax: %s\nDescription: %s\n", heading, entry.syntax, entry.description); err != nil {
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
	names := availableCommands(kind)
	cells := make([]string, 0, len(names))
	descriptions := make([]string, 0, len(names))
	for _, name := range names {
		entry := interactiveHelpEntry(name, kind)
		description := scopeCommandDescriptions[kind][name]
		if description == "" {
			description = entry.description
		}
		cells = append(cells, entry.syntax)
		descriptions = append(descriptions, description)
	}
	for _, line := range formatHelpBlock(cells, descriptions) {
		if _, err := fmt.Fprintln(out, line); err != nil {
			return err
		}
	}
	if _, err := fmt.Fprintln(out, "\nAliases: "+scopeAliasHelp(kind)); err != nil {
		return err
	}
	workflow := "Next: list -> <number> or cd <number> -> show/logs. Run help list for row selection rules."
	if kind == ScopeSession {
		workflow = "Bare cd or cd / returns to workspace; cd .. returns to endpoint. A bare number here is message text, and only the explicit cd <number> form is rejected as unavailable in session scope.\n" +
			"Entering a session renders one bounded output snapshot immediately, using the REPL line budget (0300 by default, or the startup --lines value); run logs again to re-read it.\n" +
			"Session selectors use internal resource IDs or unique names; the provider SESSION_ID is hidden from the interactive table, but logs, stop, drive and the standalone show command still accept it.\n" +
			"Type > <text> to send a message to the current session without spelling the command; the prefix is disjoint from every command word.\n" +
			"Text that matches no command is offered as a send message; declining keeps the unknown-command diagnostic.\n" +
			"A line beginning with ! runs one allowlisted command in the session working directory; the endpoint decides the allowlist.\n" +
			"Actions require adapter capability support and fresh session data; scope availability alone does not guarantee support."
	}
	example := "Start example: start <endpoint> <resource> --profile <id> --profile-revision <revision>"
	if kind == ScopeSession {
		example = "Session example: show or logs; type > <text> to send a message; use cd .. before starting another agent."
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
	if _, err := fmt.Fprintln(out, "Bare ASCII numbers are shorthand for cd <number> in workspace and endpoint scopes; in session scope a bare number is message text and only the explicit cd <number> form is rejected."); err != nil {
		return err
	}
	if _, err := fmt.Fprintln(out, commandPrefixHelp); err != nil {
		return err
	}
	cells := make([]string, 0, len(commandHelpOrder))
	middles := make([]string, 0, len(commandHelpOrder))
	descriptions := make([]string, 0, len(commandHelpOrder))
	for _, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		cells = append(cells, entry.syntax)
		middles = append(middles, "scopes: "+strings.Join(commandScopes(name), ", "))
		descriptions = append(descriptions, entry.description)
	}
	for _, line := range formatHelpBlockColumns(cells, middles, descriptions) {
		if _, err := fmt.Fprintln(out, line); err != nil {
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

// scopeAliasHelp renders the aliases usable in one scope, so the first-use
// overview names them instead of hiding them until help all. An alias outside
// the current scope is omitted, because advertising a spelling the scope rejects
// would send the operator straight into a scope error.
func scopeAliasHelp(kind ScopeKind) string {
	aliases := make([]string, 0, len(commandAliases))
	for alias, canonical := range commandAliases {
		if commandAllowed(alias, kind) {
			aliases = append(aliases, alias+"="+canonical)
		}
	}
	sort.Strings(aliases)
	return strings.Join(aliases, ", ")
}

// printScopeHelpOverview renders one command group per scope. All groups share one
// description column, so the overview reads as a single aligned document instead
// of three blocks that each pick their own column.
func printScopeHelpOverview(out io.Writer) error {
	if _, err := fmt.Fprintln(out, "Commands by scope:"); err != nil {
		return err
	}
	groupCells := make([][]string, 0, len(scopeHelpOrder))
	groupDescriptions := make([][]string, 0, len(scopeHelpOrder))
	allCells := make([]string, 0)
	for _, kind := range scopeHelpOrder {
		cells, descriptions := scopeCommandCells(kind)
		groupCells = append(groupCells, cells)
		groupDescriptions = append(groupDescriptions, descriptions)
		allCells = append(allCells, cells...)
	}
	width := helpColumnWidth(allCells)
	for index, kind := range scopeHelpOrder {
		if _, err := fmt.Fprintf(out, "\n%s:\n", kind); err != nil {
			return err
		}
		for _, line := range formatHelpBlockAt(groupCells[index], groupDescriptions[index], width) {
			if _, err := fmt.Fprintln(out, line); err != nil {
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
		"  quit, q               outside workspace scope: return to workspace scope; in workspace scope: leave interactive mode",
		"  exit                  leave interactive mode from every scope",
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
	if name == "quit" && kind != ScopeWorkspace {
		// Outside workspace scope quit and its q alias navigate back instead of
		// leaving the REPL, so the scoped help must not advertise them as a quit.
		entry.description = "return to workspace scope and re-render the list; in workspace scope it leaves interactive mode"
		entry.parameters = []string{"q: the same command, so it behaves identically in every scope", "use exit to leave interactive mode from any scope"}
		entry.examples = []string{"quit", "q"}
	}
	if name == "status" && kind == ScopeSession {
		entry.syntax = "status [command-id]"
		entry.description = "show an explicit command result; without an ID, use the last command submitted in this CLI, otherwise show current session state"
		entry.parameters = []string{"command-id: optional submitted command identifier", "without an ID: last submitted command takes precedence over current session state"}
		entry.examples = []string{"status", "status cmd_123"}
	}
	if name == "send" || name == "btw" {
		// The REPL takes the rest of the line as literal content, so these two
		// commands accept no options at all. --help is not an option here: it is
		// sent as literal text, and help <command> is the only help entry. The
		// standalone command keeps --help, because argv position separates the
		// command word from the payload there.
		entry.parameters = append(entry.parameters, "no options: the rest of the line is literal content, so "+name+" --help sends the text --help; run help "+name+" for this help")
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
