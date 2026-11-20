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
	"time"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// Policy identifiers for the frame-level read queries that have no protocol
// operation constant. They are policy names only and never appear on the wire,
// because these queries travel as their own frame type rather than as an
// immutable intent. A stable name is still required, because a policy file has
// to be able to grant or refuse them.
const (
	OperationLaunchQuery  = protocol.OperationLaunchQuery
	OperationHistoryRead  = protocol.OperationHistoryRead
	OperationMessagesRead = protocol.OperationMessagesRead
	OperationMetricsRead  = protocol.OperationMetricsRead
	OperationDetailRead   = protocol.OperationDetailRead
)

// Directives accepted in one access policy file.
const (
	accessPolicyTokenDirective     = "token"
	accessPolicyTokenHashDirective = "token-sha256"
	// accessPolicyKeyIDDirective names the public key identifier a signed
	// credential is addressed by.
	//
	// It is a separate directive rather than a field derived from the token value
	// because the two answer different questions. The token value is the secret a
	// bearer caller presents; the key identifier is the public name a signing
	// caller puts on the wire. A rule may legitimately need both, and deriving one
	// from the other would make the policy file's meaning depend on the shape of a
	// secret.
	accessPolicyKeyIDDirective       = "key-id"
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

// maxAccessKeyIDBytes bounds a key identifier declared in a policy file. It
// matches the bound the credential parser enforces, so a file cannot declare an
// identifier that no credential could ever present.
const maxAccessKeyIDBytes = 128

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
		protocol.OperationProjectList,
		OperationLaunchQuery,
		OperationHistoryRead,
		OperationMessagesRead,
		OperationMetricsRead,
		OperationDetailRead,
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
	//
	// A digest can only be compared against a presented secret, so a rule that
	// declares a digest is usable in bearer mode only. HMAC verification needs the
	// secret itself, because a digest cannot produce a signature; using the digest
	// as the HMAC key would make the digest an equivalent credential and defeat the
	// reason for storing a digest at all.
	TokenSHA256 string
	// KeyID is the public key identifier a signed credential is addressed by,
	// empty when the file declares no key-id directive.
	//
	// It is public: it travels on the wire and may be logged. It is the identity
	// the policy is evaluated against in HMAC mode, so a leaked policy file
	// reveals which identifiers exist without revealing a usable secret.
	KeyID string
	// Secret is the HMAC secret used to verify a signed credential, empty when the
	// rule cannot verify one.
	//
	// It is populated only when the file declares both key-id and a token in
	// key_id.secret form, because those are the two facts verification needs: the
	// identifier to look the rule up and the secret to check the signature.
	Secret string
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
	// A rule that names a key identifier is identified by it, because that is the
	// name a signed caller presents and therefore the name two files would
	// collide on. Falling through to the token digest would let two files declare
	// the same key identifier with different secrets and load without a conflict,
	// and the effective policy would then depend on directory read order.
	if r.KeyID != "" {
		return "key-id:" + r.KeyID
	}
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
	if r.KeyID != "" {
		parts = append(parts, "key-id="+r.KeyID)
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
	// byKeyID indexes the rules a signed credential can be verified against. It
	// is separate from byToken because the two are addressed by different names:
	// a bearer caller presents a secret, while a signing caller presents a public
	// key identifier. One map could not serve both without letting a caller
	// present a key identifier as if it were a secret.
	byKeyID map[string]AccessRule
	// nonces remembers the nonces already accepted, so a correctly signed request
	// cannot be replayed inside the signature window. It lives on the policy rather
	// than on each verifier because a verifier is rebuilt whenever the declared
	// secrets change, and a rebuilt verifier with a fresh cache would accept every
	// previously seen nonce again.
	nonces *security.NonceCache
}

// NewPermissiveAccessPolicy returns a policy that permits every caller. It is
// the state of an Endpoint that was not pointed at a policy directory.
func NewPermissiveAccessPolicy() *AccessPolicy {
	return &AccessPolicy{byToken: map[string]AccessRule{}, byHash: map[string]AccessRule{}, byKeyID: map[string]AccessRule{}}
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
		if rule.KeyID != "" {
			policy.byKeyID[rule.KeyID] = rule
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
	return len(p.byToken) + len(p.byHash) + len(p.byKeyID)
}

// Rules returns the rules in force, ordered by source file, for logging.
func (p *AccessPolicy) Rules() []AccessRule {
	if p == nil {
		return nil
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	rules := make([]AccessRule, 0, len(p.byToken)+len(p.byHash)+len(p.byKeyID))
	for _, rule := range p.byToken {
		rules = append(rules, rule)
	}
	for _, rule := range p.byHash {
		rules = append(rules, rule)
	}
	for _, rule := range p.byKeyID {
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
	p.byKeyID = next.byKeyID
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

// PermitKeyID decides whether a caller that proved one key identifier may
// exercise one operation on this Endpoint.
//
// It is separate from Permit because the two are addressed by different names. A
// bearer caller presents a secret and is matched against the token indexes; a
// signing caller presents a public key identifier and is matched against the
// key-id index. Merging them would let a caller present a key identifier where a
// secret is expected, and the lookup would then succeed for a value that was never
// secret.
//
// The caller must have verified the signature before calling this, because this
// function decides authority and never authenticity. Keeping the two apart is what
// makes the ordering testable: a test can call PermitKeyID directly to prove the
// grant table works, and a separate test proves the transport never reaches it
// without a valid signature.
func (p *AccessPolicy) PermitKeyID(endpointID, keyID, operation string) error {
	if p == nil {
		return nil
	}
	p.mu.RLock()
	defer p.mu.RUnlock()
	if !p.configured {
		return nil
	}
	if keyID == "" {
		return fmt.Errorf("operation %q requires a signed endpoint credential", operation)
	}
	rule, ok := p.byKeyID[keyID]
	if !ok {
		return fmt.Errorf("operation %q is not permitted: the presented key identifier is not configured on this endpoint", operation)
	}
	return rule.permit(endpointID, operation)
}

// PermitCredential decides whether one already-verified credential may exercise
// one operation.
//
// It takes both identities because the mode decides which one is meaningful, and
// it dispatches on which one is present rather than on a mode argument. That keeps
// the decision in one place: a caller that verified a signature passes the key
// identifier, a caller that verified a bearer token passes the token, and neither
// caller has to repeat the mode rules the verifier already applied.
//
// Exactly one identity is expected. Both being empty is refused by the branch that
// runs, because an empty identity matches no rule; both being set is a programming
// error in the caller, and it is refused rather than resolved by precedence,
// because a precedence rule would silently ignore one of two credentials.
func (p *AccessPolicy) PermitCredential(endpointID, keyID, token, operation string) error {
	if keyID != "" && token != "" {
		return fmt.Errorf("operation %q was presented with both a key identifier and a token", operation)
	}
	if keyID != "" {
		return p.PermitKeyID(endpointID, keyID, operation)
	}
	return p.Permit(endpointID, token, operation)
}

// Verifier returns a verifier holding every secret this policy can check a
// signature against.
//
// It is rebuilt from the rules in force rather than kept beside them, so a reload
// cannot leave a verifier that still accepts a secret the policy no longer
// declares. A rule with no secret is absent from the result, which means a
// key-id-only rule can be granted authority but can never verify a signature; that
// combination is rejected at load time instead of being silently unusable.
func (p *AccessPolicy) Verifier(window time.Duration) *security.Verifier {
	// The nonce cache is owned by the policy rather than by each verifier, so a
	// reload that rebuilds the token set keeps the replay state. A fresh cache per
	// verifier would accept every previously seen nonce again, which would turn a
	// reload into a replay window.
	p.mu.Lock()
	if p.nonces == nil {
		p.nonces = security.NewNonceCache(0, window)
	}
	nonces := p.nonces
	p.mu.Unlock()
	tokens := make(map[string]security.Token)
	if p != nil {
		p.mu.RLock()
		for keyID, rule := range p.byKeyID {
			if rule.Secret == "" {
				continue
			}
			tokens[keyID] = security.Token{KeyID: keyID, Secret: rule.Secret}
		}
		p.mu.RUnlock()
	}
	verifier := security.NewVerifier(tokens, window)
	verifier.Nonces = nonces
	return verifier
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
		case accessPolicyKeyIDDirective:
			if seen[directive] {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q may appear at most once", source, lineNumber, directive)
			}
			seen[directive] = true
			if len(values) != 1 {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q requires exactly one value", source, lineNumber, directive)
			}
			keyID := values[0]
			if len(keyID) > maxAccessKeyIDBytes {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q is longer than %d bytes", source, lineNumber, directive, maxAccessKeyIDBytes)
			}
			if strings.ContainsAny(keyID, " \t\r\n,") {
				return AccessRule{}, nil, fmt.Errorf("%s line %d: %q must not contain whitespace or a comma", source, lineNumber, directive)
			}
			rule.KeyID = keyID
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
	// A key identifier is only useful if a signature can be checked against it, so
	// the secret is resolved here rather than at verification time. Resolving it at
	// verification time would make a misconfigured file look like a caller with a
	// wrong secret, and the operator would rotate a credential that was never the
	// problem.
	if rule.KeyID != "" {
		if rule.TokenSHA256 != "" {
			return AccessRule{}, nil, fmt.Errorf("%s: %q cannot be combined with %q, because a digest cannot verify a signature; declare the secret with %q instead", source, accessPolicyKeyIDDirective, accessPolicyTokenHashDirective, accessPolicyTokenDirective)
		}
		parsed, parseErr := security.ParseToken(rule.Token)
		if parseErr != nil {
			return AccessRule{}, nil, fmt.Errorf("%s: %q requires a %q value in key_id.secret form: %w", source, accessPolicyKeyIDDirective, accessPolicyTokenDirective, parseErr)
		}
		if parsed.KeyID != rule.KeyID {
			return AccessRule{}, nil, fmt.Errorf("%s: %q %q does not match the key identifier in the %q value %q", source, accessPolicyKeyIDDirective, rule.KeyID, accessPolicyTokenDirective, parsed.KeyID)
		}
		rule.Secret = parsed.Secret
	} else if rule.Token != "" {
		// A token in key_id.secret form names its own key identifier, so the
		// identifier is derived from the value rather than required twice. This is
		// the documented default: an operator who rotates a token to the pair form
		// does not also have to add a directive that repeats the prefix.
		//
		// A token with no dot yields no identifier, so the rule stays bearer-only.
		// That is the fail-closed direction: a deployment that has not rotated its
		// tokens yet keeps working in bearer mode and is refused in HMAC mode,
		// instead of being accepted with an identifier nobody declared.
		if parsed, parseErr := security.ParseToken(rule.Token); parseErr == nil {
			rule.KeyID = parsed.KeyID
			rule.Secret = parsed.Secret
		}
	}
	if rule.AllowAll && rule.DenyAll {
		return AccessRule{}, nil, fmt.Errorf("%s: %q and %q may not be combined", source, accessPolicyAllowAllDirective, accessPolicyDenyAllDirective)
	}
	if (rule.AllowAll || rule.DenyAll) && (len(rule.Endpoints) > 0 || len(rule.Scopes) > 0 || len(rule.Permissions) > 0) {
		return AccessRule{}, nil, fmt.Errorf("%s: %q and %q may not be combined with declarations, because the effective policy would depend on line order", source, accessPolicyAllowAllDirective, accessPolicyDenyAllDirective)
	}
	// The warnings travel inside the rule as well as in the second return value,
	// because the rule is what survives into the policy in force. A caller that
	// only keeps the rule would otherwise lose every warning, which is exactly how
	// the documented "accept but warn" contract became "accept" only.
	rule.Warnings = warnings
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
	protocol.OperationProjectList:        {},
	protocol.OperationAgentModelSelect:   {},
	protocol.OperationOutputRead:         {},
	protocol.OperationOutputFollow:       {},
	protocol.OperationCommandExec:        {},
	OperationLaunchQuery:                 {},
	OperationHistoryRead:                 {},
	OperationMessagesRead:                {},
	OperationMetricsRead:                 {},
	OperationDetailRead:                  {},
}

// KnownAccessOperations returns the closed set of operations this build serves,
// sorted so a caller can compare it deterministically.
//
// It exists for the BDD coverage guard, which must compare the production
// vocabulary against the feature matrix. The alternative, a hand-copied list in
// the test, would drift silently the moment an operation is added here, and that
// silent drift is the exact defect the guard exists to catch. The returned slice
// is a copy, so a caller cannot mutate the closed set, and nothing else about the
// set is exposed.
func KnownAccessOperations() []string {
	names := make([]string, 0, len(knownAccessOperations))
	for name := range knownAccessOperations {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// ScopeOperations returns the operations each scope covers, with every operation
// list copied so a caller cannot mutate the mapping.
//
// It exists for the same reason as KnownAccessOperations: the coverage guard has
// to prove that every operation in the closed set is reachable through at least
// one scope, and a hand-copied scope table would drift from this one.
func ScopeOperations() map[string][]string {
	scopes := make(map[string][]string, len(scopeOperations))
	for scope, operations := range scopeOperations {
		scopes[scope] = append([]string(nil), operations...)
	}
	return scopes
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
