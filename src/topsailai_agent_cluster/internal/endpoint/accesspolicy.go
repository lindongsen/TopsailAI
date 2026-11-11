package endpoint

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"sort"
	"strings"
	"sync"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// Policy identifiers for the three frame-level read queries that have no
// protocol operation constant. They are policy names only and never appear on
// the wire, because these queries travel as their own frame type rather than as
// an immutable intent. A stable name is still required, because a policy file
// has to be able to grant or refuse them.
const (
	OperationLaunchQuery  = "launch.query"
	OperationHistoryRead  = "history.read"
	OperationMessagesRead = "messages.read"
)

// Directives accepted in one access policy file.
const (
	accessPolicyTokenDirective       = "token"
	accessPolicyTokenHashDirective   = "token-sha256"
	accessPolicyEndpointsDirective   = "endpoints"
	accessPolicyScopesDirective      = "scopes"
	accessPolicyPermissionsDirective = "permissions"
	accessPolicyAllowAllDirective    = "allow-all"
	accessPolicyDenyAllDirective     = "deny-all"
)

// accessPolicyFileSuffix selects which files in the policy directory are policy
// files. Only this suffix is read, so an operator can keep examples, backups and
// editor scratch files beside the live policy without them taking effect. The
// loader reports every skipped file, so the rule is visible rather than silent.
const accessPolicyFileSuffix = ".conf"

// accessPolicyWildcard matches every operation or every scope, depending on the
// declaration it appears in.
const accessPolicyWildcard = "*"

// scopeOperations maps one operator scope onto the operations it covers. The
// scope vocabulary is the one the Server already defines, so an operator does
// not learn a second vocabulary; only the meaning changes, because on the
// Endpoint a scope describes what this machine serves rather than what an
// operator may submit.
//
// security.ScopeEndpointAdmin is deliberately absent: it is reserved, so it
// covers no operation. Keeping the name in the vocabulary means a policy file
// that already names it still loads.
var scopeOperations = map[string][]string{
	security.ScopeView: {
		protocol.OperationAgentModelList,
		OperationLaunchQuery,
		OperationHistoryRead,
		OperationMessagesRead,
	},
	security.ScopeReadOutput: {
		protocol.OperationOutputRead,
		protocol.OperationOutputFollow,
	},
	security.ScopeSendMessage: {
		protocol.OperationMessageSend,
		protocol.OperationContextInject,
	},
	security.ScopeControl: {
		protocol.OperationExecutionInterrupt,
		protocol.OperationAgentStart,
		protocol.OperationAgentResume,
		protocol.OperationAgentStop,
		protocol.OperationAgentDriveStart,
		protocol.OperationAgentDriveStop,
		protocol.OperationWorkspaceClean,
		protocol.OperationAgentModelSelect,
		protocol.OperationCommandExec,
	},
}

// AccessRule is one token's effective grants, parsed from one policy file.
//
// Scopes and Permissions are both grants and combine by union: a token may
// exercise every operation its scopes cover and every operation its permissions
// name. Neither narrows the other, so adding a line can only add authority.
// Endpoints is the one declaration that narrows, because it restricts where the
// token is honoured.
type AccessRule struct {
	// Token is the plain-text secret, empty when the file declares a hash instead.
	Token string
	// TokenSHA256 is the lower-case hex digest of the secret, empty when the file
	// declares the secret itself.
	TokenSHA256 string
	// Endpoints names the Endpoints that honour this token. Empty means every
	// Endpoint that holds the file.
	Endpoints []string
	// Scopes names the capability classes granted.
	Scopes []string
	// Permissions names individual operations granted.
	Permissions []string
	// AllowAll grants every operation on every Endpoint for this token.
	AllowAll bool
	// DenyAll refuses every operation for this token.
	DenyAll bool
	// Source is the file the rule was read from, used in logs and errors.
	Source string
	// Warnings records load-time findings that did not fail the load, such as a
	// permission naming an operation this build does not serve.
	Warnings []string
}

// identity returns a value that is equal for two files declaring the same token,
// whether they declare the secret or its digest. It is used to reject a
// duplicate token, because the effective policy would otherwise depend on
// directory read order.
func (r AccessRule) identity() string {
	if r.TokenSHA256 != "" {
		return r.TokenSHA256
	}
	return hashAccessToken(r.Token)
}

