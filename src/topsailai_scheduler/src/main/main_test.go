package main

import (
	"encoding/json"
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

// TestParseFlagsKeepsValueFlagAttached verifies a flag that takes a value keeps
// its value while the arguments are reordered.
//
// Without this, "check --tasks-root dir --json" would move --json next to
// --tasks-root, the value would be read as a flag name, and a valid command line
// would fail as a usage error.
func TestParseFlagsKeepsValueFlagAttached(t *testing.T) {
	flags := flag.NewFlagSet("check", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	root := flags.String("tasks-root", "", "root")
	asJSON := flags.Bool("json", false, "json")

	positional, err := parseFlags(flags, []string{"--tasks-root", "some/dir", "--json"})
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if *root != "some/dir" {
		t.Fatalf("unexpected tasks root %q", *root)
	}
	if !*asJSON {
		t.Fatal("expected --json to be set")
	}
	if len(positional) != 0 {
		t.Fatalf("expected no positional arguments, got %q", positional)
	}
}

// TestParseFlagsKeepsValueFlagBeforePositional verifies a value flag followed by
// a positional argument does not consume it.
func TestParseFlagsKeepsValueFlagBeforePositional(t *testing.T) {
	flags := flag.NewFlagSet("check", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	root := flags.String("tasks-root", "", "root")

	positional, err := parseFlags(flags, []string{"--tasks-root", "some/dir", "extra"})
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if *root != "some/dir" {
		t.Fatalf("unexpected tasks root %q", *root)
	}
	if len(positional) != 1 || positional[0] != "extra" {
		t.Fatalf("unexpected positional arguments %q", positional)
	}
}

// TestParseFlagsAcceptsJoinedValue verifies the "--name=value" form still works,
// because that form carries its own value and must not consume the next word.
func TestParseFlagsAcceptsJoinedValue(t *testing.T) {
	flags := flag.NewFlagSet("check", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	root := flags.String("tasks-root", "", "root")
	asJSON := flags.Bool("json", false, "json")

	positional, err := parseFlags(flags, []string{"--tasks-root=some/dir", "--json"})
	if err != nil {
		t.Fatalf("parse failed: %v", err)
	}
	if *root != "some/dir" {
		t.Fatalf("unexpected tasks root %q", *root)
	}
	if !*asJSON {
		t.Fatal("expected --json to be set")
	}
	if len(positional) != 0 {
		t.Fatalf("expected no positional arguments, got %q", positional)
	}
}

// TestBuildCheckReportSeparatesValidAndInvalid verifies a clean task and a
// rejected file are both reported, with the reason attached to the rejected one.
//
// Reporting only the failures would make "no output" ambiguous between a clean
// tree and a checker that did not run.
func TestBuildCheckReportSeparatesValidAndInvalid(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "data/good", "schedule: \"0 8 * * *\"\n", "a complete task content that is long enough")
	writeCheckTask(t, root, "data/bad", "schedule: \"every morning\"\n", "a complete task content that is long enough")

	report, err := buildCheckReport(root, 30)
	if err != nil {
		t.Fatalf("buildCheckReport failed: %v", err)
	}
	if !report.TasksRootExists {
		t.Fatal("expected the tasks root to be reported as present")
	}
	if report.Valid != 1 || report.Invalid != 1 {
		t.Fatalf("unexpected counts valid=%d invalid=%d", report.Valid, report.Invalid)
	}
	if len(report.Tasks) != 2 {
		t.Fatalf("expected both tasks to be reported, got %d", len(report.Tasks))
	}

	good := findCheckResult(t, report, "data/good")
	if !good.Valid {
		t.Fatalf("expected data/good to be valid, got %q", good.Error)
	}
	if good.Enabled == nil || !*good.Enabled {
		t.Fatal("expected data/good to be reported as enabled")
	}

	bad := findCheckResult(t, report, "data/bad")
	if bad.Valid {
		t.Fatal("expected data/bad to be invalid")
	}
	if !strings.Contains(bad.Error, "every morning") {
		t.Fatalf("expected the reason to name the expression, got %q", bad.Error)
	}
	if bad.Enabled != nil {
		t.Fatal("expected a rejected task to omit the enabled flag")
	}
}

// TestBuildCheckReportReportsDisabledTask verifies a disabled task is valid but
// distinguishable from an enabled one.
func TestBuildCheckReportReportsDisabledTask(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "off", "schedule: \"0 8 * * *\"\nenabled: false\n", "a complete task content that is long enough")

	report, err := buildCheckReport(root, 30)
	if err != nil {
		t.Fatalf("buildCheckReport failed: %v", err)
	}
	if report.Valid != 1 || report.Invalid != 0 {
		t.Fatalf("unexpected counts valid=%d invalid=%d", report.Valid, report.Invalid)
	}
	result := findCheckResult(t, report, "off")
	if result.Enabled == nil || *result.Enabled {
		t.Fatal("expected the task to be reported as disabled")
	}
}

// TestBuildCheckReportMissingRootIsEmpty verifies a missing tasks folder is an
// empty result rather than an error, matching how the daemon treats it.
func TestBuildCheckReportMissingRootIsEmpty(t *testing.T) {
	root := filepath.Join(t.TempDir(), "absent")

	report, err := buildCheckReport(root, 30)
	if err != nil {
		t.Fatalf("buildCheckReport failed: %v", err)
	}
	if report.TasksRootExists {
		t.Fatal("expected the missing root to be reported as absent")
	}
	if len(report.Tasks) != 0 || report.Valid != 0 || report.Invalid != 0 {
		t.Fatalf("expected an empty report, got %+v", report)
	}
}

// TestBuildCheckReportSortsByID verifies the report is ordered so the output is
// stable between runs.
func TestBuildCheckReportSortsByID(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "z/last", "schedule: \"0 8 * * *\"\n", "a complete task content that is long enough")
	writeCheckTask(t, root, "a/first", "schedule: \"0 8 * * *\"\n", "a complete task content that is long enough")

	report, err := buildCheckReport(root, 30)
	if err != nil {
		t.Fatalf("buildCheckReport failed: %v", err)
	}
	if len(report.Tasks) != 2 {
		t.Fatalf("expected 2 tasks, got %d", len(report.Tasks))
	}
	if report.Tasks[0].ID != "a/first" || report.Tasks[1].ID != "z/last" {
		t.Fatalf("unexpected order %q, %q", report.Tasks[0].ID, report.Tasks[1].ID)
	}
}

// TestRunCheckExitsNonZeroOnInvalidTask verifies the exit code reflects the
// result, so a pipeline does not have to parse the output.
func TestRunCheckExitsNonZeroOnInvalidTask(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "bad", "schedule: \"every morning\"\n", "a complete task content that is long enough")

	code := captureStdoutCode(t, func() int {
		return runCheck([]string{"--tasks-root", root})
	})
	if code != exitFailure {
		t.Fatalf("expected exit %d, got %d", exitFailure, code)
	}
}

