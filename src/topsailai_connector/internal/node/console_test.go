package node

import (
	"bytes"
	"context"
	"log/slog"
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

// TestConsoleLogCommandChangesTheProcessLevel pins the switch that answers the measured
// complaint: a Node retrying a refused dial writes a warning every five seconds, and the
// warning lands in the middle of whatever the operator is typing.
//
// The assertion is on the LevelVar the process logger was built from, not on the console's
// own output. A console that printed "log level: off" while the dialer kept writing would
// pass an output-only test and fix nothing.
func TestConsoleLogCommandChangesTheProcessLevel(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	level := &slog.LevelVar{}
	level.Set(slog.LevelInfo)
	console.SetLogLevel(level)

	printed := runConsole(t, console, out, "log", "log off", "log", "quit")

	if !strings.Contains(printed, "log level: info") {
		t.Fatalf("the console printed %q, want it to report the level in force", printed)
	}
	if !strings.Contains(printed, "log level: off") {
		t.Fatalf("the console printed %q, want it to report the new level", printed)
	}
	if got := level.Level(); got != levelOff {
		t.Fatalf("the process level = %v, want %v", got, levelOff)
	}
}

// TestConsoleLogOffSilencesTheHandler proves the level the console sets actually silences a
// handler built the way the process builds one.
//
// Setting a LevelVar and asserting its value is a test of the setter. This test writes a
// record through a real handler and asserts nothing reached the buffer, which is the
// property the operator asked for.
func TestConsoleLogOffSilencesTheHandler(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	level := &slog.LevelVar{}
	level.Set(slog.LevelInfo)
	console.SetLogLevel(level)

	var logged bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&logged, &slog.HandlerOptions{Level: level}))

	logger.Warn("before the switch")
	if logged.Len() == 0 {
		t.Fatal("the handler wrote nothing before the switch; this test is measuring nothing")
	}

	runConsole(t, console, out, "log off", "quit")
	logged.Reset()
	logger.Warn("after the switch")

	if logged.Len() != 0 {
		t.Fatalf("the handler wrote %q after the level was set to off, want nothing", logged.String())
	}
}

// TestConsoleLogRefusesAnUnknownLevel checks that a typo is refused rather than rounded to
// a level the operator did not ask for.
func TestConsoleLogRefusesAnUnknownLevel(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	level := &slog.LevelVar{}
	level.Set(slog.LevelInfo)
	console.SetLogLevel(level)

	printed := runConsole(t, console, out, "log silent", "quit")

	if !strings.Contains(printed, `unknown level "silent"`) {
		t.Fatalf("the console printed %q, want it to name the unknown level", printed)
	}
	if got := level.Level(); got != slog.LevelInfo {
		t.Fatalf("the level = %v after a refused value, want it unchanged at info", got)
	}
}

// TestConsoleLogWithoutASwitchRefusesInsteadOfPretending checks the console built by a
// caller that never installed a level. Reporting a level it cannot change would be a
// console that lies about the state of the process.
func TestConsoleLogWithoutASwitchRefusesInsteadOfPretending(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	printed := runConsole(t, console, out, "log", "quit")

	if !strings.Contains(printed, "no log switch") {
		t.Fatalf("the console printed %q, want it to say there is no switch", printed)
	}
}

// TestConsoleQuitSaysTheNodeKeepsRunning pins the sentence that distinguishes "the console
// stopped" from "the process stopped". Without it a silent exit reads as a hang.
func TestConsoleQuitSaysTheNodeKeepsRunning(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	printed := runConsole(t, console, out, "quit")

	if !strings.Contains(printed, "console closed; the node keeps running") {
		t.Fatalf("the console printed %q, want it to say the node keeps running", printed)
	}
}

// TestConsoleCredentialListPointsAtShowCredentials checks that the natural word for "show
// me the credentials" reaches the command that does it.
//
// The measured failure was `credential list` answering with the usage line for add, rotate
// and remove, which reads as "this feature does not exist" rather than "the command is
// called something else".
func TestConsoleCredentialListPointsAtShowCredentials(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	printed := runConsole(t, console, out, "credential list", "quit")

	if !strings.Contains(printed, "use show credentials") {
		t.Fatalf("the console printed %q, want it to name show credentials", printed)
	}
}

// TestConsoleCredentialNamesTheMissingKeyID checks that a command with the action but no
// key id reports the usage for that action rather than the usage for all three.
func TestConsoleCredentialNamesTheMissingKeyID(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	printed := runConsole(t, console, out, "credential add", "quit")

	if !strings.Contains(printed, "usage: credential add <key-id>") {
		t.Fatalf("the console printed %q, want the usage for add alone", printed)
	}
}