// Summary describes the rule for a log line without revealing the secret.
func (r AccessRule) Summary() string {
	parts := make([]string, 0, 4)
	if r.AllowAll {
		parts = append(parts, "allow-all")
	}
	if r.DenyAll {
		parts = append(parts, "deny-all")
	}
	if len(r.Endpoints) > 0 {
		parts = append(parts, "endpoints="+strings.Join(r.Endpoints, ","))
	}
	if len(r.Scopes) > 0 {
		parts = append(parts, "scopes="+strings.Join(r.Scopes, ","))
	}
	if len(r.Permissions) > 0 {
		parts = append(parts, "permissions="+strings.Join(r.Permissions, ","))
	}
	if len(parts) == 0 {
		return "no grants"
	}
	return strings.Join(parts, " ")
}

// AccessPolicy is the Endpoint-local access policy.
//
// Three states are possible, and the difference matters:
//
//   - Not configured, or configured with no policy file: every caller may
//     exercise every operation. This is the upgrade-safe default, because an
//     Endpoint that refused every caller by default would break every existing
//     deployment the moment the feature shipped.
//   - Configured with at least one policy file: only the listed tokens, and only
//     the operations they grant. A token with no matching file is refused rather
//     than allowed, because otherwise adding one file would leave every other
//     caller at full authority.
//   - A file declaring deny-all: that one token is refused every operation while
//     every other token keeps its own grants.
//
// The policy is safe for concurrent use and can be replaced atomically, which is
// what makes reload possible without restarting the Endpoint.
type AccessPolicy struct {
	mu         sync.RWMutex
	configured bool
	byToken    map[string]AccessRule
	byHash     map[string]AccessRule
}

// NewPermissiveAccessPolicy returns a policy that permits every caller. It is
// the state of an Endpoint that was not pointed at a policy directory.
func NewPermissiveAccessPolicy() *AccessPolicy {
	return &AccessPolicy{byToken: map[string]AccessRule{}, byHash: map[string]AccessRule{}}
}

// NewAccessPolicy builds a policy from already validated rules. An empty rule
// list yields a permissive policy, so an empty directory changes nothing.
func NewAccessPolicy(rules []AccessRule) *AccessPolicy {
	policy := NewPermissiveAccessPolicy()
	policy.configured = len(rules) > 0
	for _, rule := range rules {
		if rule.Token != "" {
			policy.byToken[rule.Token] = rule
		}
		if rule.TokenSHA256 != "" {
			policy.byHash[rule.TokenSHA256] = rule
		}
	}
	return policy
}