// TestRunCheckExitsZeroOnCleanTree verifies a clean tree succeeds.
func TestRunCheckExitsZeroOnCleanTree(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "good", "schedule: \"0 8 * * *\"\n", "a complete task content that is long enough")

	code := captureStdoutCode(t, func() int {
		return runCheck([]string{"--tasks-root", root})
	})
	if code != exitOK {
		t.Fatalf("expected exit %d, got %d", exitOK, code)
	}
}

// TestRunCheckRejectsPositionalArgument verifies a stray argument is a usage
// error rather than being silently ignored.
//
// One argument now selects a task, so the stray-argument case is two names: the
// command must refuse to guess which of them was meant.
func TestRunCheckRejectsPositionalArgument(t *testing.T) {
	code := captureStdoutCode(t, func() int {
		return runCheck([]string{"first", "second"})
	})
	if code != exitUsage {
		t.Fatalf("expected exit %d, got %d", exitUsage, code)
	}
}

// TestRunCheckJSONParses verifies the JSON form is a single parseable document,
// because a caller reads it with a JSON parser rather than by eye.
func TestRunCheckJSONParses(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "bad", "schedule: \"every morning\"\n", "a complete task content that is long enough")

	output := captureStdout(t, func() {
		runCheck([]string{"--tasks-root", root, "--json"})
	})

	var report checkReport
	if err := json.Unmarshal([]byte(output), &report); err != nil {
		t.Fatalf("expected parseable JSON, got %v in %q", err, output)
	}
	if report.Invalid != 1 {
		t.Fatalf("expected 1 invalid task, got %d", report.Invalid)
	}
	if len(report.Tasks) != 1 || report.Tasks[0].ID != "bad" {
		t.Fatalf("unexpected tasks %+v", report.Tasks)
	}
}

