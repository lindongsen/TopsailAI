package node

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"topsailai_connector/internal/security"
)

// mustCredentialList returns the credentials in force, failing the test on an error.
//
// The helper exists because every test in this file needs the list and none of them is
// about the error path: a test that repeated the check would bury the assertion it is
// actually making.
func mustCredentialList(t *testing.T, runtime *Runtime) []security.Credential {
	t.Helper()

	list, err := runtime.CredentialList()
	if err != nil {
		t.Fatalf("CredentialList() = %v, want nil", err)
	}
	return list
}

// newConsoleFixture returns a stateless runtime and a console writing to a buffer.
//
// The runtime is stateless on purpose: the console exists because a stateless Node has
// no file to edit, so a test that used a file-backed runtime would be testing the
// easier half.
func newConsoleFixture(t *testing.T) (*Runtime, *bytes.Buffer, *Console) {
	t.Helper()

	config, _ := newStatelessFixture(t)
	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	t.Cleanup(func() {
		if err := runtime.Close(); err != nil {
			t.Errorf("Close() = %v, want nil", err)
		}
	})

	out := &bytes.Buffer{}
	return runtime, out, NewConsole(runtime, out, nil, discardLogger())
}

// runConsole feeds the given lines to the console and returns what it printed.
func runConsole(t *testing.T, console *Console, out *bytes.Buffer, lines ...string) string {
	t.Helper()

	input := strings.NewReader(strings.Join(lines, "\n") + "\n")
	if err := console.Run(context.Background(), input); err != nil {
		t.Fatalf("Run() = %v, want nil", err)
	}
	return out.String()
}

// TestConsoleRegenerateRequestsAnIdentityChange pins the wiring defect this unit fixes.
//
// The console is built before the dialer, so the callback is installed afterwards. If
// the setter is never called, `regenerate id` changes the identity in memory and leaves
// the live channel authenticated under the retired one. The test therefore asserts the
// callback ran, not only that the identity changed: the identity change alone passes
// with the wiring missing.
func TestConsoleRegenerateRequestsAnIdentityChange(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	before := runtime.IdentityHolder().NodeID()

	requests := 0
	console.SetIdentityChangeRequest(func() { requests++ })

	printed := runConsole(t, console, out, "regenerate id", "quit")

	after := runtime.IdentityHolder().NodeID()
	if after == before {
		t.Fatalf("the node id is still %q, want a new one", before)
	}
	if requests != 1 {
		t.Fatalf("the identity change was requested %d times, want 1", requests)
	}
	if !strings.Contains(printed, after) {
		t.Fatalf("the console printed %q, want it to name the new node id %q", printed, after)
	}
}

// TestConsoleRegenerateLeavesCredentialsUntouched checks the property the file-backed
// command also holds: the address and the secret are separate, so changing one does not
// reissue the other.
func TestConsoleRegenerateLeavesCredentialsUntouched(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	before := mustCredentialList(t, runtime)
	if len(before) == 0 {
		t.Fatal("the fixture has no credential, so this test would measure nothing")
	}

	runConsole(t, console, out, "regenerate id", "quit")

	after := mustCredentialList(t, runtime)
	if len(after) != len(before) {
		t.Fatalf("the credential count changed from %d to %d, want it unchanged", len(before), len(after))
	}
	for i := range before {
		if before[i].KeyID != after[i].KeyID || before[i].Secret != after[i].Secret {
			t.Fatalf("credential %d changed from %q to %q, want it untouched", i, before[i].KeyID, after[i].KeyID)
		}
	}
}

// TestConsoleShowCredentialsNeverPrintsASecret is the rule that matters most in this
// file. A console that printed a secret would put a never-expiring credential into a
// terminal scrollback, a pasted log and a ticket.
func TestConsoleShowCredentialsNeverPrintsASecret(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	credentials := mustCredentialList(t, runtime)
	if len(credentials) == 0 {
		t.Fatal("the fixture has no credential, so this test would measure nothing")
	}

	printed := runConsole(t, console, out, "show credentials", "quit")

	for _, credential := range credentials {
		if strings.Contains(printed, string(credential.Secret)) {
			t.Fatalf("the console printed the secret of %q, want only the key id", credential.KeyID)
		}
		if !strings.Contains(printed, credential.KeyID) {
			t.Fatalf("the console printed %q, want it to name the key id %q", printed, credential.KeyID)
		}
	}
}

// TestConsoleCredentialAddRefusesADuplicateKeyID checks that adding a caller cannot
// silently replace an existing one, which would revoke a caller by accident.
func TestConsoleCredentialAddRefusesADuplicateKeyID(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	existing := mustCredentialList(t, runtime)[0].KeyID

	printed := runConsole(t, console, out, "credential add "+existing, "quit")

	if !strings.Contains(printed, "error:") {
		t.Fatalf("the console printed %q, want an error for a duplicate key id", printed)
	}
	if got := len(mustCredentialList(t, runtime)); got != 1 {
		t.Fatalf("the credential count is %d, want 1", got)
	}
}