// TestConsoleRegenerateNamesTheBadSubject checks that a wrong subject is named instead of
// repeating the usage line, which is what `show` already does.
func TestConsoleRegenerateNamesTheBadSubject(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	printed := runConsole(t, console, out, "regenerate bogus", "quit")

	if !strings.Contains(printed, `unknown subject "bogus"`) {
		t.Fatalf("the console printed %q, want it to name the bad subject", printed)
	}
}

// TestConsoleShowConfigIsOneFieldPerLine pins the layout that keeps a value from being
// broken across two lines on a narrow terminal.
//
// The measured case was `config_dir=stateless` rendered as `stat` and `eless` at 100
// columns, which reads as a different value. The assertion is on the line count and on the
// absence of a wrapped value, not on the exact wording.
func TestConsoleShowConfigIsOneFieldPerLine(t *testing.T) {
	_, out, console := newConsoleFixture(t)

	printed := runConsole(t, console, out, "show config", "quit")

	lines := strings.Split(strings.TrimSpace(printed), "\n")
	// The last line is the quit sentence, so the configuration is everything before it.
	fields := 0
	for _, line := range lines {
		if strings.HasPrefix(line, "console closed") {
			break
		}
		if !strings.Contains(line, ": ") {
			t.Fatalf("the line %q is not a field, want one field per line", line)
		}
		if len(line) > 80 {
			t.Fatalf("the line %q is %d characters, want it short enough not to wrap", line, len(line))
		}
		fields++
	}
	if fields < 5 {
		t.Fatalf("show config printed %d fields, want at least 5", fields)
	}
}

// TestConsoleServerReportsTheAddressInForce checks the reporting half of the command.
//
// The assertion compares the two places the address is printed rather than a literal,
// because the property that matters is that `server` and `show config` agree. A test
// against a literal would pass while the two disagreed, which is the state a reader
// would act on wrongly.
func TestConsoleServerReportsTheAddressInForce(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	printed := runConsole(t, console, out, "server", "show config", "quit")

	want := "server: " + runtime.ServerURL()
	if strings.Count(printed, want) != 2 {
		t.Fatalf("the console printed %q, want %q twice: once for server and once for show config", printed, want)
	}
}

// TestConsoleServerReplacesTheAddressAndRequestsAReconnect pins the wiring defect this
// unit fixes.
//
// Three things must happen together and each one alone is insufficient: the runtime must
// hold the new address, the dialer must be told, and the live channel must be dropped.
// A test that asserted only the first would pass with the dialer still dialing the old
// address, which is the failure the operator would see as "the change did not take".
func TestConsoleServerReplacesTheAddressAndRequestsAReconnect(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	before := runtime.ServerURL()

	var handed []string
	console.SetServerURLSetter(func(value string) { handed = append(handed, value) })

	requests := 0
	console.SetReconnectRequest(func() { requests++ })

	// The identity callback is installed as well, so the test can prove the repoint did
	// not report itself as a regeneration. Without this the split could be undone by
	// pointing both callbacks at the same function and every assertion above would pass.
	identityRequests := 0
	console.SetIdentityChangeRequest(func() { identityRequests++ })

	const replacement = "ws://127.0.0.1:1/channel"
	printed := runConsole(t, console, out, "server "+replacement, "quit")

	if got := runtime.ServerURL(); got != replacement {
		t.Fatalf("ServerURL() = %q, want %q", got, replacement)
	}
	if len(handed) != 1 || handed[0] != replacement {
		t.Fatalf("the dialer was handed %v, want [%q]", handed, replacement)
	}
	if requests != 1 {
		t.Fatalf("the reconnect was requested %d times, want 1", requests)
	}
	if identityRequests != 0 {
		t.Fatalf("the identity change was requested %d times for a repoint, want 0", identityRequests)
	}
	if !strings.Contains(printed, "server: "+replacement) {
		t.Fatalf("the console printed %q, want it to report the new address", printed)
	}
	if !strings.Contains(printed, "the live channel is dropped") {
		t.Fatalf("the console printed %q, want it to say the channel is dropped", printed)
	}
	if !strings.Contains(printed, "not remembered across a restart") {
		t.Fatalf("the console printed %q, want it to say the change is not remembered", printed)
	}
	if before == replacement {
		t.Fatal("the fixture already used the replacement address, so this test measures nothing")
	}
}