// writeCheckTask writes one task pair under root.
func writeCheckTask(t *testing.T, root, id, yamlContent, markdown string) {
	t.Helper()

	yamlPath := filepath.Join(root, id+".yaml")
	markdownPath := filepath.Join(root, id+".md")
	if err := os.MkdirAll(filepath.Dir(yamlPath), 0o755); err != nil {
		t.Fatalf("create task folder: %v", err)
	}
	if err := os.WriteFile(yamlPath, []byte(yamlContent), 0o644); err != nil {
		t.Fatalf("write task yaml: %v", err)
	}
	if err := os.WriteFile(markdownPath, []byte(markdown), 0o644); err != nil {
		t.Fatalf("write task markdown: %v", err)
	}
}

// findCheckResult returns the reported task with the given id.
func findCheckResult(t *testing.T, report checkReport, id string) checkResult {
	t.Helper()

	for _, result := range report.Tasks {
		if result.ID == id {
			return result
		}
	}
	t.Fatalf("task %q is missing from the report", id)
	return checkResult{}
}

// captureStdoutCode runs fn with os.Stdout redirected and returns its exit code.
func captureStdoutCode(t *testing.T, fn func() int) int {
	t.Helper()

	var code int
	captureStdout(t, func() { code = fn() })
	return code
}

// TestResolveCheckTargetAcceptsATaskID checks the id form names the YAML file.
func TestResolveCheckTargetAcceptsATaskID(t *testing.T) {
	root := t.TempDir()

	path, err := resolveCheckTarget(root, "data/work")
	if err != nil {
		t.Fatalf("resolve task id: %v", err)
	}
	want := filepath.Join(root, "data", "work.yaml")
	if path != want {
		t.Fatalf("resolved %q, want %q", path, want)
	}
}

// TestResolveCheckTargetAcceptsARelativePath checks a path is joined to the root.
func TestResolveCheckTargetAcceptsARelativePath(t *testing.T) {
	root := t.TempDir()

	path, err := resolveCheckTarget(root, "data/work.yaml")
	if err != nil {
		t.Fatalf("resolve relative path: %v", err)
	}
	want := filepath.Join(root, "data", "work.yaml")
	if path != want {
		t.Fatalf("resolved %q, want %q", path, want)
	}
}