// TestConsoleCredentialRotateReplacesTheSecretUnderTheSameKeyID covers the defect the
// holder has: it compares key identifiers, so a rotation that keeps the identifier and
// replaces the secret is reported as unchanged. The console must install the new set
// anyway, or the rotation silently does nothing.
func TestConsoleCredentialRotateReplacesTheSecretUnderTheSameKeyID(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	before := mustCredentialList(t, runtime)[0]

	printed := runConsole(t, console, out, "credential rotate "+before.KeyID, "quit")

	after := mustCredentialList(t, runtime)
	if len(after) != 1 {
		t.Fatalf("the credential count is %d, want 1", len(after))
	}
	if after[0].KeyID != before.KeyID {
		t.Fatalf("the key id changed from %q to %q, want it unchanged", before.KeyID, after[0].KeyID)
	}
	if after[0].Secret == before.Secret {
		t.Fatal("the secret is unchanged, want a new one: the rotation did not take effect")
	}
	if !strings.Contains(printed, string(after[0].Secret)) {
		t.Fatalf("the console printed %q, want it to print the new secret once", printed)
	}

	// The holder is the set the dispatcher authenticates against, so a rotation that
	// updated only the runtime's own list would leave the Node accepting the retired
	// secret. The holder reports "unchanged" when the key identifiers match, which is
	// why this assertion is the one that catches a rotation that silently did nothing.
	installed, present := runtime.IdentityHolder().Credentials().Lookup(before.KeyID)
	if !present {
		t.Fatalf("the holder does not hold %q after the rotation", before.KeyID)
	}
	if installed != after[0].Secret {
		t.Fatalf("the holder holds a different secret than the runtime reports; the dispatcher would accept the retired one")
	}
	if installed == before.Secret {
		t.Fatal("the holder still holds the retired secret, want the new one")
	}
}

// TestConsoleCredentialRemoveRefusesTheLastCredential checks the refusal the file-backed
// command also holds: a Node with no credential accepts nothing, so removing the last one
// would lock the operator out with no way back in.
func TestConsoleCredentialRemoveRefusesTheLastCredential(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	only := mustCredentialList(t, runtime)[0].KeyID

	printed := runConsole(t, console, out, "credential remove "+only, "quit")

	if !strings.Contains(printed, "refusing to remove the last credential") {
		t.Fatalf("the console printed %q, want the last-credential refusal", printed)
	}
	if got := len(mustCredentialList(t, runtime)); got != 1 {
		t.Fatalf("the credential count is %d, want 1", got)
	}
}

// TestConsoleContinuesAfterAnUnknownCommand checks that a typo does not end the console.
// A console that exited on a typo would force a restart to get back, which on a stateless
// Node also loses the identity.
func TestConsoleContinuesAfterAnUnknownCommand(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	before := runtime.IdentityHolder().NodeID()

	printed := runConsole(t, console, out, "nonsense", "regenerate id", "quit")

	if !strings.Contains(printed, "error:") {
		t.Fatalf("the console printed %q, want an error for the unknown command", printed)
	}
	if runtime.IdentityHolder().NodeID() == before {
		t.Fatal("the command after the unknown one did not run, want the loop to continue")
	}
}

// TestConsoleStatelessWritesNoFile checks that the console keeps the mode's promise.
//
// The console is the one place that changes state, so it is the one place that could
// break the promise by writing a file. The check walks the tree rather than naming the
// two files, because a write to a path the test did not think of would pass a check that
// only looked at the paths it expected.
func TestConsoleStatelessWritesNoFile(t *testing.T) {
	config, base := newStatelessFixture(t)

	runtime, err := Open(config, discardLogger())
	if err != nil {
		t.Fatalf("Open() = %v, want nil", err)
	}
	defer runtime.Close()

	before := countEntries(t, base)

	out := &bytes.Buffer{}
	console := NewConsole(runtime, out, nil, discardLogger())
	runConsole(t, console, out,
		"regenerate id",
		"credential add second-caller",
		"credential rotate second-caller",
		"credential remove second-caller",
		"quit",
	)

	after := countEntries(t, base)
	if after != before {
		t.Fatalf("the tree held %d entries before the console ran and %d after, want no new entry", before, after)
	}
}

// TestConsoleShowConfigRedactsTheTunnelToken checks that inspecting the configuration
// cannot print the Server-wide secret. The tunnel token admits a Node to the Server, so a
// console that echoed it would hand over the credential the whole channel gate rests on.
func TestConsoleShowConfigRedactsTheTunnelToken(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	printed := runConsole(t, console, out, "show config", "quit")

	if strings.Contains(printed, string(runtime.Config().TunnelToken)) {
		t.Fatalf("the console printed the tunnel token, want it redacted")
	}
	if !strings.Contains(printed, "stateless") {
		t.Fatalf("the console printed %q, want it to report the stateless mode", printed)
	}
}
