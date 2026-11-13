package main

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

const helperModeEnvironment = "AGENT_CLUSTER_TOPSAILAI_TEST_HELPER"

// TestCLIRunnerPassesLiteralArgv verifies that shell syntax remains one literal argument.
func TestCLIRunnerPassesLiteralArgv(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the test helper uses the current Unix test executable")
	}
	runner := cliRunner{
		executable:  os.Args[0],
		environment: append(os.Environ(), helperModeEnvironment+"=argv"),
		timeout:     time.Second,
	}
	literal := `$(touch should-not-run); echo unsafe`
	stdout, stderr, err := runner.Run(context.Background(), []string{"-test.run=TestProviderRunnerHelper", "--", literal}, nil)
	if err != nil {
		t.Fatalf("run helper: %v stderr=%s", err, stderr)
	}
	if got := strings.TrimSpace(string(stdout)); got != literal {
		t.Fatalf("literal argv = %q", got)
	}
}

// TestNewCLIRunnerUsesLocalExecutableConfiguration verifies startup-only configuration.
func TestNewCLIRunnerUsesLocalExecutableConfiguration(t *testing.T) {
	runner := newCLIRunner([]string{
		"PATH=/usr/bin",
		executableEnvironment + "=/opt/topsailai/bin/topsailai",
	})
	if runner.executable != "/opt/topsailai/bin/topsailai" {
		t.Fatalf("executable = %q", runner.executable)
	}
	if got := environmentValue(runner.environment, "PATH"); !strings.HasPrefix(got, "/opt/topsailai/bin"+string(os.PathListSeparator)) {
		t.Fatalf("PATH = %q", got)
	}
}

// TestProviderEnvironmentDoesNotDuplicatePath verifies stable repeated setup.
func TestProviderEnvironmentDoesNotDuplicatePath(t *testing.T) {
	path := "/opt/topsailai/bin" + string(os.PathListSeparator) + "/usr/bin"
	environment := providerEnvironment("/opt/topsailai/bin/topsailai", []string{"PATH=" + path})
	if got := environmentValue(environment, "PATH"); got != path {
		t.Fatalf("PATH = %q", got)
	}
}

// TestCLIRunnerTimesOut verifies bounded child lifetime.
func TestCLIRunnerTimesOut(t *testing.T) {
	runner := cliRunner{
		executable:  os.Args[0],
		environment: append(os.Environ(), helperModeEnvironment+"=sleep"),
		timeout:     20 * time.Millisecond,
	}
	_, _, err := runner.Run(context.Background(), []string{"-test.run=TestProviderRunnerHelper"}, nil)
	if err == nil || !strings.Contains(err.Error(), "deadline exceeded") {
		t.Fatalf("error = %v", err)
	}
}

// TestCLIRunnerFollowUsesParentLifetime verifies that unary timeout does not end a live follow.
func TestCLIRunnerFollowUsesParentLifetime(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the test helper uses the current Unix test executable")
	}
	runner := cliRunner{
		executable:  os.Args[0],
		environment: append(os.Environ(), helperModeEnvironment+"=follow-lines"),
		timeout:     time.Nanosecond,
	}
	var records []followRecord
	err := runner.Follow(context.Background(), []string{"-test.run=TestProviderRunnerHelper"}, 64, func(record followRecord) error {
		records = append(records, record)
		return nil
	})
	if err != nil {
		t.Fatalf("follow helper: %v", err)
	}
	if len(records) != 2 || records[0].Line != "first" || records[1].Line != "second" {
		t.Fatalf("records = %+v", records)
	}
}

// TestCLIRunnerFollowReportsCancellation verifies parent cancellation owns the stream lifetime.
func TestCLIRunnerFollowReportsCancellation(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the test helper uses the current Unix test executable")
	}
	runner := cliRunner{
		executable:  os.Args[0],
		environment: append(os.Environ(), helperModeEnvironment+"=sleep"),
		timeout:     time.Hour,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	err := runner.Follow(ctx, []string{"-test.run=TestProviderRunnerHelper"}, 64, func(followRecord) error { return nil })
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("error = %v", err)
	}
}

