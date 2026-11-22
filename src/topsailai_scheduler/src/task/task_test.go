package task

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// testMinRunes is the content floor used by tests that are not about the
// boundary itself. It matches the production default so a fixture that passes
// here would also pass in a real deployment.
const testMinRunes = 30

// testBoundaryRunes is a small floor used by the boundary tests. They pass it
// explicitly so the boundary is verified independently of the production
// default, which a deployment may change.
const testBoundaryRunes = 10

// writeTask creates a task file pair under root and returns the YAML path.
func writeTask(t *testing.T, root, relative, yaml, markdown string) string {
	t.Helper()

	yamlPath := filepath.Join(root, relative)
	if err := os.MkdirAll(filepath.Dir(yamlPath), 0o755); err != nil {
		t.Fatalf("create task folder: %v", err)
	}
	if err := os.WriteFile(yamlPath, []byte(yaml), 0o644); err != nil {
		t.Fatalf("write yaml: %v", err)
	}
	if markdown != "" {
		markdownPath := strings.TrimSuffix(yamlPath, YAMLExt) + MDExt
		if err := os.WriteFile(markdownPath, []byte(markdown), 0o644); err != nil {
			t.Fatalf("write markdown: %v", err)
		}
	}
	return yamlPath
}

// TestLoadNestedTaskID verifies that nesting depth does not affect discovery and
// that the task id is the slash-separated path without its extension.
func TestLoadNestedTaskID(t *testing.T) {
	root := t.TempDir()
	writeTask(t, root, "a/b/c.yaml", "schedule: \"0 8 * * *\"\n", "deep task content padded to the floor")
	writeTask(t, root, "top.yaml", "schedule: \"@daily\"\n", "top task content padded to the floor")

	tasks, failures, err := Load(root, testMinRunes)
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if len(failures) != 0 {
		t.Fatalf("expected no failures, got %v", failures)
	}
	if len(tasks) != 2 {
		t.Fatalf("expected 2 tasks, got %d", len(tasks))
	}

	// Results are sorted by id, so "a/b/c" precedes "top".
	if tasks[0].ID != "a/b/c" {
		t.Errorf("expected first task id a/b/c, got %q", tasks[0].ID)
	}
	if tasks[1].ID != "top" {
		t.Errorf("expected second task id top, got %q", tasks[1].ID)
	}
	if tasks[0].Stem != "c" {
		t.Errorf("expected stem c, got %q", tasks[0].Stem)
	}
	if !strings.HasSuffix(tasks[0].MarkdownPath, filepath.Join("a", "b", "c.md")) {
		t.Errorf("unexpected markdown path %q", tasks[0].MarkdownPath)
	}
	if !strings.HasSuffix(tasks[0].LockPath, filepath.Join("a", "b", "c.lock")) {
		t.Errorf("unexpected lock path %q", tasks[0].LockPath)
	}
}

// TestLoadMissingMarkdownIsReported verifies that a YAML without its sibling
// Markdown is a reported failure rather than a silently skipped task.
func TestLoadMissingMarkdownIsReported(t *testing.T) {
	root := t.TempDir()
	writeTask(t, root, "orphan.yaml", "schedule: \"@hourly\"\n", "")

	tasks, failures, err := Load(root, testMinRunes)
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if len(tasks) != 0 {
		t.Fatalf("expected no valid tasks, got %d", len(tasks))
	}
	if len(failures) != 1 {
		t.Fatalf("expected 1 failure, got %d", len(failures))
	}
	if !strings.Contains(failures[0].Error(), "missing task content file") {
		t.Errorf("unexpected failure message %q", failures[0].Error())
	}
}

