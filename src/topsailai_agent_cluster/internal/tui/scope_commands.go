package tui

import (
	"fmt"
	"sort"
	"strings"
)

// commandScopeRule declares which scopes may execute one canonical command.
type commandScopeRule struct {
	Name      string
	Workspace bool
	Endpoint  bool
	Session   bool
}

// allows reports whether the rule permits the given scope.
func (r commandScopeRule) allows(kind ScopeKind) bool {
	switch kind {
	case ScopeWorkspace:
		return r.Workspace
	case ScopeEndpoint:
		return r.Endpoint
	case ScopeSession:
		return r.Session
	default:
		return false
	}
}

// commandScopeMatrix is the single source of truth for canonical command availability.
var commandScopeMatrix = []commandScopeRule{
	{Name: "list", Workspace: true, Endpoint: true, Session: true},
	{Name: "endpoints", Workspace: true},
	{Name: "cd", Workspace: true, Endpoint: true, Session: true},
	{Name: "show", Workspace: true, Endpoint: true, Session: true},
	{Name: "info", Workspace: true, Endpoint: true, Session: true},
	{Name: "start", Workspace: true, Endpoint: true},
	// resume is available only where a history row can be selected: session scope
	// requires a live generation, while resume authorizes on a proven absence, so
	// the two conditions are mutually exclusive and session scope stays excluded.
	{Name: "resume", Workspace: true, Endpoint: true},
	{Name: "stop", Workspace: true, Endpoint: true, Session: true},
	{Name: "btw", Session: true},
	{Name: "interrupt", Session: true},
	{Name: "ctl", Session: true},
	{Name: "drive", Workspace: true, Endpoint: true, Session: true},
	{Name: "logs", Endpoint: true, Session: true},
	{Name: "send", Session: true},
	{Name: "status", Workspace: true, Endpoint: true, Session: true},
	{Name: "refresh", Workspace: true, Endpoint: true, Session: true},
	{Name: "watch", Workspace: true, Endpoint: true},
	// history is a read-only projection of retained provider history, so it is
	// available wherever an endpoint can be resolved and never in session scope.
	{Name: "history", Workspace: true, Endpoint: true},
	// messages reads persisted provider data, so it needs neither a live
	// generation nor a proven absence. It is therefore the only conversation
	// surface available in all three scopes, including session scope where the
	// selected session already names the target.
	{Name: "messages", Workspace: true, Endpoint: true, Session: true},
	{Name: "help", Workspace: true, Endpoint: true, Session: true},
	{Name: "quit", Workspace: true, Endpoint: true, Session: true},
	{Name: "exit", Workspace: true, Endpoint: true, Session: true},
}

// sendPrefix is the one-character alias of send. It is disjoint from every
// command word, so a message can never be mistaken for a command and a typo can
// never be mistaken for a message.
const sendPrefix = ">"

// logsFollowAlias is the shorthand spelling of "logs -f". It is a form rather
// than an alias entry, because it also supplies the follow flag: resolving the
// word to "logs" alone would parse an empty tail and render a one-shot snapshot,
// which would look like a stream while silently missing everything written after
// it. It is deliberately absent from commandAliases, for the same reason the
// dotted ctl form is: an alias maps one word to another, while a form changes the
// accepted spelling of a command. Registering it as an alias would also make "lo"
// ambiguous between "logs" and "logf", so Tab would stop completing the far more
// common "logs". The shorthand is documented in the logs help body instead, so it
// stays discoverable without entering the alias registry.
const logsFollowAlias = "logf"

// LogsFollowAlias is the exported spelling of logsFollowAlias, so the standalone
// dispatcher accepts the same shorthand without duplicating the literal. One
// constant keeps the two surfaces from drifting into different spellings.
const LogsFollowAlias = logsFollowAlias

// logsFollowRest rewrites the tail of a logf invocation into the equivalent logs
// tail, so the shorthand inherits logs' grammar instead of owning a second
// parser. The follow flag is prepended, so "logf -n 7" becomes "-f -n 7" and a
// repeated "-f" is rejected by the same duplicate check that guards "logs".
func logsFollowRest(rest string) string {
	if strings.TrimSpace(rest) == "" {
		return "-f"
	}
	return "-f " + rest
}

// listFullAlias is the shorthand spelling of "list --full". It is a form rather
// than an alias entry for exactly the reason logsFollowAlias is one: it also
// supplies a flag. Resolving the word to "list" alone would parse an empty tail
// and render the ordinary truncated table, which is the worst outcome for this
// command, because a clipped table looks complete while silently hiding the tail
// of every over-wide value. It is deliberately absent from commandAliases, so
// "l" keeps completing "list" and "logs" instead of becoming ambiguous with "lf".
// The shorthand is documented in the list help body instead, so it stays
// discoverable without entering the alias registry.
const listFullAlias = "lf"

