package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/security"
)

// TestSplitCommand checks the subcommand split, which is the only place a typo
// can turn into a silently started Server.
//
// The cases mirror the Node's own table so the two binaries cannot drift into
// disagreeing about what a leading word means.
func TestSplitCommand(t *testing.T) {
	cases := []struct {
		name        string
		arguments   []string
		wantCommand string
		wantRest    []string
	}{
		{"no arguments", nil, "", nil},
		{"run", []string{"run"}, "run", []string{}},
		{"cli", []string{"cli"}, "cli", []string{}},
		{"run with flags", []string{"run", "--listen", ":8443"}, "run", []string{"--listen", ":8443"}},
		{"cli with flags", []string{"cli", "--server", "https://x"}, "cli", []string{"--server", "https://x"}},
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
// silently starting the Server.
//
// Starting the default subcommand on an unrecognised word would bind the port and
// look healthy, so the operator would never learn that the command they typed does
// not exist.
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

// TestRunServerRejectsAMissingSecret checks that a Server with no configured
// secret refuses to start.
//
// This is the property the whole three-secret design rests on: an unset
// environment variable is the most likely way to accidentally disable
// authentication, so it must be a startup failure rather than an "accept
// anything" mode.
//
// Both Server-owned gates are covered. A test that clears only one of them proves
// only that one of them is required, and the second gate fails differently: a
// Server with a tunnel token and no client credential accepts a channel and then
// refuses every caller, which looks like a working Server that denies everything.
func TestRunServerRejectsAMissingSecret(t *testing.T) {
	cases := []struct {
		name        string
		environment map[string]string
		wantMessage string
	}{
		{
			name: "no tunnel token",
			environment: map[string]string{
				"CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE": writeClientCredentialFile(t),
			},
			wantMessage: "CONNECTOR_SERVER_TUNNEL_TOKEN",
		},
		{
			name: "no client credential file",
			environment: map[string]string{
				"CONNECTOR_SERVER_TUNNEL_TOKEN": strings.Repeat("a", 32),
			},
			wantMessage: "CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE",
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			clearServerEnvironment(t)
			for name, value := range testCase.environment {
				t.Setenv(name, value)
			}

			err := runServer(nil)
			if err == nil {
				t.Fatal("runServer with a missing secret = nil error, want a startup failure")
			}
			if !strings.Contains(err.Error(), testCase.wantMessage) {
				t.Fatalf("runServer = %v, want the message to name %s", err, testCase.wantMessage)
			}
		})
	}
}

// clearServerEnvironment unsets every variable LoadConfig reads, so a value that
// happens to be set in the test runner's environment cannot decide the outcome.
//
// Clearing only the variable under test would leave the others ambient, and an
// ambient CONNECTOR_SERVER_LISTEN would fail validation before the secret was
// reached, so the test would pass while measuring a different refusal.
func clearServerEnvironment(t *testing.T) {
	t.Helper()
	for _, name := range []string{
		"CONNECTOR_SERVER_LISTEN",
		"CONNECTOR_SERVER_TLS_CERT",
		"CONNECTOR_SERVER_TLS_KEY",
		"CONNECTOR_SERVER_TUNNEL_TOKEN",
		"CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE",
		"CONNECTOR_SERVER_REPLAY_WINDOW_SECONDS",
		"CONNECTOR_SERVER_REPLAY_CAPACITY",
		"CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS",
	} {
		t.Setenv(name, "")
	}
}

// writeClientCredentialFile writes a one-entry client credential file and returns
// its path.
//
// The file is written with the mode the Server requires, so a test that needs a
// valid credential measures the refusal it is about rather than a file-mode
// refusal. The credential is generated rather than hardcoded, because a hardcoded
// secret in a test file is a secret in the repository.
func writeClientCredentialFile(t *testing.T) string {
	t.Helper()
	credential, err := security.NewCredentialWithKeyID("operator")
	if err != nil {
		t.Fatalf("NewCredentialWithKeyID() = %v", err)
	}
	content, err := security.FormatCredentialSet([]security.Credential{credential})
	if err != nil {
		t.Fatalf("FormatCredentialSet() = %v", err)
	}
	path := filepath.Join(t.TempDir(), "client-credentials.yaml")
	if err := os.WriteFile(path, content, 0o600); err != nil {
		t.Fatalf("write credential file: %v", err)
	}
	return path
}

// TestRunServerRejectsBadFlags checks that an unparsable flag is reported instead
// of being ignored.
func TestRunServerRejectsBadFlags(t *testing.T) {
	err := runServer([]string{"--no-such-flag"})
	if err == nil {
		t.Fatal("runServer with an unknown flag = nil error, want a refusal")
	}
}

// TestRunServerRejectsAnInvalidListenAddress checks that a malformed listen
// address fails startup rather than binding something unintended.
func TestRunServerRejectsAnInvalidListenAddress(t *testing.T) {
	clearServerEnvironment(t)
	t.Setenv("CONNECTOR_SERVER_LISTEN", "not-an-address")
	t.Setenv("CONNECTOR_SERVER_TUNNEL_TOKEN", strings.Repeat("a", 32))
	t.Setenv("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE", writeClientCredentialFile(t))

	err := runServer(nil)
	if err == nil {
		t.Fatal("runServer with an invalid listen address = nil error, want a refusal")
	}
}
