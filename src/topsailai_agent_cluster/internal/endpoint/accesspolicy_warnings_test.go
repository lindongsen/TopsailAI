package endpoint

import (
	"strings"
	"testing"
)

// TestAccessPolicyWarningsSurviveIntoThePolicyInForce is the regression test for
// the documented "accept but warn" contract.
//
// The warning has to survive into the policy in force, not only into the second
// return value of ParseAccessRule, because the policy is what the Endpoint keeps.
// A caller that discards the second value would otherwise lose every warning
// while the load still succeeded, which is exactly how the contract became
// "accept" only.
func TestAccessPolicyWarningsSurviveIntoThePolicyInForce(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "typo.conf", "token typo-secret\npermissions mesages.read\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("an unknown permission must be accepted so one file set serves a version-skewed fleet: %v", err)
	}
	warnings := loaded.Policy.Warnings()
	if len(warnings) != 1 {
		t.Fatalf("the policy in force must carry exactly one warning, got %v", warnings)
	}
	if !strings.Contains(warnings[0], "mesages.read") {
		t.Fatalf("the warning must name the misspelled operation, got %q", warnings[0])
	}
	if !strings.Contains(warnings[0], "typo.conf") {
		t.Fatalf("the warning must name the file, so an operator can find the line, got %q", warnings[0])
	}
}

// TestAccessPolicyWarningsAreEmptyForAValidPolicy is the paired negative case.
//
// Without it, a policy that warned about every permission would pass the test
// above, and the warning would stop identifying a mistake.
func TestAccessPolicyWarningsAreEmptyForAValidPolicy(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "good.conf", "token good-secret\npermissions output.read\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if warnings := loaded.Policy.Warnings(); len(warnings) != 0 {
		t.Fatalf("a policy naming only served operations must not warn, got %v", warnings)
	}
}

// TestAccessPolicyWarningsFollowAReload proves the reload path reports the
// current state of the files rather than the state at startup.
//
// A reload is the moment an operator expects feedback on a file they just
// edited, so a warning that only appeared at startup would be missing exactly
// when the mistake was introduced, and a warning that never cleared would keep
// accusing a file that had already been fixed.
func TestAccessPolicyWarningsFollowAReload(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "typo.conf", "token typo-secret\npermissions mesages.read\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	if len(loaded.Policy.Warnings()) != 1 {
		t.Fatalf("the misspelled permission must warn before the reload, got %v", loaded.Policy.Warnings())
	}

	writePolicyFile(t, dir, "typo.conf", "token typo-secret\npermissions messages.read\n")
	if err := loaded.Reload(); err != nil {
		t.Fatalf("reload: %v", err)
	}
	if warnings := loaded.Policy.Warnings(); len(warnings) != 0 {
		t.Fatalf("a corrected file must stop warning after the reload, got %v", warnings)
	}
}

// TestAccessPolicyWarningsAreOrderedBySourceFile keeps the log output stable.
//
// The warnings are emitted one per line, so a nondeterministic order would make
// two runs of the same configuration produce different logs and defeat any
// comparison an operator or a test wants to make.
func TestAccessPolicyWarningsAreOrderedBySourceFile(t *testing.T) {
	dir := t.TempDir()
	writePolicyFile(t, dir, "b.conf", "token b-secret\npermissions bbbbbbb.read\n")
	writePolicyFile(t, dir, "a.conf", "token a-secret\npermissions aaaaaaa.read\n")
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	warnings := loaded.Policy.Warnings()
	if len(warnings) != 2 {
		t.Fatalf("both files must warn, got %v", warnings)
	}
	if !strings.Contains(warnings[0], "a.conf") || !strings.Contains(warnings[1], "b.conf") {
		t.Fatalf("warnings must be ordered by source file, got %v", warnings)
	}
}
