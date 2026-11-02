package tui

import (
	"fmt"
	"strings"
)

// commandScopeRule declares which scopes may execute one command.
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

// commandScopeMatrix is the single source of truth for scope command availability.
// Order is the stable order used by every availability message.
var commandScopeMatrix = []commandScopeRule{
	{Name: "list", Workspace: true, Endpoint: true, Session: true},
	{Name: "cd", Workspace: true, Endpoint: true, Session: true},
	{Name: "show", Workspace: true, Endpoint: true, Session: true},
	{Name: "logs", Workspace: false, Endpoint: true, Session: true},
	{Name: "send", Workspace: false, Endpoint: false, Session: true},
	{Name: "status", Workspace: true, Endpoint: true, Session: true},
	{Name: "refresh", Workspace: true, Endpoint: true, Session: true},
	{Name: "help", Workspace: true, Endpoint: true, Session: true},
	{Name: "quit", Workspace: true, Endpoint: true, Session: true},
}

// alwaysAvailableCommands must stay usable even if the matrix is misconfigured.
var alwaysAvailableCommands = map[string]bool{
	"help": true,
	"?":    true,
	"quit": true,
	"exit": true,
}

// commandAllowed reports whether the command may run in the given scope.
// Names outside the matrix are allowed so unknown-command and removal
// diagnostics keep their original wording.
func commandAllowed(name string, kind ScopeKind) bool {
	if alwaysAvailableCommands[name] {
		return true
	}
	for _, rule := range commandScopeMatrix {
		if rule.Name != name {
			continue
		}
		return rule.allows(kind)
	}
	return true
}

// availableCommands returns the permitted command names in stable order.
func availableCommands(kind ScopeKind) []string {
	names := make([]string, 0, len(commandScopeMatrix))
	for _, rule := range commandScopeMatrix {
		if rule.allows(kind) {
			names = append(names, rule.Name)
		}
	}
	return names
}

// scopeUnavailableError builds the uniform scope rejection message.
func scopeUnavailableError(name string, kind ScopeKind) error {
	return fmt.Errorf("command %q is unavailable in %s scope; available commands: %s", name, kind, strings.Join(availableCommands(kind), ", "))
}

// requireCommandScope rejects a command that the current scope does not permit.
func requireCommandScope(name string, kind ScopeKind) error {
	if commandAllowed(name, kind) {
		return nil
	}
	return scopeUnavailableError(name, kind)
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
