package endpoint

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// readOperations is every operation that reads detail rather than listing
// resources. The policy must be able to refuse each one, so the tests below
// enumerate the whole set instead of sampling it: a single unguarded operation
// would leak detail while the policy looked correct.
var readOperations = []string{
	protocol.OperationOutputRead,
	protocol.OperationOutputFollow,
	protocol.OperationAgentModelList,
	OperationLaunchQuery,
	OperationHistoryRead,
	OperationMessagesRead,
}

func TestAccessPolicyPermissiveWhenNotConfigured(t *testing.T) {
	policy := NewPermissiveAccessPolicy()
	if policy.Configured() {
		t.Fatalf("a policy that was never configured must not report itself as configured")
	}
	for _, operation := range readOperations {
		if err := policy.Permit("any-endpoint", "", operation); err != nil {
			t.Fatalf("unconfigured policy must permit %q without a token: %v", operation, err)
		}
	}
}

func TestAccessPolicyPermissiveWhenDirectoryMissing(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("a missing directory must be the permissive state, not an error: %v", err)
	}
	if loaded.Policy.Configured() {
		t.Fatalf("a missing directory must not restrict callers")
	}
	if err := loaded.Policy.Permit("e1", "", protocol.OperationOutputRead); err != nil {
		t.Fatalf("missing directory must permit every operation: %v", err)
	}
}

func TestAccessPolicyPermissiveWhenDirectoryEmpty(t *testing.T) {
	dir := t.TempDir()
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("an empty directory must load: %v", err)
	}
	if loaded.Policy.Configured() {
		t.Fatalf("an empty directory must not restrict callers, so creating the directory is not a policy change")
	}
}

func TestAccessPolicyIgnoresFilesWithoutPolicySuffix(t *testing.T) {
	dir := t.TempDir()
	// A backup and an example beside the live policy must not take effect, and
	// must not fail the load either.
	if err := os.WriteFile(filepath.Join(dir, "admin.conf.bak"), []byte("token leaked\nallow-all\n"), 0o600); err != nil {
		t.Fatalf("write backup: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "README.md"), []byte("token example\nallow-all\n"), 0o600); err != nil {
		t.Fatalf("write readme: %v", err)
	}
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("non-policy files must be skipped, not parsed: %v", err)
	}
	if loaded.Policy.Configured() {
		t.Fatalf("non-policy files must not configure the policy")
	}
}

func TestAccessPolicyRefusesUnlistedTokenOnceConfigured(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "admin.conf", "token admin-secret\nallow-all\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if !loaded.Policy.Configured() {
		t.Fatalf("a directory with one policy file must restrict callers")
	}
	if err := loaded.Policy.Permit("e1", "admin-secret", protocol.OperationOutputRead); err != nil {
		t.Fatalf("the configured token must be permitted: %v", err)
	}
	// An unlisted token is refused rather than allowed, because otherwise adding
	// one file would leave every other caller at full authority.
	if err := loaded.Policy.Permit("e1", "other-secret", protocol.OperationOutputRead); err == nil {
		t.Fatalf("an unlisted token must be refused once a policy file exists")
	}
	if err := loaded.Policy.Permit("e1", "", protocol.OperationOutputRead); err == nil {
		t.Fatalf("a missing token must be refused once a policy file exists")
	}
}

func TestAccessPolicyRefusesEveryReadOperationWithoutGrant(t *testing.T) {
	dir := t.TempDir()
	// This token grants only a mutating operation, so every read operation must
	// be refused. Enumerating the whole set catches an operation that the
	// enforcement points forgot to guard.
	writePolicyFile(t, dir, "sender.conf", "token sender-secret\npermissions message.send\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	for _, operation := range readOperations {
		if err := loaded.Policy.Permit("e1", "sender-secret", operation); err == nil {
			t.Fatalf("operation %q must be refused when the token grants only message.send", operation)
		}
	}
	if err := loaded.Policy.Permit("e1", "sender-secret", protocol.OperationMessageSend); err != nil {
		t.Fatalf("the granted operation must be permitted: %v", err)
	}
}

