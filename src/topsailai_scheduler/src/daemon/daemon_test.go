package daemon

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_scheduler/config"
	"topsailai_scheduler/launcher"
	"topsailai_scheduler/lock"
	"topsailai_scheduler/logging"
	"topsailai_scheduler/provider"
	"topsailai_scheduler/runtime"
	"topsailai_scheduler/task"
)

// fakeProviderScript is a provider executable that answers the protocol without
// running anything.
//
// A shell script is used rather than a Go value because a provider is an
// independent program: the daemon must be tested against a foreign executable,
// not against an in-process double. Its behaviour is scripted through the
// environment, which the provider inherits from the scheduler, so the test needs
// no JSON parsing in the script.
//
//	FAKE_PROVIDER_PLAN      running, or finished:<exit code> (default finished:0)
//	FAKE_PROVIDER_RECORD    file that receives the start request document
//	FAKE_PROVIDER_STOP_LOG  file that receives each stop request document
const fakeProviderScript = `#!/bin/sh
operation="$1"
payload=$(cat)
case "$operation" in
  start)
    if [ -n "$FAKE_PROVIDER_RECORD" ]; then
      printf '%s' "$payload" > "$FAKE_PROVIDER_RECORD"
    fi
    printf '{"protocol_version":1,"run_id":"run-%s","pid":%s}' "$$" "$$"
    ;;
  poll)
    plan="${FAKE_PROVIDER_PLAN:-finished:0}"
    case "$plan" in
      running) printf '{"state":"running"}' ;;
      finished:*) printf '{"state":"finished","exit_code":%s}' "${plan#finished:}" ;;
      *) printf '{"state":"%s"}' "$plan" ;;
    esac
    ;;
  stop)
    if [ -n "$FAKE_PROVIDER_STOP_LOG" ]; then
      printf '%s\n' "$payload" >> "$FAKE_PROVIDER_STOP_LOG"
    fi
    exit 0
    ;;
  *) echo "unknown operation $operation" >&2; exit 2 ;;
esac
`

// fakeProviderName is the file name of the fake provider every daemon test uses.
const fakeProviderName = "fake"

// fakeProviderPath returns the path of the fake provider for a test root.
//
// The executable lives in a dot-folder, which the task scan skips, and the path
// is derived from the root so a test can name the provider before the daemon
// exists. The lock-record tests need that: they write a record naming the
// provider, and the record must match what the daemon later computes.
func fakeProviderPath(root string) string {
	return filepath.Join(root, ".provider", fakeProviderName)
}

// writeFakeProvider installs the fake provider for root and returns its path.
//
// The scheduler takes a provider path, so the helper returns the executable
// itself rather than a providers root: there is no folder layout to follow.
func writeFakeProvider(t *testing.T, root string) string {
	t.Helper()

	path := fakeProviderPath(root)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("create provider folder: %v", err)
	}
	if err := os.WriteFile(path, []byte(fakeProviderScript), 0o755); err != nil {
		t.Fatalf("write fake provider: %v", err)
	}
	return path
}

// writeFakeProviderAt installs the fake provider at an exact path.
//
// A test that needs the provider to appear later, or to disappear, controls the
// path itself instead of letting writeFakeProvider choose one.
func writeFakeProviderAt(t *testing.T, path string) {
	t.Helper()

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("create provider folder: %v", err)
	}
	if err := os.WriteFile(path, []byte(fakeProviderScript), 0o755); err != nil {
		t.Fatalf("write fake provider: %v", err)
	}
}

// findStatus returns the status of one task, failing when it is absent.
func findStatus(t *testing.T, snapshot runtime.Snapshot, id string) runtime.TaskStatus {
	t.Helper()

	for _, status := range snapshot.Tasks {
		if status.ID == id {
			return status
		}
	}
	t.Fatalf("task %q is missing from the status", id)
	return runtime.TaskStatus{}
}

// testConfig builds a configuration pointing at root with short timings so a
// test never waits for a production default.
func testConfig(root, providerPath string) config.Config {
	return config.Config{
		TasksRoot:           root,
		Workspace:           root,
		DefaultTimeout:      10 * time.Second,
		MaxConcurrent:       4,
		RescanInterval:      time.Hour,
		ShutdownGrace:       time.Second,
		MaxOutputBytes:      4096,
		ControlSocket:       filepath.Join(root, "scheduler.sock"),
		DefaultProviderPath: providerPath,
		PollInterval:        50 * time.Millisecond,
		ProviderCallTimeout: 5 * time.Second,
		MinContentRunes:     config.DefaultMinContentRunes,
	}
}

// newTestDaemon builds a daemon over root whose log is written to logPath.
func newTestDaemon(t *testing.T, root, logPath string) *Daemon {
	t.Helper()

	return newTestDaemonWithProvider(t, root, logPath, writeFakeProvider(t, root))
}

// newTestDaemonWithProvider builds a daemon over root using the provider at
// providerPath.
//
// A test whose root cannot hold the provider uses this form: the tasks root may
// be a file, which is exactly what one test checks, so the provider has to live
// somewhere else.
func newTestDaemonWithProvider(t *testing.T, root, logPath, providerPath string) *Daemon {
	t.Helper()

	logger, closer, err := logging.New(logging.Options{Output: logPath, Level: "debug"})
	if err != nil {
		t.Fatalf("build logger: %v", err)
	}
	t.Cleanup(func() {
		if closeErr := closer.Close(); closeErr != nil {
			t.Errorf("close log: %v", closeErr)
		}
	})

	providers := provider.NewResolver(provider.ResolverOptions{
		CallTimeout:    5 * time.Second,
		MaxOutputBytes: 4096,
	})

	cfg := testConfig(root, providerPath)
	return New(cfg, logger, task.NewFilesystemSource(root, cfg.MinContentRunes), launcher.DefaultRegistry(), providers, providerPath)
}

// writeTask writes the YAML and Markdown files of one task.
func writeTask(t *testing.T, root, id, yamlContent, markdown string) {
	t.Helper()

	dir := filepath.Join(root, filepath.Dir(id))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("create task folder: %v", err)
	}
	stem := filepath.Base(id)
	if err := os.WriteFile(filepath.Join(dir, stem+".yaml"), []byte(yamlContent), 0o644); err != nil {
		t.Fatalf("write yaml: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, stem+".md"), []byte(markdown), 0o644); err != nil {
		t.Fatalf("write markdown: %v", err)
	}
}

