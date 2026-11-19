package main

import (
	"os"
	"strings"
	"testing"
)

// captureStreams runs a function with stdout and stderr redirected to temporary files and
// returns what each received.
//
// The streams are redirected rather than the function being changed to accept writers,
// because the property under test is what the process prints. A function that took a
// writer would prove the writer received the text, not that the operator sees it.
func captureStreams(t *testing.T, action func() error) (string, string, error) {
	t.Helper()

	stdoutFile, err := os.CreateTemp(t.TempDir(), "stdout")
	if err != nil {
		t.Fatalf("create stdout file: %v", err)
	}
	stderrFile, err := os.CreateTemp(t.TempDir(), "stderr")
	if err != nil {
		t.Fatalf("create stderr file: %v", err)
	}

	originalStdout, originalStderr := os.Stdout, os.Stderr
	os.Stdout, os.Stderr = stdoutFile, stderrFile
	defer func() {
		os.Stdout, os.Stderr = originalStdout, originalStderr
	}()

	actionErr := action()

	os.Stdout, os.Stderr = originalStdout, originalStderr

	stdout, err := os.ReadFile(stdoutFile.Name())
	if err != nil {
		t.Fatalf("read stdout: %v", err)
	}
	stderr, err := os.ReadFile(stderrFile.Name())
	if err != nil {
		t.Fatalf("read stderr: %v", err)
	}
	return string(stdout), string(stderr), actionErr
}

// TestHelpExitsZeroOnStdout checks the ordinary help request.
//
// The status is the part that matters: a help request succeeded at what it asked for, so
// a script that runs `--help` to check an installation must not see a failure.
func TestHelpExitsZeroOnStdout(t *testing.T) {
	for _, arguments := range [][]string{{"--help"}, {"-h"}, {"help"}} {
		stdout, stderr, err := captureStreams(t, func() error { return run(arguments) })
		if err != nil {
			t.Fatalf("run(%v) = %v, want nil", arguments, err)
		}
		if status := exitStatus(err); status != 0 {
			t.Errorf("run(%v) status = %d, want 0", arguments, status)
		}
		if !strings.Contains(stdout, "NAME") {
			t.Errorf("run(%v) stdout = %q, want the help text", arguments, stdout)
		}
		if stderr != "" {
			t.Errorf("run(%v) stderr = %q, want nothing", arguments, stderr)
		}
	}
}

// TestVersionExitsZeroOnStdout checks the version request.
func TestVersionExitsZeroOnStdout(t *testing.T) {
	stdout, _, err := captureStreams(t, func() error { return run([]string{"--version"}) })
	if err != nil {
		t.Fatalf("run(--version) = %v, want nil", err)
	}
	if !strings.Contains(stdout, "connector-server") {
		t.Errorf("stdout = %q, want the program name", stdout)
	}
}

// TestHelpForASubcommandPrintsThatPage checks the named form.
func TestHelpForASubcommandPrintsThatPage(t *testing.T) {
	stdout, _, err := captureStreams(t, func() error { return run([]string{"help", "run"}) })
	if err != nil {
		t.Fatalf("run(help run) = %v, want nil", err)
	}
	if !strings.Contains(stdout, "connector-server run") {
		t.Errorf("stdout = %q, want the run page", stdout)
	}
}

// TestHelpForAnUnknownSubcommandExitsTwo checks that a name the binary does not offer is
// refused rather than answered with the main page.
func TestHelpForAnUnknownSubcommandExitsTwo(t *testing.T) {
	stdout, stderr, err := captureStreams(t, func() error { return run([]string{"help", "nosuch"}) })
	if err == nil {
		t.Fatal("run(help nosuch) = nil, want a refusal")
	}
	if status := exitStatus(err); status != 2 {
		t.Errorf("status = %d, want 2", status)
	}
	if stdout != "" {
		t.Errorf("stdout = %q, want nothing", stdout)
	}
	if !strings.Contains(stderr, "usage:") {
		t.Errorf("stderr = %q, want a usage: message", stderr)
	}
}

