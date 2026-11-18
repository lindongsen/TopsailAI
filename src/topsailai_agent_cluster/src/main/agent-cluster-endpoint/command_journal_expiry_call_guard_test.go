package main

// The command journal retention window is read and wired into the collector by
// main.go, and nothing in this package proves that main does either. The
// behavioural tests build a collector directly, so deleting the read or the
// wiring leaves every one of them green while the Endpoint silently stops
// bounding its command journal.
//
// That gap is the same one measured for the access policy warnings: removing a
// main.go call site kept all eight warning tests passing. A retention window that
// is parsed but never passed to the collector is indistinguishable from a
// deployment that never configured one, which is exactly the unbounded growth the
// retention exists to prevent.
//
// The guard reads main.go instead of restating it, following the convention in
// catalog_deployment_guard_test.go. It pins the failure path as well as the
// wiring, because a window that cannot be parsed must stop the process rather than
// fall back to a default: a silent fallback would bound the journal at a value the
// operator never chose.

import (
	"strings"
	"testing"
)

// commandJournalExpirySource is the file that owns the read and the wiring.
const commandJournalExpirySource = "src/main/agent-cluster-endpoint/main.go"

// commandJournalExpiryWiring is one required statement: what it must contain and
// why losing it matters.
type commandJournalExpiryWiring struct {
	name     string
	fragment string
	why      string
}

// commandJournalExpiryWirings are the statements that must all be present. They
// are separate because each one fails differently: losing the read leaves the
// window at zero, losing the wiring leaves the parsed window unused, and losing
// the failure path turns an invalid configuration into a silent default.
var commandJournalExpiryWirings = []commandJournalExpiryWiring{
	{
		name:     "read",
		fragment: "journalExpiry, err := commandJournalExpiry()",
		why:      "the retention window is never read, so the collector receives zero and the command journal grows without bound",
	},
	{
		name:     "failure path",
		fragment: `logger.Error("load command journal expiry", "error", err)`,
		why:      "an invalid retention window is not reported, so a misconfigured Endpoint starts with a window the operator never chose",
	},
	{
		name:     "wiring",
		fragment: "CommandJournalExpiry: journalExpiry",
		why:      "the parsed retention window is never passed to the collector, so retention is disabled while the configuration looks correct",
	},
	{
		name:     "deletion log",
		fragment: `logger.Info("deleted expired command journal", "command_id", entry.CommandID, "phase", string(entry.Phase), "effect_certainty", entry.EffectCertainty`,
		why:      "a deleted journal row is irreversible, so the deletion must be logged with the command, phase and effect certainty",
	},
}

// TestCommandJournalExpiryIsReadAndWired pins that main.go reads the retention
// window, fails startup when it is invalid, passes it to the collector and logs
// every deletion.
func TestCommandJournalExpiryIsReadAndWired(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, commandJournalExpirySource)

	for _, wiring := range commandJournalExpiryWirings {
		if !strings.Contains(source, wiring.fragment) {
			t.Fatalf("%s does not contain the %s statement %q, so %s", commandJournalExpirySource, wiring.name, wiring.fragment, wiring.why)
		}
	}
}

// TestCommandJournalExpiryFailureStopsStartup pins that the failure path exits
// rather than continuing. A retention window that cannot be parsed must not
// degrade into a default, because the operator would then believe the journal is
// bounded at a value they never configured.
func TestCommandJournalExpiryFailureStopsStartup(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, commandJournalExpirySource)

	readIndex := strings.Index(source, "journalExpiry, err := commandJournalExpiry()")
	if readIndex < 0 {
		t.Fatalf("%s does not read the command journal expiry", commandJournalExpirySource)
	}
	// The failure block is the text between the read and the collector wiring.
	wiringIndex := strings.Index(source, "CommandJournalExpiry: journalExpiry")
	if wiringIndex < 0 {
		t.Fatalf("%s does not wire the command journal expiry", commandJournalExpirySource)
	}
	if wiringIndex < readIndex {
		t.Fatalf("the command journal expiry is wired before it is read in %s", commandJournalExpirySource)
	}
	failureBlock := source[readIndex:wiringIndex]
	if !strings.Contains(failureBlock, "os.Exit(1)") {
		t.Fatalf("the command journal expiry failure path does not exit in %s, so an invalid window starts the Endpoint with retention disabled", commandJournalExpirySource)
	}
}
