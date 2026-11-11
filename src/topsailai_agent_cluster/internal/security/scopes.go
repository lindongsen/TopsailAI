// Package security provides boundary authentication and authorization helpers.
package security

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
