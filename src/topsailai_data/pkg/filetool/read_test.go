package filetool

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// writeFixture creates a file with the given content and returns its path.
func writeFixture(t *testing.T, name, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write fixture: %v", err)
	}
	return path
}

func TestReadFileWholeContent(t *testing.T) {
	path := writeFixture(t, "note.md", "hello\nworld\n")

	got, err := ReadFile(path, ReadFileOptions{Size: -1})
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if got != "hello\nworld\n" {
		t.Fatalf("unexpected content %q", got)
	}
}

func TestReadFileSeekAndSize(t *testing.T) {
	path := writeFixture(t, "note.txt", "0123456789")

	got, err := ReadFile(path, ReadFileOptions{Seek: 2, Size: 3})
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if got != "234" {
		t.Fatalf("expected %q, got %q", "234", got)
	}

	got, err = ReadFile(path, ReadFileOptions{Seek: -3, Size: -1})
	if err != nil {
		t.Fatalf("read file from end: %v", err)
	}
	if got != "789" {
		t.Fatalf("expected %q, got %q", "789", got)
	}
}

func TestReadFileTruncatesUnknownExtension(t *testing.T) {
	content := strings.Repeat("a", 200)
	path := writeFixture(t, "blob.bin", content)

	got, err := ReadFile(path, ReadFileOptions{Size: -1, Options: Options{TruncateLimit: 50}})
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if got != strings.Repeat("a", 50)+TruncateSuffix {
		t.Fatalf("unexpected truncated content %q", got)
	}
}

func TestReadFileWhitelistedExtensionIsNotTruncated(t *testing.T) {
	content := strings.Repeat("b", 200)
	path := writeFixture(t, "code.go", content)

	got, err := ReadFile(path, ReadFileOptions{Size: -1, Options: Options{TruncateLimit: 50}})
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if got != content {
		t.Fatalf("expected full content, got %d bytes", len(got))
	}
}

func TestReadFileWhitelistOverrides(t *testing.T) {
	path := writeFixture(t, "blob.bin", strings.Repeat("c", 100))

	never, err := ReadFile(path, ReadFileOptions{Size: -1, Options: Options{TruncateLimit: 10, NoTruncateExtensions: []string{"*"}}})
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if never != strings.Repeat("c", 100) {
		t.Fatalf("expected no truncation with *, got %d bytes", len(never))
	}

	always, err := ReadFile(path, ReadFileOptions{Size: -1, Options: Options{TruncateLimit: 10, NoTruncateExtensions: []string{"!*"}}})
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if always != strings.Repeat("c", 10)+TruncateSuffix {
		t.Fatalf("expected truncation with !*, got %q", always)
	}
}

func TestReadFileRejectsEmptyPath(t *testing.T) {
	_, err := ReadFile("", ReadFileOptions{Size: -1})
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestReadFileMissingFile(t *testing.T) {
	_, err := ReadFile(filepath.Join(t.TempDir(), "absent.txt"), ReadFileOptions{Size: -1})
	if err == nil {
		t.Fatal("expected an error for a missing file")
	}
}

func TestReadFilesReturnsEveryEntry(t *testing.T) {
	first := writeFixture(t, "a.md", "alpha")
	second := writeFixture(t, "b.md", "beta")

	got, err := ReadFiles([]string{first, second}, ReadFileOptions{Size: -1})
	if err != nil {
		t.Fatalf("read files: %v", err)
	}
	if got[first] != "alpha" || got[second] != "beta" {
		t.Fatalf("unexpected map %v", got)
	}
}

func TestReadFilesRecordsFailure(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "absent.md")

	got, err := ReadFiles([]string{missing}, ReadFileOptions{Size: -1})
	if err != nil {
		t.Fatalf("read files: %v", err)
	}
	if !strings.HasPrefix(got[missing], "Error:") {
		t.Fatalf("expected an error entry, got %q", got[missing])
	}
}

func TestReadFileLinesRange(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\ntwo\nthree\nfour\n")

	got, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 2, EndNum: 3})
	if err != nil {
		t.Fatalf("read lines: %v", err)
	}
	if got != "2-two\n3-three" {
		t.Fatalf("unexpected output %q", got)
	}
}

func TestReadFileLinesZeroEndNumReadsOneLine(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\ntwo\nthree\n")

	got, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 2})
	if err != nil {
		t.Fatalf("read lines: %v", err)
	}
	if got != "2-two" {
		t.Fatalf("unexpected output %q", got)
	}
}

func TestReadFileLinesThroughEnd(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\ntwo\nthree\n")

	got, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 2, EndNum: -1})
	if err != nil {
		t.Fatalf("read lines: %v", err)
	}
	if got != "2-two\n3-three" {
		t.Fatalf("unexpected output %q", got)
	}
}

func TestReadFileLinesEmptyFile(t *testing.T) {
	path := writeFixture(t, "empty.txt", "")

	got, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 1, EndNum: -1})
	if err != nil {
		t.Fatalf("read lines: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty output, got %q", got)
	}
}

