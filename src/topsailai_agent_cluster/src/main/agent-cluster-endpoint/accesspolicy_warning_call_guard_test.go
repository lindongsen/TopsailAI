package main

// The access policy load warnings are emitted by two call sites in main.go, and
// nothing in this package proves that main calls them. The behavioural tests call
// logAccessPolicyWarnings directly, so deleting either call site leaves every one
// of them green while the operator stops receiving the diagnostic.
//
// That gap was measured, not assumed: removing the startup call site kept all
// eight warning tests passing. A warning that is parsed and stored but never
// logged is indistinguishable from a policy that loaded cleanly, which is exactly
// the defect the warnings exist to prevent.
//
// The guard reads main.go instead of restating it, following the convention in
// catalog_deployment_guard_test.go. It pins the two event strings as well as the
// call, because the event string is what tells an operator which load produced
// the warning.

import (
	"strings"
	"testing"
)

// accessPolicyWarningSource is the file that owns both call sites.
const accessPolicyWarningSource = "src/main/agent-cluster-endpoint/main.go"

// accessPolicyWarningLoad is one load moment: the call that emits its warnings
// and the count line that reports its outcome.
type accessPolicyWarningLoad struct {
	name  string
	call  string
	count string
}

// accessPolicyWarningLoads are the two moments that must log warnings. The
// startup load and the SIGHUP reload are separate: an operator who edits a policy
// file sees the reload event, and one who starts the Endpoint sees the load
// event. Losing either one hides the warning from that operator.
var accessPolicyWarningLoads = []accessPolicyWarningLoad{
	{
		name:  "startup",
		call:  `logAccessPolicyWarnings(logger, "load endpoint access policy warning", accessPolicy.Policy)`,
		count: `logger.Info("loaded endpoint access policy"`,
	},
	{
		name:  "reload",
		call:  `logAccessPolicyWarnings(logger, "reload endpoint access policy warning", accessPolicy.Policy)`,
		count: `logger.Info("reloaded endpoint access policy"`,
	},
}

// TestAccessPolicyWarningsAreCalledAtBothLoadSites pins that main.go emits the
// warnings at startup and at reload, so a parsed warning cannot be dropped
// silently by deleting one call.
func TestAccessPolicyWarningsAreCalledAtBothLoadSites(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, accessPolicyWarningSource)

	for _, load := range accessPolicyWarningLoads {
		if !strings.Contains(source, load.call) {
			t.Fatalf("%s does not contain the %s warning call %q, so the warnings parsed at that load are never logged", accessPolicyWarningSource, load.name, load.call)
		}
	}
}

// TestAccessPolicyWarningCallsPrecedeTheTokenCount pins the ordering the reload
// path documents: the diagnostic must be logged before the reassuring token
// count, because a count printed first reads as a clean load and buries the line
// that explains why one entry grants nothing.
func TestAccessPolicyWarningCallsPrecedeTheTokenCount(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, accessPolicyWarningSource)

	for _, load := range accessPolicyWarningLoads {
		callIndex := strings.Index(source, load.call)
		if callIndex < 0 {
			t.Fatalf("%s does not contain the %s warning call %q", accessPolicyWarningSource, load.name, load.call)
		}
		countIndex := strings.Index(source, load.count)
		if countIndex < 0 {
			t.Fatalf("%s does not contain the %s count line %q", accessPolicyWarningSource, load.name, load.count)
		}
		if countIndex < callIndex {
			t.Fatalf("the %s token count is logged before its warnings in %s, so a clean count is printed ahead of the diagnostic", load.name, accessPolicyWarningSource)
		}
	}
}
