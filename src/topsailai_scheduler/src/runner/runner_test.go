package runner

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// TestRunCapturesOutputAndExitCode verifies that a successful run reports exit
// code zero and the child's combined output.
func TestRunCapturesOutputAndExitCode(t *testing.T) {
	result := Run(context.Background(), Request{
		Command: "/bin/sh",
		Args:    []string{"-c", "echo hello; echo oops >&2"},
	})

	if result.Err != nil {
		t.Fatalf("unexpected error: %v", result.Err)
	}
	if result.ExitCode != 0 {
		t.Errorf("expected exit code 0, got %d", result.ExitCode)
	}
	if !strings.Contains(result.Output, "hello") || !strings.Contains(result.Output, "oops") {
		t.Errorf("expected both streams in the output, got %q", result.Output)
	}
	if result.TimedOut || result.Canceled {
		t.Error("a successful run must not be flagged as timed out or canceled")
	}
}

// TestRunNonZeroExitIsNotAnError verifies that a failing task is a normal
// outcome reported through the exit code, not a runner error.
func TestRunNonZeroExitIsNotAnError(t *testing.T) {
	result := Run(context.Background(), Request{
		Command: "/bin/sh",
		Args:    []string{"-c", "exit 3"},
	})

	if result.Err != nil {
		t.Fatalf("a non-zero exit must not be an error, got %v", result.Err)
	}
	if result.ExitCode != 3 {
		t.Errorf("expected exit code 3, got %d", result.ExitCode)
	}
}

// TestRunEmptyCommandIsAnError verifies that a missing command is rejected
// before any process is started.
func TestRunEmptyCommandIsAnError(t *testing.T) {
	result := Run(context.Background(), Request{Command: "  "})
	if result.Err == nil {
		t.Fatal("expected an error for an empty command")
	}
	if result.ExitCode != -1 {
		t.Errorf("expected exit code -1, got %d", result.ExitCode)
	}
}

// TestRunMissingBinaryIsAnError verifies that a command that cannot be started
// is reported as an error rather than a silent success.
func TestRunMissingBinaryIsAnError(t *testing.T) {
	result := Run(context.Background(), Request{Command: "/nonexistent/binary"})
	if result.Err == nil {
		t.Fatal("expected an error for a missing binary")
	}
	if result.ExitCode != -1 {
		t.Errorf("expected exit code -1, got %d", result.ExitCode)
	}
}

// TestRunTimeoutKillsTheRun verifies that a run exceeding its timeout is killed
// and flagged, so a hung task cannot hold its lock forever.
func TestRunTimeoutKillsTheRun(t *testing.T) {
	started := time.Now()
	result := Run(context.Background(), Request{
		Command: "/bin/sleep",
		Args:    []string{"30"},
		Timeout: 200 * time.Millisecond,
	})
	elapsed := time.Since(started)

	if !result.TimedOut {
		t.Fatalf("expected the run to be flagged as timed out, got %+v", result)
	}
	if elapsed > 10*time.Second {
		t.Errorf("expected the run to end promptly, took %v", elapsed)
	}
	if result.ExitCode != -1 {
		t.Errorf("expected exit code -1 for a killed run, got %d", result.ExitCode)
	}
}

// TestRunTimeoutKillsChildren verifies that a timeout terminates the whole
// process group, so a grandchild cannot survive as an orphan holding the lock.
func TestRunTimeoutKillsChildren(t *testing.T) {
	pidFile := filepath.Join(t.TempDir(), "child.pid")

	// The shell starts a long sleep in the background, records its pid, then
	// waits. Killing only the shell would leave the sleep running.
	script := "sleep 30 & echo $! > " + pidFile + "; wait"

	result := Run(context.Background(), Request{
		Command: "/bin/sh",
		Args:    []string{"-c", script},
		Timeout: 300 * time.Millisecond,
	})
	if !result.TimedOut {
		t.Fatalf("expected a timeout, got %+v", result)
	}

	raw, err := os.ReadFile(pidFile)
	if err != nil {
		t.Fatalf("read child pid: %v", err)
	}
	childPID, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil {
		t.Fatalf("parse child pid %q: %v", raw, err)
	}

	// The grandchild must be gone. Signal 0 only probes for existence.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if syscall.Kill(childPID, 0) != nil {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("grandchild %d survived the timeout", childPID)
}

// TestRunContextCancel verifies that cancelling the context stops the run and is
// reported as canceled rather than timed out.
func TestRunContextCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(150 * time.Millisecond)
		cancel()
	}()

	result := Run(ctx, Request{Command: "/bin/sleep", Args: []string{"30"}})
	if !result.Canceled {
		t.Fatalf("expected the run to be flagged as canceled, got %+v", result)
	}
	if result.TimedOut {
		t.Error("a canceled run must not be flagged as timed out")
	}
}

// TestRunOnStartReceivesPID verifies that the start callback reports the child
// pid, which is how the daemon records and later stops a run.
func TestRunOnStartReceivesPID(t *testing.T) {
	var reported int
	result := Run(context.Background(), Request{
		Command: "/bin/sh",
		Args:    []string{"-c", "exit 0"},
		OnStart: func(pid int) { reported = pid },
	})

	if result.Err != nil {
		t.Fatalf("unexpected error: %v", result.Err)
	}
	if reported <= 0 {
		t.Fatalf("expected a positive pid, got %d", reported)
	}
}

