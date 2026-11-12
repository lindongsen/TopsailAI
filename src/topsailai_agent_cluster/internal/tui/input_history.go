package tui

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

// Input history kinds. The distinction exists because recording and recalling
// are different questions: every input is recorded, but only a command line is
// recallable. An answer such as "y" or "3" is meaningful only in the prompt that
// asked for it, so recalling it at the REPL prompt would offer a command the
// operator never typed, and recalling it at a destructive confirmation would let
// Up plus Enter re-confirm an action.
const (
	// InputHistoryKindCommand marks a REPL command line: recorded and recallable.
	InputHistoryKindCommand = "command"
	// InputHistoryKindAnswer marks a prompt answer: recorded, never recallable.
	InputHistoryKindAnswer = "answer"
)

// Input history defaults mirror the provider CLI's own input-history convention
// (cli_topsailai/history.py), so one operator learns one set of numbers instead
// of two. They are defaults, not limits: every value is configurable at the
// process boundary.
const (
	// DefaultInputHistoryMaxEntries bounds both the recall list and the number of
	// entries loaded at startup.
	DefaultInputHistoryMaxEntries = 100
	// DefaultInputHistoryMaxSizeMB bounds the active file before rotation.
	DefaultInputHistoryMaxSizeMB = 1
	// DefaultInputHistoryMaxBackups bounds the number of retained rotated files.
	DefaultInputHistoryMaxBackups = 1
	// inputHistoryFileMode keeps the file private. History contains whatever the
	// operator typed, including message bodies, so it must not be world readable.
	inputHistoryFileMode = 0o600
	// inputHistoryTailBytes bounds how much of the file is read at startup. The
	// whole file is never loaded: it is append-only, and only the most recent
	// entries can be recalled.
	inputHistoryTailBytes = 256 << 10
	// inputHistoryTimestampLayout is the local ISO 8601 form with a numeric
	// offset, matching the provider CLI's own history entries.
	inputHistoryTimestampLayout = "2006-01-02T15:04:05-0700"
)

// InputHistoryEntry is one persisted input. The field names match the provider
// CLI's history entries, so the two files stay readable by the same tooling; the
// kind field is the only addition this requirement needs.
type InputHistoryEntry struct {
	TS   string `json:"ts"`
	Kind string `json:"kind"`
	Text string `json:"text"`
}

// InputHistoryLimits carries the resolved bounds. It is a value rather than
// ambient environment reads, because the process boundary resolves configuration
// once and passes it down.
type InputHistoryLimits struct {
	MaxEntries   int
	MaxSizeBytes int64
	MaxBackups   int
}

// NormalizeInputHistoryLimits replaces every non-positive bound with its default.
// A non-positive value cannot mean "unbounded" here: an unbounded append-only file
// grows without limit, which is exactly what the rotation rules forbid.
func NormalizeInputHistoryLimits(limits InputHistoryLimits) InputHistoryLimits {
	if limits.MaxEntries <= 0 {
		limits.MaxEntries = DefaultInputHistoryMaxEntries
	}
	if limits.MaxSizeBytes <= 0 {
		limits.MaxSizeBytes = DefaultInputHistoryMaxSizeMB << 20
	}
	if limits.MaxBackups <= 0 {
		limits.MaxBackups = DefaultInputHistoryMaxBackups
	}
	return limits
}

// InputHistory persists every interactive input as JSON Lines and supplies the
// recall list for a new editor.
//
// It owns persistence only. The in-memory recall list stays in lineEditor, so one
// value has one owner and the two cannot disagree about what Up recalls.
type InputHistory struct {
	path        string
	limits      InputHistoryLimits
	diagnostics io.Writer
	mu          sync.Mutex
	commands    []string
}

