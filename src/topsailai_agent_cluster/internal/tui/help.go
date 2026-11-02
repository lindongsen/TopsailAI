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
	"SESSION: session display name, falling back to the internal resource ID.",
	"GENERATION: exact provider process-instance identity used to fence commands; it is not a timestamp or restart count.",
	"STATE: provider-reported lifecycle state, such as running, stopped, or failed.",
	"STALE: displayed data was retained from an earlier successful collection because the latest collection was failed or incomplete.",
	"UNKNOWN: no trustworthy adapter data is available for the row.",
	"COLLECTION: result of the latest collection attempt: succeeded, partial, failed, or unknown.",
	"LAST_SUCCESS_MS: Unix epoch timestamp in milliseconds of the latest successful collection; never means no success has been recorded.",
}

var commandHelpCatalog = map[string]commandHelp{
	"list":    {"list [endpoint] [--clean]", ListHelpDescription, []string{"endpoint: optional endpoint ID filter", "--clean: omit endpoints that failed to report; diagnostics still go to stderr"}, []string{"list", "list endpoint-1", "list --clean"}},
	"cd":      {"cd [target]", "navigate between workspace, endpoint, and session scopes; bare cd returns to workspace", []string{"target: hostname, hostname/endpoint-id, session, hostname/endpoint-id/session, .., or /"}, []string{"cd", "cd ai-dev", "cd ai-dev/endpoint-1", "cd .."}},
	"show":    {"show [endpoint-or-session]", "show detailed information for an endpoint or session; defaults to the current scope target", []string{"endpoint-or-session: optional endpoint ID or session/resource ID"}, []string{"show", "show endpoint-1"}},
	"logs":    {"logs [session]", "show bounded output for a session in the current endpoint", []string{"session: optional session/resource ID; defaults to the current session"}, []string{"logs", "logs res_abc"}},
	"send":    {"send <json>", "send a JSON message to the selected session", []string{"json: message payload"}, []string{`send {"text":"hello"}`}},
	"status":  {"status <command-id>", "show the durable result of a command", []string{"command-id: submitted command identifier"}, []string{"status cmd_123"}},
	"refresh": {"refresh", "refresh endpoint inventories and the interactive session table", nil, []string{"refresh"}},
	"help":    {"help [command]", "show the command overview or detailed help for one command", []string{"command: optional command name"}, []string{"help", "help list"}},
	"quit":    {"quit", "leave interactive mode", nil, []string{"quit"}},
}

var commandHelpOrder = []string{"list", "cd", "show", "logs", "send", "status", "refresh", "help", "quit"}

// CommandHelpLines returns the shared command descriptions used by CLI and REPL help.
func CommandHelpLines() []string {
	lines := make([]string, 0, len(commandHelpOrder))
	for _, name := range commandHelpOrder {
		entry := commandHelpCatalog[name]
		lines = append(lines, entry.syntax+"   "+entry.description)
	}
	return lines
}

// PrintCommandHelp renders overview or detailed help without ANSI styling.
func PrintCommandHelp(out io.Writer, target string) error {
	target = strings.ToLower(strings.TrimSpace(target))
	if target == "" {
		if _, err := fmt.Fprintln(out, "commands:"); err != nil {
			return err
		}
		for _, line := range CommandHelpLines() {
			if _, err := fmt.Fprintln(out, "  "+line); err != nil {
				return err
			}
		}
		return nil
	}
	entry, ok := commandHelpCatalog[target]
	if !ok {
		return fmt.Errorf("unknown help command %q; available commands: %s", target, strings.Join(commandHelpOrder, ", "))
	}
	if _, err := fmt.Fprintf(out, "%s\n\nSyntax: %s\nDescription: %s\n", target, entry.syntax, entry.description); err != nil {
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

// HelpCommandNames returns command names in stable display order.
func HelpCommandNames() []string {
	result := append([]string(nil), commandHelpOrder...)
	sort.Strings(result)
	return result
}
