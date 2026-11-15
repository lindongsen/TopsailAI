package main

import (
	"strings"
	"testing"
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
func TestRunServerRejectsAMissingSecret(t *testing.T) {
	// The environment is cleared for the duration of the call, so a secret that
	// happens to be set in the test runner's environment cannot make this pass.
	t.Setenv("CONNECTOR_SERVER_TUNNEL_TOKEN", "")
	t.Setenv("CONNECTOR_SERVER_CLIENT_TOKEN", "")

	err := runServer(nil)
	if err == nil {
		t.Fatal("runServer with no secrets = nil error, want a startup failure")
	}
	if !strings.Contains(err.Error(), "CONNECTOR_SERVER_TUNNEL_TOKEN") {
		t.Fatalf("runServer = %v, want the message to name the missing variable", err)
	}
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
	t.Setenv("CONNECTOR_SERVER_LISTEN", "not-an-address")
	t.Setenv("CONNECTOR_SERVER_TUNNEL_TOKEN", strings.Repeat("a", 32))
	t.Setenv("CONNECTOR_SERVER_CLIENT_TOKEN", strings.Repeat("b", 32))

	err := runServer(nil)
	if err == nil {
		t.Fatal("runServer with an invalid listen address = nil error, want a refusal")
	}
}
