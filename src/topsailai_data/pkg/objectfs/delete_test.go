package objectfs

import (
	"errors"
	"testing"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestDeleteFileRemovesFile proves a file inside an object is removed.
func TestDeleteFileRemovesFile(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "marker",
		"notes.md": "note body",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.DeleteFile("notes.md"); err != nil {
		t.Fatalf("delete file: %v", err)
	}
	if _, err := fs.ReadFile("notes.md"); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected the file to be gone, got %v", err)
	}
	if _, err := fs.ReadFile("demo.md"); err != nil {
		t.Fatalf("expected the boundary file to survive, got %v", err)
	}
}

// TestDeleteFileRecordsWriteStatistic proves the removal behaves like a write,
// so the object's write counter advances.
func TestDeleteFileRecordsWriteStatistic(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "marker",
		"notes.md": "note body",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatalf("layout: %v", err)
	}
	dir, err := layout.ObjectMetaPath("demo")
	if err != nil {
		t.Fatalf("meta path: %v", err)
	}
	before, err := local.ReadStat(dir)
	if err != nil {
		t.Fatalf("read stat before: %v", err)
	}

	if err := fs.DeleteFile("notes.md"); err != nil {
		t.Fatalf("delete file: %v", err)
	}

	after, err := local.ReadStat(dir)
	if err != nil {
		t.Fatalf("read stat after: %v", err)
	}
	if after.WriteCount != before.WriteCount+1 {
		t.Fatalf("expected the write count to advance from %d, got %d", before.WriteCount, after.WriteCount)
	}
}

// TestDeleteFileAcceptsLeadingSlash proves an absolute-looking path is treated
// as object-relative, matching the other file operations.
func TestDeleteFileAcceptsLeadingSlash(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "marker",
		"notes.md": "note body",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.DeleteFile("/notes.md"); err != nil {
		t.Fatalf("delete file with leading slash: %v", err)
	}
	if _, err := fs.ReadFile("notes.md"); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected the file to be gone, got %v", err)
	}
}

// TestDeleteFileRefusesObjectRoot proves the object root cannot be addressed as
// a file to delete.
func TestDeleteFileRefusesObjectRoot(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	for _, path := range []string{"", ".", "/"} {
		if err := fs.DeleteFile(path); err == nil {
			t.Fatalf("expected the object root %q to be refused", path)
		}
	}
	if _, err := fs.ReadFile("demo.md"); err != nil {
		t.Fatalf("expected the object to survive, got %v", err)
	}
}

// TestDeleteFileRefusesBoundaryMarkdown proves the mandatory object Markdown
// cannot be removed, because it marks the payload boundary.
func TestDeleteFileRefusesBoundaryMarkdown(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	err := fs.DeleteFile("demo.md")
	if err == nil {
		t.Fatal("expected the boundary Markdown to be refused")
	}
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument, got %v", err)
	}
	if _, readErr := fs.ReadFile("demo.md"); readErr != nil {
		t.Fatalf("expected the boundary file to survive, got %v", readErr)
	}
}

// TestDeleteFileReportsMissingFile proves an absent file is reported as
// ErrObjectNotFound.
func TestDeleteFileReportsMissingFile(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	err := fs.DeleteFile("nope.md")
	if err == nil {
		t.Fatal("expected a missing file error")
	}
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

// TestDeleteFileRefusesFolder proves a folder is refused, so this operation
// never removes a whole subtree.
func TestDeleteFileRefusesFolder(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":     "marker",
		"notes/a.md":  "note body",
		"notes/b.txt": "other",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	err := fs.DeleteFile("notes")
	if err == nil {
		t.Fatal("expected a folder rejection")
	}
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument, got %v", err)
	}
	if _, readErr := fs.ReadFile("notes/a.md"); readErr != nil {
		t.Fatalf("expected the folder content to survive, got %v", readErr)
	}
}

// TestDeleteFileRejectsUnknownObject proves an unknown object id fails before
// any file is touched.
func TestDeleteFileRejectsUnknownObject(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "marker"})
	fs := newObjectFS(t, ctx, mgr, "nope")

	err := fs.DeleteFile("demo.md")
	if err == nil {
		t.Fatal("expected an unknown object error")
	}
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}
