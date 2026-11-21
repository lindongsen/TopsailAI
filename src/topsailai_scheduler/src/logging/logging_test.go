package logging

import (
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestNewDefaultsToStdout verifies an empty options value yields a usable
// logger, because a missing configuration must never stop the service.
func TestNewDefaultsToStdout(t *testing.T) {
	logger, closer, err := New(Options{})
	if err != nil {
		t.Fatalf("New failed: %v", err)
	}
	if logger == nil {
		t.Fatal("expected a logger")
	}
	if closer == nil {
		t.Fatal("expected a closer")
	}
	if err := closer.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}
}

// TestNewRejectsInvalidLevel verifies a typo in the level is an error instead of
// silently falling back to info.
func TestNewRejectsInvalidLevel(t *testing.T) {
	if _, _, err := New(Options{Level: "verbose"}); err == nil {
		t.Fatal("expected an invalid level to be rejected")
	}
}

// TestNewAcceptsKnownLevels verifies every documented level is accepted.
func TestNewAcceptsKnownLevels(t *testing.T) {
	for _, level := range []string{"", "debug", "info", "warn", "warning", "error", "DEBUG", " Info "} {
		_, closer, err := New(Options{Level: level})
		if err != nil {
			t.Fatalf("level %q rejected: %v", level, err)
		}
		if err := closer.Close(); err != nil {
			t.Fatalf("close failed: %v", err)
		}
	}
}

// TestNewWritesJSONToFile verifies a file output produces one JSON object per
// line, which is what makes the log queryable.
func TestNewWritesJSONToFile(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "scheduler.log")

	logger, closer, err := New(Options{Output: logPath, Level: "debug"})
	if err != nil {
		t.Fatalf("New failed: %v", err)
	}
	logger.Info("hello", slog.String("task", "data/work"))
	if err := closer.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	lines := strings.Split(strings.TrimSpace(string(content)), "\n")
	if len(lines) != 1 {
		t.Fatalf("expected one log line, got %d: %q", len(lines), string(content))
	}

	var entry map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &entry); err != nil {
		t.Fatalf("log line is not JSON: %v", err)
	}
	if entry["msg"] != "hello" {
		t.Fatalf("unexpected message %v", entry["msg"])
	}
	if entry["task"] != "data/work" {
		t.Fatalf("unexpected task field %v", entry["task"])
	}
	if _, ok := entry["time"]; !ok {
		t.Fatal("expected a time field")
	}
}

// TestNewHonoursLevel verifies a level below the configured one is dropped.
func TestNewHonoursLevel(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "scheduler.log")

	logger, closer, err := New(Options{Output: logPath, Level: "warn"})
	if err != nil {
		t.Fatalf("New failed: %v", err)
	}
	logger.Debug("dropped")
	logger.Info("dropped too")
	logger.Warn("kept")
	if err := closer.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	if strings.Contains(string(content), "dropped") {
		t.Fatalf("expected debug and info to be dropped, got %q", string(content))
	}
	if !strings.Contains(string(content), "kept") {
		t.Fatalf("expected the warn entry, got %q", string(content))
	}
}

// TestNewStderrOutput verifies stderr is accepted as a destination.
func TestNewStderrOutput(t *testing.T) {
	_, closer, err := New(Options{Output: "stderr"})
	if err != nil {
		t.Fatalf("New failed: %v", err)
	}
	if err := closer.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}
}

// TestNewAppliesRotationDefaults verifies a file output with no rotation values
// still gets bounded defaults, so a forgotten configuration cannot fill the
// disk.
func TestNewAppliesRotationDefaults(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	logger, closer, err := New(Options{Output: logPath})
	if err != nil {
		t.Fatalf("New failed: %v", err)
	}
	logger.Info("entry")
	if err := closer.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}
	if _, err := os.Stat(logPath); err != nil {
		t.Fatalf("expected the log file to exist: %v", err)
	}
}

// TestModuleAddsModuleField verifies the module tag is present so entries from
// different parts of the scheduler can be separated.
func TestModuleAddsModuleField(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	logger, closer, err := New(Options{Output: logPath})
	if err != nil {
		t.Fatalf("New failed: %v", err)
	}
	Module(logger, "daemon").Info("entry")
	if err := closer.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	if !strings.Contains(string(content), `"module":"daemon"`) {
		t.Fatalf("expected the module field, got %q", string(content))
	}
}

// TestWithTraceAddsTraceField verifies the trace id is present so every entry of
// one run can be correlated.
func TestWithTraceAddsTraceField(t *testing.T) {
	logPath := filepath.Join(t.TempDir(), "scheduler.log")
	logger, closer, err := New(Options{Output: logPath})
	if err != nil {
		t.Fatalf("New failed: %v", err)
	}
	WithTrace(logger, "trace-1").Info("entry")
	if err := closer.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}

	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read log: %v", err)
	}
	if !strings.Contains(string(content), `"trace_id":"trace-1"`) {
		t.Fatalf("expected the trace id field, got %q", string(content))
	}
}

// TestParseLevel verifies the textual level mapping.
func TestParseLevel(t *testing.T) {
	cases := []struct {
		text string
		want slog.Level
	}{
		{"", slog.LevelInfo},
		{"info", slog.LevelInfo},
		{"debug", slog.LevelDebug},
		{"warn", slog.LevelWarn},
		{"warning", slog.LevelWarn},
		{"error", slog.LevelError},
		{"ERROR", slog.LevelError},
		{"  debug  ", slog.LevelDebug},
	}
	for _, testCase := range cases {
		got, err := parseLevel(testCase.text)
		if err != nil {
			t.Fatalf("level %q rejected: %v", testCase.text, err)
		}
		if got != testCase.want {
			t.Fatalf("level %q: want %v, got %v", testCase.text, testCase.want, got)
		}
	}
}

// TestParseLevelRejectsUnknown verifies an unknown level is an error.
func TestParseLevelRejectsUnknown(t *testing.T) {
	if _, err := parseLevel("trace"); err == nil {
		t.Fatal("expected an unknown level to be rejected")
	}
}

// TestPositiveOr verifies the fallback rule used for rotation values.
func TestPositiveOr(t *testing.T) {
	if got := positiveOr(0, 7); got != 7 {
		t.Fatalf("want 7, got %d", got)
	}
	if got := positiveOr(-3, 7); got != 7 {
		t.Fatalf("want 7, got %d", got)
	}
	if got := positiveOr(5, 7); got != 5 {
		t.Fatalf("want 5, got %d", got)
	}
}

// TestNopCloser verifies the standard-stream closer is safe to call.
func TestNopCloser(t *testing.T) {
	if err := (nopCloser{}).Close(); err != nil {
		t.Fatalf("nop closer failed: %v", err)
	}
}
