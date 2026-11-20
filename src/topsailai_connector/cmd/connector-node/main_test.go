package main

import (
	"context"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/security"
)

// captureStdout runs action with os.Stdout redirected to a pipe and returns what
// it printed.
//
// The pair is printed to stdout rather than to the log, so a test that wants to
// check the printed value has to read stdout. Redirecting it here keeps the test
// output clean and keeps the assertion about the printed value honest.
func captureStdout(t *testing.T, action func() error) (string, error) {
	t.Helper()

	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatalf("create pipe: %v", err)
	}

	original := os.Stdout
	os.Stdout = writer

	actionErr := action()

	os.Stdout = original
	if err := writer.Close(); err != nil {
		t.Fatalf("close pipe writer: %v", err)
	}

	printed, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("read pipe: %v", err)
	}
	if err := reader.Close(); err != nil {
		t.Fatalf("close pipe reader: %v", err)
	}
	return string(printed), actionErr
}

// setNodeEnvironment configures a complete environment for the subcommands that
// load a configuration, so a test exercises the command rather than the
// configuration checks.
func setNodeEnvironment(t *testing.T) string {
	t.Helper()

	configDir := t.TempDir()
	t.Setenv("CONNECTOR_NODE_SERVER_URL", "wss://127.0.0.1:8443/channel")
	t.Setenv("CONNECTOR_NODE_TUNNEL_TOKEN", "tunnel-token-of-sufficient-length")
	t.Setenv("CONNECTOR_NODE_CONFIG_DIR", configDir)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", "")
	return configDir
}

// TestSplitCommand checks the subcommand split, including the case that used to
// start the Node on a typo.
//
// A leading word that is not a known command must be returned as the command, so
// `run` reports it. Returning the default subcommand instead would start a Node
// that waits for a signal, and the operator would never learn about the typo.
func TestSplitCommand(t *testing.T) {
	cases := []struct {
		name        string
		arguments   []string
		wantCommand string
		wantRest    []string
	}{
		{"no arguments", nil, "", nil},
		{"run", []string{"run"}, "run", []string{}},
		{"id", []string{"id"}, "id", []string{}},
		{"regenerate", []string{"regenerate"}, "regenerate", []string{}},
		{"run with flags", []string{"run", "--verbose"}, "run", []string{"--verbose"}},
		{"leading long flag", []string{"--help"}, "", []string{"--help"}},
		{"leading short flag", []string{"-h"}, "", []string{"-h"}},
		{"unknown word", []string{"serve"}, "serve", []string{}},
		{"unknown word with flags", []string{"serve", "--port", "1"}, "serve", []string{"--port", "1"}},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			command, rest := splitCommand(testCase.arguments)
			if command != testCase.wantCommand {
				t.Fatalf("splitCommand(%v) command = %q, want %q", testCase.arguments, command, testCase.wantCommand)
			}
			if len(rest) != len(testCase.wantRest) {
				t.Fatalf("splitCommand(%v) rest = %v, want %v", testCase.arguments, rest, testCase.wantRest)
			}
			for index := range rest {
				if rest[index] != testCase.wantRest[index] {
					t.Fatalf("splitCommand(%v) rest = %v, want %v", testCase.arguments, rest, testCase.wantRest)
				}
			}
		})
	}
}

