package main

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/topsailai/topsailai_data/pkg/config"
	"github.com/topsailai/topsailai_data/pkg/manager"
)

// binaryPath is the path to a freshly built topsailai_data binary used by the
// os/exec integration tests. It is built once in TestMain and removed after all
// tests finish.
var binaryPath string

func TestMain(m *testing.M) {
	tmpDir, err := os.MkdirTemp("", "topsailai_data_main_test_*")
	if err != nil {
		fmt.Fprintf(os.Stderr, "create temp dir: %v\n", err)
		os.Exit(1)
	}

	binaryPath = filepath.Join(tmpDir, "topsailai_data")
	cmd := exec.Command("go", "build", "-o", binaryPath, ".")
	cmd.Dir = "/TopsailAI/src/topsailai_data/cmd/topsailai_data"
	if out, err := cmd.CombinedOutput(); err != nil {
		fmt.Fprintf(os.Stderr, "build binary: %v\n%s\n", err, out)
		os.Exit(1)
	}

	code := m.Run()
	_ = os.RemoveAll(tmpDir)
	os.Exit(code)
}

func captureStderr(t *testing.T, fn func()) string {
	t.Helper()
	old := os.Stderr
	r, w, _ := os.Pipe()
	os.Stderr = w
	fn()
	_ = w.Close()
	os.Stderr = old
	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	return buf.String()
}

func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	fn()
	_ = w.Close()
	os.Stdout = old
	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	return buf.String()
}

func TestRunConfigLoadError(t *testing.T) {
	wantErr := errors.New("config error")
	deps := dependencies{
		loadConfig: func() (*config.Config, error) { return nil, wantErr },
	}

	stderr := captureStderr(t, func() {
		if got := run([]string{"list"}, deps); got != 1 {
			t.Fatalf("expected exit code 1, got %d", got)
		}
	})

	if !strings.Contains(stderr, "load configuration") {
		t.Fatalf("expected load configuration message, got %q", stderr)
	}
	if !strings.Contains(stderr, wantErr.Error()) {
		t.Fatalf("expected wrapped error message, got %q", stderr)
	}
}

func TestRunManagerNewError(t *testing.T) {
	wantErr := errors.New("manager error")
	deps := dependencies{
		loadConfig: func() (*config.Config, error) {
			return &config.Config{
				Root:                t.TempDir(),
				MetadataAdapter:     "local",
				ActualDataAdapter:   "local",
				CeasedRetentionDays: 30,
			}, nil
		},
		newManager: func(*config.Config) (*manager.Manager, error) { return nil, wantErr },
	}

	stderr := captureStderr(t, func() {
		if got := run([]string{"list"}, deps); got != 1 {
			t.Fatalf("expected exit code 1, got %d", got)
		}
	})

	if !strings.Contains(stderr, "initialize manager") {
		t.Fatalf("expected initialize manager message, got %q", stderr)
	}
	if !strings.Contains(stderr, wantErr.Error()) {
		t.Fatalf("expected wrapped error message, got %q", stderr)
	}
}

func TestRunCLIError(t *testing.T) {
	wantErr := errors.New("cli error")
	root := t.TempDir()
	deps := dependencies{
		loadConfig: func() (*config.Config, error) {
			return &config.Config{
				Root:                root,
				MetadataAdapter:     "local",
				ActualDataAdapter:   "local",
				CeasedRetentionDays: 30,
			}, nil
		},
		newManager: manager.New,
		runCLI:     func(context.Context, *manager.Manager, []string) error { return wantErr },
	}

	stderr := captureStderr(t, func() {
		if got := run([]string{"list"}, deps); got != 1 {
			t.Fatalf("expected exit code 1, got %d", got)
		}
	})

	if !strings.Contains(stderr, wantErr.Error()) {
		t.Fatalf("expected cli error message, got %q", stderr)
	}
}

func TestRunSuccess(t *testing.T) {
	root := t.TempDir()
	t.Setenv("TOPSAILAI_DATA_ROOT", root)

	if got := run([]string{"list"}, realDependencies()); got != 0 {
		t.Fatalf("expected exit code 0, got %d", got)
	}
}

func TestRunHelp(t *testing.T) {
	root := t.TempDir()
	t.Setenv("TOPSAILAI_DATA_ROOT", root)

	out := captureStdout(t, func() {
		if got := run([]string{"help"}, realDependencies()); got != 0 {
			t.Fatalf("expected exit code 0, got %d", got)
		}
	})

	if !strings.Contains(out, "Usage: topsailai_data") {
		t.Fatalf("help output missing usage: %s", out)
	}
	if !strings.Contains(out, "create") {
		t.Fatalf("help output missing commands: %s", out)
	}
}