// TestAUsageRefusalIsPrintedOnce is the regression test for the double print.
//
// The refusal is written by the help dispatcher and carried back as a status. A caller
// that printed every error it received would show the operator the same sentence twice,
// and the second copy would look like a second failure.
func TestAUsageRefusalIsPrintedOnce(t *testing.T) {
	_, stderr, err := captureStreams(t, func() error { return run([]string{"help", "nosuch"}) })
	if err == nil {
		t.Fatal("run(help nosuch) = nil, want a refusal")
	}

	// exitStatus is what main calls, and it must not print the message again.
	_, printedAgain, _ := captureStreams(t, func() error {
		exitStatus(err)
		return nil
	})
	if printedAgain != "" {
		t.Errorf("exitStatus printed %q, want nothing: the message was already written", printedAgain)
	}
	if count := strings.Count(stderr, "has no subcommand"); count != 1 {
		t.Errorf("the refusal appears %d times in stderr, want 1: %q", count, stderr)
	}
}

// TestAnUnknownCommandExitsTwo checks the typo case.
//
// The status and the message are produced by two functions, so the test drives the pair
// the way main does. Capturing only run would see no message, because run returns the
// error and exitStatus writes it.
func TestAnUnknownCommandExitsTwo(t *testing.T) {
	var status int
	_, stderr, _ := captureStreams(t, func() error {
		status = exitStatus(run([]string{"nosuchcmd"}))
		return nil
	})
	if status != 2 {
		t.Errorf("status = %d, want 2", status)
	}
	if !strings.Contains(stderr, "usage:") {
		t.Errorf("stderr = %q, want a usage: message", stderr)
	}
}

// TestABadFlagExitsTwoWithOneMessage checks that the flag parser's own output is
// suppressed.
//
// The parser writes its error and a `Usage of run:` line to stderr before returning. That
// line names an internal FlagSet rather than the program, and printing it beside the real
// message shows the operator the same failure twice, once with a name they cannot type.
func TestABadFlagExitsTwoWithOneMessage(t *testing.T) {
	var status int
	_, stderr, _ := captureStreams(t, func() error {
		status = exitStatus(run([]string{"--nonsense"}))
		return nil
	})
	if status != 2 {
		t.Errorf("status = %d, want 2", status)
	}
	if strings.Contains(stderr, "Usage of run") {
		t.Errorf("stderr = %q, want no internal FlagSet usage line", stderr)
	}
	if count := strings.Count(stderr, "not defined"); count != 1 {
		t.Errorf("the message appears %d times, want 1: %q", count, stderr)
	}
}

// TestAStartupFailureExitsOne checks that a real failure is not reported as a usage error.
//
// The distinction is the whole point of the two statuses: a missing secret is a
// configuration problem, not a rejected command line, and a script that retried on 2
// would retry a command that can never succeed.
func TestAStartupFailureExitsOne(t *testing.T) {
	t.Setenv("CONNECTOR_SERVER_TUNNEL_TOKEN", "")
	t.Setenv("CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE", "")

	var status int
	_, stderr, _ := captureStreams(t, func() error {
		status = exitStatus(run([]string{"run"}))
		return nil
	})
	if status != 1 {
		t.Errorf("status = %d, want 1", status)
	}
	if strings.Contains(stderr, "usage:") {
		t.Errorf("stderr = %q, want no usage: prefix on a configuration failure", stderr)
	}
}

// TestTheCLIStatusIsPropagated checks that the cli subcommand's own status reaches main.
//
// The subcommand decides its status because a CLI must exit non-zero on an error code.
// A run that swallowed it would report success for a failed request.
func TestTheCLIStatusIsPropagated(t *testing.T) {
	_, _, err := captureStreams(t, func() error { return run([]string{"cli"}) })
	if err == nil {
		t.Fatal("run(cli) with no arguments = nil, want a status")
	}
	if status := exitStatus(err); status != 2 {
		t.Errorf("status = %d, want 2: the cli subcommand refuses a missing operation", status)
	}
}

// TestExitStatusOfNilIsZero checks the success case.
func TestExitStatusOfNilIsZero(t *testing.T) {
	if status := exitStatus(nil); status != 0 {
		t.Errorf("exitStatus(nil) = %d, want 0", status)
	}
}
