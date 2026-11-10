package cli

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/config"
	"github.com/topsailai/topsailai_data/pkg/manager"
)

// setupFileManager creates a manager whose configuration carries explicit file
// read limits, so tests never depend on process-wide environment variables.
func setupFileManager(t *testing.T, maxBytes int, noTruncate []string) (*manager.Manager, context.Context) {
	t.Helper()
	tmp := t.TempDir()
	cfg := &config.Config{
		Root:                     tmp,
		MetadataAdapter:          "local",
		ActualDataAdapter:        "local",
		CeasedRetentionDays:      30,
		LogLevel:                 "ERROR",
		TrackStat:                true,
		StatFlush:                config.DefaultStatFlush,
		FileMaxBytes:             maxBytes,
		FileNoTruncateExtensions: noTruncate,
	}
	mgr, err := manager.New(cfg)
	if err != nil {
		t.Fatalf("new manager: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	t.Cleanup(func() {
		cancel()
		_ = mgr.Close()
	})
	return mgr, ctx
}

// writeTempFile writes content to a file inside the test temporary directory.
// It is used for --from sources, which stay on the operating-system file system
// even though every destination lives inside a data object.
func writeTempFile(t *testing.T, dir, name, content string) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
	return path
}

// runFileCommand runs one "file" subcommand and returns its stdout.
func runFileCommand(t *testing.T, ctx context.Context, mgr *manager.Manager, args ...string) string {
	t.Helper()
	var out string
	out = captureStdout(t, func() {
		if err := runFile(ctx, mgr, args); err != nil {
			t.Fatalf("file %v failed: %v", args, err)
		}
	})
	return out
}

// runFileCommandError runs one "file" subcommand and returns its error.
func runFileCommandError(t *testing.T, ctx context.Context, mgr *manager.Manager, args ...string) error {
	t.Helper()
	var err error
	captureStdout(t, func() {
		err = runFile(ctx, mgr, args)
	})
	return err
}

// TestFileCommandRequiresObject proves --object is mandatory for every
// subcommand, so a file command can never fall back to operating-system paths.
func TestFileCommandRequiresObject(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)

	cases := map[string][]string{
		"read":            {"read", "x.md"},
		"read-lines":      {"read-lines", "x.md"},
		"read-around":     {"read-around", "x.md", "1"},
		"read-context":    {"read-context", "x.md", "pattern"},
		"read-files":      {"read-files", "x.md"},
		"write":           {"write", "x.md", "--content", "c"},
		"append":          {"append", "x.md", "--content", "c"},
		"exists":          {"exists", "a=x.md"},
		"mkdirs":          {"mkdirs", "folder"},
		"list-dirs":       {"list-dirs", ""},
		"size":            {"size", "x.md"},
		"overwrite-lines": {"overwrite-lines", "x.md", "1", "--content", "c"},
		"insert":          {"insert", "x.md", "1", "--content", "c"},
	}
	for name, args := range cases {
		err := runFileCommandError(t, ctx, mgr, args...)
		if err == nil {
			t.Fatalf("%s: expected a missing --object error", name)
		}
		if !strings.Contains(err.Error(), "--object <id> is required") {
			t.Fatalf("%s: expected required-object guidance, got %v", name, err)
		}
	}
}

// TestFileCommandRejectsEmptyObjectValue proves an explicitly empty --object is
// rejected instead of being treated as "no object".
func TestFileCommandRejectsEmptyObjectValue(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)

	err := runFileCommandError(t, ctx, mgr, "read", "x.md", "--object", "")
	if err == nil {
		t.Fatal("expected an empty --object rejection")
	}
	if !strings.Contains(err.Error(), "--object <id> is required") {
		t.Fatalf("expected required-object guidance, got %v", err)
	}
}

func TestFileReadCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "marker",
		"note.md":  "hello world\n",
		"other.md": "other",
	})

	out := runFileCommand(t, ctx, mgr, "read", "note.md", "--object", "demo")
	if out != "hello world\n" {
		t.Fatalf("expected full content, got %q", out)
	}
}

