package manager

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// writePayloadFile writes one extra payload file into an object so a delete
// test has something to remove.
func writePayloadFile(t *testing.T, mgr *Manager, ctx context.Context, id models.ObjectID, name, content string) {
	t.Helper()
	if err := mgr.WriteActualFile(ctx, id, name, strings.NewReader(content)); err != nil {
		t.Fatalf("write payload file %s: %v", name, err)
	}
}

// TestDeleteActualFileRemovesFileAndRecordsWrite proves a successful removal
// removes the file, advances the object timestamp, and records one write.
func TestDeleteActualFileRemovesFileAndRecordsWrite(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = true
	ctx := context.Background()
	obj := createTestObject(t, mgr, "delete-probe")
	writePayloadFile(t, mgr, ctx, obj.ID, "notes/a.md", "note body")

	before, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get object before delete: %v", err)
	}

	// The timestamp comparison needs a measurable gap on coarse clocks.
	time.Sleep(2 * time.Millisecond)

	if err := mgr.DeleteActualFile(ctx, obj.ID, "notes/a.md"); err != nil {
		t.Fatalf("delete actual file: %v", err)
	}

	if _, err := mgr.StatActualFile(ctx, obj.ID, "notes/a.md"); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected the file to be gone, got %v", err)
	}

	after, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get object after delete: %v", err)
	}
	if !after.UpdatedAt.After(before.UpdatedAt) {
		t.Fatalf("expected UpdatedAt to advance: before %v after %v", before.UpdatedAt, after.UpdatedAt)
	}

	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatalf("layout: %v", err)
	}
	dir, err := layout.ObjectMetaPath(obj.ID)
	if err != nil {
		t.Fatalf("meta path: %v", err)
	}
	stat, err := local.ReadStat(dir)
	if err != nil {
		t.Fatalf("read stat: %v", err)
	}
	// One write for creation, one for the extra payload file, one for the delete.
	if stat.WriteCount != 3 {
		t.Fatalf("expected 3 writes, got %d", stat.WriteCount)
	}
}

// TestDeleteActualFileRejectsNonActiveObject proves a deleted object cannot
// have its payload edited, matching every other write operation.
func TestDeleteActualFileRejectsNonActiveObject(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()
	obj := createTestObject(t, mgr, "delete-inactive")
	writePayloadFile(t, mgr, ctx, obj.ID, "notes/a.md", "note body")

	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("soft delete: %v", err)
	}

	err := mgr.DeleteActualFile(ctx, obj.ID, "notes/a.md")
	if err == nil {
		t.Fatal("expected a non-active rejection")
	}
	if !errors.Is(err, apperrors.ErrObjectNotActive) {
		t.Fatalf("expected ErrObjectNotActive, got %v", err)
	}
}

// TestDeleteActualFileReportsMissingFile proves an absent file is reported as
// ErrObjectNotFound.
func TestDeleteActualFileReportsMissingFile(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()
	obj := createTestObject(t, mgr, "delete-missing")

	err := mgr.DeleteActualFile(ctx, obj.ID, "nope.md")
	if err == nil {
		t.Fatal("expected a missing file error")
	}
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

// TestDeleteActualFileRefusesBoundaryMarkdown proves the mandatory object
// Markdown cannot be removed through the manager either.
func TestDeleteActualFileRefusesBoundaryMarkdown(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()
	obj := createTestObject(t, mgr, "delete-boundary")

	err := mgr.DeleteActualFile(ctx, obj.ID, obj.Name+".md")
	if err == nil {
		t.Fatal("expected the boundary Markdown to be refused")
	}
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument, got %v", err)
	}
	if _, statErr := mgr.StatActualFile(ctx, obj.ID, obj.Name+".md"); statErr != nil {
		t.Fatalf("expected the boundary file to survive, got %v", statErr)
	}
}
