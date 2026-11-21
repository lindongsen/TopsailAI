package main

import (
	"flag"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_scheduler/config"
	"topsailai_scheduler/runtime"
)

// captureStdout runs fn with os.Stdout redirected and returns what was written.
func captureStdout(t *testing.T, fn func()) string {
	t.Helper()

	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatalf("create pipe: %v", err)
	}
	original := os.Stdout
	os.Stdout = writer

	done := make(chan string, 1)
	go func() {
		content, _ := io.ReadAll(reader)
		done <- string(content)
	}()

	fn()

	os.Stdout = original
	if err := writer.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	return <-done
}

// TestRunWithoutArgumentsPrintsUsage verifies an empty command line is a usage
// error rather than a silent success.
func TestRunWithoutArgumentsPrintsUsage(t *testing.T) {
	if code := run(nil); code != exitUsage {
		t.Fatalf("want exit %d, got %d", exitUsage, code)
	}
}

// TestRunUnknownCommand verifies an unknown subcommand is a usage error.
func TestRunUnknownCommand(t *testing.T) {
	if code := run([]string{"nonsense"}); code != exitUsage {
		t.Fatalf("want exit %d, got %d", exitUsage, code)
	}
}

// TestRunHelp verifies every help spelling succeeds and prints the usage.
func TestRunHelp(t *testing.T) {
	for _, argument := range []string{"help", "-h", "--help"} {
		code := run([]string{argument})
		if code != exitOK {
			t.Fatalf("%q: want exit %d, got %d", argument, exitOK, code)
		}
	}
}

// TestUsageDocumentsEverySubcommand verifies the usage text names the
// subcommands and the task file layout, because it is the only built-in
// documentation a user sees.
func TestUsageDocumentsEverySubcommand(t *testing.T) {
	for _, expected := range []string{
		"scheduler run", "scheduler status", "scheduler launch", "scheduler stop",
		".yaml", ".md", ".lock", "SCHEDULER_TASKS_ROOT",
	} {
		if !strings.Contains(usage, expected) {
			t.Fatalf("usage does not mention %q", expected)
		}
	}
}

