package tui

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// recordedInput is one input observed by the test recorder.
type recordedInput struct {
	kind string
	text string
}

// recordingInputRecorder observes what the editor hands to the persistence seam
// without touching a real file, so a test can assert the record decision itself.
type recordingInputRecorder struct {
	entries []recordedInput
	err     error
}

// Record appends one observed input.
func (r *recordingInputRecorder) Record(kind, text string) error {
	r.entries = append(r.entries, recordedInput{kind: kind, text: text})
	return r.err
}

// equal reports whether the observed inputs match want exactly.
func (r *recordingInputRecorder) equal(want []recordedInput) bool {
	if len(r.entries) != len(want) {
		return false
	}
	for index := range want {
		if r.entries[index] != want[index] {
			return false
		}
	}
	return true
}

// readHistoryLines returns the raw lines of path.
func readHistoryLines(t *testing.T, path string) []string {
	t.Helper()
	file, err := os.Open(path)
	if err != nil {
		t.Fatalf("open history: %v", err)
	}
	defer file.Close()
	var lines []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scan history: %v", err)
	}
	return lines
}

// TestInputHistoryRecordsEveryKindAsJSONL proves the file is JSON Lines with one
// object per input, and that both kinds are written.
func TestInputHistoryRecordsEveryKindAsJSONL(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	history := NewInputHistory(path, InputHistoryLimits{}, nil)
	if err := history.Record(InputHistoryKindCommand, "list"); err != nil {
		t.Fatalf("record command: %v", err)
	}
	if err := history.Record(InputHistoryKindAnswer, "y"); err != nil {
		t.Fatalf("record answer: %v", err)
	}
	lines := readHistoryLines(t, path)
	if len(lines) != 2 {
		t.Fatalf("lines=%v", lines)
	}
	for index, want := range []InputHistoryEntry{{Kind: InputHistoryKindCommand, Text: "list"}, {Kind: InputHistoryKindAnswer, Text: "y"}} {
		var entry InputHistoryEntry
		if err := json.Unmarshal([]byte(lines[index]), &entry); err != nil {
			t.Fatalf("line %d is not JSON: %v", index, err)
		}
		if entry.Kind != want.Kind || entry.Text != want.Text || entry.TS == "" {
			t.Fatalf("entry=%+v want=%+v", entry, want)
		}
	}
}

