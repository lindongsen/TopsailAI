// Package cli tests object-scoped file command behaviour that the per-command
// tests do not cover.
//
// Every test here creates a real data object through the manager and then runs
// the "file" subcommands with --object, so the object-backed file system is
// exercised end to end instead of being mocked.
package cli

import (
	"archive/tar"
	"bytes"
	"context"
	"strings"
	"testing"

	"github.com/topsailai/topsailai_data/pkg/manager"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// createObjectWithFiles creates one active object whose actual data contains the
// given files, so object-scoped file commands have real content to work on.
func createObjectWithFiles(t *testing.T, ctx context.Context, mgr *manager.Manager, name string, files map[string]string) {
	t.Helper()

	var buf bytes.Buffer
	writer := tar.NewWriter(&buf)
	for path, content := range files {
		header := &tar.Header{
			Name: path,
			Mode: 0o644,
			Size: int64(len(content)),
		}
		if err := writer.WriteHeader(header); err != nil {
			t.Fatalf("write tar header %s: %v", path, err)
		}
		if _, err := writer.Write([]byte(content)); err != nil {
			t.Fatalf("write tar body %s: %v", path, err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatalf("close tar: %v", err)
	}

	if _, err := mgr.CreateObject(ctx, name, manager.CreateObjectOptions{
		Description: "test object " + name,
		Data:        &buf,
	}); err != nil {
		t.Fatalf("create object %s: %v", name, err)
	}
}

// readObjectFile returns the stored content of one file inside an object.
func readObjectFile(t *testing.T, ctx context.Context, mgr *manager.Manager, id, filename string) string {
	t.Helper()
	rc, err := mgr.ReadActualFile(ctx, models.ObjectID(id), filename)
	if err != nil {
		t.Fatalf("read %s from %s: %v", filename, id, err)
	}
	defer rc.Close()
	var buf bytes.Buffer
	if _, err := buf.ReadFrom(rc); err != nil {
		t.Fatalf("read body: %v", err)
	}
	return buf.String()
}

// TestFileCommandRejectsUnknownObject fails clearly instead of falling back to
// the operating-system file system.
func TestFileCommandRejectsUnknownObject(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)

	err := runFileCommandError(t, ctx, mgr, "read", "anything.md", "--object", "ghost")
	if err == nil {
		t.Fatal("expected an error for an unknown object")
	}
	if !strings.Contains(err.Error(), "object not found") {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestFileCommandRejectsPathEscape keeps a caller inside the object folder.
func TestFileCommandRejectsPathEscape(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})

	// A traversal path is normalised into the object, so it must not resolve to
	// a file outside the object. The read fails because the object has no such
	// file.
	err := runFileCommandError(t, ctx, mgr, "read", "../../etc/passwd", "--object", "demo")
	if err == nil {
		t.Fatal("expected an error for a traversal path")
	}
}

// TestFileCommandRejectsMetadataMarker proves a caller cannot bypass lifecycle
// management by editing a metadata marker through the file commands.
func TestFileCommandRejectsMetadataMarker(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})

	for _, marker := range []string{"demo.tags", "demo.lock", "demo.deleted", "demo.ceased", ".stat.json"} {
		err := runFileCommandError(t, ctx, mgr, "write", marker, "--content", "x", "--object", "demo")
		if err == nil {
			t.Fatalf("%s: expected a metadata marker rejection", marker)
		}
	}
}

// TestFileCommandRecordsStatistics verifies that object-scoped reads and writes
// update the usage statistics.
func TestFileCommandRecordsStatistics(t *testing.T) {
	mgr, ctx := setupFileManager(t, 0, nil)
	createObjectWithFiles(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "body",
	})

	before := objectStatOf(t, ctx, mgr, "demo")

	runFileCommand(t, ctx, mgr, "read", "notes.md", "--object", "demo")
	runFileCommand(t, ctx, mgr, "write", "notes.md", "--content", "changed", "--object", "demo")

	after := objectStatOf(t, ctx, mgr, "demo")
	if after.ReadCount <= before.ReadCount {
		t.Fatalf("read count did not increase: before=%d after=%d", before.ReadCount, after.ReadCount)
	}
	if after.WriteCount <= before.WriteCount {
		t.Fatalf("write count did not increase: before=%d after=%d", before.WriteCount, after.WriteCount)
	}
}

// objectStatOf loads the usage statistics of one object.
func objectStatOf(t *testing.T, ctx context.Context, mgr *manager.Manager, id string) *models.ObjectStat {
	t.Helper()
	obj, err := mgr.GetObject(ctx, models.ObjectID(id), false)
	if err != nil {
		t.Fatalf("get object %s: %v", id, err)
	}
	stat, err := readObjectStat(obj)
	if err != nil {
		t.Fatalf("read stat for %s: %v", id, err)
	}
	return stat
}

// TestFileCommandRequiresManager rejects --object without a manager.
func TestFileCommandRequiresManager(t *testing.T) {
	ctx := context.Background()
	err := runFile(ctx, nil, []string{"read", "anything.md", "--object", "demo"})
	if err == nil {
		t.Fatal("expected an error when the manager is missing")
	}
	if !strings.Contains(err.Error(), "requires a configured manager") {
		t.Fatalf("unexpected error: %v", err)
	}
}
