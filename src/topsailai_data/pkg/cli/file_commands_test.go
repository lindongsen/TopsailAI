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

func TestFileReadCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "hello world\n")

	out := runFileCommand(t, ctx, mgr, "read", path)
	if out != "hello world\n" {
		t.Fatalf("expected full content, got %q", out)
	}
}

func TestFileReadCommandSeekAndSize(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "0123456789")

	out := runFileCommand(t, ctx, mgr, "read", path, "--seek", "2", "--size", "3")
	if out != "234" {
		t.Fatalf("expected window 234, got %q", out)
	}

	out = runFileCommand(t, ctx, mgr, "read", path, "--seek", "-3")
	if out != "789" {
		t.Fatalf("expected negative seek to read 789, got %q", out)
	}
}

func TestFileReadCommandTruncatesUnlistedExtension(t *testing.T) {
	mgr, ctx := setupFileManager(t, 10, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "blob.bin", strings.Repeat("x", 50))

	out := runFileCommand(t, ctx, mgr, "read", path)
	if !strings.HasSuffix(out, " ... (force to truncate)") {
		t.Fatalf("expected truncation suffix, got %q", out)
	}
	if !strings.HasPrefix(out, strings.Repeat("x", 10)) {
		t.Fatalf("expected content truncated at 10 bytes, got %q", out)
	}
}

func TestFileReadCommandHonoursWhitelistOverride(t *testing.T) {
	mgr, ctx := setupFileManager(t, 10, []string{"*"})
	dir := t.TempDir()
	path := writeTempFile(t, dir, "blob.bin", strings.Repeat("x", 50))

	out := runFileCommand(t, ctx, mgr, "read", path)
	if strings.Contains(out, "force to truncate") {
		t.Fatalf("expected no truncation with * override, got %q", out)
	}
	if len(out) != 50 {
		t.Fatalf("expected all 50 bytes, got %d", len(out))
	}
}

func TestFileReadLinesCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "alpha\nbeta\ngamma\ndelta\n")

	out := runFileCommand(t, ctx, mgr, "read-lines", path, "--start", "2", "--end", "3")
	if out != "2-beta\n3-gamma" {
		t.Fatalf("expected lines 2-3, got %q", out)
	}

	out = runFileCommand(t, ctx, mgr, "read-lines", path, "--start", "3", "--end", "-1")
	if out != "3-gamma\n4-delta" {
		t.Fatalf("expected lines 3 to end, got %q", out)
	}

	out = runFileCommand(t, ctx, mgr, "read-lines", path, "--start", "2")
	if out != "2-beta" {
		t.Fatalf("expected only line 2, got %q", out)
	}
}

func TestFileReadAroundCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "alpha\nbeta\ngamma\ndelta\n")

	out := runFileCommand(t, ctx, mgr, "read-around", path, "2", "--context", "1")
	if out != "1-alpha\n2:beta\n3-gamma" {
		t.Fatalf("expected context around line 2, got %q", out)
	}
}

func TestFileReadAroundCommandRejectsOutOfRange(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "alpha\n")

	err := runFile(ctx, mgr, []string{"read-around", path, "9"})
	if err == nil {
		t.Fatal("expected an out-of-range error")
	}
	if !strings.Contains(err.Error(), "out of range") {
		t.Fatalf("expected out-of-range message, got %v", err)
	}
}

func TestFileReadContextCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "alpha\nbeta\ngamma\ndelta\n")

	out := runFileCommand(t, ctx, mgr, "read-context", path, "beta", "--context", "1")
	if out != "1-alpha\n2:beta\n3-gamma" {
		t.Fatalf("expected context around beta, got %q", out)
	}
}

func TestFileReadContextCommandCaseSensitivity(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "Alpha\nbeta\n")

	out := runFileCommand(t, ctx, mgr, "read-context", path, "alpha")
	if !strings.Contains(out, "1:Alpha") {
		t.Fatalf("expected case-insensitive match, got %q", out)
	}

	out = runFileCommand(t, ctx, mgr, "read-context", path, "alpha", "--case-sensitive")
	if out != "" {
		t.Fatalf("expected no case-sensitive match, got %q", out)
	}
}

func TestFileReadFilesCommandJSON(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	first := writeTempFile(t, dir, "a.md", "one\n")
	second := writeTempFile(t, dir, "b.md", "two\n")

	out := runFileCommand(t, ctx, mgr, "read-files", first, second, "--format", "json")

	var parsed map[string]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	if parsed[first] != "one\n" || parsed[second] != "two\n" {
		t.Fatalf("unexpected read-files result: %v", parsed)
	}
}

func TestFileReadFilesCommandRecordsErrors(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	good := writeTempFile(t, dir, "a.md", "one\n")
	missing := filepath.Join(dir, "missing.md")

	out := runFileCommand(t, ctx, mgr, "read-files", good, missing, "--format", "json")

	var parsed map[string]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	if parsed[good] != "one\n" {
		t.Fatalf("expected readable file content, got %q", parsed[good])
	}
	if !strings.HasPrefix(parsed[missing], "Error:") {
		t.Fatalf("expected an error entry for the missing file, got %q", parsed[missing])
	}
}

func TestFileWriteCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := filepath.Join(dir, "out.txt")

	out := runFileCommand(t, ctx, mgr, "write", path, "--content", "hello\n")
	if strings.TrimSpace(out) != "OK" {
		t.Fatalf("expected OK, got %q", out)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read written file: %v", err)
	}
	if string(data) != "hello\n" {
		t.Fatalf("expected hello, got %q", string(data))
	}
}

func TestFileWriteCommandFromFile(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	source := writeTempFile(t, dir, "src.txt", "from source\n")
	path := filepath.Join(dir, "out.txt")

	runFileCommand(t, ctx, mgr, "write", path, "--from", source)

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read written file: %v", err)
	}
	if string(data) != "from source\n" {
		t.Fatalf("expected source content, got %q", string(data))
	}
}

func TestFileWriteCommandInsertAtSeek(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "out.txt", "abcdef")

	runFileCommand(t, ctx, mgr, "write", path, "--content", "XY", "--seek", "2", "--insert")

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "abXYcdef" {
		t.Fatalf("expected insertion at offset 2, got %q", string(data))
	}
}

func TestFileWriteCommandAppendWithNegativeSeek(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "out.txt", "abc")

	runFileCommand(t, ctx, mgr, "write", path, "--content", "Z", "--seek", "-1", "--insert")

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "abcZ" {
		t.Fatalf("expected append with seek -1, got %q", string(data))
	}
}

func TestFileAppendCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "out.txt", "one\n")

	runFileCommand(t, ctx, mgr, "append", path, "--content", "two\n")

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\ntwo\n" {
		t.Fatalf("expected appended content, got %q", string(data))
	}
}

func TestFileExistsCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	present := writeTempFile(t, dir, "a.md", "x")
	absent := filepath.Join(dir, "missing.md")

	out := runFileCommand(t, ctx, mgr, "exists", "a="+present, "b="+absent, "--format", "json")

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

	err := runFile(ctx, mgr, []string{"exists", "no-equals-sign"})
	if err == nil {
		t.Fatal("expected a malformed pair error")
	}
	if !strings.Contains(err.Error(), "name=path") {
		t.Fatalf("expected name=path guidance, got %v", err)
	}
}

func TestFileMkdirsCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	target := filepath.Join(dir, "a", "b", "c")

	out := runFileCommand(t, ctx, mgr, "mkdirs", target)
	if strings.TrimSpace(out) != "OK" {
		t.Fatalf("expected OK, got %q", out)
	}
	info, err := os.Stat(target)
	if err != nil || !info.IsDir() {
		t.Fatalf("expected directory %s to exist: %v", target, err)
	}
}

func TestFileMkdirsCommandRejectsRelativePath(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)

	err := runFile(ctx, mgr, []string{"mkdirs", "relative/dir"})
	if err == nil {
		t.Fatal("expected a relative path rejection")
	}
	if !strings.Contains(err.Error(), "absolute") {
		t.Fatalf("expected absolute path guidance, got %v", err)
	}
}

func TestFileListDirsCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	writeTempFile(t, dir, "b.md", "x")
	writeTempFile(t, dir, "a.md", "x")

	out := runFileCommand(t, ctx, mgr, "list-dirs", dir, "--format", "json")

	var parsed map[string][]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	entries := parsed[dir]
	if len(entries) != 2 || entries[0] != "a.md" || entries[1] != "b.md" {
		t.Fatalf("expected sorted entries, got %v", entries)
	}
}

func TestFileListDirsCommandRecordsErrors(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	missing := filepath.Join(dir, "missing")

	out := runFileCommand(t, ctx, mgr, "list-dirs", missing, "--format", "json")

	var parsed map[string][]string
	if err := json.Unmarshal([]byte(out), &parsed); err != nil {
		t.Fatalf("expected JSON output, got %q: %v", out, err)
	}
	entries := parsed[missing]
	if len(entries) != 1 || !strings.HasPrefix(entries[0], "Error:") {
		t.Fatalf("expected an error entry, got %v", entries)
	}
}

func TestFileSizeCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "a.md", "12345")

	out := runFileCommand(t, ctx, mgr, "size", path)
	if strings.TrimSpace(out) != "5" {
		t.Fatalf("expected size 5, got %q", out)
	}
}

func TestFileOverwriteLinesCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "one\ntwo\nthree\n")

	out := runFileCommand(t, ctx, mgr, "overwrite-lines", path, "2", "--content", "TWO\n")
	if !strings.Contains(out, "You CANNOT call continuously") {
		t.Fatalf("expected the overwrite warning, got %q", out)
	}
	if !strings.Contains(out, "-two") || !strings.Contains(out, "+TWO") {
		t.Fatalf("expected a unified diff, got %q", out)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\nTWO\nthree\n" {
		t.Fatalf("expected line 2 replaced, got %q", string(data))
	}
}