// TestRunRejectsAnUnknownCommand checks that a typo is reported rather than
// silently starting the Node, which is the defect the integration suite found as
// a hang instead of a failure.
func TestRunRejectsAnUnknownCommand(t *testing.T) {
	err := run([]string{"serve"})
	if err == nil {
		t.Fatal("run(serve) = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "unknown command") {
		t.Fatalf("run(serve) = %v, want a message naming an unknown command", err)
	}
	if !strings.Contains(err.Error(), "serve") {
		t.Fatalf("run(serve) = %v, want the message to name the rejected word", err)
	}
}

// TestRunIDPrintsTheNodeID checks that `id` prints the node id and nothing else, so it
// can be copied into a script.
func TestRunIDPrintsThePair(t *testing.T) {
	configDir := setNodeEnvironment(t)

	printed, err := captureStdout(t, func() error { return run([]string{"id"}) })
	if err != nil {
		t.Fatalf("run(id) = %v, want nil", err)
	}

	trimmed := strings.TrimSpace(printed)
	if trimmed == "" {
		t.Fatal("run(id) printed nothing, want the node id")
	}
	if strings.Contains(trimmed, ".") {
		t.Fatalf("run(id) printed %q, want no dot: the id is an address and the credential is a separate value", trimmed)
	}
	if strings.Contains(trimmed, "\n") {
		t.Fatalf("run(id) printed %q, want a single line", trimmed)
	}

	stored, err := node.LoadIdentity(node.IdentityPath(configDir))
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if stored != trimmed {
		t.Fatalf("run(id) printed %q, want the stored id %q", trimmed, stored)
	}
}

// TestRunIDIsStableAcrossCalls checks that `id` does not regenerate the id, because an
// id that changed on every call would invalidate the address the operator already
// distributed.
func TestRunIDIsStableAcrossCalls(t *testing.T) {
	setNodeEnvironment(t)

	first, err := captureStdout(t, func() error { return run([]string{"id"}) })
	if err != nil {
		t.Fatalf("first run(id) = %v, want nil", err)
	}
	second, err := captureStdout(t, func() error { return run([]string{"id"}) })
	if err != nil {
		t.Fatalf("second run(id) = %v, want nil", err)
	}
	if first != second {
		t.Fatalf("run(id) printed %q then %q, want the same id", first, second)
	}
}

// TestRunRegenerateReplacesTheID checks that `regenerate` writes a new id and prints
// it, because the operator has to copy the new address.
func TestRunRegenerateReplacesThePair(t *testing.T) {
	configDir := setNodeEnvironment(t)

	before, err := captureStdout(t, func() error { return run([]string{"id"}) })
	if err != nil {
		t.Fatalf("run(id) = %v, want nil", err)
	}

	after, err := captureStdout(t, func() error { return run([]string{"regenerate"}) })
	if err != nil {
		t.Fatalf("run(regenerate) = %v, want nil", err)
	}
	if strings.TrimSpace(after) == strings.TrimSpace(before) {
		t.Fatalf("run(regenerate) printed %q, want a new id", after)
	}

	stored, err := node.LoadIdentity(node.IdentityPath(configDir))
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if stored != strings.TrimSpace(after) {
		t.Fatalf("stored id = %q, want the printed id %q", stored, strings.TrimSpace(after))
	}
}

// TestRunRegenerateRejectsKeepID checks that `--keep-id` is refused rather than
// silently ignored.
//
// Regeneration now changes only the address, so keeping the address would make the
// command do nothing. A flag that is accepted and has no effect is a flag the operator
// believes took effect.
func TestRunRegenerateRejectsKeepID(t *testing.T) {
	setNodeEnvironment(t)

	if err := run([]string{"regenerate", "--keep-id"}); err == nil {
		t.Fatal("run(regenerate --keep-id) = nil error, want a flag refusal")
	}
}

// TestRunRejectsBadFlags checks that a flag a subcommand does not define is
// reported, because a silently ignored flag is a flag the operator believes took
// effect.
func TestRunRejectsBadFlags(t *testing.T) {
	setNodeEnvironment(t)

	for _, arguments := range [][]string{
		{"id", "--not-a-flag"},
		{"regenerate", "--not-a-flag"},
		{"run", "--not-a-flag"},
	} {
		if err := run(arguments); err == nil {
			t.Fatalf("run(%v) = nil error, want a flag refusal", arguments)
		}
	}
}

// TestRunNodeRejectsAnIncompleteEnvironment checks that `run` refuses to start
// without a configuration, because a Node that started with a missing secret
// would be a Node whose operator believes it is serving something it is not.
func TestRunNodeRejectsAnIncompleteEnvironment(t *testing.T) {
	t.Setenv("CONNECTOR_NODE_SERVER_URL", "")
	t.Setenv("CONNECTOR_NODE_TUNNEL_TOKEN", "")
	t.Setenv("CONNECTOR_NODE_CONFIG_DIR", t.TempDir())
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", "")

	if err := run([]string{"run"}); err == nil {
		t.Fatal("run(run) = nil error, want a configuration refusal")
	}
}

// TestRunNodeRejectsAMissingPolicy checks that `run` refuses to start when the
// policy file does not exist, because an empty policy is not an implicit allow.
func TestRunNodeRejectsAMissingPolicy(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", filepath.Join(configDir, "absent.yaml"))

	if err := run([]string{"run"}); err == nil {
		t.Fatal("run(run) = nil error, want a policy refusal")
	}
}

// TestContextFromSignalsCancelsOnSignal checks that a signal cancels the context
// the dialer runs under, so the deferred cleanup runs and the connection closes.
//
// The channel is a parameter rather than created inside the function, so the test
// can deliver a signal without sending one to the test process. Sending a real
// signal would make the test depend on the order in which two handlers register,
// and a mistake there would kill the test binary instead of failing the test.
func TestContextFromSignalsCancelsOnSignal(t *testing.T) {
	signals := make(chan os.Signal, 1)

	ctx, stop := contextFromSignals(signals)
	defer stop()

	signals <- os.Interrupt

	select {
	case <-ctx.Done():
	case <-timeoutAfter(t):
		t.Fatal("contextFromSignals() did not cancel after a signal")
	}
}

// TestContextFromSignalsStopsWithoutASignal checks that the cancel function
// releases the watcher even when no signal arrives, so a process that stops for
// another reason does not leave a goroutine waiting on a channel nobody sends to.
func TestContextFromSignalsStopsWithoutASignal(t *testing.T) {
	signals := make(chan os.Signal, 1)

	ctx, stop := contextFromSignals(signals)
	stop()

	select {
	case <-ctx.Done():
	case <-timeoutAfter(t):
		t.Fatal("stop() did not cancel the context")
	}
}

// timeoutAfter returns a channel that fires after a short deadline, so a test
// that waits for a goroutine fails instead of hanging the suite.
func timeoutAfter(t *testing.T) <-chan time.Time {
	t.Helper()
	return time.After(5 * time.Second)
}

// writeNodePolicy writes a policy that exposes one scope, so a test can open a
// runtime instead of failing on a missing policy.
func writeNodePolicy(t *testing.T, configDir string) string {
	t.Helper()

	// The scope is a sibling of the config directory, not a child of it. A scope
	// that contains the config directory could list the Node's own credentials,
	// which Open refuses at startup, so a fixture that nested the scope inside the
	// config directory would exercise the refusal instead of the code under test.
	scopeDir := t.TempDir()
	if err := os.MkdirAll(scopeDir, 0o755); err != nil {
		t.Fatalf("create scope directory: %v", err)
	}

	policyPath := filepath.Join(configDir, "policy.yaml")
	policy := "version: 1\n" +
		"scopes:\n" +
		"  project:\n" +
		"    path: " + scopeDir + "\n" +
		"grants:\n" +
		"  - scope: project\n" +
		"    permissions: [read, list, stat]\n"
	if err := os.WriteFile(policyPath, []byte(policy), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	return policyPath
}

// openNodeRuntime opens a runtime over a complete environment and a real policy,
// so a test can drive the tail of the process rather than the configuration
// checks that precede it.
func openNodeRuntime(t *testing.T) *node.Runtime {
	t.Helper()

	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	config, err := node.LoadConfig(os.Getenv)
	if err != nil {
		t.Fatalf("LoadConfig() error = %v", err)
	}

	runtime, err := node.Open(config, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatalf("Open() error = %v", err)
	}
	t.Cleanup(func() {
		if err := runtime.Close(); err != nil {
			t.Errorf("Close() error = %v", err)
		}
	})
	return runtime
}

// TestServeNodeStopsOnACancelledContext checks that the tail of the process
// returns as soon as the context is cancelled, because a shutdown must not wait
// for a reconnect delay or for a dial to time out.
//
// The context is a parameter rather than created inside the function, so the test
// drives the real dispatcher and the real dialer without signalling the test
// binary.
func TestServeNodeStopsOnACancelledContext(t *testing.T) {
	runtime := openNodeRuntime(t)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if err := serveNode(ctx, runtime, slog.New(slog.NewTextHandler(io.Discard, nil))); err != nil {
		t.Fatalf("serveNode() error = %v, want nil for a cancelled context", err)
	}
}

// TestServeNodeRefusesAnUnusableIdentity checks that the tail refuses to build a
// dialer from an identity the Server could never accept, because a Node that
// dialled with a malformed identity would appear connected and serve nothing.
//
// The check is exercised through the dialer constructor rather than through
// serveNode, because serveNode takes the identity from the runtime's holder and a
// runtime cannot be opened with an unusable identity: Open refuses it first. The
// constructor is the guard that still runs when a caller supplies its own holder.
func TestServeNodeRefusesAnUnusableIdentity(t *testing.T) {
	runtime := openNodeRuntime(t)

	// An empty id is refused by ValidateNodeID.
	holder := node.NewIdentityHolder("", runtime.IdentityHolder().Credentials())
	dispatcher, err := node.NewDispatcher(runtime.Authority(), holder, security.DefaultReplayWindow, security.DefaultReplayCapacity, nil)
	if err != nil {
		t.Fatalf("NewDispatcher() = %v, want nil", err)
	}

	if _, err := node.NewDialerWithHolder(runtime.Config(), holder, dispatcher, nil); err == nil {
		t.Fatal("NewDialerWithHolder() = nil error, want a refusal for an unusable identity")
	}
}

// TestServeNodeRetriesUntilTheContextEnds checks that the tail keeps retrying a
// Server that is not listening and still returns when the context ends, because a
// Node whose Server is down must wait rather than exit.
func TestServeNodeRetriesUntilTheContextEnds(t *testing.T) {
	runtime := openNodeRuntime(t)

	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()

	if err := serveNode(ctx, runtime, slog.New(slog.NewTextHandler(io.Discard, nil))); err != nil {
		t.Fatalf("serveNode() error = %v, want nil after the context ended", err)
	}
}

// TestRunNodeWithSignalsServesUntilASignalArrives checks the complete process:
// configuration, identity, policy, scopes, dial and shutdown.
//
// The signal channel is a parameter so the test delivers a signal without
// signalling the test binary. The Server address points at a closed port, so the
// dial fails and the retry loop is what the signal interrupts; that is the
// behaviour an operator relies on when the Server is down.
func TestRunNodeWithSignalsServesUntilASignalArrives(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	done := make(chan error, 1)
	go func() {
		done <- runNodeWithSignals(nil, signals)
	}()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("runNodeWithSignals() error = %v, want nil after a signal", err)
		}
	case <-timeoutAfter(t):
		t.Fatal("runNodeWithSignals() did not return after a signal")
	}
}

