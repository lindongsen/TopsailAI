package topsailai

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// requireProgram skips a test when the host does not provide the program. The
// runner is exercised against real processes because the properties under test
// (exit status, process-group termination, bounded capture) only exist when a
// real child runs.
func requireProgram(t *testing.T, name string) string {
	t.Helper()
	path, err := exec.LookPath(name)
	if err != nil {
		t.Skipf("host does not provide %q", name)
	}
	return path
}

func TestRunCommandCapturesStdoutAndExitZero(t *testing.T) {
	echo := requireProgram(t, "echo")
	runner := execCommandRunner{timeout: 10 * time.Second}
	outcome, err := runner.RunCommand(context.Background(), echo, []string{"echo", "hello"}, t.TempDir())
	if err != nil {
		t.Fatalf("RunCommand: %v", err)
	}
	if outcome.ExitCode != 0 {
		t.Fatalf("exit code = %d, want 0", outcome.ExitCode)
	}
	if strings.TrimSpace(string(outcome.Stdout)) != "hello" {
		t.Fatalf("stdout = %q, want hello", outcome.Stdout)
	}
	if outcome.Truncated {
		t.Fatal("small output was reported as truncated")
	}
}

func TestRunCommandTreatsNonZeroExitAsResult(t *testing.T) {
	falseProgram := requireProgram(t, "false")
	runner := execCommandRunner{timeout: 10 * time.Second}
	outcome, err := runner.RunCommand(context.Background(), falseProgram, []string{"false"}, t.TempDir())
	if err != nil {
		t.Fatalf("RunCommand returned an error for a non-zero exit: %v", err)
	}
	if outcome.ExitCode == 0 {
		t.Fatal("exit code = 0, want a non-zero code")
	}
}

func TestRunCommandRunsInRequestedDirectory(t *testing.T) {
	pwd := requireProgram(t, "pwd")
	directory := resolvedTempDir(t)
	runner := execCommandRunner{timeout: 10 * time.Second}
	outcome, err := runner.RunCommand(context.Background(), pwd, []string{"pwd"}, directory)
	if err != nil {
		t.Fatalf("RunCommand: %v", err)
	}
	if strings.TrimSpace(string(outcome.Stdout)) != directory {
		t.Fatalf("pwd = %q, want %q", outcome.Stdout, directory)
	}
}

func TestRunCommandTimesOutAndKillsProcessGroup(t *testing.T) {
	sleep := requireProgram(t, "sleep")
	runner := execCommandRunner{timeout: 200 * time.Millisecond}
	started := time.Now()
	outcome, err := runner.RunCommand(context.Background(), sleep, []string{"sleep", "30"}, t.TempDir())
	elapsed := time.Since(started)
	if !errors.Is(err, errCommandTimeout) {
		t.Fatalf("error = %v, want errCommandTimeout", err)
	}
	// The bounded lifetime must actually bound the wait: a runner that waited for
	// the child would take 30 seconds.
	if elapsed > 10*time.Second {
		t.Fatalf("RunCommand took %s, want a bounded return", elapsed)
	}
	if outcome.ExitCode != 0 {
		t.Fatalf("exit code = %d, want 0 for a terminated process", outcome.ExitCode)
	}
}

func TestRunCommandTruncatesOversizedOutput(t *testing.T) {
	cat := requireProgram(t, "cat")
	directory := resolvedTempDir(t)
	payload := strings.Repeat("a", commandExecMaxStreamBytes+4096)
	if err := os.WriteFile(filepath.Join(directory, "large.txt"), []byte(payload), 0o600); err != nil {
		t.Fatalf("write payload: %v", err)
	}
	runner := execCommandRunner{timeout: 20 * time.Second}
	outcome, err := runner.RunCommand(context.Background(), cat, []string{"cat", "large.txt"}, directory)
	if err != nil {
		t.Fatalf("RunCommand: %v", err)
	}
	if len(outcome.Stdout) != commandExecMaxStreamBytes {
		t.Fatalf("stdout length = %d, want %d", len(outcome.Stdout), commandExecMaxStreamBytes)
	}
	if !outcome.Truncated {
		t.Fatal("oversized output was not reported as truncated")
	}
}

func TestRunCommandDoesNotInheritEndpointSecrets(t *testing.T) {
	env := requireProgram(t, "env")
	t.Setenv("AGENT_CLUSTER_SERVER_AUTH_TOKEN", "super-secret-token")
	t.Setenv("AGENT_CLUSTER_DATABASE_DSN", "postgres://user:secret@host/db")
	runner := execCommandRunner{timeout: 10 * time.Second}
	outcome, err := runner.RunCommand(context.Background(), env, []string{"env"}, t.TempDir())
	if err != nil {
		t.Fatalf("RunCommand: %v", err)
	}
	output := string(outcome.Stdout)
	for _, secret := range []string{"AGENT_CLUSTER_SERVER_AUTH_TOKEN", "AGENT_CLUSTER_DATABASE_DSN", "super-secret-token", "postgres://"} {
		if strings.Contains(output, secret) {
			t.Fatalf("child environment leaked %q:\n%s", secret, output)
		}
	}
	if !strings.Contains(output, "TERM=dumb") {
		t.Fatalf("child environment did not set TERM=dumb:\n%s", output)
	}
}

func TestRunCommandReportsStartFailure(t *testing.T) {
	runner := execCommandRunner{timeout: 5 * time.Second}
	_, err := runner.RunCommand(context.Background(), filepath.Join(t.TempDir(), "absent"), []string{"absent"}, t.TempDir())
	if err == nil {
		t.Fatal("expected an error when the executable does not exist")
	}
	if errors.Is(err, errCommandTimeout) {
		t.Fatal("a start failure must not be reported as a timeout")
	}
}

func TestConfigureProcessGroupCreatesGroup(t *testing.T) {
	sleep := requireProgram(t, "sleep")
	cmd := exec.Command(sleep, "30")
	configureProcessGroup(cmd)
	if cmd.SysProcAttr == nil || !cmd.SysProcAttr.Setpgid {
		t.Fatal("configureProcessGroup did not request a new process group")
	}
	if err := cmd.Start(); err != nil {
		t.Fatalf("start: %v", err)
	}
	if err := killProcessGroup(cmd); err != nil {
		t.Fatalf("killProcessGroup: %v", err)
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("process did not terminate after killProcessGroup")
	}
}

func TestKillProcessGroupWithoutProcessIsSafe(t *testing.T) {
	if err := killProcessGroup(&exec.Cmd{}); err != nil {
		t.Fatalf("killProcessGroup on an unstarted command = %v, want nil", err)
	}
}
