package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/tui"
)

// lookupFrom builds the injected lookup a test needs, so the resolution rules
// are exercised without mutating process-wide environment.
func lookupFrom(values map[string]string) func(string) string {
	return func(name string) string { return values[name] }
}

// TestResolveInputHistoryPathPrefersConfiguredFile proves an explicit file wins
// over the per-user default, because an operator who names a file expects that
// file to be used.
func TestResolveInputHistoryPathPrefersConfiguredFile(t *testing.T) {
	configured := filepath.Join(t.TempDir(), "custom.jsonl")
	got := resolveInputHistoryPath(lookupFrom(map[string]string{inputHistoryFileEnv: configured}), "/home/operator")
	if got != configured {
		t.Fatalf("path=%q want=%q", got, configured)
	}
}

// TestResolveInputHistoryPathDefaultsBesideConfig proves the default lands in the
// same directory as the per-user configuration file, so one directory holds this
// operator's CLI state.
func TestResolveInputHistoryPathDefaultsBesideConfig(t *testing.T) {
	got := resolveInputHistoryPath(lookupFrom(nil), "/home/operator")
	want := filepath.Join("/home/operator", filepath.FromSlash(inputHistoryRelativePath))
	if got != want {
		t.Fatalf("path=%q want=%q", got, want)
	}
	if !strings.HasSuffix(got, ".topsailai_agent_cluster.history.jsonl") {
		t.Fatalf("path=%q does not end with the history file name", got)
	}
}

// TestResolveInputHistoryPathWithoutHome proves an unresolvable home directory
// yields no path instead of a relative file in the working directory, which would
// scatter history files wherever the CLI happened to run.
func TestResolveInputHistoryPathWithoutHome(t *testing.T) {
	if got := resolveInputHistoryPath(lookupFrom(nil), ""); got != "" {
		t.Fatalf("path=%q want empty", got)
	}
}