// TestResolveCheckTargetDoesNotDoubleTheRoot checks a path that already starts
// with the tasks root is not prefixed with it a second time.
//
// The spelling "tasks/data/work.yaml" is what a user types from the parent of
// the tasks folder, so joining it to the root produced
// "tasks/tasks/data/work.yaml" and reported a missing file instead of checking
// the task.
func TestResolveCheckTargetDoesNotDoubleTheRoot(t *testing.T) {
	parent := t.TempDir()
	root := filepath.Join(parent, "tasks")
	if err := os.MkdirAll(filepath.Join(root, "data"), 0o755); err != nil {
		t.Fatalf("create task folder: %v", err)
	}
	want := filepath.Join(root, "data", "work.yaml")
	if err := os.WriteFile(want, []byte("schedule: \"0 8 * * *\"\n"), 0o644); err != nil {
		t.Fatalf("write task file: %v", err)
	}

	previous, err := os.Getwd()
	if err != nil {
		t.Fatalf("read working directory: %v", err)
	}
	if err := os.Chdir(parent); err != nil {
		t.Fatalf("enter parent folder: %v", err)
	}
	t.Cleanup(func() {
		if err := os.Chdir(previous); err != nil {
			t.Fatalf("restore working directory: %v", err)
		}
	})

	path, err := resolveCheckTarget(root, "tasks/data/work.yaml")
	if err != nil {
		t.Fatalf("resolve root-relative path: %v", err)
	}
	if path != want {
		t.Fatalf("resolved %q, want %q", path, want)
	}
}

// TestResolveCheckTargetKeepsAnAbsolutePath checks an absolute path is not
// rebased onto the tasks root.
func TestResolveCheckTargetKeepsAnAbsolutePath(t *testing.T) {
	root := t.TempDir()
	absolute := filepath.Join(t.TempDir(), "elsewhere", "work.yaml")

	path, err := resolveCheckTarget(root, absolute)
	if err != nil {
		t.Fatalf("resolve absolute path: %v", err)
	}
	if path != absolute {
		t.Fatalf("resolved %q, want %q", path, absolute)
	}
}

// TestResolveCheckTargetRejectsAnEmptyName checks a blank argument is refused
// rather than silently resolving to the tasks root.
func TestResolveCheckTargetRejectsAnEmptyName(t *testing.T) {
	if _, err := resolveCheckTarget(t.TempDir(), "   "); err == nil {
		t.Fatal("expected an empty task name to be rejected")
	}
}

// TestBuildSingleCheckReportReportsOneValidTask checks a single check reports
// only the task that was asked for.
func TestBuildSingleCheckReportReportsOneValidTask(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "data/work", "schedule: \"0 8 * * *\"\n", "a harmless task body that is long enough")
	writeCheckTask(t, root, "data/other", "schedule: \"0 9 * * *\"\n", "another harmless body")

	report, err := buildSingleCheckReport(root, "data/work", 10)
	if err != nil {
		t.Fatalf("build single report: %v", err)
	}
	if len(report.Tasks) != 1 {
		t.Fatalf("expected one task, got %d: %+v", len(report.Tasks), report.Tasks)
	}
	if report.Valid != 1 || report.Invalid != 0 {
		t.Fatalf("unexpected counts valid=%d invalid=%d", report.Valid, report.Invalid)
	}
	result := findCheckResult(t, report, "data/work")
	if !result.Valid {
		t.Fatalf("expected a valid task, got %+v", result)
	}
	if result.Schedule != "0 8 * * *" {
		t.Fatalf("unexpected schedule %q", result.Schedule)
	}
}

// TestBuildSingleCheckReportReportsAnInvalidTask checks a broken task is
// reported with its reason instead of being dropped.
func TestBuildSingleCheckReportReportsAnInvalidTask(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "data/work", "schedule: \"every morning\"\n", "a harmless task body that is long enough")

	report, err := buildSingleCheckReport(root, "data/work", 10)
	if err != nil {
		t.Fatalf("build single report: %v", err)
	}
	if report.Invalid != 1 || report.Valid != 0 {
		t.Fatalf("unexpected counts valid=%d invalid=%d", report.Valid, report.Invalid)
	}
	result := findCheckResult(t, report, "data/work")
	if result.Valid {
		t.Fatalf("expected an invalid task, got %+v", result)
	}
	if !strings.Contains(result.Error, "invalid schedule") {
		t.Fatalf("expected the reason to name the schedule, got %q", result.Error)
	}
}