// readLog returns the log file content.
func readLog(t *testing.T, logPath string) string {
	t.Helper()

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	return string(content)
}

// TestRescanSchedulesNestedTasks verifies a task in a nested folder is
// registered under its relative id.
func TestRescanSchedulesNestedTasks(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "a/b/c", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	if _, scheduled := scheduler.entries["a/b/c"]; !scheduled {
		t.Fatalf("expected a/b/c to be scheduled, got %v", scheduler.entries)
	}
	if !strings.Contains(readLog(t, logPath), "task scheduled") {
		t.Fatal("expected a scheduling log entry")
	}
}

// TestRescanSkipsDisabledTask verifies a disabled task is loaded for Status but
// never registered with the cron.
func TestRescanSkipsDisabledTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "off", "schedule: \"0 8 * * *\"\nenabled: false\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	if _, scheduled := scheduler.entries["off"]; scheduled {
		t.Fatal("expected a disabled task not to be scheduled")
	}
	if _, known := scheduler.tasks["off"]; !known {
		t.Fatal("expected a disabled task to remain known")
	}
}

// TestRescanRemovesDeletedTask verifies deleting the files unschedules the task
// without a restart.
func TestRescanRemovesDeletedTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "gone", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}
	if _, scheduled := scheduler.entries["gone"]; !scheduled {
		t.Fatal("expected the task to be scheduled first")
	}

	if err := os.Remove(filepath.Join(root, "gone.yaml")); err != nil {
		t.Fatalf("remove yaml: %v", err)
	}
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("second rescan failed: %v", err)
	}

	if _, scheduled := scheduler.entries["gone"]; scheduled {
		t.Fatal("expected the deleted task to be unscheduled")
	}
	if !strings.Contains(readLog(t, logPath), "task removed") {
		t.Fatal("expected a removal log entry")
	}
}

// TestRescanReschedulesChangedTask verifies a content change replaces the cron
// entry, which is how a retimed task takes effect without a restart.
func TestRescanReschedulesChangedTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "changing", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}
	before := scheduler.entries["changing"]

	writeTask(t, root, "changing", "schedule: \"0 9 * * *\"\n", "task content padded to the floor")
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("second rescan failed: %v", err)
	}
	after := scheduler.entries["changing"]

	if before.entryID == after.entryID {
		t.Fatal("expected a new cron entry for the changed task")
	}
	if before.fingerprint == after.fingerprint {
		t.Fatal("expected the fingerprint to change")
	}
	if !strings.Contains(readLog(t, logPath), "task changed, rescheduling") {
		t.Fatal("expected a rescheduling log entry")
	}
}

// TestRescanKeepsUnchangedTask verifies an unchanged task is not rescheduled on
// every scan, which would reset its next run.
func TestRescanKeepsUnchangedTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "stable", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}
	before := scheduler.entries["stable"]

	if err := scheduler.rescan(); err != nil {
		t.Fatalf("second rescan failed: %v", err)
	}
	if after := scheduler.entries["stable"]; after.entryID != before.entryID {
		t.Fatal("expected the cron entry to be kept")
	}
}

// TestRescanReportsInvalidSchedule verifies a task whose schedule cannot be
// parsed is rejected at load time and skipped without aborting the scan.
//
// The rejection happens while loading rather than while registering, because
// task.ValidateSchedule runs inside Spec.Validate. That is deliberate: a task
// that loads but never registers would appear idle and healthy, which is
// indistinguishable from a task that is simply waiting for its next run.
func TestRescanReportsInvalidSchedule(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "bad", "schedule: \"not a cron\"\n", "task content padded to the floor")
	writeTask(t, root, "good", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	if _, scheduled := scheduler.entries["bad"]; scheduled {
		t.Fatal("expected the invalid schedule to be skipped")
	}
	if _, scheduled := scheduler.entries["good"]; !scheduled {
		t.Fatal("expected the valid task to still be scheduled")
	}

	logged := readLog(t, logPath)
	if !strings.Contains(logged, "task file rejected") {
		t.Fatal("expected the invalid schedule to be reported as a rejected file")
	}
	if !strings.Contains(logged, "invalid schedule") {
		t.Fatal("expected the rejection to name the invalid schedule")
	}

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("Status failed: %v", err)
	}
	broken, ok := snapshot.Find("bad")
	if !ok {
		t.Fatal("expected the invalid schedule to appear in the snapshot")
	}
	if broken.State != runtime.StateInvalid {
		t.Fatalf("expected state %q, got %q", runtime.StateInvalid, broken.State)
	}
	if !strings.Contains(broken.Error, "invalid schedule") {
		t.Fatalf("expected the reason to name the invalid schedule, got %q", broken.Error)
	}
}

// TestRescanReportsBrokenFileOnce verifies an unchanged broken file is logged
// once instead of on every scan, and that a fixed file is reported as recovered.
func TestRescanReportsBrokenFileOnce(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "broken", "schedule: \"0 8 * * *\"\nunknown_key: 1\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("second rescan failed: %v", err)
	}

	if count := strings.Count(readLog(t, logPath), "task file rejected"); count != 1 {
		t.Fatalf("expected one rejection entry, got %d", count)
	}

	writeTask(t, root, "broken", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("third rescan failed: %v", err)
	}
	if !strings.Contains(readLog(t, logPath), "task file recovered") {
		t.Fatal("expected a recovery log entry")
	}
}

