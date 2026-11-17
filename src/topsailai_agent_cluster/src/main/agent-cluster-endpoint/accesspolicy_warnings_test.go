package main

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"

	endpointservice "topsailai_agent_cluster/internal/endpoint"
)

// captureWarnings runs logAccessPolicyWarnings against a policy loaded from dir
// and returns the decoded log records.
//
// The records are decoded rather than matched as text, because the assertion has
// to prove the level is WARN and that the warning text reached the log. A text
// match on the message alone would pass for an INFO line, which is the exact
// defect this test exists to prevent: a diagnostic that is emitted at a level
// nobody reads is indistinguishable from one that is never emitted.
func captureWarnings(t *testing.T, dir, event string) []map[string]any {
	t.Helper()
	loaded, err := endpointservice.LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load: %v", err)
	}
	var buffer bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buffer, &slog.HandlerOptions{Level: slog.LevelDebug}))
	logAccessPolicyWarnings(logger, event, loaded.Policy)

	records := make([]map[string]any, 0)
	for _, line := range strings.Split(strings.TrimSpace(buffer.String()), "\n") {
		if line == "" {
			continue
		}
		record := make(map[string]any)
		if err := json.Unmarshal([]byte(line), &record); err != nil {
			t.Fatalf("decode log line %q: %v", line, err)
		}
		records = append(records, record)
	}
	return records
}

// TestAccessPolicyWarningsAreLoggedAtWarn proves the documented warning reaches
// the log at a level an operator will actually see.
func TestAccessPolicyWarningsAreLoggedAtWarn(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "typo.conf"), []byte("token typo-secret\npermissions mesages.read\n"), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	records := captureWarnings(t, dir, "load endpoint access policy warning")
	if len(records) != 1 {
		t.Fatalf("one misspelled permission must produce exactly one log record, got %d: %v", len(records), records)
	}
	if level := records[0]["level"]; level != "WARN" {
		t.Fatalf("the warning must be logged at WARN, got %v", level)
	}
	if msg := records[0]["msg"]; msg != "load endpoint access policy warning" {
		t.Fatalf("the record must name the load site, got %v", msg)
	}
	warning, _ := records[0]["warning"].(string)
	if !strings.Contains(warning, "mesages.read") {
		t.Fatalf("the log record must name the misspelled operation, got %q", warning)
	}
	if !strings.Contains(warning, "typo.conf") {
		t.Fatalf("the log record must name the file, got %q", warning)
	}
}

// TestAccessPolicyWarningsLogNothingForAValidPolicy is the paired negative case.
//
// Without it, a helper that logged a record for every policy would pass the test
// above while making the warning meaningless.
func TestAccessPolicyWarningsLogNothingForAValidPolicy(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "good.conf"), []byte("token good-secret\npermissions output.read\n"), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	if records := captureWarnings(t, dir, "load endpoint access policy warning"); len(records) != 0 {
		t.Fatalf("a valid policy must log no warning, got %v", records)
	}
}

// TestAccessPolicyWarningsLogEachWarningSeparately keeps one warning per record.
//
// A single record carrying a joined list would be truncated by any log pipeline
// that bounds a field, and the operator would lose the later warnings without
// any indication that they existed.
func TestAccessPolicyWarningsLogEachWarningSeparately(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "a.conf"), []byte("token a-secret\npermissions aaaaaaa.read\n"), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "b.conf"), []byte("token b-secret\npermissions bbbbbbb.read\n"), 0o600); err != nil {
		t.Fatalf("write policy: %v", err)
	}
	records := captureWarnings(t, dir, "load endpoint access policy warning")
	if len(records) != 2 {
		t.Fatalf("two warnings must produce two records, got %d: %v", len(records), records)
	}
	for index, want := range []string{"a.conf", "b.conf"} {
		warning, _ := records[index]["warning"].(string)
		if !strings.Contains(warning, want) {
			t.Fatalf("record %d must name %s, got %q", index, want, warning)
		}
	}
}

// TestAccessPolicyWarningsTolerateANilPolicy guards the permissive state.
//
// An Endpoint with no configured policy directory holds a nil policy on some
// paths, and the helper runs unconditionally at both load sites. A nil
// dereference there would crash an Endpoint that never configured a policy,
// which is the upgrade-safe default.
func TestAccessPolicyWarningsTolerateANilPolicy(t *testing.T) {
	var buffer bytes.Buffer
	logger := slog.New(slog.NewJSONHandler(&buffer, nil))
	logAccessPolicyWarnings(logger, "load endpoint access policy warning", nil)
	if buffer.Len() != 0 {
		t.Fatalf("a nil policy must log nothing, got %q", buffer.String())
	}
}
