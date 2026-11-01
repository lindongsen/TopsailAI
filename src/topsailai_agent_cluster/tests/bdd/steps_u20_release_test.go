package bdd

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestWriteReleaseWithoutHoldDirDoesNotCreateFile verifies unconfigured phases are side-effect free.
func TestWriteReleaseWithoutHoldDirDoesNotCreateFile(t *testing.T) {
	dir := t.TempDir()
	t.Chdir(dir)
	if err := writeRelease("", "finished"); err != nil {
		t.Fatalf("writeRelease returned an error without a hold directory: %v", err)
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("read temporary directory: %v", err)
	}
	if len(entries) != 0 {
		t.Fatalf("writeRelease created files without a hold directory: %v", entries)
	}
}

// TestWriteReleaseCreatesFileInHoldDir verifies release files stay in the configured directory.
func TestWriteReleaseCreatesFileInHoldDir(t *testing.T) {
	dir := t.TempDir()
	if err := writeRelease(dir, "finished"); err != nil {
		t.Fatalf("writeRelease returned an error: %v", err)
	}
	path := filepath.Join(dir, "release-finished")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read release file: %v", err)
	}
	if string(data) != "release\n" {
		t.Fatalf("release file content = %q, want %q", data, "release\\n")
	}
}

// TestWriteReleaseReportsWriteFailure verifies release write failures are returned with context.
func TestWriteReleaseReportsWriteFailure(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "missing")
	err := writeRelease(dir, "finished")
	if err == nil {
		t.Fatal("writeRelease unexpectedly succeeded for an unavailable directory")
	}
	if !strings.Contains(err.Error(), "write release file") {
		t.Fatalf("error = %q, want release-write context", err)
	}
}