// TestRunNodeWithSignalsPrintsAGeneratedIdentity checks that a first start reports the
// generated id and credential, because the operator has to copy both and there is no
// lookup endpoint.
//
// The assertion is on the summary rather than on a "generated:" line, because the
// summary is what an operator reads. A test that only looked for the word "generated"
// would pass while the values themselves were missing.
func TestRunNodeWithSignalsPrintsAGeneratedIdentity(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	printed, err := captureStdout(t, func() error {
		return runNodeWithSignals(nil, signals)
	})
	if err != nil {
		t.Fatalf("runNodeWithSignals() error = %v", err)
	}
	if !strings.Contains(printed, "a new node id was written by this start") {
		t.Fatalf("stdout = %q, want the notice that the node id was generated", printed)
	}
	if !strings.Contains(printed, "a new credential was written by this start") {
		t.Fatalf("stdout = %q, want the notice that the credential was generated", printed)
	}
	if !strings.Contains(printed, "node id       : node_") {
		t.Fatalf("stdout = %q, want the node id in the summary", printed)
	}
	if !strings.Contains(printed, "key id        : ") {
		t.Fatalf("stdout = %q, want the key id in the summary", printed)
	}
}

// TestRunNodeWithOutputPrintsTheSecretOnATerminal checks that a human watching the
// terminal sees the whole credential.
//
// This is the requirement: starting the binary is enough to use it, so the value the
// operator must copy into a CLI has to appear. The assertion reads the credential file
// and requires the exact secret in the output, because a summary that printed a
// different value would be worse than one that printed none.
func TestRunNodeWithOutputPrintsTheSecretOnATerminal(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	var buffer strings.Builder
	if err := runNodeWithOutput(nil, signals, &buffer, true); err != nil {
		t.Fatalf("runNodeWithOutput() error = %v", err)
	}
	printed := buffer.String()

	credentials, err := node.LoadCredentialList(node.CredentialsPath(configDir))
	if err != nil {
		t.Fatalf("LoadCredentialList() error = %v", err)
	}
	if len(credentials) != 1 {
		t.Fatalf("credential file holds %d credentials, want 1", len(credentials))
	}
	secret := string(credentials[0].Secret)
	if !strings.Contains(printed, secret) {
		t.Fatalf("stdout = %q, want the secret %q on a terminal", printed, secret)
	}
	if !strings.Contains(printed, credentials[0].String()) {
		t.Fatalf("stdout = %q, want the copyable credential %q", printed, credentials[0].String())
	}
	if strings.Contains(printed, "withheld") {
		t.Fatalf("stdout = %q, want no withholding notice on a terminal", printed)
	}
}