// TestBuildSingleCheckReportReportsAMissingTask checks a task that does not
// exist is reported as invalid, not as a command failure.
func TestBuildSingleCheckReportReportsAMissingTask(t *testing.T) {
	root := t.TempDir()

	report, err := buildSingleCheckReport(root, "data/absent", 10)
	if err != nil {
		t.Fatalf("build single report: %v", err)
	}
	if report.Invalid != 1 {
		t.Fatalf("expected one invalid task, got %+v", report)
	}
	result := findCheckResult(t, report, "data/absent")
	if result.Valid {
		t.Fatalf("expected an invalid task, got %+v", result)
	}
	if !strings.Contains(result.Error, "no such file") {
		t.Fatalf("expected a missing-file reason, got %q", result.Error)
	}
}

// TestBuildSingleCheckReportRejectsANonYAMLFile checks a file that is not a task
// configuration is refused rather than parsed as one.
func TestBuildSingleCheckReportRejectsANonYAMLFile(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "data/work", "schedule: \"0 8 * * *\"\n", "a harmless task body that is long enough")

	_, err := buildSingleCheckReport(root, "data/work.md", 10)
	if err == nil {
		t.Fatal("expected a non-YAML target to be refused")
	}
	if !strings.Contains(err.Error(), "not a task configuration file") {
		t.Fatalf("expected a wrong-extension reason, got %q", err)
	}
}

// TestRunCheckSingleTaskExitsZeroOnAValidTask checks the command accepts a task
// argument and reports success.
func TestRunCheckSingleTaskExitsZeroOnAValidTask(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "data/work", "schedule: \"0 8 * * *\"\n", "a harmless task body that is long enough")

	code := captureStdoutCode(t, func() int {
		return runCheck([]string{"--tasks-root", root, "data/work"})
	})
	if code != exitOK {
		t.Fatalf("expected exit %d, got %d", exitOK, code)
	}
}

// TestRunCheckSingleTaskExitsNonZeroOnAnInvalidTask checks a broken task makes
// the command fail so a pipeline can branch on it.
func TestRunCheckSingleTaskExitsNonZeroOnAnInvalidTask(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "data/work", "schedule: \"every morning\"\n", "a harmless task body that is long enough")

	code := captureStdoutCode(t, func() int {
		return runCheck([]string{"--tasks-root", root, "data/work"})
	})
	if code != exitFailure {
		t.Fatalf("expected exit %d, got %d", exitFailure, code)
	}
}

// TestRunCheckRejectsTwoTaskArguments checks the command refuses to guess which
// of two tasks was meant.
func TestRunCheckRejectsTwoTaskArguments(t *testing.T) {
	root := t.TempDir()

	code := captureStdoutCode(t, func() int {
		return runCheck([]string{"--tasks-root", root, "data/work", "data/other"})
	})
	if code != exitUsage {
		t.Fatalf("expected exit %d, got %d", exitUsage, code)
	}
}

// TestRunCheckSingleTaskJSONParses checks the single-task report is valid JSON.
func TestRunCheckSingleTaskJSONParses(t *testing.T) {
	root := t.TempDir()
	writeCheckTask(t, root, "data/work", "schedule: \"0 8 * * *\"\n", "a harmless task body that is long enough")

	output := captureStdout(t, func() {
		runCheck([]string{"--tasks-root", root, "--json", "data/work"})
	})

	var report checkReport
	if err := json.Unmarshal([]byte(output), &report); err != nil {
		t.Fatalf("expected parseable JSON, got %v in %q", err, output)
	}
	if report.Valid != 1 || report.Invalid != 0 {
		t.Fatalf("unexpected counts valid=%d invalid=%d", report.Valid, report.Invalid)
	}
	if len(report.Tasks) != 1 || report.Tasks[0].ID != "data/work" {
		t.Fatalf("unexpected tasks %+v", report.Tasks)
	}
}