func TestAccessPolicyScopeGrantsCoveredOperations(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "reader.conf", "token reader-secret\nscopes read_output\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	for _, operation := range []string{protocol.OperationOutputRead, protocol.OperationOutputFollow} {
		if err := loaded.Policy.Permit("e1", "reader-secret", operation); err != nil {
			t.Fatalf("scope read_output must cover %q: %v", operation, err)
		}
	}
	for _, operation := range []string{OperationHistoryRead, OperationMessagesRead, protocol.OperationMessageSend} {
		if err := loaded.Policy.Permit("e1", "reader-secret", operation); err == nil {
			t.Fatalf("scope read_output must not cover %q", operation)
		}
	}
}

func TestAccessPolicyScopesAndPermissionsCombineByUnion(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "mixed.conf", "token mixed-secret\nscopes read_output\npermissions history.read\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	// Neither declaration narrows the other: both grants are in force.
	for _, operation := range []string{protocol.OperationOutputRead, OperationHistoryRead} {
		if err := loaded.Policy.Permit("e1", "mixed-secret", operation); err != nil {
			t.Fatalf("scopes and permissions must combine by union, so %q must be permitted: %v", operation, err)
		}
	}
}

func TestAccessPolicyControlScopeCoversProviderControlFamily(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "ctl.conf", "token ctl-secret\nscopes control\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	// The action inventory is Endpoint-local configuration, so the scope has to
	// cover an action this build has never heard of.
	if err := loaded.Policy.Permit("e1", "ctl-secret", security.ProviderControlPrefix+"anything"); err != nil {
		t.Fatalf("scope control must cover the whole ctl. family: %v", err)
	}
	if err := loaded.Policy.Permit("e1", "ctl-secret", protocol.OperationOutputRead); err == nil {
		t.Fatalf("scope control must not cover a read operation")
	}
}

func TestAccessPolicyEndpointsDeclarationNarrows(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "site.conf", "token site-secret\nendpoints gd-dev\npermissions output.read\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if err := loaded.Policy.Permit("gd-dev", "site-secret", protocol.OperationOutputRead); err != nil {
		t.Fatalf("the declared endpoint must be permitted: %v", err)
	}
	// The endpoints declaration is the only narrowing declaration, so a token
	// scoped to one machine must be refused on another.
	if err := loaded.Policy.Permit("other-host", "site-secret", protocol.OperationOutputRead); err == nil {
		t.Fatalf("a token declared for gd-dev must be refused on another endpoint")
	}
}

func TestAccessPolicyDenyAllRefusesOnlyThatToken(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "revoked.conf", "token revoked-secret\ndeny-all\n")
	writePolicyFile(t, dir, "admin.conf", "token admin-secret\nallow-all\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	for _, operation := range readOperations {
		if err := loaded.Policy.Permit("e1", "revoked-secret", operation); err == nil {
			t.Fatalf("deny-all must refuse %q", operation)
		}
	}
	// A revoked token must not revoke anyone else.
	if err := loaded.Policy.Permit("e1", "admin-secret", protocol.OperationOutputRead); err != nil {
		t.Fatalf("deny-all on one token must not affect another token: %v", err)
	}
}

func TestAccessPolicyTokenHashMatchesPlainToken(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "hashed.conf", "token-sha256 "+hashAccessToken("hashed-secret")+"\nallow-all\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if err := loaded.Policy.Permit("e1", "hashed-secret", protocol.OperationOutputRead); err != nil {
		t.Fatalf("a hashed declaration must match the plain token: %v", err)
	}
	if err := loaded.Policy.Permit("e1", "wrong-secret", protocol.OperationOutputRead); err == nil {
		t.Fatalf("a hashed declaration must not match a different token")
	}
}

func TestAccessPolicyRejectsDuplicateTokenAcrossFiles(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "a.conf", "token same-secret\nallow-all\n")
	writePolicyFile(t, dir, "b.conf", "token same-secret\ndeny-all\n")
	if _, err := LoadAccessPolicyDir(dir); err == nil {
		t.Fatalf("two files declaring the same token must be rejected, because the effective policy would depend on read order")
	}
}