// TestStatusReportsTaskStates verifies idle, disabled and invalid tasks are all
// visible, sorted by id.
func TestStatusReportsTaskStates(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "b/idle", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")
	writeTask(t, root, "a/off", "schedule: \"0 8 * * *\"\nenabled: false\n", "task content padded to the floor")
	writeTask(t, root, "c/broken", "schedule: \"0 8 * * *\"\nunknown_key: 1\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("Status failed: %v", err)
	}
	if snapshot.TasksRoot != root {
		t.Fatalf("unexpected tasks root %q", snapshot.TasksRoot)
	}

	idle, ok := snapshot.Find("b/idle")
	if !ok || idle.State != runtime.StateIdle {
		t.Fatalf("unexpected idle status %+v", idle)
	}
	if idle.Schedule != "0 8 * * *" {
		t.Fatalf("unexpected schedule %q", idle.Schedule)
	}
	if idle.Launcher != launcher.NameAgent {
		t.Fatalf("unexpected launcher %q", idle.Launcher)
	}
	if !strings.HasSuffix(idle.YAMLPath, filepath.Join("b", "idle.yaml")) {
		t.Fatalf("unexpected yaml path %q", idle.YAMLPath)
	}
	if !strings.HasSuffix(idle.MarkdownPath, filepath.Join("b", "idle.md")) {
		t.Fatalf("unexpected markdown path %q", idle.MarkdownPath)
	}

	disabled, ok := snapshot.Find("a/off")
	if !ok || disabled.State != runtime.StateDisabled {
		t.Fatalf("unexpected disabled status %+v", disabled)
	}

	var invalid *runtime.TaskStatus
	for index := range snapshot.Tasks {
		if snapshot.Tasks[index].State == runtime.StateInvalid {
			invalid = &snapshot.Tasks[index]
		}
	}
	if invalid == nil {
		t.Fatal("expected an invalid task in the snapshot")
	}
	if invalid.Error == "" {
		t.Fatal("expected the invalid task to carry its error")
	}
	// A rejected file must keep the same relative id a valid task would have.
	// Reporting its absolute path would make one task appear under two names
	// depending on whether it currently parses.
	if invalid.ID != "c/broken" {
		t.Fatalf("want invalid task id c/broken, got %q", invalid.ID)
	}
	if !strings.HasSuffix(invalid.YAMLPath, filepath.Join("c", "broken.yaml")) {
		t.Fatalf("unexpected invalid yaml path %q", invalid.YAMLPath)
	}

	for index := 1; index < len(snapshot.Tasks); index++ {
		if snapshot.Tasks[index-1].ID > snapshot.Tasks[index].ID {
			t.Fatalf("snapshot is not sorted: %q before %q",
				snapshot.Tasks[index-1].ID, snapshot.Tasks[index].ID)
		}
	}
}

// TestStatusReportsNextRun verifies a scheduled task exposes its next run once
// the cron is running.
func TestStatusReportsNextRun(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "timed", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}
	scheduler.cron.Start()
	t.Cleanup(func() { <-scheduler.cron.Stop().Done() })

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("Status failed: %v", err)
	}
	status, ok := snapshot.Find("timed")
	if !ok {
		t.Fatal("expected the task in the snapshot")
	}
	if status.NextRun.IsZero() {
		t.Fatal("expected a next run time")
	}
}

// TestLaunchRunsTaskAndWaits verifies a launch with Wait returns the completed
// run, and that the run is recorded in Status.
func TestLaunchRunsTaskAndWaits(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "quick", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 0\"]\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	result, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "quick", Wait: true})
	if err != nil {
		t.Fatalf("Launch failed: %v", err)
	}
	if result.TaskID != "quick" {
		t.Fatalf("unexpected task id %q", result.TaskID)
	}
	if result.TraceID == "" {
		t.Fatal("expected a trace id")
	}
	if result.Record == nil {
		t.Fatal("expected a completed record")
	}
	if result.Record.ExitCode != 0 {
		t.Fatalf("unexpected exit code %d", result.Record.ExitCode)
	}
	if result.Record.TimedOut || result.Record.Stopped {
		t.Fatalf("unexpected flags %+v", result.Record)
	}
	if result.Record.Provider != fakeProviderPath(root) {
		t.Fatalf("unexpected provider %q", result.Record.Provider)
	}
	if result.Record.RunID == "" {
		t.Fatal("expected the provider run id to be recorded")
	}

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("Status failed: %v", err)
	}
	status, ok := snapshot.Find("quick")
	if !ok {
		t.Fatal("expected the task in the snapshot")
	}
	if status.State != runtime.StateIdle {
		t.Fatalf("unexpected state %q", status.State)
	}
	if status.LastRun == nil || status.LastRun.ExitCode != 0 {
		t.Fatalf("unexpected last run %+v", status.LastRun)
	}
	// The log describes the lifecycle only. There is deliberately no verdict
	// word: whether the work was good belongs to the task content.
	if !strings.Contains(readLog(t, logPath), "run finished") {
		t.Fatal("expected a lifecycle log entry")
	}
}

// TestLaunchSendsTheTaskToTheProvider verifies the request document the provider
// receives carries the facts the scheduler owns.
//
// The provider is an independent program, so the document is the only thing
// connecting it to the scheduler. A field silently missing here would make a
// provider unable to find the task it was asked to run.
func TestLaunchSendsTheTaskToTheProvider(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	recordPath := filepath.Join(t.TempDir(), "request.json")
	writeTask(t, root, "data/work", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 0\"]\ntimeout: 90s\n", "task content padded to the floor")

	t.Setenv("FAKE_PROVIDER_RECORD", recordPath)

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}
	if _, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "data/work", Wait: true}); err != nil {
		t.Fatalf("Launch failed: %v", err)
	}

	content, err := os.ReadFile(recordPath)
	if err != nil {
		t.Fatalf("read recorded request: %v", err)
	}

	var document struct {
		ProtocolVersion int    `json:"protocol_version"`
		TaskID          string `json:"task_id"`
		TaskPath        string `json:"task_path"`
		TaskDir         string `json:"task_dir"`
		Workspace       string `json:"workspace"`
		Command         string `json:"command"`
		TimeoutMS       int64  `json:"timeout_ms"`
	}
	if err := json.Unmarshal(content, &document); err != nil {
		t.Fatalf("decode recorded request %q: %v", content, err)
	}

	if document.ProtocolVersion != provider.ProtocolVersion {
		t.Errorf("protocol version = %d, want %d", document.ProtocolVersion, provider.ProtocolVersion)
	}
	if document.TaskID != "data/work" {
		t.Errorf("task id = %q, want %q", document.TaskID, "data/work")
	}
	if !strings.HasSuffix(document.TaskPath, filepath.Join("data", "work.md")) {
		t.Errorf("task path = %q, want the markdown file", document.TaskPath)
	}
	if !strings.HasSuffix(document.TaskDir, filepath.Join("data")) {
		t.Errorf("task dir = %q, want the task folder", document.TaskDir)
	}
	if document.Workspace != root {
		t.Errorf("workspace = %q, want %q", document.Workspace, root)
	}
	if document.Command != "/bin/sh" {
		t.Errorf("command = %q, want %q", document.Command, "/bin/sh")
	}
	if document.TimeoutMS != (90 * time.Second).Milliseconds() {
		t.Errorf("timeout = %d ms, want %d", document.TimeoutMS, (90 * time.Second).Milliseconds())
	}
}