// TestConsoleServerRefusesABadSchemeAndKeepsTheAddress checks that a refusal is a
// refusal: the address in force must not move, the dialer must not be told and no
// reconnect must be requested.
//
// The message is asserted on the reason rather than on the variable name, because the
// operator typed an address at a console and never typed a variable name. A message that
// named CONNECTOR_NODE_SERVER_URL would send them looking for an environment variable
// they did not set.
func TestConsoleServerRefusesABadSchemeAndKeepsTheAddress(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	before := runtime.ServerURL()

	handed := 0
	console.SetServerURLSetter(func(string) { handed++ })
	requests := 0
	console.SetReconnectRequest(func() { requests++ })

	printed := runConsole(t, console, out, "server http://127.0.0.1:1/channel", "server", "quit")

	if got := runtime.ServerURL(); got != before {
		t.Fatalf("ServerURL() = %q after a refusal, want the unchanged %q", got, before)
	}
	if handed != 0 {
		t.Fatalf("the dialer was handed an address %d times after a refusal, want 0", handed)
	}
	if requests != 0 {
		t.Fatalf("the reconnect was requested %d times after a refusal, want 0", requests)
	}
	if !strings.Contains(printed, `has scheme "http", want wss or ws`) {
		t.Fatalf("the console printed %q, want it to name the scheme it refused", printed)
	}
	if strings.Contains(printed, "CONNECTOR_NODE_SERVER_URL") {
		t.Fatalf("the console printed %q, want the variable name dropped from a console message", printed)
	}
	if !strings.Contains(printed, "server: "+before) {
		t.Fatalf("the console printed %q, want the following server command to report %q", printed, before)
	}
}

// TestConsoleServerRefusesAnAddressWithoutAHost checks the second startup rule the
// console reuses. The two rules are asserted separately because a validator that checked
// only the scheme would pass the first test and accept an address nothing can dial.
func TestConsoleServerRefusesAnAddressWithoutAHost(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	before := runtime.ServerURL()

	printed := runConsole(t, console, out, "server ws://", "quit")

	if got := runtime.ServerURL(); got != before {
		t.Fatalf("ServerURL() = %q after a refusal, want the unchanged %q", got, before)
	}
	if !strings.Contains(printed, "has no host") {
		t.Fatalf("the console printed %q, want it to say the address has no host", printed)
	}
}

// TestConsoleServerWithTheSameAddressKeepsTheChannel checks that repeating the address
// in force is not treated as a change.
//
// Dropping a healthy channel because the operator retyped the same value would be a
// self-inflicted outage, and the sentence the console prints is the only signal that
// nothing happened.
func TestConsoleServerWithTheSameAddressKeepsTheChannel(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	requests := 0
	console.SetReconnectRequest(func() { requests++ })

	printed := runConsole(t, console, out, "server "+runtime.ServerURL(), "quit")

	if requests != 0 {
		t.Fatalf("the reconnect was requested %d times for an unchanged address, want 0", requests)
	}
	if !strings.Contains(printed, "the address is unchanged; the live channel is kept") {
		t.Fatalf("the console printed %q, want it to say the channel is kept", printed)
	}
}

// TestConsoleServerRefusesAnExtraArgument checks that a second argument is named rather
// than ignored. An ignored argument would leave the operator believing a value they typed
// was applied.
func TestConsoleServerRefusesAnExtraArgument(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	before := runtime.ServerURL()

	printed := runConsole(t, console, out, "server ws://a/channel ws://b/channel", "quit")

	if got := runtime.ServerURL(); got != before {
		t.Fatalf("ServerURL() = %q, want the unchanged %q", got, before)
	}
	if !strings.Contains(printed, `unexpected argument "ws://b/channel"`) {
		t.Fatalf("the console printed %q, want it to name the extra argument", printed)
	}
}

// TestConsoleServerChangesTheAddressWithoutASetter checks the state a console built by a
// test or by a Node that serves without a channel is in.
//
// The address must still change, because `server` and `show config` are read by the
// operator and must agree. Only the hand-off to the dialer is skipped, and skipping it is
// the correct behaviour when there is no dialer.
func TestConsoleServerChangesTheAddressWithoutASetter(t *testing.T) {
	runtime, out, console := newConsoleFixture(t)

	const replacement = "ws://127.0.0.1:2/channel"
	printed := runConsole(t, console, out, "server "+replacement, "show config", "quit")

	if got := runtime.ServerURL(); got != replacement {
		t.Fatalf("ServerURL() = %q, want %q", got, replacement)
	}

	// The assertion matches the two-line sequence show config prints, not the bare
	// address, because the `server` command prints the same address line. A search for
	// the address alone passes while show config still reports the startup value, which
	// is the disagreement this test exists to refuse. The second line is what tells the
	// two apart: `server` follows its answer with the drop notice, show config follows
	// it with the tunnel token.
	want := "server: " + replacement + "\ntunnel token: "
	if !strings.Contains(printed, want) {
		t.Fatalf("the console printed %q, want show config to report %q", printed, want)
	}
}