func TestAccessPolicyRejectsDuplicateTokenAcrossDeclarationForms(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "a.conf", "token same-secret\nallow-all\n")
	writePolicyFile(t, dir, "b.conf", "token-sha256 "+hashAccessToken("same-secret")+"\ndeny-all\n")
	if _, err := LoadAccessPolicyDir(dir); err == nil {
		t.Fatalf("a plain and a hashed declaration of the same token must be rejected as a duplicate")
	}
}

func TestAccessPolicyRejectsBrokenFileInsteadOfPartiallyApplying(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "good.conf", "token good-secret\nallow-all\n")
	writePolicyFile(t, dir, "broken.conf", "token broken-secret\nscopes not-a-scope\n")
	if _, err := LoadAccessPolicyDir(dir); err == nil {
		t.Fatalf("one broken file must fail the whole load instead of applying the other files only")
	}
}

func TestAccessPolicyReloadKeepsPreviousPolicyOnFailure(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "admin.conf", "token admin-secret\nallow-all\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	// Break the file, then reload. The previous policy must stay in force, so a
	// broken edit cannot disable or widen the policy.
	writePolicyFile(t, dir, "admin.conf", "token admin-secret\nscopes not-a-scope\n")
	if err := loaded.Reload(); err == nil {
		t.Fatalf("reload of a broken file must report an error")
	}
	if err := loaded.Policy.Permit("e1", "admin-secret", protocol.OperationOutputRead); err != nil {
		t.Fatalf("a failed reload must keep the previous policy in force: %v", err)
	}
}

func TestAccessPolicyReloadAppliesNewPolicy(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "admin.conf", "token admin-secret\nallow-all\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	writePolicyFile(t, dir, "admin.conf", "token admin-secret\npermissions output.read\n")
	if err := loaded.Reload(); err != nil {
		t.Fatalf("reload: %v", err)
	}
	if err := loaded.Policy.Permit("e1", "admin-secret", protocol.OperationOutputRead); err != nil {
		t.Fatalf("the reloaded grant must be in force: %v", err)
	}
	if err := loaded.Policy.Permit("e1", "admin-secret", OperationHistoryRead); err == nil {
		t.Fatalf("the reloaded policy must drop the previous allow-all")
	}
}

func TestParseAccessRuleRejectsMissingToken(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("allow-all\n"), "x.conf"); err == nil {
		t.Fatalf("a file without a token must be rejected, because it would grant nothing to nobody")
	}
}

func TestParseAccessRuleRejectsTokenAfterDeclaration(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("scopes view\ntoken late\n"), "x.conf"); err == nil {
		t.Fatalf("a token declared after another declaration must be rejected, so the file reads top-down")
	}
}

func TestParseAccessRuleRejectsTwoTokens(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("token a\ntoken b\n"), "x.conf"); err == nil {
		t.Fatalf("two token declarations must be rejected")
	}
}

func TestParseAccessRuleRejectsAllowAllWithDeclarations(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("token a\nallow-all\nscopes view\n"), "x.conf"); err == nil {
		t.Fatalf("allow-all combined with declarations must be rejected, because the result would depend on line order")
	}
}

func TestParseAccessRuleRejectsAllowAllWithDenyAll(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("token a\nallow-all\ndeny-all\n"), "x.conf"); err == nil {
		t.Fatalf("allow-all and deny-all must not be combined")
	}
}

func TestParseAccessRuleRejectsEmptyDeclaration(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("token a\nscopes\n"), "x.conf"); err == nil {
		t.Fatalf("a declaration with no value must be rejected, because it reads as unspecified while looking like a grant")
	}
}

func TestParseAccessRuleRejectsUnknownDirective(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("token a\npermisions output.read\n"), "x.conf"); err == nil {
		t.Fatalf("an unknown directive must be rejected, so a misspelled directive is not silently ignored")
	}
}

func TestParseAccessRuleRejectsUnknownScope(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("token a\nscopes not-a-scope\n"), "x.conf"); err == nil {
		t.Fatalf("an unknown scope must be rejected, because the scope vocabulary is closed")
	}
}