// TestLaunchReportsNonZeroExit verifies a non-zero exit is recorded as a
// lifecycle fact rather than a launch error.
//
// The scheduler does not decide what a non-zero code means: it may be the work
// failing, or a wrapper exiting. It records the number and leaves the judgement
// to the task content.
func TestLaunchReportsNonZeroExit(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "failing", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 3\"]\n", "task content padded to the floor")

	t.Setenv("FAKE_PROVIDER_PLAN", "finished:3")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	result, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "failing", Wait: true})
	if err != nil {
		t.Fatalf("Launch failed: %v", err)
	}
	if result.Record == nil || result.Record.ExitCode != 3 {
		t.Fatalf("unexpected record %+v", result.Record)
	}

	log := readLog(t, logPath)
	if !strings.Contains(log, "run finished") {
		t.Fatal("expected a lifecycle log entry")
	}
	if !strings.Contains(log, `"exit_code":3`) {
		t.Fatalf("expected the exit code to be logged as a fact, got %q", log)
	}
}

// TestLaunchSkipsRunningTask verifies a second launch of a running task starts
// no new run.
//
// The provider is told to keep reporting "running", so the first round stays
// under supervision without needing a real long-lived child process.
func TestLaunchSkipsRunningTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "slow", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 0\"]\n", "task content padded to the floor")

	t.Setenv("FAKE_PROVIDER_PLAN", "running")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	first, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "slow"})
	if err != nil {
		t.Fatalf("first Launch failed: %v", err)
	}
	if first.PID <= 0 {
		t.Fatalf("expected a pid, got %d", first.PID)
	}

	second, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "slow"})
	if err != nil {
		t.Fatalf("second Launch failed: %v", err)
	}
	if !second.Skipped {
		t.Fatal("expected the second launch to be skipped")
	}
	if second.PID != 0 {
		t.Fatalf("expected no pid for a skipped launch, got %d", second.PID)
	}

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("Status failed: %v", err)
	}
	status, ok := snapshot.Find("slow")
	if !ok || status.State != runtime.StateRunning {
		t.Fatalf("unexpected status %+v", status)
	}
	if status.Run == nil || status.Run.PID != first.PID {
		t.Fatalf("unexpected run info %+v", status.Run)
	}
	if status.Run.RunID == "" {
		t.Fatal("expected the in-flight run to expose the provider run id")
	}

	// The round must be stopped and drained before the test ends, otherwise the
	// supervisor keeps polling a temporary folder that is being removed.
	if _, err := scheduler.Stop(runtime.StopRequest{TaskID: "slow", Force: true}); err != nil {
		t.Fatalf("Stop failed: %v", err)
	}
	waitForIdle(t, scheduler, "slow")
}

// TestLaunchRejectsUnknownTask verifies an unknown id is reported with the
// contract sentinel error.
func TestLaunchRejectsUnknownTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	scheduler := newTestDaemon(t, root, logPath)

	_, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "nope"})
	if !errors.Is(err, runtime.ErrTaskNotFound) {
		t.Fatalf("want ErrTaskNotFound, got %v", err)
	}
}

// TestLaunchRejectsEmptyTaskID verifies an empty id is refused instead of
// matching something by accident.
func TestLaunchRejectsEmptyTaskID(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	scheduler := newTestDaemon(t, root, logPath)

	_, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "   "})
	if !errors.Is(err, runtime.ErrTaskNotFound) {
		t.Fatalf("want ErrTaskNotFound, got %v", err)
	}
}

// TestLaunchRejectsDisabledTask verifies a disabled task is refused, because
// running it would contradict its own configuration.
func TestLaunchRejectsDisabledTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "off", "schedule: \"0 8 * * *\"\nenabled: false\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	_, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "off"})
	if !errors.Is(err, runtime.ErrTaskDisabled) {
		t.Fatalf("want ErrTaskDisabled, got %v", err)
	}
}

// TestLaunchRejectsUnknownLauncher verifies a task naming an unregistered
// launcher fails with a message that lists the available ones.
func TestLaunchRejectsUnknownLauncher(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "weird", "schedule: \"0 8 * * *\"\nlauncher: teleport\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	_, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "weird"})
	if err == nil {
		t.Fatal("expected an unknown launcher to be rejected")
	}
	if !strings.Contains(err.Error(), "teleport") {
		t.Fatalf("unexpected error %v", err)
	}
}

// TestLaunchRefusesWhileShuttingDown verifies no new run starts once shutdown
// began.
func TestLaunchRefusesWhileShuttingDown(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "task", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 0\"]\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	scheduler.mu.Lock()
	scheduler.stopping = true
	scheduler.mu.Unlock()

	_, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "task"})
	if !errors.Is(err, runtime.ErrShuttingDown) {
		t.Fatalf("want ErrShuttingDown, got %v", err)
	}
}

// TestStopTerminatesRunningTask verifies an active stop ends the run and clears
// the running state.
func TestStopTerminatesRunningTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "slow", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 0\"]\n", "task content padded to the floor")

	t.Setenv("FAKE_PROVIDER_PLAN", "running")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	launched, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "slow"})
	if err != nil {
		t.Fatalf("Launch failed: %v", err)
	}

	stopped, err := scheduler.Stop(runtime.StopRequest{TaskID: "slow"})
	if err != nil {
		t.Fatalf("Stop failed: %v", err)
	}
	if stopped.PID != launched.PID {
		t.Fatalf("want pid %d, got %d", launched.PID, stopped.PID)
	}
	if stopped.Forced {
		t.Fatal("expected a graceful stop")
	}

	waitForIdle(t, scheduler, "slow")

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("Status failed: %v", err)
	}
	status, ok := snapshot.Find("slow")
	if !ok {
		t.Fatal("expected the task in the snapshot")
	}
	if status.State != runtime.StateIdle {
		t.Fatalf("unexpected state %q", status.State)
	}
	if status.LastRun == nil || !status.LastRun.Stopped {
		t.Fatalf("expected the run to be recorded as stopped, got %+v", status.LastRun)
	}
	if !strings.Contains(readLog(t, logPath), "run stopped by request") {
		t.Fatal("expected a stop log entry")
	}
}

