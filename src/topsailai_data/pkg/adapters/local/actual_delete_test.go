package local

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// deleteFixture builds an object directory containing the given files and
// returns the adapter, the context, and the object reference.
func deleteFixture(t *testing.T, files map[string]string) (*actualDataAdapter, context.Context, string) {
	t.Helper()
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatalf("init adapter: %v", err)
	}

	dir := filepath.Join(root, "object", "2026", "1111", "1200", "obj")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("mkdir object: %v", err)
	}
	for name, content := range files {
		path := filepath.Join(dir, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatalf("mkdir parent of %s: %v", name, err)
		}
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			t.Fatalf("write %s: %v", name, err)
		}
	}
	return adapter, ctx, actualFixtureRef(t, root, dir)
}

// TestDeleteFileRemovesNestedFile proves a nested payload file is removed.
func TestDeleteFileRemovesNestedFile(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{
		"obj.md":      "marker",
		"notes/a.md":  "note body",
		"notes/b.txt": "other",
	})

	if err := adapter.DeleteFile(ctx, ref, "notes/a.md"); err != nil {
		t.Fatalf("delete file: %v", err)
	}
	if _, err := adapter.StatFile(ctx, ref, "notes/a.md"); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected the file to be gone, got %v", err)
	}
	if _, err := adapter.StatFile(ctx, ref, "notes/b.txt"); err != nil {
		t.Fatalf("expected the sibling to survive, got %v", err)
	}
}

// TestDeleteFileRemovesEmptyParents proves a parent folder that becomes empty
// is removed, while the object folder itself is kept.
func TestDeleteFileRemovesEmptyParents(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{
		"obj.md":     "marker",
		"notes/a.md": "note body",
	})

	if err := adapter.DeleteFile(ctx, ref, "notes/a.md"); err != nil {
		t.Fatalf("delete file: %v", err)
	}

	layout, err := NewStoreLayout(adapter.root)
	if err != nil {
		t.Fatalf("layout: %v", err)
	}
	objectDir, err := layout.ResolveObjectRef(ref)
	if err != nil {
		t.Fatalf("resolve ref: %v", err)
	}
	if _, err := os.Stat(filepath.Join(objectDir, "notes")); !os.IsNotExist(err) {
		t.Fatalf("expected the empty parent to be removed, got %v", err)
	}
	if _, err := os.Stat(objectDir); err != nil {
		t.Fatalf("expected the object folder to survive, got %v", err)
	}
	if _, err := os.Stat(filepath.Join(objectDir, "obj.md")); err != nil {
		t.Fatalf("expected the boundary file to survive, got %v", err)
	}
}

// TestDeleteFileKeepsNonEmptyParents proves a parent folder that still holds
// another file is retained.
func TestDeleteFileKeepsNonEmptyParents(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{
		"obj.md":      "marker",
		"notes/a.md":  "note body",
		"notes/b.txt": "other",
	})

	if err := adapter.DeleteFile(ctx, ref, "notes/a.md"); err != nil {
		t.Fatalf("delete file: %v", err)
	}

	layout, err := NewStoreLayout(adapter.root)
	if err != nil {
		t.Fatalf("layout: %v", err)
	}
	objectDir, err := layout.ResolveObjectRef(ref)
	if err != nil {
		t.Fatalf("resolve ref: %v", err)
	}
	if _, err := os.Stat(filepath.Join(objectDir, "notes")); err != nil {
		t.Fatalf("expected the non-empty parent to survive, got %v", err)
	}
}

// TestDeleteFileRefusesBoundaryMarkdown proves the mandatory object Markdown at
// the object root cannot be removed, because it marks the payload boundary.
func TestDeleteFileRefusesBoundaryMarkdown(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{"obj.md": "marker"})

	err := adapter.DeleteFile(ctx, ref, "obj.md")
	if err == nil {
		t.Fatal("expected the boundary Markdown to be refused")
	}
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument, got %v", err)
	}
	if _, statErr := adapter.StatFile(ctx, ref, "obj.md"); statErr != nil {
		t.Fatalf("expected the boundary file to survive, got %v", statErr)
	}
}

// TestDeleteFileAllowsNestedSameNameMarkdown proves only the root boundary file
// is protected; a nested file with the same name is ordinary actual data.
func TestDeleteFileAllowsNestedSameNameMarkdown(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{
		"obj.md":     "marker",
		"sub/obj.md": "nested copy",
	})

	if err := adapter.DeleteFile(ctx, ref, "sub/obj.md"); err != nil {
		t.Fatalf("delete nested same-name file: %v", err)
	}
	if _, err := adapter.StatFile(ctx, ref, "sub/obj.md"); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected the nested file to be gone, got %v", err)
	}
	if _, err := adapter.StatFile(ctx, ref, "obj.md"); err != nil {
		t.Fatalf("expected the boundary file to survive, got %v", err)
	}
}

// TestDeleteFileRefusesFolder proves a folder is refused, so this operation
// never removes more than one file.
func TestDeleteFileRefusesFolder(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{
		"obj.md":     "marker",
		"notes/a.md": "note body",
	})

	err := adapter.DeleteFile(ctx, ref, "notes")
	if err == nil {
		t.Fatal("expected a folder rejection")
	}
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument, got %v", err)
	}
	if _, statErr := adapter.StatFile(ctx, ref, "notes/a.md"); statErr != nil {
		t.Fatalf("expected the folder content to survive, got %v", statErr)
	}
}

// TestDeleteFileReportsMissingFile proves an absent file is reported as
// ErrObjectNotFound, matching the read and stat operations.
func TestDeleteFileReportsMissingFile(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{"obj.md": "marker"})

	err := adapter.DeleteFile(ctx, ref, "nope.md")
	if err == nil {
		t.Fatal("expected a missing file error")
	}
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

// TestDeleteFileRejectsReservedTempName proves the reserved temporary
// replacement namespace stays rejected, so a caller cannot remove an internal
// file that a concurrent write may be publishing.
func TestDeleteFileRejectsReservedTempName(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{"obj.md": "marker"})

	err := adapter.DeleteFile(ctx, ref, writeTempPrefix+"abc")
	if err == nil {
		t.Fatal("expected the reserved temporary name to be rejected")
	}
	if !errors.Is(err, apperrors.ErrInvalidName) {
		t.Fatalf("expected ErrInvalidName, got %v", err)
	}
}

// TestDeleteFileRejectsTraversal proves a filename that climbs out of the
// object directory is rejected.
func TestDeleteFileRejectsTraversal(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{"obj.md": "marker"})

	err := adapter.DeleteFile(ctx, ref, "../outside.md")
	if err == nil {
		t.Fatal("expected a traversal rejection")
	}
	if !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("expected ErrInvalidPath, got %v", err)
	}
}

// TestDeleteFileHonoursCancelledContext proves a cancelled context stops the
// operation before any file is touched.
func TestDeleteFileHonoursCancelledContext(t *testing.T) {
	adapter, ctx, ref := deleteFixture(t, map[string]string{
		"obj.md":     "marker",
		"notes/a.md": "note body",
	})
	cancelled, cancel := context.WithCancel(ctx)
	cancel()

	err := adapter.DeleteFile(cancelled, ref, "notes/a.md")
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("expected context.Canceled, got %v", err)
	}
	if _, statErr := adapter.StatFile(ctx, ref, "notes/a.md"); statErr != nil {
		t.Fatalf("expected the file to survive, got %v", statErr)
	}
}