// TestRunTruncatesOutput verifies that retained output is capped and flagged, so
// a chatty task cannot exhaust memory.
func TestRunTruncatesOutput(t *testing.T) {
	result := Run(context.Background(), Request{
		Command:        "/bin/sh",
		Args:           []string{"-c", "printf 'x%.0s' $(seq 1 5000)"},
		MaxOutputBytes: 100,
	})

	if result.Err != nil {
		t.Fatalf("unexpected error: %v", result.Err)
	}
	if !result.Truncated {
		t.Error("expected the output to be flagged as truncated")
	}
	if len(result.Output) != 100 {
		t.Errorf("expected exactly 100 retained bytes, got %d", len(result.Output))
	}
}

// TestRunUsesWorkingDirectory verifies that the request directory is honoured,
// so a task can run inside its own workspace.
func TestRunUsesWorkingDirectory(t *testing.T) {
	dir := t.TempDir()
	result := Run(context.Background(), Request{
		Command: "/bin/sh",
		Args:    []string{"-c", "pwd"},
		Dir:     dir,
	})

	if result.Err != nil {
		t.Fatalf("unexpected error: %v", result.Err)
	}
	if !strings.Contains(result.Output, filepath.Base(dir)) {
		t.Errorf("expected the output to name %q, got %q", dir, result.Output)
	}
}

// TestRunUsesEnvironment verifies that the request environment reaches the
// child, so per-task variables are visible.
func TestRunUsesEnvironment(t *testing.T) {
	result := Run(context.Background(), Request{
		Command: "/bin/sh",
		Args:    []string{"-c", "printf %s \"$TASK_MARKER\""},
		Env:     BuildEnv(CurrentEnv(), map[string]string{"TASK_MARKER": "present"}),
	})

	if result.Err != nil {
		t.Fatalf("unexpected error: %v", result.Err)
	}
	if result.Output != "present" {
		t.Errorf("expected the marker in the output, got %q", result.Output)
	}
}

// TestStopTerminatesGroup verifies that Stop ends a run started elsewhere, which
// is the mechanism behind the contract's active stop.
func TestStopTerminatesGroup(t *testing.T) {
	command := exec.Command("/bin/sleep", "30")
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := command.Start(); err != nil {
		t.Fatalf("start sleep: %v", err)
	}
	pid := command.Process.Pid

	waited := make(chan error, 1)
	go func() { waited <- command.Wait() }()

	if err := Stop(pid, false); err != nil {
		t.Fatalf("Stop failed: %v", err)
	}

	select {
	case <-waited:
	case <-time.After(10 * time.Second):
		_ = Stop(pid, true)
		t.Fatal("the stopped process did not exit")
	}
}

// TestStopRejectsInvalidPID verifies that a nonsensical pid is rejected instead
// of being signalled, because pid 0 and negative pids address other groups.
func TestStopRejectsInvalidPID(t *testing.T) {
	for _, pid := range []int{0, -1} {
		if err := Stop(pid, false); err == nil {
			t.Errorf("expected pid %d to be rejected", pid)
		}
	}
}

// TestBuildEnvOverridesWithoutDuplicates verifies that an extra variable
// replaces the inherited one instead of appearing twice.
func TestBuildEnvOverridesWithoutDuplicates(t *testing.T) {
	base := []string{"KEEP=1", "OVERRIDE=old"}
	merged := BuildEnv(base, map[string]string{"OVERRIDE": "new"})

	count := 0
	for _, entry := range merged {
		if strings.HasPrefix(entry, "OVERRIDE=") {
			count++
			if entry != "OVERRIDE=new" {
				t.Errorf("expected the override to win, got %q", entry)
			}
		}
	}
	if count != 1 {
		t.Errorf("expected exactly one OVERRIDE entry, got %d", count)
	}

	found := false
	for _, entry := range merged {
		if entry == "KEEP=1" {
			found = true
		}
	}
	if !found {
		t.Error("expected unrelated variables to be preserved")
	}
}

// TestBuildEnvWithoutExtrasReturnsBase verifies that no extras means no copy, so
// the common case stays cheap.
func TestBuildEnvWithoutExtrasReturnsBase(t *testing.T) {
	base := []string{"A=1"}
	merged := BuildEnv(base, nil)
	if len(merged) != 1 || merged[0] != "A=1" {
		t.Errorf("expected the base environment unchanged, got %v", merged)
	}
}

// TestCappedBufferKeepsLimit verifies the buffer contract directly, including
// that it always reports a full write so the child is never blocked.
func TestCappedBufferKeepsLimit(t *testing.T) {
	buffer := &cappedBuffer{limit: 4}

	written, err := buffer.Write([]byte("abcdef"))
	if err != nil {
		t.Fatalf("Write failed: %v", err)
	}
	if written != 6 {
		t.Errorf("expected the full length to be reported, got %d", written)
	}
	if buffer.String() != "abcd" {
		t.Errorf("expected the first four bytes, got %q", buffer.String())
	}
	if !buffer.truncated {
		t.Error("expected the buffer to be flagged as truncated")
	}

	// A write after the limit is reached must still be accepted and dropped.
	if _, err := buffer.Write([]byte("more")); err != nil {
		t.Fatalf("Write after the limit failed: %v", err)
	}
	if buffer.String() != "abcd" {
		t.Errorf("expected the retained content to stay capped, got %q", buffer.String())
	}
}

// TestPositiveOr verifies the fallback helper used for the output cap.
func TestPositiveOr(t *testing.T) {
	if positiveOr(0, 7) != 7 {
		t.Error("expected the fallback for zero")
	}
	if positiveOr(-1, 7) != 7 {
		t.Error("expected the fallback for a negative value")
	}
	if positiveOr(3, 7) != 3 {
		t.Error("expected the value when positive")
	}
}