// TestLoadMalformedYAMLIsReported verifies that a broken YAML is reported with
// its path and does not hide the other tasks.
func TestLoadMalformedYAMLIsReported(t *testing.T) {
	root := t.TempDir()
	writeTask(t, root, "broken.yaml", "schedule: [unclosed\n", "task content padded to the floor")
	writeTask(t, root, "good.yaml", "schedule: \"@daily\"\n", "task content padded to the floor")

	tasks, failures, err := Load(root, testMinRunes)
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if len(tasks) != 1 || tasks[0].ID != "good" {
		t.Fatalf("expected only the good task, got %+v", tasks)
	}
	if len(failures) != 1 {
		t.Fatalf("expected 1 failure, got %d", len(failures))
	}
	if !strings.Contains(failures[0].Path, "broken.yaml") {
		t.Errorf("failure should name the broken file, got %q", failures[0].Path)
	}
}

// TestLoadMissingRootIsEmpty verifies that an absent tasks root is a valid empty
// state rather than an error.
func TestLoadMissingRootIsEmpty(t *testing.T) {
	tasks, failures, err := Load(filepath.Join(t.TempDir(), "absent"), testMinRunes)
	if err != nil {
		t.Fatalf("a missing root must not be an error, got %v", err)
	}
	if len(tasks) != 0 || len(failures) != 0 {
		t.Fatalf("expected an empty result, got %d tasks and %d failures", len(tasks), len(failures))
	}
}

// TestLoadRootIsFile verifies that a tasks root pointing at a file is rejected.
func TestLoadRootIsFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "file")
	if err := os.WriteFile(path, []byte("x"), 0o644); err != nil {
		t.Fatalf("write file: %v", err)
	}
	if _, _, err := Load(path, testMinRunes); err == nil {
		t.Fatal("expected an error for a file as tasks root")
	}
}

// TestLoadSkipsDotFolders verifies that hidden folders are not scanned, so
// editor and tooling directories cannot inject tasks.
func TestLoadSkipsDotFolders(t *testing.T) {
	root := t.TempDir()
	writeTask(t, root, ".hidden/task.yaml", "schedule: \"@daily\"\n", "task content padded to the floor")

	tasks, failures, err := Load(root, testMinRunes)
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if len(tasks) != 0 || len(failures) != 0 {
		t.Fatalf("expected hidden folders to be skipped, got %d tasks and %d failures", len(tasks), len(failures))
	}
}

// TestFingerprintTracksContent verifies that a content change in either file
// changes the fingerprint, which is how the daemon detects a reschedule need.
func TestFingerprintTracksContent(t *testing.T) {
	root := t.TempDir()
	writeTask(t, root, "task.yaml", "schedule: \"@daily\"\n", "first content padded to the floor")

	before, _, err := Load(root, testMinRunes)
	if err != nil || len(before) != 1 {
		t.Fatalf("load before: %v, %d tasks", err, len(before))
	}

	writeTask(t, root, "task.yaml", "schedule: \"@daily\"\n", "second content padded to the floor")
	after, _, err := Load(root, testMinRunes)
	if err != nil || len(after) != 1 {
		t.Fatalf("load after: %v, %d tasks", err, len(after))
	}

	if before[0].Fingerprint == after[0].Fingerprint {
		t.Error("expected the fingerprint to change when the markdown content changes")
	}

	// Moving bytes between the two files must also change the hash, which is
	// why the fingerprint length-prefixes each part.
	writeTask(t, root, "task.yaml", "schedule: \"@daily\"\n#x\n", "second content padded to the fl")
	moved, _, err := Load(root, testMinRunes)
	if err != nil || len(moved) != 1 {
		t.Fatalf("load moved: %v, %d tasks", err, len(moved))
	}
	if moved[0].Fingerprint == after[0].Fingerprint {
		t.Error("expected the fingerprint to change when bytes move between files")
	}
}

// TestParseSpecStrict verifies that an unknown key is rejected, so a typo cannot
// silently leave a task unscheduled.
func TestParseSpecStrict(t *testing.T) {
	if _, err := ParseSpec([]byte("schedul: \"@daily\"\n")); err == nil {
		t.Fatal("expected an unknown key to be rejected")
	}
}

// TestParseSpecEmpty verifies that an empty configuration is rejected.
func TestParseSpecEmpty(t *testing.T) {
	if _, err := ParseSpec([]byte("")); err == nil {
		t.Fatal("expected an empty configuration to be rejected")
	}
}