// TestRunNodeWithOutputWithholdsTheSecretWhenRedirected checks that a redirected stdout
// does not receive the secret.
//
// This is the branch that protects a launcher which writes stdout to a log file. Without
// it, every start of such a launcher would append a credential that never expires to a
// file on disk, which is the leak the earlier print-once rule existed to prevent.
//
// The test asserts both halves: the secret is absent, and the summary is still present.
// A test that only asserted absence would pass if the whole summary were dropped, which
// would leave an operator with no information at all.
func TestRunNodeWithOutputWithholdsTheSecretWhenRedirected(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	var buffer strings.Builder
	if err := runNodeWithOutput(nil, signals, &buffer, false); err != nil {
		t.Fatalf("runNodeWithOutput() error = %v", err)
	}
	printed := buffer.String()

	credentials, err := node.LoadCredentialList(node.CredentialsPath(configDir))
	if err != nil {
		t.Fatalf("LoadCredentialList() error = %v", err)
	}
	if len(credentials) != 1 {
		t.Fatalf("credential file holds %d credentials, want 1", len(credentials))
	}
	secret := string(credentials[0].Secret)
	if strings.Contains(printed, secret) {
		t.Fatalf("stdout = %q, want the secret withheld when stdout is not a terminal", printed)
	}
	if !strings.Contains(printed, "withheld") {
		t.Fatalf("stdout = %q, want a notice explaining the secret was withheld", printed)
	}
	if !strings.Contains(printed, "node id       : node_") {
		t.Fatalf("stdout = %q, want the summary to still name the node", printed)
	}
	if !strings.Contains(printed, credentials[0].KeyID) {
		t.Fatalf("stdout = %q, want the public key id, which is not a secret", printed)
	}
}