// ListFullAlias is the exported spelling of listFullAlias, so the standalone
// dispatcher accepts the same shorthand without duplicating the literal. One
// constant keeps the two surfaces from drifting into different spellings.
const ListFullAlias = listFullAlias

// listFullRest rewrites the tail of an lf invocation into the equivalent list
// tail, so the shorthand inherits list's grammar instead of owning a second
// parser. The full flag is prepended, so "lf --clean" becomes "--full --clean"
// and a repeated "--full" is rejected by the same duplicate check that guards
// "list".
func listFullRest(rest string) string {
	if strings.TrimSpace(rest) == "" {
		return "--full"
	}
	return "--full " + rest
}

// commandAliases maps accepted short or compatibility names to canonical commands.
// "exit" is deliberately absent: it is its own canonical command that always
// leaves the process, so it must never inherit the scope-aware "quit" behaviour.
var commandAliases = map[string]string{
	"?":        "help",
	"q":        "quit",
	"r":        "refresh",
	"l":        "list",
	"w":        "watch",
	"control":  "ctl",
	sendPrefix: "send",
}

// canonicalCommandName returns the registered command for an accepted spelling.
func canonicalCommandName(name string) string {
	if canonical, ok := commandAliases[name]; ok {
		return canonical
	}
	return name
}

// quitReturnsToWorkspace reports whether the canonical command "quit" must
// navigate back to workspace scope instead of leaving the REPL. It is a dispatch
// rule, not a scope-availability rule, and it keys on the canonical command, so
// "q" and "quit" are one behaviour rather than two: "q" is only an alias of
// "quit" and never carries a rule of its own. Outside workspace scope both
// navigate back; in workspace scope both leave the REPL. "exit" is a separate
// canonical command that always leaves the process, so an operator never loses an
// unambiguous way out of any scope.
func quitReturnsToWorkspace(canonical string, kind ScopeKind) bool {
	return canonical == "quit" && kind != ScopeWorkspace
}

// alwaysAvailableCommands must stay usable even if the matrix is misconfigured.
var alwaysAvailableCommands = map[string]bool{
	"help": true,
	"quit": true,
}

// commandAllowed reports whether a canonical or aliased command may run in a scope.
func commandAllowed(name string, kind ScopeKind) bool {
	name = canonicalCommandName(name)
	if alwaysAvailableCommands[name] {
		return true
	}
	for _, rule := range commandScopeMatrix {
		if rule.Name == name {
			return rule.allows(kind)
		}
	}
	return true
}

// availableCommands returns canonical permitted command names in stable order.
func availableCommands(kind ScopeKind) []string {
	names := make([]string, 0, len(commandScopeMatrix))
	for _, rule := range commandScopeMatrix {
		if rule.allows(kind) {
			names = append(names, rule.Name)
		}
	}
	return names
}

// completableCommands returns the command words completion may offer in a scope:
// every canonical command plus each multi-character alias the scope permits.
//
// A one-character alias is already complete the moment it is typed, so offering
// it would never add a character and would only turn a unique completion into a
// false ambiguity. A multi-character alias such as "control" is genuinely
// partial while it is being typed, so it must be completable; otherwise the
// operator has to know a spelling that the help text advertises.
func completableCommands(kind ScopeKind) []string {
	names := availableCommands(kind)
	aliases := make([]string, 0, len(commandAliases))
	for alias := range commandAliases {
		if len(alias) < 2 || !commandAllowed(alias, kind) {
			continue
		}
		aliases = append(aliases, alias)
	}
	sort.Strings(aliases)
	return append(names, aliases...)
}

// scopeUnavailableError builds the uniform scope rejection message.
func scopeUnavailableError(name string, kind ScopeKind) error {
	return fmt.Errorf("command %q is unavailable in %s scope; available commands: %s", name, kind, strings.Join(availableCommands(kind), ", "))
}

// requireCommandScope rejects a command that the current scope does not permit.
func requireCommandScope(name string, kind ScopeKind) error {
	canonical := canonicalCommandName(name)
	if _, known := commandHelpCatalog[canonical]; known && !containsCanonicalCommand(canonical) {
		return fmt.Errorf("unknown command %q (try help)", name)
	}
	if commandAllowed(canonical, kind) {
		return nil
	}
	return scopeUnavailableError(canonical, kind)
}

// containsCanonicalCommand reports whether a name is registered in the matrix.
func containsCanonicalCommand(name string) bool {
	for _, rule := range commandScopeMatrix {
		if rule.Name == name {
			return true
		}
	}
	return false
}

// scopedListFilter narrows a list filter to the current endpoint outside workspace scope.
func scopedListFilter(state *interactiveState, filter string) (string, error) {
	if state.Scope.Kind == ScopeWorkspace {
		return filter, nil
	}
	current := state.Scope.EndpointID
	if filter != "" && filter != current {
		return "", fmt.Errorf("list filter %q does not match the current endpoint %q", filter, current)
	}
	return current, nil
}