// TestParseSpecRequiresSchedule verifies that a missing schedule is rejected.
func TestParseSpecRequiresSchedule(t *testing.T) {
	if _, err := ParseSpec([]byte("enabled: true\n")); err == nil {
		t.Fatal("expected a missing schedule to be rejected")
	}
}

// TestParseSpecRejectsEmptyEnvKey verifies that an empty environment variable
// name is rejected instead of producing a malformed child environment.
func TestParseSpecRejectsEmptyEnvKey(t *testing.T) {
	_, err := ParseSpec([]byte("schedule: \"@daily\"\nenv:\n  \"\": value\n"))
	if err == nil {
		t.Fatal("expected an empty env key to be rejected")
	}
}

// TestParseSpecFull verifies that every documented field is decoded.
func TestParseSpecFull(t *testing.T) {
	content := []byte(`schedule: "0 8 * * *"
enabled: false
launcher: command
provider: my-provider
command: /bin/echo
args: ["a", "b"]
workspace: /work/demo
timeout: 90s
env:
  KEY: value
`)
	spec, err := ParseSpec(content)
	if err != nil {
		t.Fatalf("ParseSpec failed: %v", err)
	}
	if spec.Schedule != "0 8 * * *" {
		t.Errorf("unexpected schedule %q", spec.Schedule)
	}
	if spec.IsEnabled() {
		t.Error("expected the task to be disabled")
	}
	if spec.Launcher != "command" || spec.Command != "/bin/echo" {
		t.Errorf("unexpected launcher %q command %q", spec.Launcher, spec.Command)
	}
	if spec.Provider != "my-provider" {
		t.Errorf("unexpected provider %q", spec.Provider)
	}
	if len(spec.Args) != 2 || spec.Args[0] != "a" {
		t.Errorf("unexpected args %v", spec.Args)
	}
	if spec.Workspace != "/work/demo" {
		t.Errorf("unexpected workspace %q", spec.Workspace)
	}
	if spec.Timeout.Duration != 90*time.Second {
		t.Errorf("unexpected timeout %v", spec.Timeout.Duration)
	}
	if spec.Env["KEY"] != "value" {
		t.Errorf("unexpected env %v", spec.Env)
	}
}

// TestSpecEnabledDefaultsTrue verifies that an omitted enabled flag means the
// task runs.
func TestSpecEnabledDefaultsTrue(t *testing.T) {
	spec, err := ParseSpec([]byte("schedule: \"@daily\"\n"))
	if err != nil {
		t.Fatalf("ParseSpec failed: %v", err)
	}
	if !spec.IsEnabled() {
		t.Error("expected an omitted enabled flag to mean enabled")
	}
}

// TestDurationRejectsBadValues verifies that a bare number and a non-positive
// duration are rejected, because their unit would be ambiguous.
func TestDurationRejectsBadValues(t *testing.T) {
	cases := map[string]string{
		"bare number":  "schedule: \"@daily\"\ntimeout: 30\n",
		"not a period": "schedule: \"@daily\"\ntimeout: soon\n",
		"zero":         "schedule: \"@daily\"\ntimeout: 0s\n",
		"negative":     "schedule: \"@daily\"\ntimeout: -5s\n",
	}
	for name, content := range cases {
		t.Run(name, func(t *testing.T) {
			if _, err := ParseSpec([]byte(content)); err == nil {
				t.Fatalf("expected %s to be rejected", name)
			}
		})
	}
}

// TestLoadErrorUnwrap verifies that a load error exposes its cause so a caller
// can inspect it with errors.Is.
func TestLoadErrorUnwrap(t *testing.T) {
	cause := os.ErrNotExist
	failure := LoadError{Path: "/tmp/x.yaml", Err: cause}
	if !strings.Contains(failure.Error(), "/tmp/x.yaml") {
		t.Errorf("expected the path in the message, got %q", failure.Error())
	}
	if failure.Unwrap() != cause {
		t.Error("expected Unwrap to return the cause")
	}
}