// TestParseFlagsAcceptsFlagAfterPositional verifies the natural command line
// "launch demo/hello --wait" works, which the standard flag package rejects.
func TestParseFlagsAcceptsFlagAfterPositional(t *testing.T) {
	flags := flag.NewFlagSet("launch", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	wait := flags.Bool("wait", false, "wait")

	positional, err := parseFlags(flags, []string{"demo/hello", "--wait"})
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if !*wait {
		t.Fatal("expected --wait to be set")
	}
	if len(positional) != 1 || positional[0] != "demo/hello" {
		t.Fatalf("unexpected positional arguments %q", positional)
	}
}

// TestParseFlagsAcceptsFlagBeforePositional verifies the conventional order
// keeps working.
func TestParseFlagsAcceptsFlagBeforePositional(t *testing.T) {
	flags := flag.NewFlagSet("launch", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	wait := flags.Bool("wait", false, "wait")

	positional, err := parseFlags(flags, []string{"--wait", "demo/hello"})
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if !*wait {
		t.Fatal("expected --wait to be set")
	}
	if len(positional) != 1 || positional[0] != "demo/hello" {
		t.Fatalf("unexpected positional arguments %q", positional)
	}
}

// TestParseFlagsKeepsMultiplePositionals verifies extra arguments are reported
// so a caller can reject them.
func TestParseFlagsKeepsMultiplePositionals(t *testing.T) {
	flags := flag.NewFlagSet("launch", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.Bool("wait", false, "wait")

	positional, err := parseFlags(flags, []string{"a", "b", "--wait"})
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if len(positional) != 2 {
		t.Fatalf("want 2 positional arguments, got %q", positional)
	}
}

// TestParseFlagsRejectsUnknownFlag verifies an unknown flag is an error instead
// of being treated as a task id.
func TestParseFlagsRejectsUnknownFlag(t *testing.T) {
	flags := flag.NewFlagSet("launch", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.Bool("wait", false, "wait")

	if _, err := parseFlags(flags, []string{"demo/hello", "--nope"}); err == nil {
		t.Fatal("expected an unknown flag to be rejected")
	}
}

// TestParseFlagsKeepsSingleDash verifies a lone "-" stays positional, because it
// conventionally means standard input rather than a flag.
func TestParseFlagsKeepsSingleDash(t *testing.T) {
	flags := flag.NewFlagSet("launch", flag.ContinueOnError)
	flags.SetOutput(io.Discard)

	positional, err := parseFlags(flags, []string{"-"})
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if len(positional) != 1 || positional[0] != "-" {
		t.Fatalf("unexpected positional arguments %q", positional)
	}
}

// TestPrintJSON verifies a value is rendered as indented JSON.
func TestPrintJSON(t *testing.T) {
	output := captureStdout(t, func() {
		if code := printJSON(map[string]int{"count": 2}); code != exitOK {
			t.Fatalf("want exit %d, got %d", exitOK, code)
		}
	})
	if !strings.Contains(output, `"count": 2`) {
		t.Fatalf("unexpected output %q", output)
	}
}

// TestPrintJSONRejectsUnencodableValue verifies an encoding failure is reported
// instead of printing nothing.
func TestPrintJSONRejectsUnencodableValue(t *testing.T) {
	output := captureStdout(t, func() {
		if code := printJSON(make(chan int)); code != exitFailure {
			t.Fatalf("want exit %d, got %d", exitFailure, code)
		}
	})
	if output != "" {
		t.Fatalf("expected no output, got %q", output)
	}
}

// TestPrintSnapshotRendersTasks verifies the table shows the state, schedule,
// next run, last exit code and pid of each task.
func TestPrintSnapshotRendersTasks(t *testing.T) {
	nextRun := time.Date(2026, 11, 20, 8, 0, 0, 0, time.UTC)
	snapshot := runtime.Snapshot{
		TasksRoot: "/work/scheduler/tasks",
		Tasks: []runtime.TaskStatus{
			{
				ID:       "data/work",
				State:    runtime.StateRunning,
				Schedule: "0 8 * * *",
				NextRun:  nextRun,
				LastRun:  &runtime.RunRecord{ExitCode: 3},
				Run:      &runtime.RunInfo{PID: 4242},
			},
			{ID: "idle/task", State: runtime.StateIdle},
		},
	}

	output := captureStdout(t, func() { printSnapshot(snapshot) })

	for _, expected := range []string{
		"/work/scheduler/tasks", "data/work", "running", "0 8 * * *",
		"2026-11-20T08:00:00Z", "4242", "idle/task",
	} {
		if !strings.Contains(output, expected) {
			t.Fatalf("output does not contain %q:\n%s", expected, output)
		}
	}
}

// TestPrintSnapshotReportsEmptyTree verifies an empty tasks folder is reported
// as a normal state.
func TestPrintSnapshotReportsEmptyTree(t *testing.T) {
	output := captureStdout(t, func() {
		printSnapshot(runtime.Snapshot{TasksRoot: "/work/scheduler/tasks"})
	})
	if !strings.Contains(output, "no tasks found") {
		t.Fatalf("unexpected output %q", output)
	}
}

// TestPrintSnapshotShowsTaskError verifies an invalid task's error is visible,
// so a broken task file is not only discoverable in the log.
func TestPrintSnapshotShowsTaskError(t *testing.T) {
	snapshot := runtime.Snapshot{
		Tasks: []runtime.TaskStatus{
			{ID: "broken", State: runtime.StateInvalid, Error: "schedule is required"},
		},
	}
	output := captureStdout(t, func() { printSnapshot(snapshot) })
	if !strings.Contains(output, "schedule is required") {
		t.Fatalf("unexpected output %q", output)
	}
}

// TestPrintRecordRendersOutcome verifies the completed run summary.
func TestPrintRecordRendersOutcome(t *testing.T) {
	started := time.Date(2026, 11, 20, 8, 0, 0, 0, time.UTC)
	record := runtime.RunRecord{
		StartedAt:  started,
		FinishedAt: started.Add(1500 * time.Millisecond),
		ExitCode:   2,
		TimedOut:   true,
		Stopped:    true,
	}

	output := captureStdout(t, func() { printRecord(record) })

	for _, expected := range []string{"exit code: 2", "1.5s", "timed out: yes", "stopped:   yes"} {
		if !strings.Contains(output, expected) {
			t.Fatalf("output does not contain %q:\n%s", expected, output)
		}
	}
}

// TestPrintRecordOmitsAbsentFlags verifies a clean run does not claim it timed
// out or was stopped.
func TestPrintRecordOmitsAbsentFlags(t *testing.T) {
	started := time.Date(2026, 11, 20, 8, 0, 0, 0, time.UTC)
	record := runtime.RunRecord{StartedAt: started, FinishedAt: started.Add(time.Second)}

	output := captureStdout(t, func() { printRecord(record) })

	if strings.Contains(output, "timed out") {
		t.Fatalf("unexpected timed out line:\n%s", output)
	}
	if strings.Contains(output, "stopped") {
		t.Fatalf("unexpected stopped line:\n%s", output)
	}
	if !strings.Contains(output, "exit code: 0") {
		t.Fatalf("unexpected output %q", output)
	}
}

// TestFailReturnsFailureCode verifies the shared error helper reports a failure.
func TestFailReturnsFailureCode(t *testing.T) {
	if code := fail("boom %d", 1); code != exitFailure {
		t.Fatalf("want exit %d, got %d", exitFailure, code)
	}
}

// TestApplyTasksRootOverridePrefersFlag verifies the command line wins over the
// environment-derived value.
func TestApplyTasksRootOverridePrefersFlag(t *testing.T) {
	cfg := config.Config{TasksRoot: "tasks", MaxConcurrent: 4, MaxOutputBytes: 1024, DefaultTimeout: time.Minute, RescanInterval: time.Second, ControlSocket: "scheduler.sock", DefaultProviderPath: "providers/mock/bin/mock", PollInterval: time.Second, ProviderCallTimeout: time.Second}

	got, err := applyTasksRootOverride(cfg, "/srv/jobs")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.TasksRoot != "/srv/jobs" {
		t.Fatalf("want /srv/jobs, got %q", got.TasksRoot)
	}
}

// TestApplyTasksRootOverrideKeepsEnvironmentWhenFlagEmpty verifies an absent
// flag leaves the environment-derived value untouched.
func TestApplyTasksRootOverrideKeepsEnvironmentWhenFlagEmpty(t *testing.T) {
	cfg := config.Config{TasksRoot: "from-env", MaxConcurrent: 4, MaxOutputBytes: 1024, DefaultTimeout: time.Minute, RescanInterval: time.Second, ControlSocket: "scheduler.sock", DefaultProviderPath: "providers/mock/bin/mock", PollInterval: time.Second, ProviderCallTimeout: time.Second}

	for _, value := range []string{"", "   "} {
		got, err := applyTasksRootOverride(cfg, value)
		if err != nil {
			t.Fatalf("unexpected error for %q: %v", value, err)
		}
		if got.TasksRoot != "from-env" {
			t.Fatalf("flag %q must not override, got %q", value, got.TasksRoot)
		}
	}
}

// TestApplyTasksRootOverrideRejectsBlankValue verifies a whitespace-only
// override cannot blank the tasks root.
func TestApplyTasksRootOverrideRejectsBlankValue(t *testing.T) {
	cfg := config.Config{TasksRoot: "tasks", MaxConcurrent: 4, MaxOutputBytes: 1024, DefaultTimeout: time.Minute, RescanInterval: time.Second, ControlSocket: "scheduler.sock", DefaultProviderPath: "providers/mock/bin/mock", PollInterval: time.Second, ProviderCallTimeout: time.Second}

	if _, err := applyTasksRootOverride(cfg, "  "); err != nil {
		t.Fatalf("blank override must fall back, got error: %v", err)
	}
}

// TestResolveDefaultProviderPathRequiresAValue verifies the scheduler refuses to
// start without a provider executable.
//
// A scheduler with no provider cannot run anything, so the missing value is a
// startup error rather than a default. Failing here names the variable, while
// defaulting would surface later as a confusing failure at the first due task.
func TestResolveDefaultProviderPathRequiresAValue(t *testing.T) {
	cfg := config.Config{DefaultProviderPath: "   "}

	_, err := resolveDefaultProviderPath(cfg)
	if err == nil {
		t.Fatal("expected a missing provider path to be rejected")
	}
	if !strings.Contains(err.Error(), config.EnvDefaultProviderPath) {
		t.Fatalf("the error must name the variable, got %v", err)
	}
}

// TestResolveDefaultProviderPathReturnsAnAbsolutePath verifies a relative
// provider path is resolved against the working directory.
//
// The scheduler accepts a relative path for the same reason it does for the
// tasks root and the control socket: one rule covers every path it takes.
func TestResolveDefaultProviderPathReturnsAnAbsolutePath(t *testing.T) {
	cfg := config.Config{DefaultProviderPath: "providers/mock/bin/mock"}

	path, err := resolveDefaultProviderPath(cfg)
	if err != nil {
		t.Fatalf("resolve failed: %v", err)
	}
	if !filepath.IsAbs(path) {
		t.Fatalf("expected an absolute path, got %q", path)
	}
	if !strings.HasSuffix(path, filepath.Join("providers", "mock", "bin", "mock")) {
		t.Fatalf("unexpected path %q", path)
	}
}

// TestResolveDefaultProviderPathKeepsAnAbsolutePath verifies an absolute path is
// used as given, so a provider outside the working directory works.
func TestResolveDefaultProviderPathKeepsAnAbsolutePath(t *testing.T) {
	cfg := config.Config{DefaultProviderPath: "/opt/providers/mock/bin/mock"}

	path, err := resolveDefaultProviderPath(cfg)
	if err != nil {
		t.Fatalf("resolve failed: %v", err)
	}
	if path != "/opt/providers/mock/bin/mock" {
		t.Fatalf("unexpected path %q", path)
	}
}