// Configured reports whether any policy file is in force. A false value means
// every caller is permitted.
func (p *AccessPolicy) Configured() bool {
	if p == nil {
		return false
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.configured
}

// Len reports the number of tokens currently in force.
func (p *AccessPolicy) Len() int {
	if p == nil {
		return 0
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	return len(p.byToken) + len(p.byHash)
}

// Rules returns the rules in force, ordered by source file, for logging.
func (p *AccessPolicy) Rules() []AccessRule {
	if p == nil {
		return nil
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	rules := make([]AccessRule, 0, len(p.byToken)+len(p.byHash))
	for _, rule := range p.byToken {
		rules = append(rules, rule)
	}
	for _, rule := range p.byHash {
		rules = append(rules, rule)
	}
	sort.Slice(rules, func(i, j int) bool { return rules[i].Source < rules[j].Source })
	return rules
}

// Warnings returns every load-time warning in force, ordered by source file.
func (p *AccessPolicy) Warnings() []string {
	warnings := make([]string, 0)
	for _, rule := range p.Rules() {
		warnings = append(warnings, rule.Warnings...)
	}
	return warnings
}

// replace swaps the rules atomically. The new rule set is parsed completely
// before the swap, so a parse failure keeps the previous policy in force and
// never leaves a partially applied policy behind.
func (p *AccessPolicy) replace(next *AccessPolicy) {
	p.mu.Lock()
	p.configured = next.configured
	p.byToken = next.byToken
	p.byHash = next.byHash
	p.mu.Unlock()
}

// Permit decides whether a caller may exercise one operation on this Endpoint.
//
// The token is the only dimension that can identify a caller, because it is the
// only thing the Endpoint can verify: the caller presents it, the Endpoint holds
// it, and nothing else about the caller is provable. A missing token is refused
// rather than treated as anonymous, because a missing credential must never be
// weaker than a wrong one.
//
// The returned error names the refused operation, so the caller can report the
// shared policy_denied code with a message that says which operation was
// refused. Naming it costs nothing: the caller asked for that operation and
// learns nothing it did not already know.
func (p *AccessPolicy) Permit(endpointID, token, operation string) error {
	if p == nil {
		return nil
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	if !p.configured {
		return nil
	}
	if token == "" {
		return fmt.Errorf("operation %q requires an endpoint token", operation)
	}
	rule, ok := p.byToken[token]
	if !ok {
		rule, ok = p.byHash[hashAccessToken(token)]
	}
	if !ok {
		return fmt.Errorf("operation %q is not permitted: the presented token is not configured on this endpoint", operation)
	}
	return rule.permit(endpointID, operation)
}

// permit applies one rule to one operation.
func (r AccessRule) permit(endpointID, operation string) error {
	if r.DenyAll {
		return fmt.Errorf("operation %q is not permitted: this token is denied every operation", operation)
	}
	if r.AllowAll {
		return nil
	}
	if len(r.Endpoints) > 0 && !containsAccessValue(r.Endpoints, endpointID) {
		return fmt.Errorf("operation %q is not permitted: this token is not honoured by endpoint %q", operation, endpointID)
	}
	for _, permission := range r.Permissions {
		if matchAccessOperation(permission, operation) {
			return nil
		}
	}
	for _, scope := range r.Scopes {
		if scopeCoversOperation(scope, operation) {
			return nil
		}
	}
	return fmt.Errorf("operation %q is not permitted: this token grants neither the operation nor a scope covering it", operation)
}

// matchAccessOperation reports whether one permission pattern matches an
// operation. A bare wildcard matches everything, a trailing ".*" is a prefix
// match, and anything else is an exact name. There is no other wildcard form,
// because a general glob would make the effective policy hard to read.
func matchAccessOperation(pattern, operation string) bool {
	if pattern == accessPolicyWildcard {
		return true
	}
	if strings.HasSuffix(pattern, ".*") {
		return strings.HasPrefix(operation, strings.TrimSuffix(pattern, "*"))
	}
	return pattern == operation
}

// scopeCoversOperation reports whether one scope covers an operation.
func scopeCoversOperation(scope, operation string) bool {
	if scope == accessPolicyWildcard {
		return true
	}
	// The provider control family is one scope, not one operation per action,
	// because the action inventory is Endpoint-local configuration and may name
	// an action this build does not know.
	if scope == security.ScopeControl && strings.HasPrefix(operation, security.ProviderControlPrefix) {
		return true
	}
	return containsAccessValue(scopeOperations[scope], operation)
}

// ParseAccessRule parses one policy file.
//
// The second result carries load-time warnings that did not fail the load. A
// permission naming an operation this build does not serve is accepted with a
// warning, because one file set has to serve a version-skewed fleet and writing
// a policy before the operation ships is a normal deployment order. The warning
// is not optional: this acceptance is the only place in the design where a
// mistake can be silent, so a misspelled operation name would otherwise never
// take effect and never be reported.
func ParseAccessRule(data []byte, source string) (AccessRule, []string, error) {
	rule := AccessRule{Source: source}
	warnings := make([]string, 0)
	seen := make(map[string]bool, 3)
	scanner := bufio.NewScanner(bytes.NewReader(data))
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	lineNumber := 0
	for scanner.Scan() {
		lineNumber++
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if containsAccessControlCharacter(line) {
			return AccessRule{}, nil, fmt.Errorf("%s line %d: line contains a control character", source, lineNumber)
		}
		fields := strings.Fields(line)
		directive, values := fields[0], fields[1:]
		switch directive {
		case accessPolicyTokenDirective, accessPolicyTokenHashDirective:
			if rule.Token != "" || rule.TokenSHA256 != "" {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: a token is already declared", source, lineNumber)
			}
			if len(values) != 1 {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q requires exactly one value", source, lineNumber, directive)
			}
			if len(rule.Endpoints) > 0 || len(rule.Scopes) > 0 || len(rule.Permissions) > 0 || rule.AllowAll || rule.DenyAll {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: the token must be declared before any other declaration", source, lineNumber)
			}
			if directive == accessPolicyTokenDirective {
				rule.Token = values[0]
				break
			}
			digest := strings.ToLower(values[0])
			if len(digest) != 64 {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q requires a 64-character hex digest", source, lineNumber, directive)
			}
			if _, err := hex.DecodeString(digest); err != nil {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q requires a hex digest: %w", source, lineNumber, directive, err)
			}
			rule.TokenSHA256 = digest
		case accessPolicyEndpointsDirective:
			if seen[directive] {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q may appear at most once", source, lineNumber, directive)
			}
			seen[directive] = true
			if len(values) == 0 {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q requires at least one value", source, lineNumber, directive)
			}
			rule.Endpoints = values
		case accessPolicyScopesDirective:
			if seen[directive] {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q may appear at most once", source, lineNumber, directive)
			}
			seen[directive] = true
			if len(values) == 0 {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q requires at least one value", source, lineNumber, directive)
			}
			for _, scope := range values {
				if scope != accessPolicyWildcard && !security.KnownScope(scope) {
					return AccessRule{}, nil, fmt.Errorf("%s line %d: unknown scope %q", source, lineNumber, scope)
				}
			}
			rule.Scopes = values
		case accessPolicyPermissionsDirective:
			if seen[directive] {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q may appear at most once", source, lineNumber, directive)
			}
			seen[directive] = true
			if len(values) == 0 {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q requires at least one value", source, lineNumber, directive)
			}
			for _, permission := range values {
				if !knownAccessOperation(permission) {
					warnings = append(warnings, fmt.Sprintf("%s line %d: permission %q names an operation this endpoint does not serve; it is accepted so one file set serves a version-skewed fleet, but it grants nothing here", source, lineNumber, permission))
				}
			}
			rule.Permissions = values
		case accessPolicyAllowAllDirective:
			if len(values) != 0 {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q takes no value", source, lineNumber, directive)
			}
			rule.AllowAll = true
		case accessPolicyDenyAllDirective:
			if len(values) != 0 {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q takes no value", source, lineNumber, directive)
			}
			rule.DenyAll = true
		default:
			return AccessRule{}, nil, fmt.Errorf("%s line %d: unknown directive %q", source, lineNumber, directive)
		}
	}
	if err := scanner.Err(); err != nil {
		return AccessRule{}, nil, fmt.Errorf("read access policy file %q: %w", source, err)
	}
	if rule.Token == "" && rule.TokenSHA256 == "" {
		return AccessRule{}, nil, fmt.Errorf("%s: a %q or %q line is required", source, accessPolicyTokenDirective, accessPolicyTokenHashDirective)
	}
	if rule.AllowAll && rule.DenyAll {
		return AccessRule{}, nil, fmt.Errorf("%s: %q and %q may not be combined", source, accessPolicyAllowAllDirective, accessPolicyDenyAllDirective)
	}
	if (rule.AllowAll || rule.DenyAll) && (len(rule.Endpoints) > 0 || len(rule.Scopes) > 0 || len(rule.Permissions) > 0) {
		return AccessRule{}, nil, fmt.Errorf("%s: %q and %q may not be combined with declarations, because the effective policy would depend on line order", source, accessPolicyAllowAllDirective, accessPolicyDenyAllDirective)
	}
	return rule, warnings, nil
}

// knownAccessOperation reports whether a permission names something this build
// can serve. A bare wildcard and the provider control family are accepted as
// patterns, because the action inventory is Endpoint-local configuration and may
// legitimately name an action this build does not know.
func knownAccessOperation(name string) bool {
	if name == accessPolicyWildcard {
		return true
	}
	if strings.HasPrefix(name, security.ProviderControlPrefix) {
		return true
	}
	_, ok := knownAccessOperations[name]
	return ok
}

// knownAccessOperations is the closed set of operations this build serves. It
// exists so a permission naming an operation outside the vocabulary is reported
// at load time instead of silently granting nothing.
var knownAccessOperations = map[string]struct{}{
	protocol.OperationMessageSend:        {},
	protocol.OperationContextInject:      {},
	protocol.OperationExecutionInterrupt: {},
	protocol.OperationAgentStart:         {},
	protocol.OperationAgentResume:        {},
	protocol.OperationAgentStop:          {},
	protocol.OperationAgentDriveStart:    {},
	protocol.OperationAgentDriveStop:     {},
	protocol.OperationWorkspaceClean:     {},
	protocol.OperationAgentModelList:     {},
	protocol.OperationAgentModelSelect:   {},
	protocol.OperationOutputRead:         {},
	protocol.OperationOutputFollow:       {},
	protocol.OperationCommandExec:        {},
	OperationLaunchQuery:                 {},
	OperationHistoryRead:                 {},
	OperationMessagesRead:                {},
}

// hashAccessToken returns the lower-case hex SHA-256 of a token, so a file can
// declare the digest instead of the secret.
func hashAccessToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// containsAccessValue reports whether a slice contains a value.
func containsAccessValue(values []string, target string) bool {
	for _, value := range values {
		if value == target {
			return true
		}
	}
	return false
}

// containsAccessControlCharacter reports whether a line contains a control
// character. A tab is allowed because it separates fields; every other control
// character is rejected, because it would make the parsed value differ from what
// a reader sees.
func containsAccessControlCharacter(line string) bool {
	for _, r := range line {
		if r < 0x20 && r != '\t' {
			return true
		}
	}
	return false
}