// TestLoadRejectsEmptyMarkdown verifies that a task whose content file is empty
// is reported and never scheduled, because an agent given no content has
// nothing to act on.
func TestLoadRejectsEmptyMarkdown(t *testing.T) {
	root := t.TempDir()
	writeTask(t, root, "empty.yaml", "schedule: \"@daily\"\n", "")
	// writeTask skips writing the Markdown when the content is empty, so the
	// file is created explicitly to distinguish "empty" from "missing".
	if err := os.WriteFile(filepath.Join(root, "empty.md"), nil, 0o644); err != nil {
		t.Fatalf("write empty markdown: %v", err)
	}

	tasks, failures, err := Load(root, testBoundaryRunes)
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if len(tasks) != 0 {
		t.Fatalf("expected no valid tasks, got %d", len(tasks))
	}
	if len(failures) != 1 {
		t.Fatalf("expected 1 failure, got %d", len(failures))
	}
	want := fmt.Sprintf("at least %d are required", testBoundaryRunes)
	if !strings.Contains(failures[0].Error(), want) {
		t.Errorf("expected %q in %q", want, failures[0].Error())
	}
}

// TestLoadRejectsWhitespaceOnlyMarkdown verifies that content made only of
// whitespace counts as zero characters rather than as its byte length.
func TestLoadRejectsWhitespaceOnlyMarkdown(t *testing.T) {
	root := t.TempDir()
	writeTask(t, root, "blank.yaml", "schedule: \"@daily\"\n", "   \n\n\t\n   ")

	tasks, failures, err := Load(root, testMinRunes)
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if len(tasks) != 0 {
		t.Fatalf("expected no valid tasks, got %d", len(tasks))
	}
	if len(failures) != 1 {
		t.Fatalf("expected 1 failure, got %d", len(failures))
	}
	if !strings.Contains(failures[0].Error(), "has 0 characters") {
		t.Errorf("whitespace should count as zero characters, got %q", failures[0].Error())
	}
}

// TestLoadRejectsShortMarkdown verifies the boundary against an explicit floor:
// one character below it is rejected and exactly at it is accepted. The floor is
// passed in rather than read from the production default, so changing the
// default cannot silently move this boundary.
func TestLoadRejectsShortMarkdown(t *testing.T) {
	cases := []struct {
		name     string
		content  string
		accepted bool
	}{
		{name: "one below the floor", content: "123456789", accepted: false},
		{name: "exactly at the floor", content: "1234567890", accepted: true},
		{name: "at the floor with padding", content: "  1234567890  ", accepted: true},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			root := t.TempDir()
			writeTask(t, root, "task.yaml", "schedule: \"@daily\"\n", testCase.content)

			tasks, failures, err := Load(root, testBoundaryRunes)
			if err != nil {
				t.Fatalf("Load returned an error: %v", err)
			}
			if testCase.accepted {
				if len(failures) != 0 {
					t.Fatalf("expected no failures, got %v", failures)
				}
				if len(tasks) != 1 {
					t.Fatalf("expected 1 task, got %d", len(tasks))
				}
				return
			}
			if len(tasks) != 0 {
				t.Fatalf("expected no valid tasks, got %d", len(tasks))
			}
			if len(failures) != 1 {
				t.Fatalf("expected 1 failure, got %d", len(failures))
			}
			want := fmt.Sprintf("has %d characters", testBoundaryRunes-1)
			if !strings.Contains(failures[0].Error(), want) {
				t.Errorf("expected %q in %q", want, failures[0].Error())
			}
		})
	}
}

// TestLoadCountsRunesNotBytes verifies that content is measured by characters.
// Counting bytes would accept the short phrase, because four Chinese characters
// occupy twelve bytes while four ASCII characters occupy four.
func TestLoadCountsRunesNotBytes(t *testing.T) {
	root := t.TempDir()
	// Four characters, twelve bytes: rejected as too short.
	writeTask(t, root, "short.yaml", "schedule: \"@daily\"\n", "你好世界")
	// Ten characters, thirty bytes: accepted.
	writeTask(t, root, "long.yaml", "schedule: \"@daily\"\n", "一二三四五六七八九十")

	tasks, failures, err := Load(root, testBoundaryRunes)
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if len(tasks) != 1 || tasks[0].ID != "long" {
		t.Fatalf("expected only the long task, got %+v", tasks)
	}
	if len(failures) != 1 {
		t.Fatalf("expected 1 failure, got %d", len(failures))
	}
	if !strings.Contains(failures[0].Error(), "has 4 characters") {
		t.Errorf("a four-character phrase should count as four, got %q", failures[0].Error())
	}
}

