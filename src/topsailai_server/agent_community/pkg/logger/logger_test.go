package logger

import (
	"bytes"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"log/slog"
)

// resetDefault clears the package-level default logger so tests do not interfere.
func resetDefault() {
	defaultLogger = nil
}

// parseLastLogLine extracts the last non-empty JSON line from a buffer.
func parseLastLogLine(buf *bytes.Buffer) (map[string]any, error) {
	text := strings.TrimSpace(buf.String())
	if text == "" {
		return nil, nil
	}
	lines := strings.Split(text, "\n")
	var last string
	for i := len(lines) - 1; i >= 0; i-- {
		if strings.TrimSpace(lines[i]) != "" {
			last = strings.TrimSpace(lines[i])
			break
		}
	}
	if last == "" {
		return nil, nil
	}
	var out map[string]any
	if err := json.Unmarshal([]byte(last), &out); err != nil {
		return nil, err
	}
	return out, nil
}

// assertLogLine checks that a parsed log line contains expected fields.
func assertLogLine(t *testing.T, line map[string]any, level, msg string) {
	t.Helper()
	if line == nil {
		t.Fatal("expected a log line, got none")
	}
	if got := line["level"]; got != level {
		t.Fatalf("expected level %q, got %v", level, got)
	}
	if got := line["message"]; got != msg {
		t.Fatalf("expected message %q, got %v", msg, got)
	}
	if _, ok := line["module"]; !ok {
		t.Fatal("expected module field")
	}
	if _, ok := line["trace_id"]; !ok {
		t.Fatal("expected trace_id field")
	}
	if ts, ok := line["timestamp"].(string); ok {
		if _, err := time.Parse(iso8601UTCFormat, ts); err != nil {
			t.Fatalf("timestamp %q is not in expected ISO 8601 UTC format: %v", ts, err)
		}
	} else {
		t.Fatalf("expected timestamp string, got %T", line["timestamp"])
	}
}

func TestNew_StdoutOutput(t *testing.T) {
	t.Cleanup(resetDefault)
	logger := New(Config{Output: "stdout", Level: "info"})
	if logger == nil {
		t.Fatal("expected non-nil logger")
	}
	if logger.inner == nil {
		t.Fatal("expected non-nil inner logger")
	}
}

func TestNew_FileOutput(t *testing.T) {
	t.Cleanup(resetDefault)
	f, err := os.CreateTemp("", "logger-test-*.log")
	if err != nil {
		t.Fatalf("failed to create temp file: %v", err)
	}
	defer os.Remove(f.Name())
	f.Close()

	logger := New(Config{Output: "file", FilePath: f.Name(), Level: "info"})
	if logger == nil {
		t.Fatal("expected non-nil logger")
	}

	logger.Info("", "", "file test")

	content, err := os.ReadFile(f.Name())
	if err != nil {
		t.Fatalf("failed to read log file: %v", err)
	}
	if !strings.Contains(string(content), `"message":"file test"`) {
		t.Fatalf("expected log file to contain file test message, got: %s", string(content))
	}
}

func TestParseLevel(t *testing.T) {
	cases := []struct {
		input    string
		expected slog.Level
	}{
		{"debug", slog.LevelDebug},
		{"info", slog.LevelInfo},
		{"warn", slog.LevelWarn},
		{"warning", slog.LevelWarn},
		{"error", slog.LevelError},
		{"unknown", slog.LevelInfo},
		{"", slog.LevelInfo},
	}

	for _, tc := range cases {
		t.Run(tc.input, func(t *testing.T) {
			got := parseLevel(tc.input)
			if got != tc.expected {
				t.Fatalf("parseLevel(%q) = %v, want %v", tc.input, got, tc.expected)
			}
		})
	}
}

