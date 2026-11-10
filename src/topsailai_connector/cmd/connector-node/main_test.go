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

// TestRunIDPrintsThePair checks that `id` prints the pair and nothing else, so it
// can be copied into a script.
func TestRunIDPrintsThePair(t *testing.T) {
	configDir := setNodeEnvironment(t)

	printed, err := captureStdout(t, func() error { return run([]string{"id"}) })
	if err != nil {
		t.Fatalf("run(id) = %v, want nil", err)
	}

	trimmed := strings.TrimSpace(printed)
	if trimmed == "" {
		t.Fatal("run(id) printed nothing, want the pair")
	}
	if strings.Count(trimmed, ".") != 1 {
		t.Fatalf("run(id) printed %q, want exactly one dot", trimmed)
	}
	if strings.Contains(trimmed, "\n") {
		t.Fatalf("run(id) printed %q, want a single line", trimmed)
	}

	identity, err := node.LoadIdentity(node.IdentityPath(configDir))
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if identity.String() != trimmed {
		t.Fatalf("run(id) printed %q, want the stored pair %q", trimmed, identity.String())
	}
}

// TestRunIDIsStableAcrossCalls checks that `id` does not regenerate the pair,
// because a pair that changed on every call would invalidate the copy the
// operator already distributed.
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
		t.Fatalf("run(id) printed %q then %q, want the same pair", first, second)
	}
}

// TestRunRegenerateReplacesThePair checks that `regenerate` writes a new pair and
// prints it, because the operator has to copy the new value.
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
		t.Fatalf("run(regenerate) printed %q, want a new pair", after)
	}

	stored, err := node.LoadIdentity(node.IdentityPath(configDir))
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if stored.String() != strings.TrimSpace(after) {
		t.Fatalf("stored pair = %q, want the printed pair %q", stored.String(), strings.TrimSpace(after))
	}
}

// TestRunRegenerateKeepIDKeepsTheIdentifier checks that --keep-id preserves the
// routing name while replacing the secret, because the CLI's target must stay
// valid while the credential changes.
func TestRunRegenerateKeepIDKeepsTheIdentifier(t *testing.T) {
	configDir := setNodeEnvironment(t)

	before, err := captureStdout(t, func() error { return run([]string{"id"}) })
	if err != nil {
		t.Fatalf("run(id) = %v, want nil", err)
	}
	original, err := node.LoadIdentity(node.IdentityPath(configDir))
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}

	after, err := captureStdout(t, func() error { return run([]string{"regenerate", "--keep-id"}) })
	if err != nil {
		t.Fatalf("run(regenerate --keep-id) = %v, want nil", err)
	}

	regenerated, err := node.LoadIdentity(node.IdentityPath(configDir))
	if err != nil {
		t.Fatalf("LoadIdentity() = %v, want nil", err)
	}
	if regenerated.ID != original.ID {
		t.Fatalf("regenerated id = %q, want %q", regenerated.ID, original.ID)
	}
	if regenerated.Token.Equal(original.Token) {
		t.Fatal("regenerated token equals the original, want a new token")
	}
	if strings.TrimSpace(after) == strings.TrimSpace(before) {
		t.Fatalf("run(regenerate --keep-id) printed %q, want a new pair", after)
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

	scopeDir := filepath.Join(configDir, "project")
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
	identity, _ := runtime.NewIdentity()

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if err := serveNode(ctx, runtime, identity, slog.New(slog.NewTextHandler(io.Discard, nil))); err != nil {
		t.Fatalf("serveNode() error = %v, want nil for a cancelled context", err)
	}
}

// TestServeNodeRefusesAnUnusableIdentity checks that the tail refuses to build a
// dialer from an identity the Server could never accept, because a Node that
// dialled with a malformed identity would appear connected and serve nothing.
func TestServeNodeRefusesAnUnusableIdentity(t *testing.T) {
	runtime := openNodeRuntime(t)

	// An empty id is refused by ValidateNodeID. A short id is not, which is the
	// recorded defect in issues/issue-node-id-length-not-enforced.md.
	broken := security.NodeIdentity{ID: "", Token: security.Secret("tokenvalue")}
	if err := serveNode(context.Background(), runtime, broken, slog.New(slog.NewTextHandler(io.Discard, nil))); err == nil {
		t.Fatal("serveNode() = nil error, want a refusal for an unusable identity")
	}
}

// TestServeNodeRetriesUntilTheContextEnds checks that the tail keeps retrying a
// Server that is not listening and still returns when the context ends, because a
// Node whose Server is down must wait rather than exit.
func TestServeNodeRetriesUntilTheContextEnds(t *testing.T) {
	runtime := openNodeRuntime(t)
	identity, _ := runtime.NewIdentity()

	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()

	if err := serveNode(ctx, runtime, identity, slog.New(slog.NewTextHandler(io.Discard, nil))); err != nil {
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

// TestRunNodeWithSignalsPrintsAGeneratedIdentity checks that a first start prints
// the pair once, because the operator has to copy it into a CLI and there is no
// lookup endpoint.
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
	if !strings.Contains(printed, "node identity generated:") {
		t.Fatalf("stdout = %q, want the generated pair", printed)
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
