// Package security provides boundary authentication and authorization helpers.
package security

import (
	"strings"
)

// Operator scope names defined by the security baseline. A scope names one
// capability class an operator may exercise, so authorization is decided per
// operation instead of granting every authenticated caller full authority.
const (
	ScopeView          = "view"
	ScopeReadOutput    = "read_output"
	ScopeSendMessage   = "send_message"
	ScopeControl       = "control"
	ScopeEndpointAdmin = "endpoint_admin"
)

// ProviderControlPrefix marks the provider control operation family. Every
// operation in this family must declare a required permission, because the
// family includes actions that read conversation content.
const ProviderControlPrefix = "ctl."

// ScopeSet is an immutable set of operator scopes.
type ScopeSet map[string]struct{}

// NewScopeSet builds a scope set, ignoring empty entries.
func NewScopeSet(scopes ...string) ScopeSet {
	set := make(ScopeSet, len(scopes))
	for _, scope := range scopes {
		trimmed := strings.TrimSpace(scope)
		if trimmed != "" {
			set[trimmed] = struct{}{}
		}
	}
	return set
}

// Has reports whether the set contains the scope.
func (s ScopeSet) Has(scope string) bool {
	if scope == "" {
		return false
	}
	_, ok := s[scope]
	return ok
}

// Unrestricted reports whether the set grants every scope. An empty set is
// unrestricted, which models the single-credential deployment where the one
// provisioned token is the administrator. A configured set restricts the
// credential to exactly the listed scopes.
func (s ScopeSet) Unrestricted() bool {
	return len(s) == 0
}

// KnownScope reports whether name is a defined operator scope.
//
// The scope vocabulary is closed: a capability declares one of these names, and
// an Endpoint-local catalog may not invent a new one. Validating against this set
// keeps a typo from silently making an action unreachable, and keeps a catalog
// from granting a scope that no credential can hold.
func KnownScope(name string) bool {
	switch name {
	case ScopeView, ScopeReadOutput, ScopeSendMessage, ScopeControl, ScopeEndpointAdmin:
		return true
	}
	return false
}