func TestFileReadCommandSeekAndSize(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "0123456789",
	})

	out := runFileCommand(t, ctx, mgr, "read", "note.md", "--seek", "2", "--size", "3", "--object", "demo")
	if out != "234" {
		t.Fatalf("expected window 234, got %q", out)
	}

	out = runFileCommand(t, ctx, mgr, "read", "note.md", "--seek", "-3", "--object", "demo")
	if out != "789" {
		t.Fatalf("expected negative seek to read 789, got %q", out)
	}
}

func TestFileReadCommandTruncatesUnlistedExtension(t *testing.T) {
	mgr, ctx := setupFileManager(t, 10, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "marker",
		"blob.bin": strings.Repeat("x", 50),
	})

	out := runFileCommand(t, ctx, mgr, "read", "blob.bin", "--object", "demo")
	if !strings.HasSuffix(out, " ... (force to truncate)") {
		t.Fatalf("expected truncation suffix, got %q", out)
	}
	if !strings.HasPrefix(out, strings.Repeat("x", 10)) {
		t.Fatalf("expected content truncated at 10 bytes, got %q", out)
	}
}

func TestFileReadCommandHonoursWhitelistOverride(t *testing.T) {
	mgr, ctx := setupFileManager(t, 10, []string{"*"})
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "marker",
		"blob.bin": strings.Repeat("x", 50),
	})

	out := runFileCommand(t, ctx, mgr, "read", "blob.bin", "--object", "demo")
	if strings.Contains(out, "force to truncate") {
		t.Fatalf("expected no truncation with * override, got %q", out)
	}
	if len(out) != 50 {
		t.Fatalf("expected all 50 bytes, got %d", len(out))
	}
}

func TestFileReadLinesCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "marker",
		"note.md":  "alpha\nbeta\ngamma\ndelta\n",
		"other.md": "other",
	})

	out := runFileCommand(t, ctx, mgr, "read-lines", "note.md", "--start", "2", "--end", "3", "--object", "demo")
	if out != "2-beta\n3-gamma" {
		t.Fatalf("expected lines 2-3, got %q", out)
	}

	out = runFileCommand(t, ctx, mgr, "read-lines", "note.md", "--start", "3", "--end", "-1", "--object", "demo")
	if out != "3-gamma\n4-delta" {
		t.Fatalf("expected lines 3 to end, got %q", out)
	}

	out = runFileCommand(t, ctx, mgr, "read-lines", "note.md", "--start", "2", "--object", "demo")
	if out != "2-beta" {
		t.Fatalf("expected only line 2, got %q", out)
	}
}

func TestFileReadAroundCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "alpha\nbeta\ngamma\ndelta\n",
	})

	out := runFileCommand(t, ctx, mgr, "read-around", "note.md", "2", "--context", "1", "--object", "demo")
	if out != "1-alpha\n2:beta\n3-gamma" {
		t.Fatalf("expected context around line 2, got %q", out)
	}
}

func TestFileReadAroundCommandRejectsOutOfRange(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "alpha\n",
	})

	err := runFileCommandError(t, ctx, mgr, "read-around", "note.md", "9", "--object", "demo")
	if err == nil {
		t.Fatal("expected an out-of-range error")
	}
	if !strings.Contains(err.Error(), "out of range") {
		t.Fatalf("expected out-of-range message, got %v", err)
	}
}

func TestFileReadContextCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "alpha\nbeta\ngamma\ndelta\n",
	})

	out := runFileCommand(t, ctx, mgr, "read-context", "note.md", "beta", "--context", "1", "--object", "demo")
	if out != "1-alpha\n2:beta\n3-gamma" {
		t.Fatalf("expected context around beta, got %q", out)
	}
}

func TestFileReadContextCommandCaseSensitivity(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "Alpha\nbeta\n",
	})

	out := runFileCommand(t, ctx, mgr, "read-context", "note.md", "alpha", "--object", "demo")
	if !strings.Contains(out, "1:Alpha") {
		t.Fatalf("expected case-insensitive match, got %q", out)
	}

	out = runFileCommand(t, ctx, mgr, "read-context", "note.md", "alpha", "--case-sensitive", "--object", "demo")
	if out != "" {
		t.Fatalf("expected no case-sensitive match, got %q", out)
	}
}