// TestStopRejectsIdleTask verifies stopping a task with no in-flight run is
// reported with the contract sentinel error.
func TestStopRejectsIdleTask(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "idle", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	_, err := scheduler.Stop(runtime.StopRequest{TaskID: "idle"})
	if !errors.Is(err, runtime.ErrTaskNotRunning) {
		t.Fatalf("want ErrTaskNotRunning, got %v", err)
	}
}

// TestStopReportsForced verifies a forced stop is reported as forced. The
// scheduler forwards the request to the provider; it does not choose a signal.
func TestStopReportsForced(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "slow", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 0\"]\n", "task content padded to the floor")

	t.Setenv("FAKE_PROVIDER_PLAN", "running")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}
	if _, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "slow"}); err != nil {
		t.Fatalf("Launch failed: %v", err)
	}

	stopped, err := scheduler.Stop(runtime.StopRequest{TaskID: "slow", Force: true})
	if err != nil {
		t.Fatalf("Stop failed: %v", err)
	}
	if !stopped.Forced {
		t.Fatal("expected a forced stop")
	}
	waitForIdle(t, scheduler, "slow")
}

// TestLockPreventsOverlapAcrossDaemons verifies two daemons sharing one tasks
// folder never run the same task at the same time, which is the whole point of
// the .lock file.
func TestLockPreventsOverlapAcrossDaemons(t *testing.T) {
	root := t.TempDir()
	firstLog := filepath.Join(t.TempDir(), "first.log")
	secondLog := filepath.Join(t.TempDir(), "second.log")
	writeTask(t, root, "shared", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 0\"]\n", "task content padded to the floor")

	t.Setenv("FAKE_PROVIDER_PLAN", "running")

	first := newTestDaemon(t, root, firstLog)
	second := newTestDaemon(t, root, secondLog)
	for _, scheduler := range []*Daemon{first, second} {
		if err := scheduler.rescan(); err != nil {
			t.Fatalf("rescan failed: %v", err)
		}
	}

	launched, err := first.Launch(runtime.LaunchRequest{TaskID: "shared"})
	if err != nil {
		t.Fatalf("first Launch failed: %v", err)
	}
	if launched.PID <= 0 {
		t.Fatalf("expected a pid, got %d", launched.PID)
	}

	blocked, err := second.Launch(runtime.LaunchRequest{TaskID: "shared", Wait: true})
	if err != nil {
		t.Fatalf("second Launch failed: %v", err)
	}
	if blocked.Record == nil {
		t.Fatal("expected the blocked run to be recorded")
	}
	if blocked.Record.ExitCode != -1 {
		t.Fatalf("expected the blocked run to record no exit, got %d", blocked.Record.ExitCode)
	}
	if !strings.Contains(readLog(t, secondLog), "run skipped, task already running") {
		t.Fatal("expected the second daemon to log the skip")
	}

	// The first run must be stopped and drained before the test ends, otherwise
	// the still-running child recreates files while the temporary folder is
	// being removed.
	if _, err := first.Stop(runtime.StopRequest{TaskID: "shared", Force: true}); err != nil {
		t.Fatalf("Stop failed: %v", err)
	}
	waitForIdle(t, first, "shared")
	waitForIdle(t, second, "shared")
}

// TestHistoryIsBounded verifies only the most recent runs are remembered, so a
// long-lived daemon cannot grow its memory without bound.
func TestHistoryIsBounded(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "quick", "schedule: \"0 8 * * *\"\nlauncher: command\ncommand: /bin/sh\nargs: [\"-c\", \"exit 0\"]\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	for run := 0; run < historySize+2; run++ {
		if _, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "quick", Wait: true}); err != nil {
			t.Fatalf("Launch %d failed: %v", run, err)
		}
	}

	scheduler.mu.Lock()
	records := len(scheduler.history["quick"])
	scheduler.mu.Unlock()

	if records != historySize {
		t.Fatalf("want %d remembered runs, got %d", historySize, records)
	}
}

// TestRunStopsOnContextCancel verifies the daemon returns cleanly when its
// context ends, which is how SIGTERM shuts it down.
func TestRunStopsOnContextCancel(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "task", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	ctx, cancel := context.WithCancel(context.Background())

	served := make(chan error, 1)
	go func() { served <- scheduler.Run(ctx) }()

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		scheduler.mu.Lock()
		scheduled := len(scheduler.entries)
		scheduler.mu.Unlock()
		if scheduled > 0 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}

	cancel()
	select {
	case err := <-served:
		if err != nil {
			t.Fatalf("Run failed: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the daemon did not stop")
	}
	if !strings.Contains(readLog(t, logPath), "scheduler stopped") {
		t.Fatal("expected a shutdown log entry")
	}
}

// TestRunRejectsTasksRootThatIsAFile verifies a misconfigured tasks root is
// reported instead of silently scheduling nothing.
func TestRunRejectsTasksRootThatIsAFile(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	filePath := filepath.Join(root, "not-a-folder")
	if err := os.WriteFile(filePath, []byte("data"), 0o644); err != nil {
		t.Fatalf("write file: %v", err)
	}

	// The tasks root is a file here, so the provider cannot live inside it.
	providerRoot := t.TempDir()
	scheduler := newTestDaemonWithProvider(t, filePath, logPath, writeFakeProvider(t, providerRoot))
	if err := scheduler.Run(context.Background()); err == nil {
		t.Fatal("expected a tasks root that is a file to be rejected")
	}
}