// TestResolveInputHistoryWithoutHomeReturnsNilStore proves the CLI keeps working
// without a home directory: history is a convenience, not a startup requirement.
func TestResolveInputHistoryWithoutHomeReturnsNilStore(t *testing.T) {
	store, err := resolveInputHistory(lookupFrom(nil), "", &bytes.Buffer{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if store != nil {
		t.Fatalf("store=%v want nil", store)
	}
}

// TestResolveInputHistoryLimitsDefaults proves an unset bound keeps the store's
// own default, so the numbers live in one place.
func TestResolveInputHistoryLimitsDefaults(t *testing.T) {
	limits, err := resolveInputHistoryLimits(lookupFrom(nil))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if limits.MaxEntries != 0 || limits.MaxSizeBytes != 0 || limits.MaxBackups != 0 {
		t.Fatalf("limits=%+v want zero values so the store applies its defaults", limits)
	}
	normalized := tui.NormalizeInputHistoryLimits(limits)
	if normalized.MaxEntries != tui.DefaultInputHistoryMaxEntries {
		t.Fatalf("MaxEntries=%d want=%d", normalized.MaxEntries, tui.DefaultInputHistoryMaxEntries)
	}
	if normalized.MaxSizeBytes != tui.DefaultInputHistoryMaxSizeMB<<20 {
		t.Fatalf("MaxSizeBytes=%d want=%d", normalized.MaxSizeBytes, tui.DefaultInputHistoryMaxSizeMB<<20)
	}
	if normalized.MaxBackups != tui.DefaultInputHistoryMaxBackups {
		t.Fatalf("MaxBackups=%d want=%d", normalized.MaxBackups, tui.DefaultInputHistoryMaxBackups)
	}
}

// TestResolveInputHistoryLimitsConvertsMegabytes proves the configured size is
// converted to bytes exactly once, so a bound of 2 means two megabytes.
func TestResolveInputHistoryLimitsConvertsMegabytes(t *testing.T) {
	limits, err := resolveInputHistoryLimits(lookupFrom(map[string]string{
		inputHistoryMaxEntriesEnv: "7",
		inputHistoryMaxSizeMBEnv:  "2",
		inputHistoryMaxBackupsEnv: "3",
	}))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if limits.MaxEntries != 7 {
		t.Fatalf("MaxEntries=%d want=7", limits.MaxEntries)
	}
	if limits.MaxSizeBytes != 2<<20 {
		t.Fatalf("MaxSizeBytes=%d want=%d", limits.MaxSizeBytes, 2<<20)
	}
	if limits.MaxBackups != 3 {
		t.Fatalf("MaxBackups=%d want=3", limits.MaxBackups)
	}
}

// TestResolveInputHistoryLimitsRejectsMalformed proves a malformed bound fails
// startup instead of silently falling back, because a fallback would leave the
// file growing past a bound the operator believes is set.
func TestResolveInputHistoryLimitsRejectsMalformed(t *testing.T) {
	cases := []struct {
		name  string
		value string
		want  string
	}{
		{"not a number", "many", "is not an integer"},
		{"negative", "-1", "must not be negative"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			_, err := resolveInputHistoryLimits(lookupFrom(map[string]string{inputHistoryMaxEntriesEnv: testCase.value}))
			if err == nil {
				t.Fatalf("value=%q was accepted", testCase.value)
			}
			if !strings.Contains(err.Error(), testCase.want) {
				t.Fatalf("error=%q does not contain %q", err.Error(), testCase.want)
			}
			if !strings.Contains(err.Error(), inputHistoryMaxEntriesEnv) {
				t.Fatalf("error=%q does not name the variable", err.Error())
			}
		})
	}
}

// TestResolveInputHistoryRejectsMalformedBoundBeforeCreatingStore proves a
// rejected bound is reported as an error rather than a nil store, because the two
// mean different things: nil is "no history available", an error is "the operator
// configured something invalid".
func TestResolveInputHistoryRejectsMalformedBoundBeforeCreatingStore(t *testing.T) {
	store, err := resolveInputHistory(lookupFrom(map[string]string{
		inputHistoryFileEnv:       filepath.Join(t.TempDir(), "history.jsonl"),
		inputHistoryMaxBackupsEnv: "lots",
	}), "/home/operator", &bytes.Buffer{})
	if err == nil {
		t.Fatalf("malformed bound was accepted, store=%v", store)
	}
	if store != nil {
		t.Fatalf("store=%v want nil on error", store)
	}
}

// TestResolveInputHistoryPersistsAcrossStores proves the shipped resolution path
// produces a store that really writes the file, so a second process reading the
// same path recalls what the first one typed. This is the restart behaviour the
// requirement asks for, proven through the boundary rather than through the store
// alone.
func TestResolveInputHistoryPersistsAcrossStores(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	lookup := lookupFrom(map[string]string{inputHistoryFileEnv: path})

	first, err := resolveInputHistory(lookup, "/home/operator", &bytes.Buffer{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if first == nil {
		t.Fatal("first store is nil")
	}
	if err := first.Record(tui.InputHistoryKindCommand, "list --full"); err != nil {
		t.Fatalf("record command: %v", err)
	}
	if err := first.Record(tui.InputHistoryKindAnswer, "y"); err != nil {
		t.Fatalf("record answer: %v", err)
	}

	second, err := resolveInputHistory(lookup, "/home/operator", &bytes.Buffer{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	recalled := second.RecentCommands()
	if len(recalled) != 1 || recalled[0] != "list --full" {
		t.Fatalf("recalled=%v want=[list --full]", recalled)
	}

	// The answer must be on disk even though it is not recallable, because the
	// requirement is that every input is recorded.
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read history: %v", err)
	}
	if !strings.Contains(string(content), `"kind":"answer"`) {
		t.Fatalf("history=%q does not contain the recorded answer", string(content))
	}
}

// TestResolveInputHistoryUsesComponentNames verifies every history setting is
// read from its component-owned name.
func TestResolveInputHistoryUsesComponentNames(t *testing.T) {
	primaryPath := filepath.Join(t.TempDir(), "primary.jsonl")
	lookup := lookupFrom(map[string]string{
		inputHistoryFileEnv:       primaryPath,
		inputHistoryMaxEntriesEnv: "7",
		inputHistoryMaxSizeMBEnv:  "2",
		inputHistoryMaxBackupsEnv: "3",
	})
	if got := resolveInputHistoryPath(lookup, "/home/operator"); got != primaryPath {
		t.Fatalf("history path=%q want=%q", got, primaryPath)
	}
	limits, err := resolveInputHistoryLimits(lookup)
	if err != nil {
		t.Fatalf("resolve limits: %v", err)
	}
	if limits.MaxEntries != 7 || limits.MaxSizeBytes != 2<<20 || limits.MaxBackups != 3 {
		t.Fatalf("limits=%+v", limits)
	}
}

// TestResolveInputHistoryIgnoresDeprecatedNames pins the removal of the
// compatibility fallback. A deprecated name must not configure the store, so an
// operator who still exports one falls back to the per-user default path and the
// store's own bounds instead of a silently different file.
func TestResolveInputHistoryIgnoresDeprecatedNames(t *testing.T) {
	lookup := lookupFrom(map[string]string{
		"AGENT_CLUSTER_HISTORY_FILE":        filepath.Join(t.TempDir(), "deprecated.jsonl"),
		"AGENT_CLUSTER_HISTORY_MAX_ENTRIES": "7",
		"AGENT_CLUSTER_HISTORY_MAX_SIZE_MB": "2",
		"AGENT_CLUSTER_HISTORY_MAX_BACKUPS": "3",
	})
	wantPath := filepath.Join("/home/operator", filepath.FromSlash(inputHistoryRelativePath))
	if got := resolveInputHistoryPath(lookup, "/home/operator"); got != wantPath {
		t.Fatalf("history path=%q want=%q", got, wantPath)
	}
	limits, err := resolveInputHistoryLimits(lookup)
	if err != nil {
		t.Fatalf("resolve limits: %v", err)
	}
	if limits.MaxEntries != 0 || limits.MaxSizeBytes != 0 || limits.MaxBackups != 0 {
		t.Fatalf("deprecated names configured limits=%+v", limits)
	}
}
