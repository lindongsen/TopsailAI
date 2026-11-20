package node

import (
	"fmt"
	"sort"

	"topsailai_connector/internal/node/policy"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// Authority is the Node's whole permission state: the policy it loaded and one
// scope for every scope that policy defines.
//
// The two halves are joined here on purpose. A scope opened without a policy
// entry would be a directory reachable without a grant, which is not
// representable in an Authority because an Authority is only built by
// LoadAuthority. A policy entry whose directory does not exist is representable:
// the scope is recorded with no handle and refuses every request, so the policy
// and the served state cannot disagree about which scopes exist.
//
// The Node is the only authority for permissions. Nothing here consults the
// Server, and there is no field a Server could set: the policy file is the only
// input, and it is read from the Node's own disk.
type Authority struct {
	policy *policy.Policy
	scopes map[security.Scope]*Scope
}

// LoadAuthority loads the policy file and records every scope it defines.
//
// A scope that cannot be opened refuses startup rather than being skipped,
// because a Node that starts with a subset of its policy is a Node whose operator
// believes a grant exists that does not. When a later scope fails, the scopes
// already opened are closed before returning, so a failed start leaves no handle
// behind.
//
// A scope whose directory does not exist is the one case that does not refuse
// startup. It is recorded with no handle and refuses every request, so the scope
// is still defined and still advertised: the operator sees a scope that serves
// nothing rather than a scope that vanished. That is what lets a policy name a
// directory that has not been created yet, and on Windows a drive letter with no
// volume behind it.
//
// denyPaths are the Node's own files. Their identity is recorded per scope, so a
// request is refused by identity rather than by name and a symlink or a different
// spelling cannot rename them.
//
// configDir is the Node's own config directory. A scope that contains it, sits
// inside it or equals it is refused at startup, because such a scope can list the
// Node's credential files even though reading them is denied. An empty value
// states that the caller has no config directory to protect.
func LoadAuthority(policyPath string, denyPaths []string, configDir string) (*Authority, error) {
	loaded, err := policy.Load(policyPath)
	if err != nil {
		return nil, err
	}
	return buildAuthority(loaded, denyPaths, configDir)
}

// LoadPolicyForListing reads the policy document without opening any scope.
//
// It exists for `scope list`, which answers "which scope names does this policy
// define" and nothing else. Opening the scopes would apply the fence's startup
// rules, so a listing would fail on a machine where a scope directory is absent or
// where the config directory overlaps a scope. Those are refusals the Node must
// make before it serves, not conditions that should stop an operator from reading
// the names they wrote.
//
// The decoding is the same strict decoding the Node uses at startup, so a
// malformed policy fails here with the same message it would fail with at `run`
// time. A second, looser parser would be a second definition of a valid policy,
// and the listing would then report names the Node would refuse to serve.
//
// Exactly one of policyPath and policyBytes is used, matching Config: a build that
// compiled its policy in has no file to name.
func LoadPolicyForListing(policyPath string, policyBytes []byte) (*policy.Policy, error) {
	if policyBytes != nil {
		loaded, err := policy.ParseBytes(policyBytes)
		if err != nil {
			return nil, fmt.Errorf("embedded policy: %w", err)
		}
		return loaded, nil
	}
	return policy.Load(policyPath)
}

// ListScopeNames returns the scope names the Node's policy defines, in sorted
// order, without opening any scope.
//
// It is the whole of `scope list`. The names come from the policy document, which
// is the only place a scope is defined, so the answer is exactly the set the Node
// would serve rather than a second list that could drift from it.
//
// It reads the config directory and the policy source and nothing else. It does
// not dial the Server, does not load the tunnel token, and does not open a scope,
// so it works on a machine where the Node has never connected and where a scope
// directory is absent. An operator who needs the names before the first start is
// the operator this exists for.
//
// It prints names, never paths. A scope name is public: it appears in the Node's
// startup log and in the Server's connection log. A scope path is the Node's
// filesystem layout, which the design keeps off the wire and out of the Server's
// knowledge, so a listing that printed paths would disclose more than the policy
// file's owner already knows.
func ListScopeNames(lookup func(string) string) ([]security.Scope, error) {
	if lookup == nil {
		return nil, fmt.Errorf("environment lookup is nil")
	}
	// A stateless Node has no config directory, and resolving one would create it.
	// The policy source is resolved with an empty directory instead, which is the
	// same value LoadConfig passes in that mode: an embedded policy is used, or the
	// operator's absolute CONNECTOR_NODE_POLICY_FILE, and a build with neither is
	// refused with the message that names both options.
	stateless, err := resolveStateless(lookup("CONNECTOR_NODE_STATELESS"))
	if err != nil {
		return nil, err
	}
	var configDir string
	if !stateless {
		configDir, err = ResolveConfigDir(lookup)
		if err != nil {
			return nil, err
		}
	}
	policyPath, policyBytes, err := resolvePolicySource(lookup, configDir)
	if err != nil {
		return nil, err
	}
	loaded, err := LoadPolicyForListing(policyPath, policyBytes)
	if err != nil {
		return nil, err
	}
	return loaded.ScopeNames(), nil
}

// LoadAuthorityBytes builds an Authority from a policy document already in
// memory, which is how a build that compiled its policy in starts.
//
// It exists as a separate entry point rather than as a nil-path special case in
// LoadAuthority, because the two have different failure modes and a caller should
// not have to know which one it is using. LoadAuthority reports a missing file;
// this one reports a malformed document. A single function taking an empty path
// would have to guess which error the caller meant.
//
// The decoding is the same strict decoding the file path uses, because an
// embedded policy is not a more trusted policy: it was written by the same person
// and is subject to the same mistakes. A second, looser parser for the embedded
// case would be a second definition of a valid policy.
func LoadAuthorityBytes(policyBytes []byte, denyPaths []string, configDir string) (*Authority, error) {
	loaded, err := policy.ParseBytes(policyBytes)
	if err != nil {
		return nil, fmt.Errorf("embedded policy: %w", err)
	}
	return buildAuthority(loaded, denyPaths, configDir)
}

// buildAuthority opens every scope a validated policy defines.
//
// It is the shared tail of both entry points, so the scope-opening rules exist
// once. A second copy would be a second place for the fence to be configured
// differently, which is exactly the divergence the shared package exists to
// prevent.
func buildAuthority(loaded *policy.Policy, denyPaths []string, configDir string) (*Authority, error) {
	names := loaded.ScopeNames()
	scopes := make(map[security.Scope]*Scope, len(names))
	for _, name := range names {
		path, defined := loaded.ScopePath(name)
		if !defined {
			closeScopes(scopes)
			return nil, fmt.Errorf("scope %q is listed but has no path", name)
		}
		scope, err := openScope(string(name), path, denyPaths, configDir, loaded.AllowsFilesystemRoot())
		if err != nil {
			closeScopes(scopes)
			return nil, err
		}
		scopes[name] = scope
	}

	return &Authority{policy: loaded, scopes: scopes}, nil
}

// closeScopes releases every scope in a partially built set. It is called on the
// failure path of LoadAuthority, where the alternative is leaking one handle per
// scope that happened to open before the bad one.
func closeScopes(scopes map[security.Scope]*Scope) {
	for _, scope := range scopes {
		scope.Close()
	}
}

// Close releases every scope handle. It is safe to call more than once, because a
// shutdown path that runs twice must not fail on the second call.
func (a *Authority) Close() error {
	if a == nil {
		return nil
	}
	var first error
	for _, scope := range a.scopes {
		if err := scope.Close(); err != nil && first == nil {
			first = err
		}
	}
	a.scopes = nil
	return first
}

// ScopeNames returns the defined scope names in sorted order, so a startup report
// and a test are both stable.
func (a *Authority) ScopeNames() []security.Scope {
	names := make([]security.Scope, 0, len(a.scopes))
	for name := range a.scopes {
		names = append(names, name)
	}
	sort.Slice(names, func(left int, right int) bool { return names[left] < names[right] })
	return names
}

// Scope returns the open scope for a name. The second result is false when the
// policy does not define the name, so a caller cannot mistake a nil scope for a
// scope that exists.
func (a *Authority) Scope(name security.Scope) (*Scope, bool) {
	scope, ok := a.scopes[name]
	return scope, ok
}

// Allows reports whether the policy grants the permission on the scope.
//
// The answer is false when the scope is undefined, when no grant names it and
// when a grant names it without the permission. All three are refusals rather
// than errors, because a caller must not be able to tell "this scope does not
// exist" from "you may not use it": that difference is a scope-name oracle.
func (a *Authority) Allows(scope security.Scope, permission security.Permission) bool {
	return a.policy.Allows(scope, permission)
}

// Authorize is the single entry point a dispatch path uses: it checks the grant
// and returns the scope to work in, or a refusal.
//
// The two checks are deliberately ordered and independent. The grant is checked
// first, so a caller without the permission learns nothing about whether the
// scope exists or whether the path inside it exists. The fence is then applied by
// the returned scope, so a caller with the permission still cannot escape the
// directory. A refusal carries CodeDenied for every cause, because the causes are
// exactly what a caller may not probe for.
//
// A scope whose directory did not exist at startup is returned like any other.
// It has no handle, so every operation on it answers not_found; the grant is
// still checked first, so a caller without the permission gets denied and learns
// nothing about the directory. Returning it rather than refusing it here is what
// keeps the two questions separate: "may you use this scope" is answered by the
// policy, and "does this path exist" is answered by the filesystem.
func (a *Authority) Authorize(scope security.Scope, permission security.Permission) (*Scope, error) {
	if !a.policy.Allows(scope, permission) {
		return nil, newError(protocol.CodeDenied, "scope %q does not grant %q", scope, permission)
	}
	opened, ok := a.scopes[scope]
	if !ok {
		// A grant on a scope that is not in the map is unreachable through
		// LoadAuthority, which records every defined scope. It is still refused
		// rather than trusted, because a missing scope must never be read as
		// "no fence needed".
		return nil, newError(protocol.CodeDenied, "scope %q has no open handle", scope)
	}
	return opened, nil
}

// AuthorizeOperation is Authorize for a wire operation: it maps the operation to
// the permission it consumes and refuses an operation this version does not
// implement.
//
// An unknown name and a declared-but-disabled name get the same code,
// CodeUnsupportedOperation, on purpose. If an unknown name answered
// invalid_argument while `file.write` answered unsupported_operation, a caller
// could enumerate the vocabulary by comparing the two codes, which is the same
// oracle the scope check refuses to provide. Both answers are also true: this
// binary implements neither.
//
// The version gate runs before the grant check, so a caller asking for
// `file.write` learns that the operation is unimplemented rather than whether a
// write grant exists. That ordering is stated so a later change does not reverse
// it by accident.
func (a *Authority) AuthorizeOperation(operation protocol.Operation, scope security.Scope) (*Scope, error) {
	permission, known := operation.Permission()
	if !known || !operation.Enabled() {
		return nil, newError(protocol.CodeUnsupportedOperation, "operation %q is not implemented in this version", operation)
	}
	return a.Authorize(scope, permission)
}