func TestRunUnknownCommand(t *testing.T) {
	root := t.TempDir()
	t.Setenv("TOPSAILAI_DATA_ROOT", root)

	stderr := captureStderr(t, func() {
		if got := run([]string{"unknown-command"}, realDependencies()); got != 1 {
			t.Fatalf("expected exit code 1, got %d", got)
		}
	})

	if !strings.Contains(stderr, "unknown command") {
		t.Fatalf("expected unknown command error, got %q", stderr)
	}
}

func TestRunInvalidAdapterConfig(t *testing.T) {
	root := t.TempDir()
	t.Setenv("TOPSAILAI_DATA_ROOT", root)
	t.Setenv("TOPSAILAI_DATA_METADATA_ADAPTER", "unknown-adapter")

	stderr := captureStderr(t, func() {
		if got := run([]string{"list"}, realDependencies()); got != 1 {
			t.Fatalf("expected exit code 1, got %d", got)
		}
	})

	if !strings.Contains(stderr, "initialize manager") {
		t.Fatalf("expected initialize manager error, got %q", stderr)
	}
}

func TestRunMissingRoot(t *testing.T) {
	// Force config loading to fail because neither TOPSAILAI_DATA_ROOT nor HOME
	// can provide a root directory.
	t.Setenv("HOME", "")
	t.Setenv("TOPSAILAI_DATA_ROOT", "")

	stderr := captureStderr(t, func() {
		if got := run([]string{"list"}, realDependencies()); got != 1 {
			t.Fatalf("expected exit code 1, got %d", got)
		}
	})

	if !strings.Contains(stderr, "load configuration") {
		t.Fatalf("expected load configuration error, got %q", stderr)
	}
}

func TestMainFunction(t *testing.T) {
	root := t.TempDir()
	t.Setenv("TOPSAILAI_DATA_ROOT", root)

	oldArgs := os.Args
	os.Args = []string{"topsailai_data", "list"}
	defer func() { os.Args = oldArgs }()

	var exitCode int
	oldExit := osExit
	osExit = func(code int) { exitCode = code }
	defer func() { osExit = oldExit }()

	main()

	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
}

func TestMainFunctionError(t *testing.T) {
	root := t.TempDir()
	t.Setenv("TOPSAILAI_DATA_ROOT", root)

	oldArgs := os.Args
	os.Args = []string{"topsailai_data", "unknown-command"}
	defer func() { os.Args = oldArgs }()

	var exitCode int
	oldExit := osExit
	osExit = func(code int) { exitCode = code }
	defer func() { osExit = oldExit }()

	main()

	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
}

func TestBinaryExitCodeSuccess(t *testing.T) {
	root := t.TempDir()
	cmd := exec.Command(binaryPath, "help")
	cmd.Env = append(os.Environ(), "TOPSAILAI_DATA_ROOT="+root)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("help command failed: %v\n%s", err, out)
	}
	if !strings.Contains(string(out), "Usage: topsailai_data") {
		t.Fatalf("help output missing usage: %s", out)
	}
}

func TestBinaryExitCodeError(t *testing.T) {
	root := t.TempDir()
	cmd := exec.Command(binaryPath, "unknown-command")
	cmd.Env = append(os.Environ(), "TOPSAILAI_DATA_ROOT="+root)
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatal("expected unknown command to fail")
	}
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		t.Fatalf("expected exit error, got %T", err)
	}
	if exitErr.ExitCode() != 1 {
		t.Fatalf("expected exit code 1, got %d", exitErr.ExitCode())
	}
	if !strings.Contains(string(out), "unknown command") {
		t.Fatalf("expected unknown command in output: %s", out)
	}
}

func TestBinaryMissingRootHandled(t *testing.T) {
	// Run the binary with an empty environment so HOME is unset and no root can
	// be determined. The process should exit with code 1 and print an error.
	cmd := exec.Command(binaryPath, "list")
	cmd.Env = []string{}
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatal("expected error when root cannot be determined")
	}
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 1 {
		t.Fatalf("expected exit code 1, got %v", err)
	}
	if !strings.Contains(string(out), "error:") {
		t.Fatalf("expected error prefix in output: %s", out)
	}
}