func TestLogger_LogLevels(t *testing.T) {
	cases := []struct {
		name     string
		level    slog.Level
		method   func(*Logger, string, string, string)
		expected string
	}{
		{"debug", slog.LevelDebug, func(l *Logger, m, tid, msg string) { l.Debug(m, tid, msg) }, "DEBUG"},
		{"info", slog.LevelInfo, func(l *Logger, m, tid, msg string) { l.Info(m, tid, msg) }, "INFO"},
		{"warn", slog.LevelWarn, func(l *Logger, m, tid, msg string) { l.Warn(m, tid, msg) }, "WARN"},
		{"error", slog.LevelError, func(l *Logger, m, tid, msg string) { l.Error(m, tid, msg) }, "ERROR"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			logger := newWithWriter(Config{Output: "stdout", Level: "debug"}, &buf)
			tc.method(logger, "test-module", "trace-123", tc.name+" message")

			line, err := parseLastLogLine(&buf)
			if err != nil {
				t.Fatalf("failed to parse log line: %v", err)
			}
			assertLogLine(t, line, tc.expected, tc.name+" message")
			if got := line["module"]; got != "test-module" {
				t.Fatalf("expected module test-module, got %v", got)
			}
			if got := line["trace_id"]; got != "trace-123" {
				t.Fatalf("expected trace_id trace-123, got %v", got)
			}
		})
	}
}

func TestLogger_WithAttrs(t *testing.T) {
	var buf bytes.Buffer
	logger := newWithWriter(Config{Output: "stdout", Level: "info"}, &buf)
	scoped := logger.WithAttrs("mod", "tid")
	scoped.Info("", "", "with attrs message")

	line, err := parseLastLogLine(&buf)
	if err != nil {
		t.Fatalf("failed to parse log line: %v", err)
	}
	if line["module"] != "mod" {
		t.Fatalf("expected module mod, got %v", line["module"])
	}
	if line["trace_id"] != "tid" {
		t.Fatalf("expected trace_id tid, got %v", line["trace_id"])
	}
	if line["message"] != "with attrs message" {
		t.Fatalf("expected message, got %v", line["message"])
	}
}

func TestLogger_StdLogger(t *testing.T) {
	logger := New(Config{Output: "stdout", Level: "info"})
	if logger.StdLogger() == nil {
		t.Fatal("expected non-nil std logger")
	}
}

func TestDefaultLogger_Functions(t *testing.T) {
	t.Cleanup(resetDefault)

	var buf bytes.Buffer
	// Use newWithWriter to initialize the default logger with a buffer-backed writer.
	defaultLogger = newWithWriter(Config{Output: "stdout", Level: "debug"}, &buf)

	Debug("debug msg")
	Info("info msg")
	Warn("warn msg")
	Error("error msg")
	DebugM("m", "t", "debugm msg")
	InfoM("m", "t", "infom msg")
	WarnM("m", "t", "warnm msg")
	ErrorM("m", "t", "errorm msg")

	lines := strings.Split(strings.TrimSpace(buf.String()), "\n")
	if len(lines) != 8 {
		t.Fatalf("expected 8 log lines, got %d: %s", len(lines), buf.String())
	}

	expected := []struct {
		level string
		msg   string
	}{
		{"DEBUG", "debug msg"},
		{"INFO", "info msg"},
		{"WARN", "warn msg"},
		{"ERROR", "error msg"},
		{"DEBUG", "debugm msg"},
		{"INFO", "infom msg"},
		{"WARN", "warnm msg"},
		{"ERROR", "errorm msg"},
	}

	for i, exp := range expected {
		var line map[string]any
		if err := json.Unmarshal([]byte(strings.TrimSpace(lines[i])), &line); err != nil {
			t.Fatalf("failed to parse line %d: %v", i, err)
		}
		assertLogLine(t, line, exp.level, exp.msg)
	}
}

func TestEnsureDefault(t *testing.T) {
	t.Cleanup(resetDefault)

	// Ensure default logger is nil.
	if defaultLogger != nil {
		t.Fatal("expected default logger to be nil at start")
	}

	// Capture stdout by replacing it temporarily is complex; instead verify no panic and that
	// the default logger is initialized. Since Info writes to os.Stdout, we just ensure it runs.
	Info("ensure default works")

	if defaultLogger == nil {
		t.Fatal("expected default logger to be initialized after Info")
	}
}

func TestLevelFiltering(t *testing.T) {
	var buf bytes.Buffer
	logger := newWithWriter(Config{Output: "stdout", Level: "warn"}, &buf)

	logger.Debug("", "", "debug line")
	logger.Info("", "", "info line")
	logger.Warn("", "", "warn line")

	output := buf.String()
	if strings.Contains(output, "debug line") {
		t.Error("expected debug line to be filtered out")
	}
	if strings.Contains(output, "info line") {
		t.Error("expected info line to be filtered out")
	}
	if !strings.Contains(output, "warn line") {
		t.Error("expected warn line to be present")
	}
}
