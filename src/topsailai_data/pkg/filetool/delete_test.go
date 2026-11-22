package filetool

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

// recordingFS forwards every operation to the operating-system file system but
// records DeleteFile calls, so a test can prove the entry point routes through
// the supplied file system instead of touching real paths directly.
type recordingFS struct {
	OSFS
	deleted []string
}

// DeleteFile records the path and reports success without touching the disk.
func (r *recordingFS) DeleteFile(path string) error {
	r.deleted = append(r.deleted, path)
	return nil
}

// TestDeleteFileRemovesFile proves an existing file is removed.
func TestDeleteFileRemovesFile(t *testing.T) {
	path := writeFixture(t, "note.md", "content")

	if err := DeleteFile(path); err != nil {
		t.Fatalf("delete file: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("expected the file to be gone, got %v", err)
	}
}

// TestDeleteFileRejectsEmptyPath proves an empty path is rejected before any
// file system access, so a caller cannot address an unspecified file.
func TestDeleteFileRejectsEmptyPath(t *testing.T) {
	err := DeleteFile("")
	if err == nil {
		t.Fatal("expected an empty path rejection")
	}
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected ErrInvalidParameter, got %v", err)
	}
}

// TestDeleteFileRejectsFolder proves a folder is refused, so this operation
// never removes a whole subtree.
func TestDeleteFileRejectsFolder(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "folder")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}

	err := DeleteFile(dir)
	if err == nil {
		t.Fatal("expected a folder rejection")
	}
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected ErrInvalidParameter, got %v", err)
	}
	if _, statErr := os.Stat(dir); statErr != nil {
		t.Fatalf("expected the folder to survive, got %v", statErr)
	}
}

// TestDeleteFileReportsMissingFile proves an absent file is reported as
// ErrFileNotFound so a caller can distinguish it from a failed removal.
func TestDeleteFileReportsMissingFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nope.md")

	err := DeleteFile(path)
	if err == nil {
		t.Fatal("expected a missing file error")
	}
	if !errors.Is(err, ErrFileNotFound) {
		t.Fatalf("expected ErrFileNotFound, got %v", err)
	}
}

// TestDeleteFileWithFSRoutesThroughSuppliedFS proves the entry point uses the
// supplied file system instead of the operating system.
func TestDeleteFileWithFSRoutesThroughSuppliedFS(t *testing.T) {
	fs := &recordingFS{}

	if err := DeleteFileWithFS("notes/a.md", fs); err != nil {
		t.Fatalf("delete file with fs: %v", err)
	}
	if len(fs.deleted) != 1 || fs.deleted[0] != "notes/a.md" {
		t.Fatalf("expected one recorded deletion, got %v", fs.deleted)
	}
}

// TestDeleteFileWithFSRejectsEmptyPath proves the empty-path guard also applies
// when a custom file system is supplied.
func TestDeleteFileWithFSRejectsEmptyPath(t *testing.T) {
	fs := &recordingFS{}

	err := DeleteFileWithFS("", fs)
	if err == nil {
		t.Fatal("expected an empty path rejection")
	}
	if !errors.Is(err, ErrInvalidParameter) {
		t.Fatalf("expected ErrInvalidParameter, got %v", err)
	}
	if len(fs.deleted) != 0 {
		t.Fatalf("expected no recorded deletion, got %v", fs.deleted)
	}
}