// TestCLIRunnerFollowPreservesFailureEvidence verifies stderr survives a non-zero exit.
func TestCLIRunnerFollowPreservesFailureEvidence(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the test helper uses the current Unix test executable")
	}
	runner := cliRunner{
		executable:  os.Args[0],
		environment: append(os.Environ(), helperModeEnvironment+"=fail"),
		timeout:     time.Hour,
	}
	err := runner.Follow(context.Background(), []string{"-test.run=TestProviderRunnerHelper"}, 64, func(followRecord) error { return nil })
	if err == nil || !strings.Contains(err.Error(), "provider follow failed") {
		t.Fatalf("error = %v", err)
	}
}

// TestCLIRunnerFollowCancellationKillsOwnedProcessGroup verifies helper processes cannot outlive cancellation.
func TestCLIRunnerFollowCancellationKillsOwnedProcessGroup(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("process-group ownership is Unix-only")
	}
	marker := filepath.Join(t.TempDir(), "helper-finished")
	environment := append(os.Environ(),
		helperModeEnvironment+"=spawn-helper",
		"AGENT_CLUSTER_TOPSAILAI_TEST_MARKER="+marker,
	)
	runner := cliRunner{executable: os.Args[0], environment: environment, timeout: time.Hour}
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	err := runner.Follow(ctx, []string{"-test.run=TestProviderRunnerHelper"}, 64, func(followRecord) error { return nil })
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("error = %v", err)
	}
	time.Sleep(250 * time.Millisecond)
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("owned helper survived cancellation: %v", err)
	}
}

// TestProviderRunnerHelper provides a controlled direct-process fixture.
func TestProviderRunnerHelper(t *testing.T) {
	mode := os.Getenv(helperModeEnvironment)
	if mode == "" {
		return
	}
	switch mode {
	case "argv":
		separator := -1
		for index, argument := range os.Args {
			if argument == "--" {
				separator = index
				break
			}
		}
		if separator < 0 || separator+1 >= len(os.Args) {
			os.Exit(3)
		}
		_, _ = os.Stdout.WriteString(os.Args[separator+1])
		os.Exit(0)
	case "sleep":
		time.Sleep(time.Second)
		os.Exit(0)
	case "follow-lines":
		_, _ = os.Stdout.WriteString("first\n")
		time.Sleep(20 * time.Millisecond)
		_, _ = os.Stdout.WriteString("second\n")
		os.Exit(0)
	case "fail":
		_, _ = os.Stderr.WriteString("provider follow failed")
		os.Exit(9)
	case "spawn-helper":
		command := exec.Command(os.Args[0], "-test.run=TestProviderRunnerHelper")
		command.Env = replaceEnvironment(os.Environ(), helperModeEnvironment, "delayed-marker")
		if err := command.Start(); err != nil {
			os.Exit(5)
		}
		time.Sleep(time.Second)
		os.Exit(0)
	case "delayed-marker":
		time.Sleep(150 * time.Millisecond)
		if err := os.WriteFile(os.Getenv("AGENT_CLUSTER_TOPSAILAI_TEST_MARKER"), []byte("done"), 0o600); err != nil {
			os.Exit(6)
		}
		os.Exit(0)
	default:
		os.Exit(4)
	}
}

func replaceEnvironment(environment []string, key, value string) []string {
	prefix := key + "="
	result := make([]string, 0, len(environment)+1)
	for _, entry := range environment {
		if !strings.HasPrefix(entry, prefix) {
			result = append(result, entry)
		}
	}
	return append(result, prefix+value)
}

// TestLiteralArgumentDoesNotCreateAFile is a defense-in-depth assertion for shell bypass.
func TestLiteralArgumentDoesNotCreateAFile(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the test helper uses the current Unix test executable")
	}
	directory := t.TempDir()
	marker := filepath.Join(directory, "marker")
	runner := cliRunner{
		executable:  os.Args[0],
		environment: append(os.Environ(), helperModeEnvironment+"=argv"),
		timeout:     time.Second,
	}
	argument := "; touch " + marker
	_, stderr, err := runner.Run(context.Background(), []string{"-test.run=TestProviderRunnerHelper", "--", argument}, nil)
	if err != nil {
		t.Fatalf("run helper: %v stderr=%s", err, stderr)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("shell marker exists or stat failed: %v", err)
	}
}