func TestFileReadFilesCommandJSON(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"a.md":    "one\n",
		"b.md":    "two\n",
	})

	out := runFileCommand(t, ctx, mgr, "read-files", "a.md", "b.md", "--format", "json", "--object", "demo")

	var parsed map[string]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	if parsed["a.md"] != "one\n" || parsed["b.md"] != "two\n" {
		t.Fatalf("unexpected read-files result: %v", parsed)
	}
}

func TestFileReadFilesCommandRecordsErrors(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"a.md":    "one\n",
	})

	out := runFileCommand(t, ctx, mgr, "read-files", "a.md", "missing.md", "--format", "json", "--object", "demo")

	var parsed map[string]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	if parsed["a.md"] != "one\n" {
		t.Fatalf("expected readable file content, got %q", parsed["a.md"])
	}
	if !strings.HasPrefix(parsed["missing.md"], "Error:") {
		t.Fatalf("expected an error entry for the missing file, got %q", parsed["missing.md"])
	}
}

func TestFileWriteCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	out := runFileCommand(t, ctx, mgr, "write", "out.txt", "--content", "hello\n", "--object", "demo")
	if strings.TrimSpace(out) != "OK" {
		t.Fatalf("expected OK, got %q", out)
	}
	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "hello\n" {
		t.Fatalf("expected hello, got %q", got)
	}
}

func TestFileWriteCommandFromFile(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})
	source := writeTempFile(t, t.TempDir(), "src.txt", "from source\n")

	runFileCommand(t, ctx, mgr, "write", "out.txt", "--from", source, "--object", "demo")

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "from source\n" {
		t.Fatalf("expected source content, got %q", got)
	}
}

func TestFileWriteCommandInsertAtSeek(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"out.txt": "abcdef",
	})

	runFileCommand(t, ctx, mgr, "write", "out.txt", "--content", "XY", "--seek", "2", "--insert", "--object", "demo")

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "abXYcdef" {
		t.Fatalf("expected insertion at offset 2, got %q", got)
	}
}

func TestFileWriteCommandAppendWithNegativeSeek(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"out.txt": "abc",
	})

	runFileCommand(t, ctx, mgr, "write", "out.txt", "--content", "Z", "--seek", "-1", "--insert", "--object", "demo")

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "abcZ" {
		t.Fatalf("expected append with seek -1, got %q", got)
	}
}

func TestFileAppendCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"out.txt": "one\n",
	})

	runFileCommand(t, ctx, mgr, "append", "out.txt", "--content", "two\n", "--object", "demo")

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "one\ntwo\n" {
		t.Fatalf("expected appended content, got %q", got)
	}
}

func TestFileExistsCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"a.md":    "x",
	})

	out := runFileCommand(t, ctx, mgr, "exists", "a=a.md", "b=missing.md", "--format", "json", "--object", "demo")

	var parsed map[string]bool
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	if !parsed["a"] {
		t.Fatalf("expected a to exist, got %v", parsed)
	}
	if parsed["b"] {
		t.Fatalf("expected b to be absent, got %v", parsed)
	}
}

func TestFileExistsCommandRejectsMalformedPair(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	err := runFileCommandError(t, ctx, mgr, "exists", "no-equals-sign", "--object", "demo")
	if err == nil {
		t.Fatal("expected a malformed pair error")
	}
	if !strings.Contains(err.Error(), "name=path") {
		t.Fatalf("expected name=path guidance, got %v", err)
	}
}

// TestFileMkdirsCommandCreatesDiscoverableFolders proves mkdirs writes an
// AGENTS.md marker into every created level, so the new folder is immediately
// visible through list-dirs instead of being a silent no-op.
func TestFileMkdirsCommandCreatesDiscoverableFolders(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	out := runFileCommand(t, ctx, mgr, "mkdirs", "nested/a/b/c", "--object", "demo")
	if strings.TrimSpace(out) != "OK" {
		t.Fatalf("expected OK, got %q", out)
	}

	root := decodeListing(t, runFileCommand(t, ctx, mgr, "list-dirs", "", "--format", "json", "--object", "demo"))
	if !containsEntry(root[""], "nested") {
		t.Fatalf("expected the object root to list nested, got %v", root[""])
	}

	level := decodeListing(t, runFileCommand(t, ctx, mgr, "list-dirs", "nested/a/b/c", "--format", "json", "--object", "demo"))
	if !containsEntry(level["nested/a/b/c"], "AGENTS.md") {
		t.Fatalf("expected AGENTS.md in the created folder, got %v", level["nested/a/b/c"])
	}

	content := runFileCommand(t, ctx, mgr, "read", "nested/a/b/c/AGENTS.md", "--object", "demo")
	if !strings.Contains(content, "AGENTS") {
		t.Fatalf("expected the marker content, got %q", content)
	}
}