// TestInputHistoryFileIsPrivate proves the file is created 0600, because history
// holds whatever the operator typed, including message bodies.
func TestInputHistoryFileIsPrivate(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	history := NewInputHistory(path, InputHistoryLimits{}, nil)
	if err := history.Record(InputHistoryKindCommand, "list"); err != nil {
		t.Fatalf("record: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if mode := info.Mode().Perm(); mode != inputHistoryFileMode {
		t.Fatalf("mode=%o want=%o", mode, inputHistoryFileMode)
	}
}

// TestInputHistoryWriteFailureDoesNotEnterRecall proves the persistent store does
// not present a command that it failed to append. The interactive editor may keep
// its own session recall, but RecentCommands reports only successfully recorded
// history.
func TestInputHistoryWriteFailureDoesNotEnterRecall(t *testing.T) {
	root := t.TempDir()
	blocked := filepath.Join(root, "not-a-directory")
	if err := os.WriteFile(blocked, []byte("block"), inputHistoryFileMode); err != nil {
		t.Fatalf("write blocker: %v", err)
	}
	var diagnostics strings.Builder
	history := NewInputHistory(filepath.Join(blocked, "history.jsonl"), InputHistoryLimits{}, &diagnostics)
	if err := history.Record(InputHistoryKindCommand, "list"); err == nil {
		t.Fatal("record succeeded through a non-directory parent")
	}
	if got := history.RecentCommands(); len(got) != 0 {
		t.Fatalf("failed command entered recall: %v", got)
	}
	if !strings.Contains(diagnostics.String(), "append input history") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// TestInputHistorySkipsBlankInput proves a blank input is not recorded, because
// it carries nothing to recall and would only add noise.
func TestInputHistorySkipsBlankInput(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	history := NewInputHistory(path, InputHistoryLimits{}, nil)
	for _, text := range []string{"", "   ", "\t"} {
		if err := history.Record(InputHistoryKindCommand, text); err != nil {
			t.Fatalf("record %q: %v", text, err)
		}
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("blank input created the file: %v", err)
	}
}

// TestInputHistoryRecallIsCommandOnly proves an answer is persisted but never
// recallable, which is the whole point of the kind distinction.
func TestInputHistoryRecallIsCommandOnly(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	history := NewInputHistory(path, InputHistoryLimits{}, nil)
	for _, entry := range []recordedInput{
		{InputHistoryKindCommand, "list"},
		{InputHistoryKindAnswer, "y"},
		{InputHistoryKindCommand, "show"},
		{InputHistoryKindAnswer, "3"},
	} {
		if err := history.Record(entry.kind, entry.text); err != nil {
			t.Fatalf("record %v: %v", entry, err)
		}
	}
	if got := history.RecentCommands(); strings.Join(got, ",") != "list,show" {
		t.Fatalf("commands=%v", got)
	}
	// Every input is still on disk, so the record is complete even though recall
	// is filtered.
	if lines := readHistoryLines(t, path); len(lines) != 4 {
		t.Fatalf("lines=%v", lines)
	}
}

// TestInputHistorySurvivesRestart proves a second store over the same file
// recalls the commands an earlier session recorded. This is the restart
// behaviour, verified by a second store rather than by two real terminals.
func TestInputHistorySurvivesRestart(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	first := NewInputHistory(path, InputHistoryLimits{}, nil)
	for _, text := range []string{"list", "show"} {
		if err := first.Record(InputHistoryKindCommand, text); err != nil {
			t.Fatalf("record %q: %v", text, err)
		}
	}
	second := NewInputHistory(path, InputHistoryLimits{}, nil)
	if got := second.RecentCommands(); strings.Join(got, ",") != "list,show" {
		t.Fatalf("commands=%v", got)
	}
}

// TestInputHistoryLoadIsBounded proves loading reads at most the configured
// number of entries, so a large file never loads whole.
func TestInputHistoryLoadIsBounded(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	writer := NewInputHistory(path, InputHistoryLimits{}, nil)
	for index := 0; index < 20; index++ {
		if err := writer.Record(InputHistoryKindCommand, "cmd"+string(rune('a'+index))); err != nil {
			t.Fatalf("record: %v", err)
		}
	}
	reader := NewInputHistory(path, InputHistoryLimits{MaxEntries: 3}, nil)
	got := reader.RecentCommands()
	if len(got) != 3 {
		t.Fatalf("commands=%v", got)
	}
	// The newest entries are the ones kept, because only they can be recalled.
	if strings.Join(got, ",") != "cmdr,cmds,cmdt" {
		t.Fatalf("commands=%v", got)
	}
}

// TestInputHistoryRotatesAtSizeBound proves the active file is rotated once it
// exceeds its bound and that the backup count stays bounded.
//
// Rotation runs before each append, so the active file never exceeds the bound by
// more than the one record being written. That is the real contract: a strict
// "never above the bound" would require rotating after the write, which would
// leave the oversized file in place until the next append.
func TestInputHistoryRotatesAtSizeBound(t *testing.T) {
	const bound = 64
	path := filepath.Join(t.TempDir(), "history.jsonl")
	history := NewInputHistory(path, InputHistoryLimits{MaxSizeBytes: bound, MaxBackups: 1}, nil)
	longest := ""
	for index := 0; index < 12; index++ {
		text := "command-" + string(rune('a'+index))
		longest = text
		if err := history.Record(InputHistoryKindCommand, text); err != nil {
			t.Fatalf("record: %v", err)
		}
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	// One record is the largest overshoot a pre-write rotation can leave behind.
	encoded, err := json.Marshal(InputHistoryEntry{TS: "2026-11-12T09:19:40+0800", Kind: InputHistoryKindCommand, Text: longest})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if limit := bound + len(encoded) + 1; info.Size() > int64(limit) {
		t.Fatalf("active file exceeded the bound by more than one record: size=%d limit=%d", info.Size(), limit)
	}
	if _, err := os.Stat(path + ".1"); err != nil {
		t.Fatalf("backup missing: %v", err)
	}
	// The slot beyond the retained count must not exist, so rotation cannot grow
	// the file count without bound.
	if _, err := os.Stat(path + ".2"); !os.IsNotExist(err) {
		t.Fatalf("unbounded backup retained: %v", err)
	}
}

// TestInputHistoryRotationLogsBackupDeletion proves retention cleanup reports the
// exact file it deletes instead of silently removing operator history.
func TestInputHistoryRotationLogsBackupDeletion(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	if err := os.WriteFile(path, []byte(strings.Repeat("a", 65)), inputHistoryFileMode); err != nil {
		t.Fatalf("write active: %v", err)
	}
	if err := os.WriteFile(path+".1", []byte("old backup"), inputHistoryFileMode); err != nil {
		t.Fatalf("write backup: %v", err)
	}
	var diagnostics strings.Builder
	history := NewInputHistory(path, InputHistoryLimits{MaxSizeBytes: 64, MaxBackups: 1}, &diagnostics)
	if err := history.Record(InputHistoryKindCommand, "list"); err != nil {
		t.Fatalf("record: %v", err)
	}
	if want := "deleted input history backup: " + path + ".1"; !strings.Contains(diagnostics.String(), want) {
		t.Fatalf("diagnostics=%q does not contain %q", diagnostics.String(), want)
	}
}

// TestInputHistoryRotationFailureStopsAppend proves a failed retention step does
// not append past the configured bound or enter the command in persistent recall.
func TestInputHistoryRotationFailureStopsAppend(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	original := strings.Repeat("a", 65)
	if err := os.WriteFile(path, []byte(original), inputHistoryFileMode); err != nil {
		t.Fatalf("write active: %v", err)
	}
	if err := os.Mkdir(path+".1", 0o700); err != nil {
		t.Fatalf("make blocking backup: %v", err)
	}
	if err := os.WriteFile(filepath.Join(path+".1", "child"), []byte("keep directory non-empty"), inputHistoryFileMode); err != nil {
		t.Fatalf("write blocking child: %v", err)
	}
	var diagnostics strings.Builder
	history := NewInputHistory(path, InputHistoryLimits{MaxSizeBytes: 64, MaxBackups: 1}, &diagnostics)
	if err := history.Record(InputHistoryKindCommand, "list"); err == nil {
		t.Fatal("record succeeded after rotation failure")
	}
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read active: %v", err)
	}
	if string(content) != original {
		t.Fatalf("active history changed after failed rotation: %q", string(content))
	}
	if got := history.RecentCommands(); len(got) != 0 {
		t.Fatalf("failed command entered recall: %v", got)
	}
	if !strings.Contains(diagnostics.String(), "remove oldest input history backup") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// TestInputHistorySkipsMalformedLine proves one damaged line does not discard
// the rest of the file, and that the damage is reported rather than swallowed.
func TestInputHistorySkipsMalformedLine(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	content := "{\"ts\":\"t\",\"kind\":\"command\",\"text\":\"list\"}\nnot json\n{\"ts\":\"t\",\"kind\":\"command\",\"text\":\"show\"}\n"
	if err := os.WriteFile(path, []byte(content), inputHistoryFileMode); err != nil {
		t.Fatalf("write: %v", err)
	}
	var diagnostics strings.Builder
	history := NewInputHistory(path, InputHistoryLimits{}, &diagnostics)
	if got := history.RecentCommands(); strings.Join(got, ",") != "list,show" {
		t.Fatalf("commands=%v", got)
	}
	if !strings.Contains(diagnostics.String(), "parse input history entry") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// TestInputHistoryMissingFileIsNotAnError proves a missing file never prevents
// construction, because history is a convenience and a REPL must still start.
func TestInputHistoryMissingFileIsNotAnError(t *testing.T) {
	path := filepath.Join(t.TempDir(), "absent", "history.jsonl")
	var diagnostics strings.Builder
	history := NewInputHistory(path, InputHistoryLimits{}, &diagnostics)
	if got := history.RecentCommands(); len(got) != 0 {
		t.Fatalf("commands=%v", got)
	}
	if diagnostics.String() != "" {
		t.Fatalf("missing file reported as an error: %q", diagnostics.String())
	}
}

// TestInputHistoryNormalizesLimits proves a non-positive bound falls back to its
// default instead of meaning "unbounded", which would grow without limit.
func TestInputHistoryNormalizesLimits(t *testing.T) {
	got := NormalizeInputHistoryLimits(InputHistoryLimits{})
	want := InputHistoryLimits{
		MaxEntries:   DefaultInputHistoryMaxEntries,
		MaxSizeBytes: DefaultInputHistoryMaxSizeMB << 20,
		MaxBackups:   DefaultInputHistoryMaxBackups,
	}
	if got != want {
		t.Fatalf("got=%+v want=%+v", got, want)
	}
}

// TestInputHistoryTailDropsPartialFirstLine proves a bounded window that starts
// mid-line drops that fragment instead of parsing a truncated object.
func TestInputHistoryTailDropsPartialFirstLine(t *testing.T) {
	path := filepath.Join(t.TempDir(), "history.jsonl")
	// A long first entry pushes the read window past it, so the window begins
	// inside a line.
	long := strings.Repeat("x", inputHistoryTailBytes)
	content := "{\"ts\":\"t\",\"kind\":\"command\",\"text\":\"" + long + "\"}\n" +
		"{\"ts\":\"t\",\"kind\":\"command\",\"text\":\"newest\"}\n"
	if err := os.WriteFile(path, []byte(content), inputHistoryFileMode); err != nil {
		t.Fatalf("write: %v", err)
	}
	lines, err := readInputHistoryTail(path, 10)
	if err != nil {
		t.Fatalf("tail: %v", err)
	}
	if len(lines) != 1 || !strings.Contains(lines[0], "newest") {
		t.Fatalf("lines=%v", lines)
	}
}