func TestParseAccessRuleAcceptsUnknownPermissionWithWarning(t *testing.T) {
	// One file set has to serve a version-skewed fleet, so an operation this
	// build does not serve is accepted. The warning is mandatory, because this is
	// the only place in the design where a mistake can be silent.
	rule, warnings, err := ParseAccessRule([]byte("token a\npermissions mesages.read\n"), "x.conf")
	if err != nil {
		t.Fatalf("an unknown permission must be accepted so one file set serves a version-skewed fleet: %v", err)
	}
	if len(warnings) != 1 {
		t.Fatalf("an unknown permission must produce exactly one warning, got %v", warnings)
	}
	if !strings.Contains(warnings[0], "mesages.read") {
		t.Fatalf("the warning must name the operation, got %q", warnings[0])
	}
	if err := rule.permit("e1", OperationMessagesRead); err == nil {
		t.Fatalf("a misspelled permission must grant nothing")
	}
}

func TestParseAccessRuleAcceptsControlPermissionWithoutWarning(t *testing.T) {
	// The action inventory is Endpoint-local configuration, so a ctl. permission
	// may legitimately name an action this build does not know.
	_, warnings, err := ParseAccessRule([]byte("token a\npermissions ctl.anything\n"), "x.conf")
	if err != nil {
		t.Fatalf("a ctl. permission must be accepted: %v", err)
	}
	if len(warnings) != 0 {
		t.Fatalf("a ctl. permission must not warn, got %v", warnings)
	}
}

func TestParseAccessRuleRejectsControlCharacter(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("token a\x00\nallow-all\n"), "x.conf"); err == nil {
		t.Fatalf("a control character must be rejected, because the parsed value would differ from what a reader sees")
	}
}

func TestParseAccessRuleRejectsMalformedHash(t *testing.T) {
	if _, _, err := ParseAccessRule([]byte("token-sha256 nothex\nallow-all\n"), "x.conf"); err == nil {
		t.Fatalf("a malformed digest must be rejected")
	}
}

func TestAccessPolicyWildcardPermissionGrantsEverything(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "wild.conf", "token wild-secret\npermissions *\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	for _, operation := range readOperations {
		if err := loaded.Policy.Permit("e1", "wild-secret", operation); err != nil {
			t.Fatalf("a bare wildcard must grant %q: %v", operation, err)
		}
	}
}

func TestAccessPolicyPrefixPermissionGrantsFamily(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "prefix.conf", "token prefix-secret\npermissions output.*\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	for _, operation := range []string{protocol.OperationOutputRead, protocol.OperationOutputFollow} {
		if err := loaded.Policy.Permit("e1", "prefix-secret", operation); err != nil {
			t.Fatalf("output.* must grant %q: %v", operation, err)
		}
	}
	if err := loaded.Policy.Permit("e1", "prefix-secret", OperationHistoryRead); err == nil {
		t.Fatalf("output.* must not grant history.read")
	}
}

func TestAccessPolicyEndpointAdminScopeCoversNothing(t *testing.T) {
	dir := t.TempDir()
	// endpoint_admin is reserved, so it stays in the vocabulary but covers no
	// operation. A file naming it must still load.
	writePolicyFile(t, dir, "reserved.conf", "token reserved-secret\nscopes endpoint_admin\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("a reserved scope must still load: %v", err)
	}
	for _, operation := range readOperations {
		if err := loaded.Policy.Permit("e1", "reserved-secret", operation); err == nil {
			t.Fatalf("the reserved scope must cover no operation, but %q was permitted", operation)
		}
	}
}

func TestAccessPolicySummaryDoesNotRevealSecret(t *testing.T) {
	rule, _, err := ParseAccessRule([]byte("token super-secret-value\nscopes view\n"), "x.conf")
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if strings.Contains(rule.Summary(), "super-secret-value") {
		t.Fatalf("the summary must not reveal the secret, got %q", rule.Summary())
	}
}

// writePolicyFile writes one policy file into dir.
func writePolicyFile(t *testing.T, dir, name, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", name, err)
	}
}
