package main

import (
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_connector/internal/node"
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

// TestWaitForShutdownReturnsOnSignal checks that the wait returns when a signal
// arrives, so the deferred cleanup runs.
//
// The channel is a parameter rather than created inside the function, so the test
// can deliver a signal without sending one to the test process. Sending a real
// signal would make the test depend on the order in which two handlers register,
// and a mistake there would kill the test binary instead of failing the test.
func TestWaitForShutdownReturnsOnSignal(t *testing.T) {
	signals := make(chan os.Signal, 1)
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))

	done := make(chan error, 1)
	go func() { done <- waitForShutdown(logger, signals) }()

	signals <- os.Interrupt

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("waitForShutdown() = %v, want nil", err)
		}
	case <-timeoutAfter(t):
		t.Fatal("waitForShutdown() did not return after a signal")
	}
}

// timeoutAfter returns a channel that fires after a short deadline, so a test
// that waits for a goroutine fails instead of hanging the suite.
func timeoutAfter(t *testing.T) <-chan time.Time {
	t.Helper()
	return time.After(5 * time.Second)
}