// TestFileMkdirsCommandPreservesExistingContent proves mkdirs never overwrites
// an existing AGENTS.md and never adds a marker to a folder that already holds
// files.
func TestFileMkdirsCommandPreservesExistingContent(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md":         "marker",
		"notes/AGENTS.md": "custom instructions",
		"notes/keep.txt":  "keep me",
	})

	out := runFileCommand(t, ctx, mgr, "mkdirs", "notes", "--object", "demo")
	if strings.TrimSpace(out) != "OK" {
		t.Fatalf("expected OK, got %q", out)
	}

	content := runFileCommand(t, ctx, mgr, "read", "notes/AGENTS.md", "--object", "demo")
	if strings.TrimSpace(content) != "custom instructions" {
		t.Fatalf("expected the existing AGENTS.md to survive, got %q", content)
	}

	kept := runFileCommand(t, ctx, mgr, "read", "notes/keep.txt", "--object", "demo")
	if strings.TrimSpace(kept) != "keep me" {
		t.Fatalf("expected the existing file to survive, got %q", kept)
	}
}

// TestFileMkdirsCommandIsIdempotent proves a repeated mkdirs leaves the marker
// content unchanged.
func TestFileMkdirsCommandIsIdempotent(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	runFileCommand(t, ctx, mgr, "mkdirs", "docs", "--object", "demo")
	first := runFileCommand(t, ctx, mgr, "read", "docs/AGENTS.md", "--object", "demo")

	runFileCommand(t, ctx, mgr, "mkdirs", "docs", "--object", "demo")
	second := runFileCommand(t, ctx, mgr, "read", "docs/AGENTS.md", "--object", "demo")

	if first != second {
		t.Fatalf("expected an idempotent marker, got %q then %q", first, second)
	}
}

// TestFileMkdirsCommandSkipsObjectRoot proves the object root is never given a
// marker file.
func TestFileMkdirsCommandSkipsObjectRoot(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	out := runFileCommand(t, ctx, mgr, "mkdirs", ".", "--object", "demo")
	if strings.TrimSpace(out) != "OK" {
		t.Fatalf("expected OK, got %q", out)
	}

	root := decodeListing(t, runFileCommand(t, ctx, mgr, "list-dirs", "", "--format", "json", "--object", "demo"))
	if containsEntry(root[""], "AGENTS.md") {
		t.Fatalf("expected no marker at the object root, got %v", root[""])
	}
}

// decodeListing decodes list-dirs JSON output.
func decodeListing(t *testing.T, out string) map[string][]string {
	t.Helper()
	var parsed map[string][]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	return parsed
}

// containsEntry reports whether names holds want.
func containsEntry(names []string, want string) bool {
	for _, name := range names {
		if name == want {
			return true
		}
	}
	return false
}

// TestFileMkdirsCommandAcceptsRelativePathInObjectMode proves the absolute-path
// requirement applies only to operating-system folders; object paths are always
// relative to the object folder.
func TestFileMkdirsCommandAcceptsRelativePathInObjectMode(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	out := runFileCommand(t, ctx, mgr, "mkdirs", "relative/dir", "--object", "demo")
	if strings.TrimSpace(out) != "OK" {
		t.Fatalf("expected OK, got %q", out)
	}
}

func TestFileListDirsCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"b.md":    "x",
		"a.md":    "x",
	})

	out := runFileCommand(t, ctx, mgr, "list-dirs", "", "--format", "json", "--object", "demo")

	var parsed map[string][]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	entries := parsed[""]
	if len(entries) != 3 || entries[0] != "a.md" || entries[1] != "b.md" || entries[2] != "demo.md" {
		t.Fatalf("expected sorted entries, got %v", entries)
	}
}

