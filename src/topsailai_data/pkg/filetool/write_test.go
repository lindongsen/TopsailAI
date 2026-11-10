package filetool

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestWriteFileReplacesWholeFile(t *testing.T) {
	path := writeFixture(t, "note.txt", "old content")

	if err := WriteFile(path, "new content", WriteFileOptions{}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(got) != "new content" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestWriteFileCreatesParentFolders(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "deeper", "note.txt")

	if err := WriteFile(path, "content", WriteFileOptions{}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("expected file to exist: %v", err)
	}
}

func TestWriteFileInsertAtPosition(t *testing.T) {
	path := writeFixture(t, "note.txt", "abcdef")

	if err := WriteFile(path, "XY", WriteFileOptions{Seek: 2, Insert: true}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "abXYcdef" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestWriteFileInsertAppendsWithNegativeSeek(t *testing.T) {
	path := writeFixture(t, "note.txt", "abcdef")

	if err := WriteFile(path, "XY", WriteFileOptions{Seek: -1, Insert: true}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "abcdefXY" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestWriteFileInsertClampsSeek(t *testing.T) {
	path := writeFixture(t, "note.txt", "abc")

	if err := WriteFile(path, "Z", WriteFileOptions{Seek: 99, Insert: true}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "abcZ" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestWriteFileOverwriteFromPosition(t *testing.T) {
	path := writeFixture(t, "note.txt", "abcdef")

	if err := WriteFile(path, "XY", WriteFileOptions{Seek: 2}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "abXYef" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestWriteFileOverwriteExtendsFile(t *testing.T) {
	path := writeFixture(t, "note.txt", "abc")

	if err := WriteFile(path, "LONGER", WriteFileOptions{Seek: 1}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "aLONGER" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestWriteFileOverwriteNegativeSeek(t *testing.T) {
	path := writeFixture(t, "note.txt", "abcdef")

	if err := WriteFile(path, "XY", WriteFileOptions{Seek: -2}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "abcdXY" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestWriteFileCreatesMissingFileWithSeek(t *testing.T) {
	path := filepath.Join(t.TempDir(), "absent.txt")

	if err := WriteFile(path, "content", WriteFileOptions{Seek: 5}); err != nil {
		t.Fatalf("write file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "content" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestWriteFileRejectsEmptyPath(t *testing.T) {
	err := WriteFile("", "content", WriteFileOptions{})
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestAppendFileAddsContent(t *testing.T) {
	path := writeFixture(t, "note.txt", "first")

	if err := AppendFile(path, "-second"); err != nil {
		t.Fatalf("append file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "first-second" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestAppendFileCreatesFileAndFolders(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "note.txt")

	if err := AppendFile(path, "content"); err != nil {
		t.Fatalf("append file: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "content" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestOverwriteLinesReplacesRange(t *testing.T) {
	path := writeFixture(t, "code.go", "one\ntwo\nthree\nfour\n")

	diff, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 2, EndNum: 3, Content: "TWO\nTHREE\n"})
	if err != nil {
		t.Fatalf("overwrite lines: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "one\nTWO\nTHREE\nfour\n" {
		t.Fatalf("unexpected content %q", string(got))
	}
	if !strings.Contains(diff, "TWO") {
		t.Fatalf("expected diff to mention new content, got %q", diff)
	}
	if !strings.HasPrefix(diff, OverwriteWarning) {
		t.Fatalf("expected warning prefix, got %q", diff)
	}
}

func TestOverwriteLinesZeroEndNumReplacesOneLine(t *testing.T) {
	path := writeFixture(t, "code.go", "one\ntwo\nthree\n")

	if _, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 2, Content: "TWO\n"}); err != nil {
		t.Fatalf("overwrite lines: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "one\nTWO\nthree\n" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestOverwriteLinesThroughEnd(t *testing.T) {
	path := writeFixture(t, "code.go", "one\ntwo\nthree\n")

	if _, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 2, EndNum: -1, Content: "rest\n"}); err != nil {
		t.Fatalf("overwrite lines: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "one\nrest\n" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestOverwriteLinesEmptyContentDeletesLines(t *testing.T) {
	path := writeFixture(t, "code.go", "one\ntwo\nthree\n")

	if _, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 2, Content: ""}); err != nil {
		t.Fatalf("overwrite lines: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "one\nthree\n" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestOverwriteLinesPreservesMissingTrailingNewline(t *testing.T) {
	path := writeFixture(t, "code.go", "one\ntwo")

	if _, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 2, Content: "TWO"}); err != nil {
		t.Fatalf("overwrite lines: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "one\nTWO" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestOverwriteLinesRejectsStartPastEnd(t *testing.T) {
	path := writeFixture(t, "code.go", "one\n")

	_, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 9, Content: "x"})
	if !errors.Is(err, ErrInvalidRange) {
		t.Fatalf("expected range error, got %v", err)
	}
}

func TestOverwriteLinesRejectsOtherNegativeEnd(t *testing.T) {
	path := writeFixture(t, "code.go", "one\n")

	_, err := OverwriteLines(path, OverwriteLinesOptions{StartNum: 1, EndNum: -3, Content: "x"})
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestOverwriteLinesMissingFile(t *testing.T) {
	_, err := OverwriteLines(filepath.Join(t.TempDir(), "absent.go"), OverwriteLinesOptions{StartNum: 1, Content: "x"})
	if err == nil {
		t.Fatal("expected an error for a missing file")
	}
}

func TestInsertContentAfterLine(t *testing.T) {
	path := writeFixture(t, "code.go", "one\ntwo\n")

	diff, err := InsertContent(path, InsertContentOptions{LineNum: 1, Content: "inserted"})
	if err != nil {
		t.Fatalf("insert content: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "one\ninserted\ntwo\n" {
		t.Fatalf("unexpected content %q", string(got))
	}
	if !strings.Contains(diff, "inserted") {
		t.Fatalf("expected diff to mention inserted content, got %q", diff)
	}
}

func TestInsertContentBeforeLine(t *testing.T) {
	path := writeFixture(t, "code.go", "one\ntwo\n")

	if _, err := InsertContent(path, InsertContentOptions{LineNum: 2, Before: true, Content: "inserted"}); err != nil {
		t.Fatalf("insert content: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "one\ninserted\ntwo\n" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestInsertContentAppendsAfterLastLine(t *testing.T) {
	path := writeFixture(t, "code.go", "one\n")

	if _, err := InsertContent(path, InsertContentOptions{LineNum: 1, Content: "last"}); err != nil {
		t.Fatalf("insert content: %v", err)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "one\nlast\n" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestInsertContentEmptyFileReturnsEmptyDiff(t *testing.T) {
	path := writeFixture(t, "code.go", "")

	diff, err := InsertContent(path, InsertContentOptions{LineNum: 1, Content: "first"})
	if err != nil {
		t.Fatalf("insert content: %v", err)
	}
	if diff != "" {
		t.Fatalf("expected empty diff, got %q", diff)
	}
	got, _ := os.ReadFile(path)
	if string(got) != "first\n" {
		t.Fatalf("unexpected content %q", string(got))
	}
}

func TestInsertContentRejectsInvalidLineNum(t *testing.T) {
	path := writeFixture(t, "code.go", "one\n")

	_, err := InsertContent(path, InsertContentOptions{LineNum: 0, Content: "x"})
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestCheckFilesExisting(t *testing.T) {
	existing := writeFixture(t, "present.txt", "x")
	missing := filepath.Join(t.TempDir(), "absent.txt")

	got, err := CheckFilesExisting(map[string]string{"present": existing, "absent": missing})
	if err != nil {
		t.Fatalf("check files: %v", err)
	}
	if !got["present"] {
		t.Fatal("expected present to be true")
	}
	if got["absent"] {
		t.Fatal("expected absent to be false")
	}
}

func TestCheckFilesExistingRejectsEmptyMap(t *testing.T) {
	_, err := CheckFilesExisting(nil)
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestListDirReturnsSortedNames(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"b.txt", "a.txt"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte("x"), 0o644); err != nil {
			t.Fatalf("write fixture: %v", err)
		}
	}

	got, err := ListDir(dir)
	if err != nil {
		t.Fatalf("list dir: %v", err)
	}
	if len(got) != 2 || got[0] != "a.txt" || got[1] != "b.txt" {
		t.Fatalf("unexpected entries %v", got)
	}
}

func TestListDirsReturnsMap(t *testing.T) {
	first := t.TempDir()
	second := t.TempDir()
	if err := os.WriteFile(filepath.Join(first, "only.txt"), []byte("x"), 0o644); err != nil {
		t.Fatalf("write fixture: %v", err)
	}

	got, err := ListDirs([]string{first, second})
	if err != nil {
		t.Fatalf("list dirs: %v", err)
	}
	if len(got[first]) != 1 || got[first][0] != "only.txt" {
		t.Fatalf("unexpected entries for first %v", got[first])
	}
	if len(got[second]) != 0 {
		t.Fatalf("expected empty entries for second, got %v", got[second])
	}
}

func TestListDirsRecordsFailure(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "absent")

	got, err := ListDirs([]string{missing})
	if err != nil {
		t.Fatalf("list dirs: %v", err)
	}
	if len(got[missing]) != 1 || !strings.HasPrefix(got[missing][0], "Error:") {
		t.Fatalf("expected an error entry, got %v", got[missing])
	}
}

func TestFileSize(t *testing.T) {
	path := writeFixture(t, "note.txt", "12345")

	got, err := FileSize(path)
	if err != nil {
		t.Fatalf("file size: %v", err)
	}
	if got != 5 {
		t.Fatalf("expected 5, got %d", got)
	}
}

func TestFileSizeMissingFile(t *testing.T) {
	_, err := FileSize(filepath.Join(t.TempDir(), "absent.txt"))
	if err == nil {
		t.Fatal("expected an error for a missing file")
	}
}

func TestMakeDirsCreatesFolders(t *testing.T) {
	base := t.TempDir()
	first := filepath.Join(base, "one")
	second := filepath.Join(base, "two", "nested")

	if err := MakeDirs([]string{first, second}); err != nil {
		t.Fatalf("make dirs: %v", err)
	}
	for _, dir := range []string{first, second} {
		info, err := os.Stat(dir)
		if err != nil || !info.IsDir() {
			t.Fatalf("expected directory %s: %v", dir, err)
		}
	}
}

func TestMakeDirsRejectsRelativePath(t *testing.T) {
	err := MakeDirs([]string{"relative/path"})
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestMakeDirsRejectsEmptyList(t *testing.T) {
	err := MakeDirs(nil)
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected parameter error, got %v", err)
	}
}

func TestExists(t *testing.T) {
	path := writeFixture(t, "note.txt", "x")

	if !Exists(path) {
		t.Fatal("expected existing file to be reported")
	}
	if Exists(filepath.Join(t.TempDir(), "absent.txt")) {
		t.Fatal("expected missing file to be reported absent")
	}
	if Exists("") {
		t.Fatal("expected empty path to be reported absent")
	}
}