// TestRunNodeWithOutputPrintsTheSummaryOnEveryStart checks that a second start reports
// the same values as the first.
//
// The earlier behaviour printed a generated credential once and never again, which left
// an operator who lost the scroll with no way to recover the value except reading the
// file by hand. The requirement is that a restart shows it again, so the test starts the
// Node twice against one config directory and requires the same credential both times.
func TestRunNodeWithOutputPrintsTheSummaryOnEveryStart(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	start := func() string {
		signals := make(chan os.Signal, 1)
		signals <- os.Interrupt
		var buffer strings.Builder
		if err := runNodeWithOutput(nil, signals, &buffer, true); err != nil {
			t.Fatalf("runNodeWithOutput() error = %v", err)
		}
		return buffer.String()
	}

	first := start()
	second := start()

	credentials, err := node.LoadCredentialList(node.CredentialsPath(configDir))
	if err != nil {
		t.Fatalf("LoadCredentialList() error = %v", err)
	}
	secret := string(credentials[0].Secret)

	if !strings.Contains(first, secret) {
		t.Fatalf("first start = %q, want the secret", first)
	}
	if !strings.Contains(second, secret) {
		t.Fatalf("second start = %q, want the same secret again", second)
	}
	if strings.Contains(second, "a new credential was written by this start") {
		t.Fatalf("second start = %q, want no generation notice, because nothing was generated", second)
	}
}

// TestRunNodeWithOutputNamesTheServerAndTheClientVariables checks that the summary
// carries the facts an operator needs to point a CLI at this Node.
//
// The requirement names the Server address, the key and the secret. The CLI variables
// are asserted too, because assembling four values by hand from a summary is where a
// copy-paste mistake happens, and a wrong value there fails as an authentication error
// that reads like a Server problem.
func TestRunNodeWithOutputNamesTheServerAndTheClientVariables(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	var buffer strings.Builder
	if err := runNodeWithOutput(nil, signals, &buffer, true); err != nil {
		t.Fatalf("runNodeWithOutput() error = %v", err)
	}
	printed := buffer.String()

	for _, want := range []string{
		"server        : wss://127.0.0.1:8443/channel",
		"CONNECTOR_CLI_SERVER_URL=https://127.0.0.1:8443",
		"CONNECTOR_CLI_NODE_ID=node_",
		"CONNECTOR_CLI_NODE_CREDENTIAL=",
		"CONNECTOR_CLI_CLIENT_CREDENTIAL=",
		"scopes        : project",
	} {
		if !strings.Contains(printed, want) {
			t.Fatalf("stdout = %q, want %q", printed, want)
		}
	}
}

// TestRunNodeWithOutputPrintsThePlaintextCLIAddress checks that a Node dialling a
// plaintext channel prints a plaintext CLI address.
//
// The scheme must be mapped, not replaced. A `ws://` channel is served by a plaintext
// HTTP listener, so `https://` in the summary sends the operator to a TLS handshake
// against a plaintext port, which fails with "server gave HTTP response to HTTPS
// client". That message names TLS, so the operator looks for a certificate problem
// rather than for the summary that produced the wrong line.
//
// This test exists separately from the `wss://` fixture because a fixture that dials
// `wss://` and asserts `https://` is consistent with either implementation: it cannot
// tell a mapped scheme from an unconditional one.
func TestRunNodeWithOutputPrintsThePlaintextCLIAddress(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_SERVER_URL", "ws://192.168.2.3:8743/channel")
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	var buffer strings.Builder
	if err := runNodeWithOutput(nil, signals, &buffer, true); err != nil {
		t.Fatalf("runNodeWithOutput() error = %v", err)
	}
	printed := buffer.String()

	for _, want := range []string{
		"server        : ws://192.168.2.3:8743/channel",
		"CONNECTOR_CLI_SERVER_URL=http://192.168.2.3:8743",
	} {
		if !strings.Contains(printed, want) {
			t.Fatalf("stdout = %q, want %q", printed, want)
		}
	}
	if strings.Contains(printed, "CONNECTOR_CLI_SERVER_URL=https://") {
		t.Fatalf("stdout = %q, want no https address for a plaintext channel", printed)
	}
}

