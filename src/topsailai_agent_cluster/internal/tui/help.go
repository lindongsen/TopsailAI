package tui

import (
	"fmt"
	"io"
	"sort"
	"strings"
)

const (
	ListHelpDescription = "list all sessions, including endpoints that failed to report; use --clean to omit failed endpoints; diagnostics still go to stderr"
)

type commandHelp struct {
	syntax      string
	description string
	parameters  []string
	examples    []string
}

var fieldHelp = []string{
	"NO: display row number; use it with cd <hostname>/<endpoint-id>/<session>.",
	"ENDPOINT: endpoint hostname, falling back to its display name or ID.",
	"ADAPTER: provider adapter display label.",
	"SESSION: session display name, falling back to the provider session ID, then to - when neither is known.",
	"STATE: provider-reported lifecycle state, such as running, stopped, or failed.",
	"STALE: displayed data was retained from an earlier successful collection because the latest collection was failed or incomplete.",
	"UNKNOWN: no trustworthy adapter data is available for the row.",
	"COLLECTION: result of the latest collection attempt: succeeded, partial, failed, or unknown.",
	"LAST_SUCCESS: local-time timestamp of the latest successful collection; - means no success has been recorded.",
}

var commandHelpCatalog = map[string]commandHelp{
	"list":    {"list [endpoint] [--clean]", ListHelpDescription, []string{"endpoint: optional endpoint ID filter", "--clean: omit endpoints that failed to report; diagnostics still go to stderr"}, []string{"list", "list endpoint-1", "list --clean"}},
	"cd":      {"cd [target]", "navigate between workspace, endpoint, and session scopes; bare cd returns to workspace", []string{"target: hostname, hostname/endpoint-id, session, hostname/endpoint-id/session, .., or /", "a hostname shared by several endpoints prompts for a numbered choice, a hostname/endpoint-id answer, or cancel"}, []string{"cd", "cd /", "cd ..", "cd ai-dev", "cd ai-dev/endpoint-1", "cd res_abc", "cd ai-dev/endpoint-1/res_abc"}},
	"show":    {"show [endpoint-or-session]", "show detailed information for an endpoint or session; defaults to the current scope target", []string{"endpoint-or-session: optional endpoint ID or session/resource ID"}, []string{"show", "show endpoint-1"}},
	"logs":    {"logs [session]", "show bounded output for a session in the current endpoint", []string{"session: optional session/resource ID; defaults to the current session"}, []string{"logs", "logs res_abc"}},
	"send":    {"send <json>", "send a JSON message to the selected session", []string{"json: message payload"}, []string{`send {"text":"hello"}`}},
	"status":  {"status <command-id>", "show the durable result of a command", []string{"command-id: submitted command identifier"}, []string{"status cmd_123"}},
	"refresh": {"refresh", "refresh endpoint inventories and the interactive session table", nil, []string{"refresh"}},
	"help":    {"help [command]", "show the command overview or detailed help for one command", []string{"command: optional command name, or scope for the scope model"}, []string{"help", "help list", "help scope"}},
	"quit":    {"quit", "leave interactive mode", nil, []string{"quit"}},
}

var commandHelpOrder = []string{"list", "cd", "show", "logs", "send", "status", "refresh", "help", "quit"}

// scopeHelpOrder is the fixed group order used by the scope-grouped overview.
var scopeHelpOrder = []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession}

// scopeCommandDescriptions holds per-scope wording only. Availability always
// comes from commandScopeMatrix so the two can never disagree.
var scopeCommandDescriptions = map[ScopeKind]map[string]string{
	ScopeWorkspace: {
		"list":    "list sessions across all endpoints",
		"cd":      "navigate to an endpoint or session",
		"show":    "show endpoint or session details",
		"status":  "show command result",
		"refresh": "refresh inventories",
		"help":    "show help",
		"quit":    "exit",
	},
	ScopeEndpoint: {
		"list":    "list sessions in the current endpoint",
		"cd":      "navigate to a session or back to workspace",
		"show":    "show endpoint or session details",
		"logs":    "show session logs",
		"status":  "show command result",
		"refresh": "refresh the current endpoint",
		"help":    "show help",
		"quit":    "exit",
	},
	ScopeSession: {
		"list":    "list sibling sessions in the current endpoint",
		"cd":      "navigate back to endpoint or workspace",
		"show":    "show endpoint or session details",
		"logs":    "show session logs",
		"send":    "send a message to the current session",
		"status":  "show command result",
		"refresh": "revalidate the current session",
		"help":    "show help",
		"quit":    "exit",
	},
}

// CommandHelpLines returns the shared command descriptions used by CLI and REPL help.
func CommandHelpLines() []string {
	lines := make([]string, 0, len(commandHelpOrder))
	for _, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		lines = append(lines, entry.syntax+"   "+entry.description)
	}
	return lines
}

// scopeCommandLines derives one scope group from the availability matrix.
func scopeCommandLines(kind ScopeKind) []string {
	names := availableCommands(kind)
	lines := make([]string, 0, len(names))
	for _, name := range names {
		entry := commandHelpCatalog[name]
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

// PrintCommandHelp renders overview or detailed help without ANSI styling.
func PrintCommandHelp(out io.Writer, target string) error {
	target = strings.ToLower(strings.TrimSpace(target))
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
		"  session    entered with cd <session> or cd <hostname>/<endpoint-id>/<session>",
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
