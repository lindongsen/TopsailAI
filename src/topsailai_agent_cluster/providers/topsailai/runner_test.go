package main

import (
	"context"
	"os"
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
	default:
		os.Exit(4)
	}
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