// TestCLIServerURLRewritesTheChannelAddress checks the conversion from the address the
// Node dials to the address the CLI calls.
//
// The two are different surfaces on one listener: the Node dials /channel over a
// WebSocket and the CLI posts to /v1/ over HTTP. Printing the channel address as the CLI
// address would send an operator to a path that answers nothing.
func TestCLIServerURLRewritesTheChannelAddress(t *testing.T) {
	cases := []struct {
		name    string
		channel string
		want    string
	}{
		{"wss with channel path", "wss://cloud.example.com:8443/channel", "https://cloud.example.com:8443"},
		{"ws with channel path", "ws://192.168.2.3:8743/channel", "http://192.168.2.3:8743"},
		{"ws with trailing slash", "ws://192.168.2.3:8743/", "http://192.168.2.3:8743"},
		{"ws with no path", "ws://192.168.2.3:8743", "http://192.168.2.3:8743"},
		{"wss with trailing slash", "wss://cloud.example.com/", "https://cloud.example.com"},
		{"wss with no path", "wss://cloud.example.com", "https://cloud.example.com"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := cliServerURL(testCase.channel); got != testCase.want {
				t.Fatalf("cliServerURL(%q) = %q, want %q", testCase.channel, got, testCase.want)
			}
		})
	}
}

// TestRunNodeWithSignalsRejectsBadFlags checks that a flag `run` does not define
// is reported, because a silently ignored flag is a flag the operator believes
// took effect.
func TestRunNodeWithSignalsRejectsBadFlags(t *testing.T) {
	setNodeEnvironment(t)

	signals := make(chan os.Signal, 1)
	if err := runNodeWithSignals([]string{"--not-a-flag"}, signals); err == nil {
		t.Fatal("runNodeWithSignals() = nil error, want a flag refusal")
	}
}

// TestRunIDNeedsOnlyTheConfigDirectory checks that `id` works with no dial target
// and no tunnel token, because the documented first-run order runs `id` before
// the tunnel token is configured.
//
// This is the regression test for the defect where `id` called the full
// LoadConfig and therefore refused to print the pair until both dial variables
// were set. The failure was not cosmetic: README step 2 runs `id` and step 3
// supplies the tunnel token, so the documented order could not be executed at
// all, and the error message named a server address, which reads as "the Node
// needs a Server before it can have an identity" and inverts the design.
func TestRunIDNeedsOnlyTheConfigDirectory(t *testing.T) {
	configDir := t.TempDir()
	t.Setenv("CONNECTOR_NODE_SERVER_URL", "")
	t.Setenv("CONNECTOR_NODE_TUNNEL_TOKEN", "")
	t.Setenv("CONNECTOR_NODE_CONFIG_DIR", configDir)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", "")

	printed, err := captureStdout(t, func() error { return run([]string{"id"}) })
	if err != nil {
		t.Fatalf("run(id) with only the config directory = %v, want nil", err)
	}

	trimmed := strings.TrimSpace(printed)
	if trimmed == "" {
		t.Fatal("run(id) printed nothing, want the node id")
	}
	if strings.Contains(trimmed, ".") {
		t.Fatalf("run(id) printed %q, want no dot", trimmed)
	}

	stored, err := node.LoadIdentity(node.IdentityPath(configDir))
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if stored != trimmed {
		t.Fatalf("run(id) printed %q, want the stored id %q", trimmed, stored)
	}
}

// TestRunRegenerateNeedsOnlyTheConfigDirectory checks that `regenerate` works
// with no dial target and no tunnel token, for the same reason as `id`:
// regeneration rewrites a local file and never dials.
func TestRunRegenerateNeedsOnlyTheConfigDirectory(t *testing.T) {
	configDir := t.TempDir()
	t.Setenv("CONNECTOR_NODE_SERVER_URL", "")
	t.Setenv("CONNECTOR_NODE_TUNNEL_TOKEN", "")
	t.Setenv("CONNECTOR_NODE_CONFIG_DIR", configDir)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", "")

	before, err := captureStdout(t, func() error { return run([]string{"id"}) })
	if err != nil {
		t.Fatalf("run(id) = %v, want nil", err)
	}

	after, err := captureStdout(t, func() error {
		return run([]string{"regenerate"})
	})
	if err != nil {
		t.Fatalf("run(regenerate) with only the config directory = %v, want nil", err)
	}

	beforeID := strings.TrimSpace(before)
	afterID := strings.TrimSpace(after)
	if beforeID == afterID {
		t.Fatal("run(regenerate) printed the same id, want a new address")
	}
}

// TestRunStillRejectsAnIncompleteEnvironment checks that narrowing `id` and
// `regenerate` did not relax the dial path.
//
// The dial path must keep refusing to start without a secret, because a Node
// that started without one would be a Node whose operator believes it is serving
// something it is not. This test exists so a later change cannot widen the
// narrowing into a general relaxation.
func TestRunStillRejectsAnIncompleteEnvironment(t *testing.T) {
	t.Setenv("CONNECTOR_NODE_SERVER_URL", "")
	t.Setenv("CONNECTOR_NODE_TUNNEL_TOKEN", "")
	t.Setenv("CONNECTOR_NODE_CONFIG_DIR", t.TempDir())
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", "")

	err := run([]string{"run"})
	if err == nil {
		t.Fatal("run(run) = nil error, want a configuration refusal")
	}
	if !strings.Contains(err.Error(), "CONNECTOR_NODE_SERVER_URL") {
		t.Fatalf("run(run) = %v, want a message naming the missing dial target", err)
	}
}

