package policy

import (
	"fmt"
	"sort"

	"topsailai_connector/internal/security"
)

// Version is the only policy format this build understands. It is required in
// the file so a future format change is detectable instead of being read as if
// it were the current one.
const Version = 1

// ScopeDefinition is one scope: a name and the directory it maps to.
//
// The path is absolute and is resolved once at load time. The Server never
// learns it, so a directory rename does not invalidate the policy and a leaked
// policy does not leak the filesystem layout.
type ScopeDefinition struct {
	Path string `yaml:"path"`
}

// GrantDefinition is one grant: a scope and the permissions allowed on it.
//
// A grant names a scope that must already be defined. A grant naming an
// undefined scope is an error rather than a silent no-op, because a typo would
// otherwise look like a working policy.
type GrantDefinition struct {
	Scope       string   `yaml:"scope"`
	Permissions []string `yaml:"permissions"`
}

// file is the on-disk shape. It is separate from Policy so the decoded form can
// be validated before it becomes something the Node evaluates.
type file struct {
	Version int                        `yaml:"version"`
	Scopes  map[string]ScopeDefinition `yaml:"scopes"`
	Grants  []GrantDefinition          `yaml:"grants"`
}

// Policy is a validated policy: the scopes it defines and the grants it holds.
//
// A Policy is immutable once built. A reload builds a new one and swaps it in,
// so a request that is already being evaluated keeps the policy it started with
// instead of observing a half-applied change.
type Policy struct {
	scopes map[security.Scope]string
	grants []security.Grant
}

// ScopeNames returns the defined scope names in sorted order, so a startup
// report and a test are both stable.
func (p *Policy) ScopeNames() []security.Scope {
	names := make([]security.Scope, 0, len(p.scopes))
	for name := range p.scopes {
		names = append(names, name)
	}
	sort.Slice(names, func(left int, right int) bool { return names[left] < names[right] })
	return names
}

// ScopePath returns the directory a scope maps to. The second result is false
// when the scope is not defined, so a caller cannot mistake an empty path for a
// definition.
func (p *Policy) ScopePath(scope security.Scope) (string, bool) {
	path, ok := p.scopes[scope]
	return path, ok
}

// Grants returns the grants the policy holds, in file order.
func (p *Policy) Grants() []security.Grant {
	grants := make([]security.Grant, len(p.grants))
	copy(grants, p.grants)
	return grants
}

// Allows reports whether the policy grants the permission on the scope.
//
// The answer is false when the scope is undefined, when no grant names it and
// when a grant names it without the permission. All three are refusals rather
// than errors, because a caller must not be able to tell "this scope does not
// exist" from "you may not use it": that difference is a scope-name oracle.
func (p *Policy) Allows(scope security.Scope, permission security.Permission) bool {
	if _, defined := p.scopes[scope]; !defined {
		return false
	}
	for _, grant := range p.grants {
		if grant.Allows(scope, permission) {
			return true
		}
	}
	return false
}

// Parse validates a decoded file and builds a Policy.
//
// Every rule fails rather than warns. The rules are ordered so the first error a
// policy author sees is the most specific one: the version, then the scopes,
// then the grants.
func Parse(decoded file) (*Policy, error) {
	if decoded.Version == 0 {
		return nil, fmt.Errorf("version is required; a policy without a version cannot be migrated")
	}
	if decoded.Version != Version {
		return nil, fmt.Errorf("version %d is not supported; this build understands version %d", decoded.Version, Version)
	}

	scopes, err := parseScopes(decoded.Scopes)
	if err != nil {
		return nil, err
	}

	grants, err := parseGrants(decoded.Grants, scopes)
	if err != nil {
		return nil, err
	}

	return &Policy{scopes: scopes, grants: grants}, nil
}

// parseScopes validates every scope definition.
func parseScopes(definitions map[string]ScopeDefinition) (map[security.Scope]string, error) {
	scopes := make(map[security.Scope]string, len(definitions))
	for name, definition := range definitions {
		scope := security.Scope(name)
		if err := security.ValidateScopeName(scope); err != nil {
			return nil, fmt.Errorf("scope %q: %w", name, err)
		}
		if definition.Path == "" {
			return nil, fmt.Errorf("scope %q: path is required", name)
		}
		scopes[scope] = definition.Path
	}
	return scopes, nil
}

// parseGrants validates every grant against the defined scopes.
func parseGrants(definitions []GrantDefinition, scopes map[security.Scope]string) ([]security.Grant, error) {
	grants := make([]security.Grant, 0, len(definitions))
	for index, definition := range definitions {
		scope := security.Scope(definition.Scope)
		if _, defined := scopes[scope]; !defined {
			return nil, fmt.Errorf("grant %d names scope %q, which is not defined; a typo would otherwise look like a working policy", index, definition.Scope)
		}

		permissions, err := parsePermissions(index, definition.Permissions)
		if err != nil {
			return nil, err
		}
		grants = append(grants, security.Grant{Scope: scope, Permissions: permissions})
	}
	return grants, nil
}

// parsePermissions validates the permission list of one grant.
//
// A duplicate permission is refused rather than collapsed, because a policy that
// says the same thing twice is a policy whose author was not reading what they
// wrote, and the next edit is where the mistake becomes a grant.
func parsePermissions(index int, names []string) ([]security.Permission, error) {
	permissions := make([]security.Permission, 0, len(names))
	seen := make(map[security.Permission]struct{}, len(names))
	for _, name := range names {
		permission := security.Permission(name)
		if err := security.ValidatePermission(permission); err != nil {
			return nil, fmt.Errorf("grant %d: %w", index, err)
		}
		if _, duplicate := seen[permission]; duplicate {
			return nil, fmt.Errorf("grant %d lists permission %q twice", index, name)
		}
		seen[permission] = struct{}{}
		permissions = append(permissions, permission)
	}
	return permissions, nil
}