func TestFileOverwriteLinesCommandThroughEnd(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "one\ntwo\nthree\n")

	runFileCommand(t, ctx, mgr, "overwrite-lines", path, "2", "--end", "-1", "--content", "tail\n")

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\ntail\n" {
		t.Fatalf("expected replacement through the end, got %q", string(data))
	}
}

func TestFileOverwriteLinesCommandDeletesWithEmptyContent(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "one\ntwo\nthree\n")

	runFileCommand(t, ctx, mgr, "overwrite-lines", path, "2")

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\nthree\n" {
		t.Fatalf("expected line 2 deleted, got %q", string(data))
	}
}

func TestFileOverwriteLinesCommandRejectsBadRange(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "one\n")

	err := runFile(ctx, mgr, []string{"overwrite-lines", path, "5", "--content", "x"})
	if err == nil {
		t.Fatal("expected a range error")
	}
	if !strings.Contains(err.Error(), "exceeds file length") {
		t.Fatalf("expected an exceeds-length message, got %v", err)
	}
}

func TestFileInsertCommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "one\ntwo\n")

	out := runFileCommand(t, ctx, mgr, "insert", path, "1", "--content", "inserted\n")
	if !strings.Contains(out, "+inserted") {
		t.Fatalf("expected a diff with the inserted line, got %q", out)
	}

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\ninserted\ntwo\n" {
		t.Fatalf("expected insertion after line 1, got %q", string(data))
	}
}

func TestFileInsertCommandBefore(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "one\ntwo\n")

	runFileCommand(t, ctx, mgr, "insert", path, "2", "--content", "before-two\n", "--before")

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\nbefore-two\ntwo\n" {
		t.Fatalf("expected insertion before line 2, got %q", string(data))
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
}

func TestFileGroupRejectsUnknownSubcommand(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)

	err := runFile(ctx, mgr, []string{"nope"})
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
	dir := t.TempDir()
	path := filepath.Join(dir, "out.txt")

	withStdin(t, "piped content\n", func() {
		runFileCommand(t, ctx, mgr, "write", path)
	})

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read written file: %v", err)
	}
	if string(data) != "piped content\n" {
		t.Fatalf("expected piped content, got %q", string(data))
	}
}

func TestFileAppendCommandFromStdinWithoutFromFlag(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "out.txt", "one\n")

	withStdin(t, "two\n", func() {
		runFileCommand(t, ctx, mgr, "append", path)
	})

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\ntwo\n" {
		t.Fatalf("expected appended stdin content, got %q", string(data))
	}
}

func TestFileOverwriteLinesCommandFromStdinWithoutFromFlag(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "one\ntwo\nthree\n")

	withStdin(t, "TWO\n", func() {
		runFileCommand(t, ctx, mgr, "overwrite-lines", path, "2")
	})

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\nTWO\nthree\n" {
		t.Fatalf("expected stdin replacement, got %q", string(data))
	}
}

func TestFileInsertCommandFromStdinWithoutFromFlag(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "note.md", "one\ntwo\n")

	withStdin(t, "inserted\n", func() {
		runFileCommand(t, ctx, mgr, "insert", path, "1")
	})

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "one\ninserted\ntwo\n" {
		t.Fatalf("expected stdin insertion, got %q", string(data))
	}
}

func TestFileWriteCommandExplicitEmptyContentBeatsStdin(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := writeTempFile(t, dir, "out.txt", "existing\n")

	withStdin(t, "should be ignored\n", func() {
		runFileCommand(t, ctx, mgr, "write", path, "--content", "")
	})

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "" {
		t.Fatalf("expected explicit empty content to win over stdin, got %q", string(data))
	}
}

func TestFileWriteCommandFromDashReadsStdin(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	path := filepath.Join(dir, "out.txt")

	withStdin(t, "dash content\n", func() {
		runFileCommand(t, ctx, mgr, "write", path, "--from", "-")
	})

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read written file: %v", err)
	}
	if string(data) != "dash content\n" {
		t.Fatalf("expected stdin content via --from -, got %q", string(data))
	}
}

// TestFileWriteCommandFromFileBeatsContent locks the documented precedence:
// --from wins over --content so a caller can pass a file without quoting text.
func TestFileWriteCommandFromFileBeatsContent(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	dir := t.TempDir()
	src := filepath.Join(dir, "src.txt")
	if err := os.WriteFile(src, []byte("from-file\n"), 0o644); err != nil {
		t.Fatalf("write source: %v", err)
	}
	path := filepath.Join(dir, "out.txt")

	runFileCommand(t, ctx, mgr, "write", path, "--content", "inline", "--from", src)

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read written file: %v", err)
	}
	if string(data) != "from-file\n" {
		t.Fatalf("expected --from to win over --content, got %q", string(data))
	}
}