// NewInputHistory builds a store over path and loads the recent recall list.
//
// A missing, unreadable or malformed file never fails construction: history is a
// convenience, and a REPL that refuses to start because its history file is
// damaged would be unusable for the reason it is least needed. Diagnostics go to
// the supplied writer so a failure is reported rather than silently swallowed.
func NewInputHistory(path string, limits InputHistoryLimits, diagnostics io.Writer) *InputHistory {
	history := &InputHistory{path: path, limits: NormalizeInputHistoryLimits(limits), diagnostics: diagnostics}
	history.load()
	return history
}

// Path reports the file this store appends to.
func (h *InputHistory) Path() string { return h.path }

// Limits reports the resolved bounds.
func (h *InputHistory) Limits() InputHistoryLimits { return h.limits }

// RecentCommands returns a copy of the recall list, oldest first.
func (h *InputHistory) RecentCommands() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.commands...)
}

// Record appends one input to the file and, for a command, to the recall list.
//
// A blank input is not recorded, because it carries nothing to recall and would
// only add noise to the file. The returned error is for callers that want to
// assert the failure; the store has already reported it to its diagnostics
// writer, so a caller that ignores it does not hide it. A command enters the
// recall list only after persistence succeeds, so the store never presents an
// input that it failed to record.
func (h *InputHistory) Record(kind, text string) error {
	if strings.TrimSpace(text) == "" {
		return nil
	}
	if kind != InputHistoryKindCommand && kind != InputHistoryKindAnswer {
		kind = InputHistoryKindAnswer
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	entry := InputHistoryEntry{TS: time.Now().Format(inputHistoryTimestampLayout), Kind: kind, Text: text}
	if err := h.append(entry); err != nil {
		h.report("append input history", err)
		return err
	}
	if kind == InputHistoryKindCommand {
		h.rememberCommand(text)
	}
	return nil
}

// rememberCommand appends to the bounded recall list, skipping a consecutive
// duplicate so a repeated command does not fill the list with itself.
func (h *InputHistory) rememberCommand(text string) {
	if len(h.commands) > 0 && h.commands[len(h.commands)-1] == text {
		return
	}
	if len(h.commands) >= h.limits.MaxEntries {
		copy(h.commands, h.commands[1:])
		h.commands = h.commands[:len(h.commands)-1]
	}
	h.commands = append(h.commands, text)
}

// append writes one JSON line, rotating the active file first when it is already
// at its size bound.
func (h *InputHistory) append(entry InputHistoryEntry) error {
	if err := os.MkdirAll(filepath.Dir(h.path), 0o700); err != nil {
		return err
	}
	if err := h.rotateIfNeeded(); err != nil {
		return err
	}
	encoded, err := json.Marshal(entry)
	if err != nil {
		return err
	}
	file, err := os.OpenFile(h.path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, inputHistoryFileMode)
	if err != nil {
		return err
	}
	// A file created by an earlier version or by hand may carry wider permissions,
	// so the mode is enforced on the open descriptor rather than only at creation.
	if err := file.Chmod(inputHistoryFileMode); err != nil {
		_ = file.Close()
		return err
	}
	if _, err := file.Write(append(encoded, '\n')); err != nil {
		_ = file.Close()
		return err
	}
	return file.Close()
}

// rotateIfNeeded moves the active file to backup slot 1 once it exceeds its size
// bound, shifting older backups and deleting the one that falls outside the
// retained count. Rotation is size-based and implemented here rather than through
// an OS tool, so it behaves the same on every platform. Any failed filesystem
// operation aborts the append, because continuing could overwrite a retained
// backup or let the active file grow without its configured bound.
func (h *InputHistory) rotateIfNeeded() error {
	info, err := os.Stat(h.path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("stat input history for rotation: %w", err)
	}
	if info.Size() <= h.limits.MaxSizeBytes {
		return nil
	}
	oldest := h.backupPath(h.limits.MaxBackups)
	if err := os.Remove(oldest); err == nil {
		h.reportEvent("deleted input history backup", oldest)
	} else if !os.IsNotExist(err) {
		return fmt.Errorf("remove oldest input history backup: %w", err)
	}
	// Shift from the oldest remaining slot upward, so no backup is overwritten
	// before it has been moved.
	for index := h.limits.MaxBackups - 1; index >= 1; index-- {
		source := h.backupPath(index)
		if _, err := os.Stat(source); os.IsNotExist(err) {
			continue
		} else if err != nil {
			return fmt.Errorf("stat input history backup %d: %w", index, err)
		}
		if err := os.Rename(source, h.backupPath(index+1)); err != nil {
			return fmt.Errorf("rotate input history backup %d: %w", index, err)
		}
	}
	if err := os.Rename(h.path, h.backupPath(1)); err != nil {
		return fmt.Errorf("rotate input history: %w", err)
	}
	return nil
}

// backupPath names one rotated file. Slot 1 is the newest backup.
func (h *InputHistory) backupPath(index int) string {
	return fmt.Sprintf("%s.%d", h.path, index)
}

// load reads at most the configured number of trailing entries and rebuilds the
// recall list from the commands among them.
func (h *InputHistory) load() {
	lines, err := readInputHistoryTail(h.path, h.limits.MaxEntries)
	if err != nil {
		if !os.IsNotExist(err) {
			h.report("read input history", err)
		}
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	h.commands = h.commands[:0]
	for _, line := range lines {
		var entry InputHistoryEntry
		if err := json.Unmarshal([]byte(line), &entry); err != nil {
			// One damaged line must not discard the rest of the file, so it is
			// skipped and reported instead of aborting the load.
			h.report("parse input history entry", err)
			continue
		}
		if entry.Kind != InputHistoryKindCommand || strings.TrimSpace(entry.Text) == "" {
			continue
		}
		h.rememberCommand(entry.Text)
	}
}

// report writes one diagnostic line. A nil writer keeps the store silent, so a
// caller that supplied no boundary loses nothing.
func (h *InputHistory) report(action string, err error) {
	if h.diagnostics == nil {
		return
	}
	_, _ = fmt.Fprintf(h.diagnostics, "input history: %s: %v\n", action, err)
}

// reportEvent writes one successful maintenance event. File deletion is always
// reported so retention cleanup remains observable rather than silently removing
// operator data.
func (h *InputHistory) reportEvent(action, path string) {
	if h.diagnostics == nil {
		return
	}
	_, _ = fmt.Fprintf(h.diagnostics, "input history: %s: %s\n", action, path)
}

// readInputHistoryTail returns at most limit non-empty trailing lines of path.
//
// It reads a bounded window from the end of the file rather than the whole file,
// because the file is append-only and only the most recent entries are needed. A
// window that starts mid-line drops that partial line, since a truncated JSON
// object is not an entry.
func readInputHistoryTail(path string, limit int) ([]string, error) {
	if limit <= 0 {
		return nil, nil
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	size := info.Size()
	if size == 0 {
		return nil, nil
	}
	window := int64(inputHistoryTailBytes)
	start := int64(0)
	if size > window {
		start = size - window
	}
	buffer := make([]byte, size-start)
	if _, err := file.ReadAt(buffer, start); err != nil && err != io.EOF {
		return nil, err
	}
	lines := strings.Split(string(buffer), "\n")
	// A window that did not begin at offset zero begins inside a line, so its
	// first fragment is incomplete and must not be parsed.
	if start > 0 && len(lines) > 0 {
		lines = lines[1:]
	}
	kept := make([]string, 0, limit)
	for index := len(lines) - 1; index >= 0 && len(kept) < limit; index-- {
		line := strings.TrimSpace(lines[index])
		if line == "" {
			continue
		}
		kept = append(kept, line)
	}
	// Reverse into file order, so the recall list reads oldest first.
	for left, right := 0, len(kept)-1; left < right; left, right = left+1, right-1 {
		kept[left], kept[right] = kept[right], kept[left]
	}
	return kept, nil
}