// TestLoadShortContentDoesNotHideOtherTasks verifies that a rejected task is
// skipped rather than aborting the scan, so one bad file cannot hide the rest.
func TestLoadShortContentDoesNotHideOtherTasks(t *testing.T) {
	root := t.TempDir()
	writeTask(t, root, "bad.yaml", "schedule: \"@daily\"\n", "short")
	writeTask(t, root, "good.yaml", "schedule: \"@daily\"\n", "a complete task content that is long enough")

	tasks, failures, err := Load(root, testMinRunes)
	if err != nil {
		t.Fatalf("Load returned an error: %v", err)
	}
	if len(tasks) != 1 || tasks[0].ID != "good" {
		t.Fatalf("expected only the good task, got %+v", tasks)
	}
	if len(failures) != 1 {
		t.Fatalf("expected 1 failure, got %d", len(failures))
	}
	if !strings.Contains(failures[0].Path, "bad.yaml") {
		t.Errorf("failure should name the rejected file, got %q", failures[0].Path)
	}
}

// TestValidateScheduleAcceptsSupportedForms verifies every cron form the daemon
// can register is accepted, so a valid task is never rejected at load time.
//
// The five-field form is included because it is the familiar cron shape and the
// daemon's cron runs with seconds enabled; rejecting it would break the most
// common way to write a schedule.
func TestValidateScheduleAcceptsSupportedForms(t *testing.T) {
	cases := map[string]string{
		"five fields":     "0 8 * * *",
		"six fields":      "30 0 8 * * *",
		"descriptor":      "@daily",
		"every minute":    "* * * * *",
		"padded with tab": "\t0 8 * * *\t",
	}
	for name, expression := range cases {
		t.Run(name, func(t *testing.T) {
			if err := ValidateSchedule(expression); err != nil {
				t.Fatalf("expected %q to be accepted, got %v", expression, err)
			}
		})
	}
}

// TestValidateScheduleRejectsUnparseable verifies an expression the cron parser
// cannot read is rejected with a message naming the expression.
//
// Naming the expression matters because the message reaches the operator through
// Status and the log; "invalid schedule" alone would not say which value to fix.
func TestValidateScheduleRejectsUnparseable(t *testing.T) {
	cases := map[string]string{
		"words":        "not a cron",
		"too few":      "0 8 *",
		"too many":     "0 0 8 * * * *",
		"bad range":    "0 99 * * *",
		"empty":        "",
		"only spaces":  "   ",
		"unknown name": "@fortnightly",
	}
	for name, expression := range cases {
		t.Run(name, func(t *testing.T) {
			err := ValidateSchedule(expression)
			if err == nil {
				t.Fatalf("expected %q to be rejected", expression)
			}
			if !strings.Contains(err.Error(), "schedule") {
				t.Fatalf("expected the message to mention the schedule, got %q", err.Error())
			}
		})
	}
}

// TestParseSpecRejectsInvalidSchedule verifies an unparseable schedule is
// rejected while loading rather than accepted and silently never registered.
//
// This is the defect the check exists for: before it, a task with a nonsense
// schedule loaded successfully, appeared idle with no error, and simply never
// ran, which is indistinguishable from a healthy task waiting for its next run.
func TestParseSpecRejectsInvalidSchedule(t *testing.T) {
	_, err := ParseSpec([]byte("schedule: \"every morning\"\n"))
	if err == nil {
		t.Fatal("expected an unparseable schedule to be rejected")
	}
	if !strings.Contains(err.Error(), "every morning") {
		t.Fatalf("expected the message to name the expression, got %q", err.Error())
	}
}