// TestScheduleAcceptsFiveFieldExpression verifies the familiar five-field cron
// form is accepted even though the cron instance has seconds enabled.
func TestScheduleAcceptsFiveFieldExpression(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	scheduler := newTestDaemon(t, root, logPath)

	item := task.Task{ID: "five", Spec: task.Spec{Schedule: "0 8 * * *"}}
	if _, err := scheduler.schedule(item); err != nil {
		t.Fatalf("five-field schedule rejected: %v", err)
	}
}

// TestScheduleAcceptsShortcut verifies an @shortcut expression is accepted.
func TestScheduleAcceptsShortcut(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	scheduler := newTestDaemon(t, root, logPath)

	item := task.Task{ID: "daily", Spec: task.Spec{Schedule: "@daily"}}
	if _, err := scheduler.schedule(item); err != nil {
		t.Fatalf("@daily rejected: %v", err)
	}
}

// TestScheduleRejectsInvalidExpression verifies an unparsable schedule is an
// error that names the original expression.
func TestScheduleRejectsInvalidExpression(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	scheduler := newTestDaemon(t, root, logPath)

	item := task.Task{ID: "bad", Spec: task.Spec{Schedule: "every so often"}}
	_, err := scheduler.schedule(item)
	if err == nil {
		t.Fatal("expected an invalid schedule to be rejected")
	}
	if !strings.Contains(err.Error(), "every so often") {
		t.Fatalf("unexpected error %v", err)
	}
}

// TestLauncherNameDefaultsToAgent verifies a task without a launcher uses the
// agent, so the common case needs no configuration.
func TestLauncherNameDefaultsToAgent(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	scheduler := newTestDaemon(t, root, logPath)

	if got := scheduler.launcherName(task.Task{}); got != launcher.NameAgent {
		t.Fatalf("want %q, got %q", launcher.NameAgent, got)
	}
	named := task.Task{Spec: task.Spec{Launcher: " command "}}
	if got := scheduler.launcherName(named); got != launcher.NameCommand {
		t.Fatalf("want %q, got %q", launcher.NameCommand, got)
	}
}

// TestBuildRequestUsesConfiguredDefaults verifies the scheduler-wide values
// reach the launcher, so a task only states what differs.
//
// The agent launcher deliberately leaves Command empty: the invocation belongs
// to the provider, which is an independent project. The scheduler supplies only
// the facts it owns.
func TestBuildRequestUsesConfiguredDefaults(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	scheduler := newTestDaemon(t, root, logPath)

	item := task.Task{
		ID:           "data/work",
		MarkdownPath: filepath.Join(root, "data", "work.md"),
		Spec:         task.Spec{Schedule: "0 8 * * *"},
	}
	request, name, providerName, err := scheduler.buildRequest(item)
	if err != nil {
		t.Fatalf("buildRequest failed: %v", err)
	}
	if name != launcher.NameAgent {
		t.Fatalf("unexpected launcher %q", name)
	}
	if providerName != fakeProviderPath(root) {
		t.Fatalf("unexpected provider %q", providerName)
	}
	if request.Command != "" {
		t.Fatalf("the agent launcher must leave the command to the provider, got %q", request.Command)
	}
	if request.Workspace != root {
		t.Fatalf("unexpected workspace %q", request.Workspace)
	}
	if request.TaskID != "data/work" {
		t.Fatalf("unexpected task id %q", request.TaskID)
	}
	if request.Timeout != 10*time.Second {
		t.Fatalf("unexpected timeout %v", request.Timeout)
	}
}

// TestLaunchRejectsMissingProvider verifies a task naming a provider with no
// executable fails with a message that names the provider.
//
// The task scan already rejects such a task, but the task stays in the table, so
// a manual launch must still report the real reason instead of claiming the task
// does not exist. The error must name the provider: "unknown provider" without
// the name leaves an operator guessing which task is misconfigured.
func TestLaunchRejectsMissingProvider(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "data/work", "schedule: \"0 8 * * *\"\nprovider: absent\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	_, err := scheduler.Launch(runtime.LaunchRequest{TaskID: "data/work"})
	if err == nil {
		t.Fatal("expected a missing provider to be rejected")
	}
	if !strings.Contains(err.Error(), "absent") {
		t.Fatalf("unexpected error %v", err)
	}
}

// TestRescanRejectsMissingProvider verifies a task naming a provider with no
// executable is not scheduled, so it never fires and never fails at due time.
//
// The task must still be listed, because a task that silently disappears is
// harder to diagnose than one that reports why it cannot run.
func TestRescanRejectsMissingProvider(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "data/broken", "schedule: \"0 8 * * *\"\nprovider: absent\n", "task content padded to the floor")
	writeTask(t, root, "data/good", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	if _, scheduled := scheduler.entries["data/broken"]; scheduled {
		t.Fatal("expected the task with a missing provider not to be scheduled")
	}
	if _, scheduled := scheduler.entries["data/good"]; !scheduled {
		t.Fatal("expected the healthy task to stay scheduled")
	}

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("status failed: %v", err)
	}
	broken := findStatus(t, snapshot, "data/broken")
	if broken.State != runtime.StateInvalid {
		t.Fatalf("expected invalid, got %q", broken.State)
	}
	if !strings.Contains(broken.Error, "absent") {
		t.Fatalf("expected the error to name the provider, got %q", broken.Error)
	}
	if !broken.NextRun.IsZero() {
		t.Fatalf("expected no next run, got %v", broken.NextRun)
	}

	good := findStatus(t, snapshot, "data/good")
	if good.State != runtime.StateIdle {
		t.Fatalf("expected the healthy task to stay idle, got %q", good.State)
	}
}

// TestRescanReportsMissingProviderOnce verifies an unchanged provider failure is
// logged once, not on every rescan.
//
// The task tree is rescanned on a timer, so logging every time would bury the
// rest of the log under one repeated message.
func TestRescanReportsMissingProviderOnce(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "data/broken", "schedule: \"0 8 * * *\"\nprovider: absent\n", "task content padded to the floor")

	scheduler := newTestDaemon(t, root, logPath)
	for attempt := 0; attempt < 3; attempt++ {
		if err := scheduler.rescan(); err != nil {
			t.Fatalf("rescan %d failed: %v", attempt, err)
		}
	}

	if count := strings.Count(readLog(t, logPath), "task not scheduled"); count != 1 {
		t.Fatalf("expected one report, got %d", count)
	}
}