func TestReadFileLinesStartPastEnd(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\ntwo\n")

	got, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 9, EndNum: -1})
	if err != nil {
		t.Fatalf("read lines: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty output, got %q", got)
	}
}

func TestReadFileLinesInvalidRange(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\ntwo\n")

	_, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 3, EndNum: 2})
	if !errors.Is(err, ErrInvalidRange) {
		t.Fatalf("expected range error, got %v", err)
	}
}

func TestReadFileLinesRejectsOtherNegativeEnd(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\n")

	_, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 1, EndNum: -5})
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestReadFileAroundLineMarksTarget(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\ntwo\nthree\nfour\nfive\n")

	got, err := ReadFileAroundLine(path, ReadFileAroundLineOptions{LineNumber: 3, ContextNum: 1})
	if err != nil {
		t.Fatalf("read around line: %v", err)
	}
	want := "2-two\n3:three\n4-four"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestReadFileAroundLineClampsAtStart(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\ntwo\nthree\n")

	got, err := ReadFileAroundLine(path, ReadFileAroundLineOptions{LineNumber: 1, ContextNum: 2})
	if err != nil {
		t.Fatalf("read around line: %v", err)
	}
	want := "1:one\n2-two\n3-three"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestReadFileAroundLineOutOfRange(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\ntwo\n")

	_, err := ReadFileAroundLine(path, ReadFileAroundLineOptions{LineNumber: 9, ContextNum: 1})
	if !errors.Is(err, ErrInvalidRange) {
		t.Fatalf("expected range error, got %v", err)
	}
}

func TestReadFileAroundLineEmptyFile(t *testing.T) {
	path := writeFixture(t, "empty.txt", "")

	got, err := ReadFileAroundLine(path, ReadFileAroundLineOptions{LineNumber: 1, ContextNum: 1})
	if err != nil {
		t.Fatalf("read around line: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty output, got %q", got)
	}
}

func TestReadFileWithContextMarksMatches(t *testing.T) {
	path := writeFixture(t, "code.go", "package a\n\nfunc target() {\n\treturn\n}\n")

	got, err := ReadFileWithContext(path, ReadFileWithContextOptions{Pattern: "func target", ContextNum: 1})
	if err != nil {
		t.Fatalf("read with context: %v", err)
	}
	want := "2-\n3:func target() {\n4-\treturn"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestReadFileWithContextDeduplicatesOverlap(t *testing.T) {
	path := writeFixture(t, "code.go", "a\nmatch\nb\nmatch\nc\n")

	got, err := ReadFileWithContext(path, ReadFileWithContextOptions{Pattern: "match", ContextNum: 1})
	if err != nil {
		t.Fatalf("read with context: %v", err)
	}
	want := "1-a\n2:match\n3-b\n4:match\n5-c"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}

func TestReadFileWithContextCaseSensitivity(t *testing.T) {
	path := writeFixture(t, "code.go", "Alpha\nbeta\n")

	insensitive, err := ReadFileWithContext(path, ReadFileWithContextOptions{Pattern: "alpha"})
	if err != nil {
		t.Fatalf("read with context: %v", err)
	}
	if insensitive != "1:Alpha" {
		t.Fatalf("expected case-insensitive match, got %q", insensitive)
	}

	sensitive, err := ReadFileWithContext(path, ReadFileWithContextOptions{Pattern: "alpha", CaseSensitive: true})
	if err != nil {
		t.Fatalf("read with context: %v", err)
	}
	if sensitive != "" {
		t.Fatalf("expected no case-sensitive match, got %q", sensitive)
	}
}

func TestReadFileWithContextNoMatch(t *testing.T) {
	path := writeFixture(t, "code.go", "alpha\nbeta\n")

	got, err := ReadFileWithContext(path, ReadFileWithContextOptions{Pattern: "gamma"})
	if err != nil {
		t.Fatalf("read with context: %v", err)
	}
	if got != "" {
		t.Fatalf("expected empty output, got %q", got)
	}
}

func TestReadFileWithContextInvalidPattern(t *testing.T) {
	path := writeFixture(t, "code.go", "alpha\n")

	_, err := ReadFileWithContext(path, ReadFileWithContextOptions{Pattern: "("})
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestReadFileLinesHandlesCRLF(t *testing.T) {
	path := writeFixture(t, "lines.txt", "one\r\ntwo\r\n")

	got, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 1, EndNum: -1})
	if err != nil {
		t.Fatalf("read lines: %v", err)
	}
	if got != "1-one\n2-two" {
		t.Fatalf("expected CRLF stripped, got %q", got)
	}
}

func TestReadFileLinesDecodesLatin1(t *testing.T) {
	path := filepath.Join(t.TempDir(), "latin1.txt")
	if err := os.WriteFile(path, []byte{'c', 'a', 'f', 0xE9, '\n'}, 0o644); err != nil {
		t.Fatalf("write fixture: %v", err)
	}

	got, err := ReadFileLines(path, ReadFileLinesOptions{StartNum: 1, EndNum: -1})
	if err != nil {
		t.Fatalf("read lines: %v", err)
	}
	if !strings.Contains(got, "caf") {
		t.Fatalf("expected decoded content, got %q", got)
	}
}