// TestRunScopeListPrintsThePolicyNames checks the whole point of the command: an
// operator who does not want to open the policy file by hand gets the names.
//
// The assertion is on the exact printed text, not on a substring. A listing that
// printed a path, a grant or a heading would still contain the name, so a
// substring check would pass for output the operator cannot paste into --scope.
func TestRunScopeListPrintsThePolicyNames(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	printed, err := captureStdout(t, func() error {
		return run([]string{"scope", "list"})
	})
	if err != nil {
		t.Fatalf("run(scope list) = %v, want success", err)
	}
	if printed != "project\n" {
		t.Fatalf("run(scope list) printed %q, want %q", printed, "project\n")
	}
}

// TestRunScopeListPrintsEveryNameInSortedOrder checks that the listing is the
// whole set and that the order is stable.
//
// A listing that printed one name would satisfy a single-scope fixture, so this
// fixture defines three scopes whose file order is not their sorted order. The
// expected text is the sorted order, which is what the Node's startup report uses
// too, so an operator comparing the two sees the same sequence.
func TestRunScopeListPrintsEveryNameInSortedOrder(t *testing.T) {
	configDir := setNodeEnvironment(t)
	first := t.TempDir()
	second := t.TempDir()
	third := t.TempDir()

	policyPath := filepath.Join(configDir, "policy.yaml")
	policy := "version: 1\n" +
		"scopes:\n" +
		"  zebra:\n" +
		"    path: " + first + "\n" +
		"  alpha:\n" +
		"    path: " + second + "\n" +
		"  mike:\n" +
		"    path: " + third + "\n" +
		"grants:\n" +
		"  - scope: alpha\n" +
		"    permissions: [read]\n"
	if err := os.WriteFile(policyPath, []byte(policy), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", policyPath)

	printed, err := captureStdout(t, func() error {
		return run([]string{"scope", "list"})
	})
	if err != nil {
		t.Fatalf("run(scope list) = %v, want success", err)
	}
	if printed != "alpha\nmike\nzebra\n" {
		t.Fatalf("run(scope list) printed %q, want %q", printed, "alpha\nmike\nzebra\n")
	}
}

// TestRunScopeListPrintsNoPaths checks that the listing does not disclose the
// filesystem layout.
//
// A scope path is the Node's own directory structure, which the design keeps off
// the wire and out of the Server's knowledge. Printing it here would hand the
// operator's terminal a value the design deliberately withholds, and the operator
// does not need it: --scope takes a name.
func TestRunScopeListPrintsNoPaths(t *testing.T) {
	configDir := setNodeEnvironment(t)
	scopeDir := t.TempDir()

	policyPath := filepath.Join(configDir, "policy.yaml")
	policy := "version: 1\n" +
		"scopes:\n" +
		"  project:\n" +
		"    path: " + scopeDir + "\n"
	if err := os.WriteFile(policyPath, []byte(policy), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", policyPath)

	printed, err := captureStdout(t, func() error {
		return run([]string{"scope", "list"})
	})
	if err != nil {
		t.Fatalf("run(scope list) = %v, want success", err)
	}
	if strings.Contains(printed, scopeDir) {
		t.Fatalf("run(scope list) printed the scope path %q in %q", scopeDir, printed)
	}
}

// TestRunScopeListListsAScopeWhoseDirectoryIsAbsent checks the case the command
// exists for: an operator writing a policy before the directories exist.
//
// Opening the scope would refuse here, because a scope root that is absent is
// tolerated at startup but a listing that opened scopes would still have to
// decide what to do with the handle. The names are what the operator wrote, so
// they are printed regardless.
func TestRunScopeListListsAScopeWhoseDirectoryIsAbsent(t *testing.T) {
	configDir := setNodeEnvironment(t)
	absent := filepath.Join(t.TempDir(), "not-created-yet")

	policyPath := filepath.Join(configDir, "policy.yaml")
	policy := "version: 1\n" +
		"scopes:\n" +
		"  pending:\n" +
		"    path: " + absent + "\n"
	if err := os.WriteFile(policyPath, []byte(policy), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", policyPath)

	printed, err := captureStdout(t, func() error {
		return run([]string{"scope", "list"})
	})
	if err != nil {
		t.Fatalf("run(scope list) = %v, want success for an absent scope directory", err)
	}
	if printed != "pending\n" {
		t.Fatalf("run(scope list) printed %q, want %q", printed, "pending\n")
	}
}

// TestRunScopeListPrintsNothingForAnEmptyPolicy checks that a policy with no
// scopes prints nothing and still succeeds.
//
// An empty policy is valid and refuses everything, so the listing must be empty
// rather than an error. Printing a heading or a "no scopes" line would make the
// output unusable as a list, and a script that reads it would treat the heading
// as a scope name.
func TestRunScopeListPrintsNothingForAnEmptyPolicy(t *testing.T) {
	configDir := setNodeEnvironment(t)
	policyPath := filepath.Join(configDir, "policy.yaml")
	if err := os.WriteFile(policyPath, []byte("version: 1\n"), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", policyPath)

	printed, err := captureStdout(t, func() error {
		return run([]string{"scope", "list"})
	})
	if err != nil {
		t.Fatalf("run(scope list) = %v, want success for an empty policy", err)
	}
	if printed != "" {
		t.Fatalf("run(scope list) printed %q, want no output", printed)
	}
}

// TestRunScopeListRejectsAMissingPolicy checks that a missing policy file is a
// failure rather than an empty listing.
//
// The distinction matters: an empty listing reads as "this Node defines no
// scopes", which is a working Node that denies everything. A missing file is a
// configuration mistake, and reporting it as an empty list would send the
// operator looking for a policy problem in the wrong place.
func TestRunScopeListRejectsAMissingPolicy(t *testing.T) {
	setNodeEnvironment(t)

	_, err := captureStdout(t, func() error {
		return run([]string{"scope", "list"})
	})
	if err == nil {
		t.Fatal("run(scope list) = nil error, want a failure for a missing policy file")
	}
}

// TestRunScopeListRejectsAMalformedPolicy checks that the listing uses the same
// strict decoder the Node uses at startup.
//
// A second, looser parser would list names the Node then refuses to serve, which
// is the divergence the shared decoder exists to prevent. The fixture is a
// relative scope path, which the decoder refuses and the fence also refuses.
func TestRunScopeListRejectsAMalformedPolicy(t *testing.T) {
	configDir := setNodeEnvironment(t)
	policyPath := filepath.Join(configDir, "policy.yaml")
	policy := "version: 1\nscopes:\n  project:\n    path: relative/path\n"
	if err := os.WriteFile(policyPath, []byte(policy), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", policyPath)

	_, err := captureStdout(t, func() error {
		return run([]string{"scope", "list"})
	})
	if err == nil {
		t.Fatal("run(scope list) = nil error, want a failure for a relative scope path")
	}
	if !strings.Contains(err.Error(), "is relative") {
		t.Fatalf("run(scope list) = %v, want a message naming the relative path", err)
	}
}

// TestRunScopeNeedsASubcommand checks that a bare `scope` is a usage error.
//
// The word names a noun, so an operator who types it is asking about scopes
// rather than asking for a listing. Printing the list would make a future
// `scope show` unreachable, and exiting 0 would tell a script the command
// succeeded when it never ran.
func TestRunScopeNeedsASubcommand(t *testing.T) {
	setNodeEnvironment(t)

	err := run([]string{"scope"})
	if err == nil {
		t.Fatal("run(scope) = nil error, want a usage refusal")
	}
	if !strings.HasPrefix(err.Error(), "usage:") {
		t.Fatalf("run(scope) = %v, want a message beginning with usage:", err)
	}
}

// TestRunScopeRejectsAnUnknownSubcommand checks that a typo is refused rather
// than treated as a listing.
//
// A command that fell through to the listing would print names for `scope lst`,
// so the operator would believe the typo worked and never learn the correct
// spelling.
func TestRunScopeRejectsAnUnknownSubcommand(t *testing.T) {
	setNodeEnvironment(t)

	err := run([]string{"scope", "lst"})
	if err == nil {
		t.Fatal("run(scope lst) = nil error, want a usage refusal")
	}
	if !strings.HasPrefix(err.Error(), "usage:") {
		t.Fatalf("run(scope lst) = %v, want a message beginning with usage:", err)
	}
	if !strings.Contains(err.Error(), "lst") {
		t.Fatalf("run(scope lst) = %v, want a message naming the rejected subcommand", err)
	}
}

// TestRunScopeListRejectsStrayArguments checks that an extra positional argument
// is refused.
//
// `scope list project` looks like a filter, and silently ignoring the word would
// teach the operator that a filter exists. Refusing it keeps the accepted
// grammar small enough to state in the help page.
func TestRunScopeListRejectsStrayArguments(t *testing.T) {
	configDir := setNodeEnvironment(t)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", writeNodePolicy(t, configDir))

	_, err := captureStdout(t, func() error {
		return run([]string{"scope", "list", "project"})
	})
	if err == nil {
		t.Fatal("run(scope list project) = nil error, want a usage refusal")
	}
	if !strings.HasPrefix(err.Error(), "usage:") {
		t.Fatalf("run(scope list project) = %v, want a message beginning with usage:", err)
	}
}