func TestFileListDirsCommandRecordsErrors(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	out := runFileCommand(t, ctx, mgr, "list-dirs", "missing", "--format", "json", "--object", "demo")

	var parsed map[string][]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	entries := parsed["missing"]
	if len(entries) != 1 || !strings.HasPrefix(entries[0], "Error:") {
		t.Fatalf("expected an error entry, got %v", entries)
	}
}

func TestFileSizeCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"a.md":    "12345",
	})

	out := runFileCommand(t, ctx, mgr, "size", "a.md", "--object", "demo")
	if strings.TrimSpace(out) != "5" {
		t.Fatalf("expected size 5, got %q", out)
	}
}

func TestFileOverwriteLinesCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "one\ntwo\nthree\n",
	})

	out := runFileCommand(t, ctx, mgr, "overwrite-lines", "note.md", "2", "--content", "TWO\n", "--object", "demo")
	if !strings.Contains(out, "You CANNOT call continuously") {
		t.Fatalf("expected the overwrite warning, got %q", out)
	}
	if !strings.Contains(out, "-two") || !strings.Contains(out, "+TWO") {
		t.Fatalf("expected a unified diff, got %q", out)
	}

	if got := readObjectFile(t, ctx, mgr, "demo", "note.md"); got != "one\nTWO\nthree\n" {
		t.Fatalf("expected line 2 replaced, got %q", got)
	}
}

func TestFileOverwriteLinesCommandThroughEnd(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "one\ntwo\nthree\n",
	})

	runFileCommand(t, ctx, mgr, "overwrite-lines", "note.md", "2", "--end", "-1", "--content", "tail\n", "--object", "demo")

	if got := readObjectFile(t, ctx, mgr, "demo", "note.md"); got != "one\ntail\n" {
		t.Fatalf("expected replacement through the end, got %q", got)
	}
}

func TestFileOverwriteLinesCommandDeletesWithEmptyContent(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "one\ntwo\nthree\n",
	})

	runFileCommand(t, ctx, mgr, "overwrite-lines", "note.md", "2", "--object", "demo")

	if got := readObjectFile(t, ctx, mgr, "demo", "note.md"); got != "one\nthree\n" {
		t.Fatalf("expected line 2 deleted, got %q", got)
	}
}

func TestFileOverwriteLinesCommandRejectsBadRange(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "one\n",
	})

	err := runFileCommandError(t, ctx, mgr, "overwrite-lines", "note.md", "5", "--content", "x", "--object", "demo")
	if err == nil {
		t.Fatal("expected a range error")
	}
	if !strings.Contains(err.Error(), "exceeds file length") {
		t.Fatalf("expected an exceeds-length message, got %v", err)
	}
}

func TestFileInsertCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "one\ntwo\n",
	})

	out := runFileCommand(t, ctx, mgr, "insert", "note.md", "1", "--content", "inserted\n", "--object", "demo")
	if !strings.Contains(out, "+inserted") {
		t.Fatalf("expected a diff with the inserted line, got %q", out)
	}

	if got := readObjectFile(t, ctx, mgr, "demo", "note.md"); got != "one\ninserted\ntwo\n" {
		t.Fatalf("expected insertion after line 1, got %q", got)
	}
}

func TestFileInsertCommandBefore(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "one\ntwo\n",
	})

	runFileCommand(t, ctx, mgr, "insert", "note.md", "2", "--content", "before-two\n", "--before", "--object", "demo")

	if got := readObjectFile(t, ctx, mgr, "demo", "note.md"); got != "one\nbefore-two\ntwo\n" {
		t.Fatalf("expected insertion before line 2, got %q", got)
	}
}

func TestFileGroupPrintsUsage(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)

	out := runFileCommand(t, ctx, mgr)
	if !strings.Contains(out, "Usage: topsailai-data file") {
		t.Fatalf("expected file usage, got %q", out)
	}
	for _, name := range []string{"read", "write", "overwrite-lines", "insert", "mkdirs"} {
		if !strings.Contains(out, name) {
			t.Fatalf("expected usage to list %s, got %q", name, out)
		}
	}
	if !strings.Contains(out, "--object <id> is required") {
		t.Fatalf("expected usage to state the required object flag, got %q", out)
	}
}

func TestFileGroupRejectsUnknownSubcommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)

	err := runFileCommandError(t, ctx, mgr, "nope")
	if err == nil {
		t.Fatal("expected an unknown subcommand error")
	}
	if !strings.Contains(err.Error(), "unknown file subcommand") {
		t.Fatalf("expected unknown subcommand message, got %v", err)
	}
}

func TestFileGroupRegisteredInTopLevelUsage(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, nil); err != nil {
			t.Fatalf("usage failed: %v", err)
		}
	})
	if !strings.Contains(out, "file") {
		t.Fatalf("expected top-level usage to list the file group, got %q", out)
	}
}

// withStdin replaces os.Stdin with a pipe carrying content for the duration of
// fn, so a command that reads stdin can be tested without a real terminal.
func withStdin(t *testing.T, content string, fn func()) {
	t.Helper()
	oldStdin := os.Stdin
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("pipe: %v", err)
	}
	os.Stdin = r
	done := make(chan struct{})
	go func() {
		defer close(done)
		_, _ = w.Write([]byte(content))
		_ = w.Close()
	}()
	defer func() {
		<-done
		os.Stdin = oldStdin
		_ = r.Close()
	}()
	fn()
}

func TestFileWriteCommandFromStdinWithoutFromFlag(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	withStdin(t, "piped content\n", func() {
		runFileCommand(t, ctx, mgr, "write", "out.txt", "--object", "demo")
	})

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "piped content\n" {
		t.Fatalf("expected piped content, got %q", got)
	}
}

func TestFileAppendCommandFromStdinWithoutFromFlag(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"out.txt": "one\n",
	})

	withStdin(t, "two\n", func() {
		runFileCommand(t, ctx, mgr, "append", "out.txt", "--object", "demo")
	})

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "one\ntwo\n" {
		t.Fatalf("expected appended stdin content, got %q", got)
	}
}

func TestFileOverwriteLinesCommandFromStdinWithoutFromFlag(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "one\ntwo\nthree\n",
	})

	withStdin(t, "TWO\n", func() {
		runFileCommand(t, ctx, mgr, "overwrite-lines", "note.md", "2", "--object", "demo")
	})

	if got := readObjectFile(t, ctx, mgr, "demo", "note.md"); got != "one\nTWO\nthree\n" {
		t.Fatalf("expected stdin replacement, got %q", got)
	}
}

func TestFileInsertCommandFromStdinWithoutFromFlag(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"note.md": "one\ntwo\n",
	})

	withStdin(t, "inserted\n", func() {
		runFileCommand(t, ctx, mgr, "insert", "note.md", "1", "--object", "demo")
	})

	if got := readObjectFile(t, ctx, mgr, "demo", "note.md"); got != "one\ninserted\ntwo\n" {
		t.Fatalf("expected stdin insertion, got %q", got)
	}
}

func TestFileWriteCommandExplicitEmptyContentBeatsStdin(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "marker",
		"out.txt": "existing\n",
	})

	withStdin(t, "should be ignored\n", func() {
		runFileCommand(t, ctx, mgr, "write", "out.txt", "--content", "", "--object", "demo")
	})

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "" {
		t.Fatalf("expected explicit empty content to win over stdin, got %q", got)
	}
}

func TestFileWriteCommandFromDashReadsStdin(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})

	withStdin(t, "dash content\n", func() {
		runFileCommand(t, ctx, mgr, "write", "out.txt", "--from", "-", "--object", "demo")
	})

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "dash content\n" {
		t.Fatalf("expected stdin content via --from -, got %q", got)
	}
}

// TestFileWriteCommandFromFileBeatsContent locks the documented precedence:
// --from wins over --content so a caller can pass a file without quoting text.
func TestFileWriteCommandFromFileBeatsContent(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})
	src := writeTempFile(t, t.TempDir(), "src.txt", "from-file\n")

	runFileCommand(t, ctx, mgr, "write", "out.txt", "--content", "inline", "--from", src, "--object", "demo")

	if got := readObjectFile(t, ctx, mgr, "demo", "out.txt"); got != "from-file\n" {
		t.Fatalf("expected --from to win over --content, got %q", got)
	}
}
