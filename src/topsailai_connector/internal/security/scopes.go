// Package security holds the authorization primitives shared by the Server and
// the Node: the scope and permission vocabulary, the grant a Node evaluates
// before every operation, the shared secrets that gate the channel and the
// operations, and the node identity a Node generates for itself.
//
// Everything here is pure data and pure functions. It must never perform IO, so
// both binaries can compile it and neither can disagree about the contract.
package security

import (
	"fmt"
)

// Scope names one area the Node exposes. A scope is a name, never a path: the
// Node maps the name to a local directory, so the Server never learns the real
// absolute path and a directory rename does not invalidate the policy.
type Scope string

// Permission names one action a caller may perform inside a scope. Read and
// write are separate permissions, so a read grant never implies a write.
type Permission string

const (
	// PermissionRead permits reading a file inside the scope.
	PermissionRead Permission = "read"
	// PermissionWrite permits writing a file inside the scope.
	PermissionWrite Permission = "write"
	// PermissionList permits listing a directory inside the scope.
	PermissionList Permission = "list"
	// PermissionStat permits reading metadata of a path inside the scope.
	PermissionStat Permission = "stat"
	// PermissionExec permits running an allowlisted argv array inside the scope.
	PermissionExec Permission = "exec"
)

// MaxScopeNameLength bounds a scope name. The bound exists so a name that cannot
// be a directory name is refused before it reaches a filesystem call, rather
// than after.
const MaxScopeNameLength = 64

// Grant is the authority a caller holds on one scope. The Node evaluates it
// before every operation, so revoking a grant takes effect on the next call
// rather than on the next reconnect.
type Grant struct {
	Scope       Scope        `json:"scope"`
	Permissions []Permission `json:"permissions"`
}

// Allows reports whether the grant covers the permission on the given scope.
//
// A grant is a pair of scope and permission, so a permission held on one scope
// is not held on another, and an empty permission list grants nothing. Both
// refusals are deliberate: a grant that leaked across scopes would make the
// policy mean something its author did not write.
func (g Grant) Allows(scope Scope, permission Permission) bool {
	if g.Scope != scope {
		return false
	}
	for _, candidate := range g.Permissions {
		if candidate == permission {
			return true
		}
	}
	return false
}

// ValidateScopeName rejects a scope name that is not an identifier.
//
// The rule is a whitelist, not a blacklist. A blacklist has to anticipate every
// character a filesystem or a shell treats specially, and the list is different
// on Windows; a whitelist has to anticipate nothing. Letters, digits, `-` and
// `_` are the whole alphabet, so a name containing a space, a tab, a control
// character, a NUL byte, a colon, a path separator or a trailing dot is refused
// because it is not in the alphabet rather than because someone remembered to
// list it.
func ValidateScopeName(scope Scope) error {
	name := string(scope)
	if name == "" {
		return fmt.Errorf("scope name is empty")
	}
	if len(name) > MaxScopeNameLength {
		return fmt.Errorf("scope name is %d bytes, want at most %d", len(name), MaxScopeNameLength)
	}
	for _, character := range name {
		if !isScopeNameCharacter(character) {
			return fmt.Errorf("scope name %q contains %q, which is not a letter, a digit, '-' or '_'", name, character)
		}
	}
	if name[0] == '-' || name[0] == '_' {
		return fmt.Errorf("scope name %q starts with %q, which makes it look like a flag", name, name[0])
	}
	return nil
}

// isScopeNameCharacter reports whether a character belongs to the scope name
// alphabet.
func isScopeNameCharacter(character rune) bool {
	switch {
	case character >= 'a' && character <= 'z':
		return true
	case character >= 'A' && character <= 'Z':
		return true
	case character >= '0' && character <= '9':
		return true
	case character == '-', character == '_':
		return true
	default:
		return false
	}
}

// ValidatePermission rejects a permission that is not in the vocabulary. An
// unknown permission is not a permission the Node may guess at, because a guess
// in an authorization check is a grant.
func ValidatePermission(permission Permission) error {
	switch permission {
	case PermissionRead, PermissionWrite, PermissionList, PermissionStat, PermissionExec:
		return nil
	default:
		return fmt.Errorf("permission %q is not in the vocabulary", permission)
	}
}

// IsIdentifier reports whether a value is a well-formed scope name. It exists so
// a caller that only needs a yes-or-no answer does not have to inspect an error.
func IsIdentifier(value string) bool {
	return ValidateScopeName(Scope(value)) == nil
}