// TestRescanSchedulesTaskAfterProviderAppears verifies a task rejected for a
// missing provider is scheduled once the provider exists.
//
// Recovery must be visible: a task that stays invalid after the provider is
// installed looks like the fix did not work.
func TestRescanSchedulesTaskAfterProviderAppears(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	providerPath := filepath.Join(t.TempDir(), "late-provider")
	writeTask(t, root, "data/work", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemonWithProvider(t, root, logPath, providerPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("first rescan failed: %v", err)
	}
	if _, scheduled := scheduler.entries["data/work"]; scheduled {
		t.Fatal("expected the task not to be scheduled before the provider exists")
	}

	writeFakeProviderAt(t, providerPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("second rescan failed: %v", err)
	}
	if _, scheduled := scheduler.entries["data/work"]; !scheduled {
		t.Fatal("expected the task to be scheduled once the provider exists")
	}

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("status failed: %v", err)
	}
	if state := findStatus(t, snapshot, "data/work").State; state != runtime.StateIdle {
		t.Fatalf("expected idle after recovery, got %q", state)
	}
	if !strings.Contains(readLog(t, logPath), "task provider recovered") {
		t.Fatal("expected the recovery to be logged")
	}
}

// TestStatusKeepsRunningTaskWhenProviderDisappears verifies a live run is still
// reported as running after its provider executable is removed.
//
// A running process is real. Reporting it as invalid would hide work that is
// actually happening.
func TestStatusKeepsRunningTaskWhenProviderDisappears(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	providerPath := filepath.Join(t.TempDir(), "provider")
	writeFakeProviderAt(t, providerPath)
	writeTask(t, root, "data/work", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	scheduler := newTestDaemonWithProvider(t, root, logPath, providerPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	scheduler.mu.Lock()
	scheduler.runs["data/work"] = &activeRun{info: runtime.RunInfo{RunID: "run-1"}}
	scheduler.mu.Unlock()

	if err := os.Remove(providerPath); err != nil {
		t.Fatalf("remove provider: %v", err)
	}
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("second rescan failed: %v", err)
	}

	snapshot, err := scheduler.Status()
	if err != nil {
		t.Fatalf("status failed: %v", err)
	}
	if state := findStatus(t, snapshot, "data/work").State; state != runtime.StateRunning {
		t.Fatalf("expected running to win over invalid, got %q", state)
	}
}

// TestNewTraceIDIsUniquePerRun verifies two runs of one task get different trace
// ids, so their log entries stay distinguishable.
func TestNewTraceIDIsUniquePerRun(t *testing.T) {
	first := newTraceID("data/work")
	second := newTraceID("data/work")

	if first == second {
		t.Fatalf("expected distinct trace ids, got %q twice", first)
	}
	if strings.Contains(first, "/") {
		t.Fatalf("expected the slash to be replaced, got %q", first)
	}
	if !strings.HasPrefix(first, "data-work-") {
		t.Fatalf("unexpected trace id %q", first)
	}
}

// waitForIdle blocks until the task has no in-flight run.
func waitForIdle(t *testing.T, scheduler *Daemon, taskID string) {
	t.Helper()

	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		scheduler.mu.Lock()
		_, running := scheduler.runs[taskID]
		scheduler.mu.Unlock()
		if !running {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("task %q did not become idle", taskID)
}

// writeLockRecord seeds a lock file with a record, standing in for a supervisor
// that died while a run was in flight.
func writeLockRecord(t *testing.T, path string, record lock.Record) {
	t.Helper()

	document, err := json.Marshal(record)
	if err != nil {
		t.Fatalf("encode record: %v", err)
	}
	if writeErr := os.WriteFile(path, document, 0o600); writeErr != nil {
		t.Fatalf("write record: %v", writeErr)
	}
}

// readStopLog returns the stop request documents the fake provider received.
func readStopLog(t *testing.T, path string) []string {
	t.Helper()

	content, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		t.Fatalf("read stop log: %v", err)
	}
	trimmed := strings.TrimSpace(string(content))
	if trimmed == "" {
		return nil
	}
	return strings.Split(trimmed, "\n")
}

// TestStopForwardsToARecordedRun verifies a stop reaches the run named by the
// lock record when the scheduler is not supervising it.
//
// This is the case a restart creates: the run table is empty while the run may
// still be working, so the record is the only thing that names it.
func TestStopForwardsToARecordedRun(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	stopLog := filepath.Join(t.TempDir(), "stops.log")
	writeTask(t, root, "orphan", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")
	writeLockRecord(t, filepath.Join(root, "orphan.lock"), lock.Record{
		RunID:    "run-old",
		Provider: fakeProviderPath(root),
		PID:      4242,
	})

	t.Setenv("FAKE_PROVIDER_PLAN", "running")
	t.Setenv("FAKE_PROVIDER_STOP_LOG", stopLog)

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	stopped, err := scheduler.Stop(runtime.StopRequest{TaskID: "orphan"})
	if err != nil {
		t.Fatalf("Stop failed: %v", err)
	}
	if !stopped.BestEffort {
		t.Error("expected the stop to be reported as best effort")
	}
	if stopped.PID != 4242 {
		t.Errorf("want the recorded pid 4242, got %d", stopped.PID)
	}

	stops := readStopLog(t, stopLog)
	if len(stops) != 1 {
		t.Fatalf("expected exactly one stop request, got %d", len(stops))
	}
	if !strings.Contains(stops[0], "run-old") {
		t.Errorf("expected the stop to name the recorded run, got %s", stops[0])
	}

	// The scheduler cannot confirm the run ended, so the record must survive for
	// the next start to reconcile.
	record, err := lock.ReadRecord(filepath.Join(root, "orphan.lock"))
	if err != nil {
		t.Fatalf("read record: %v", err)
	}
	if record.RunID != "run-old" {
		t.Errorf("expected the record to be kept, got %+v", record)
	}
	if !strings.Contains(readLog(t, logPath), `"best_effort":true`) {
		t.Error("expected the log to mark the stop as best effort")
	}
}

// TestStopRejectsARecordedRunThatAlreadyFinished verifies a stop is not sent to
// a run that ended on its own after the supervisor died.
func TestStopRejectsARecordedRunThatAlreadyFinished(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	stopLog := filepath.Join(t.TempDir(), "stops.log")
	writeTask(t, root, "orphan", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")
	writeLockRecord(t, filepath.Join(root, "orphan.lock"), lock.Record{
		RunID:    "run-old",
		Provider: fakeProviderPath(root),
		PID:      4242,
	})

	t.Setenv("FAKE_PROVIDER_PLAN", "finished:0")
	t.Setenv("FAKE_PROVIDER_STOP_LOG", stopLog)

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	_, err := scheduler.Stop(runtime.StopRequest{TaskID: "orphan"})
	if !errors.Is(err, runtime.ErrTaskNotRunning) {
		t.Fatalf("want ErrTaskNotRunning, got %v", err)
	}
	if stops := readStopLog(t, stopLog); len(stops) != 0 {
		t.Errorf("expected no stop request for a finished run, got %v", stops)
	}
}

// TestStopRejectsATaskWithNoRecord verifies an empty lock file is not treated as
// a run to stop.
func TestStopRejectsATaskWithNoRecord(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	stopLog := filepath.Join(t.TempDir(), "stops.log")
	writeTask(t, root, "idle", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	t.Setenv("FAKE_PROVIDER_STOP_LOG", stopLog)

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	_, err := scheduler.Stop(runtime.StopRequest{TaskID: "idle"})
	if !errors.Is(err, runtime.ErrTaskNotRunning) {
		t.Fatalf("want ErrTaskNotRunning, got %v", err)
	}
	if stops := readStopLog(t, stopLog); len(stops) != 0 {
		t.Errorf("expected no stop request without a record, got %v", stops)
	}
}

// TestStopRefusesWhileALiveSupervisorHoldsTheLock verifies the fallback never
// races a live supervisor.
//
// A held lock proves a supervisor owns the task, so the empty run table is only
// stale bookkeeping in this process. The owning supervisor's own stop path is
// authoritative, and forwarding a second stop from here would be a race.
func TestStopRefusesWhileALiveSupervisorHoldsTheLock(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	stopLog := filepath.Join(t.TempDir(), "stops.log")
	writeTask(t, root, "busy", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")

	lockPath := filepath.Join(root, "busy.lock")
	writeLockRecord(t, lockPath, lock.Record{
		RunID:    "run-live",
		Provider: fakeProviderPath(root),
		PID:      5151,
	})

	t.Setenv("FAKE_PROVIDER_PLAN", "running")
	t.Setenv("FAKE_PROVIDER_STOP_LOG", stopLog)

	held, acquired, err := lock.TryAcquire(lockPath)
	if err != nil {
		t.Fatalf("acquire lock: %v", err)
	}
	if !acquired {
		t.Fatal("expected to acquire the lock")
	}
	defer func() {
		if releaseErr := held.Release(); releaseErr != nil {
			t.Errorf("release lock: %v", releaseErr)
		}
	}()

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	_, err = scheduler.Stop(runtime.StopRequest{TaskID: "busy"})
	if !errors.Is(err, runtime.ErrTaskNotRunning) {
		t.Fatalf("want ErrTaskNotRunning, got %v", err)
	}
	if stops := readStopLog(t, stopLog); len(stops) != 0 {
		t.Errorf("expected no stop request while a supervisor holds the lock, got %v", stops)
	}
}

// TestStopRejectsARecordNamingAnUnknownProvider verifies a record that names a
// provider this scheduler cannot resolve is reported rather than ignored.
//
// Asking a different provider about the run would be meaningless, and silently
// skipping would leave the caller believing the stop was handled.
func TestStopRejectsARecordNamingAnUnknownProvider(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	writeTask(t, root, "orphan", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")
	writeLockRecord(t, filepath.Join(root, "orphan.lock"), lock.Record{
		RunID:    "run-old",
		Provider: "ghost",
		PID:      4242,
	})

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	_, err := scheduler.Stop(runtime.StopRequest{TaskID: "orphan"})
	if err == nil {
		t.Fatal("expected an error for an unresolvable provider")
	}
	if errors.Is(err, runtime.ErrTaskNotRunning) {
		t.Fatalf("a provider mismatch is not a missing run, got %v", err)
	}
	if !strings.Contains(err.Error(), "ghost") {
		t.Errorf("expected the error to name the provider, got %v", err)
	}
}

// TestStopForwardsWhenTheRecordedPollFails verifies a failed poll does not stop
// the request from being forwarded.
//
// The record is the only evidence of the run, so refusing to act on an
// unanswerable provider would leave the run unmanageable. The stop is still
// reported as best effort, which is exactly what it is.
func TestStopForwardsWhenTheRecordedPollFails(t *testing.T) {
	root := t.TempDir()
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	stopLog := filepath.Join(t.TempDir(), "stops.log")
	writeTask(t, root, "orphan", "schedule: \"0 8 * * *\"\n", "task content padded to the floor")
	writeLockRecord(t, filepath.Join(root, "orphan.lock"), lock.Record{
		RunID:    "run-old",
		Provider: fakeProviderPath(root),
		PID:      4242,
	})

	// An unrecognised state makes the provider reply unparseable, so Poll fails.
	t.Setenv("FAKE_PROVIDER_PLAN", "bogus")
	t.Setenv("FAKE_PROVIDER_STOP_LOG", stopLog)

	scheduler := newTestDaemon(t, root, logPath)
	if err := scheduler.rescan(); err != nil {
		t.Fatalf("rescan failed: %v", err)
	}

	stopped, err := scheduler.Stop(runtime.StopRequest{TaskID: "orphan"})
	if err != nil {
		t.Fatalf("Stop failed: %v", err)
	}
	if !stopped.BestEffort {
		t.Error("expected the stop to be reported as best effort")
	}
	if stops := readStopLog(t, stopLog); len(stops) != 1 {
		t.Errorf("expected the stop to be forwarded anyway, got %v", stops)
	}
	if !strings.Contains(readLog(t, logPath), "poll the recorded run failed") {
		t.Error("expected the failed poll to be logged")
	}
}
