package manager

import (
	"context"
	"errors"
	"io"
	"os"
	"strings"
	"testing"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestCutoverPayloadCustody retains a shared metadata lock for the stream lifetime.
func TestCutoverPayloadCustody(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	mgr.cfg.ReadLock = true
	ctx := context.Background()
	obj := createTestObject(t, mgr, "probe")
	if err := mgr.WriteActualFile(ctx, obj.ID, "meta/notes.tags", strings.NewReader("payload")); err != nil {
		t.Fatal(err)
	}
	reader, err := mgr.ReadActualFile(ctx, obj.ID, "meta/notes.tags")
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	data, err := io.ReadAll(reader)
	if err != nil || string(data) != "payload" {
		t.Fatalf("read: %q %v", data, err)
	}
	if err := mgr.WriteActualFile(ctx, obj.ID, "meta/notes.tags", strings.NewReader("blocked")); !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("stream lock ignored: %v", err)
	}
	if err := reader.Close(); err != nil {
		t.Fatal(err)
	}
	if err := mgr.WriteActualFile(ctx, obj.ID, "meta/notes.tags", strings.NewReader("updated")); err != nil {
		t.Fatal(err)
	}
	description := "updated description"
	if _, err := mgr.UpdateObject(ctx, obj.ID, UpdateObjectOptions{Description: &description}); err != nil {
		t.Fatal(err)
	}
	if err := mgr.UpdateActualData(ctx, obj.ID, newMarkdownData(t, "probe", "archive update")); err != nil {
		t.Fatal(err)
	}
	archive, err := mgr.ReadActualArchive(ctx, obj.ID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.Copy(io.Discard, archive); err != nil {
		t.Fatal(err)
	}
	if err := archive.Close(); err != nil {
		t.Fatal(err)
	}
}

// TestCutoverMissingCustody leaves no metadata leaf for failed existing-object access.
func TestCutoverMissingCustody(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	mgr.cfg.ReadLock = true
	ctx := context.Background()
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ObjectMetaPath("missing")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := mgr.GetObject(ctx, "missing", true); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("get: %v", err)
	}
	if err := mgr.WriteActualFile(ctx, "missing", "note.md", strings.NewReader("x")); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("write: %v", err)
	}
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatalf("missing lookup created metadata: %v", err)
	}
}

// TestCutoverTagCustody protects independent tag mutation and rejects inactive records.
func TestCutoverTagCustody(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	ctx := context.Background()
	obj := createTestObject(t, mgr, "tag-probe")
	lock, err := mgr.acquireExistingObjectLock(obj.ID, false)
	if err != nil {
		t.Fatal(err)
	}
	defer releaseNamespaceLock(lock)
	if err := mgr.AddTag(ctx, obj.ID, "new-tag"); !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("tag add ignored shared custody: %v", err)
	}
	if err := mgr.RemoveTag(ctx, obj.ID, "test"); !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("tag remove ignored shared custody: %v", err)
	}
	releaseNamespaceLock(lock)
	if err := mgr.AddTag(ctx, obj.ID, "new-tag"); err != nil {
		t.Fatal(err)
	}
	after, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, tag := range after.Tags {
		found = found || tag == "new-tag"
	}
	if !found {
		t.Fatal("tag addition not persisted")
	}
	if err := mgr.RemoveTag(ctx, obj.ID, "new-tag"); err != nil {
		t.Fatal(err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if err := mgr.AddTag(ctx, obj.ID, "blocked"); !errors.Is(err, apperrors.ErrObjectNotActive) {
		t.Fatalf("inactive add: %v", err)
	}
	if err := mgr.RemoveTag(ctx, obj.ID, "test"); !errors.Is(err, apperrors.ErrObjectNotActive) {
		t.Fatalf("inactive remove: %v", err)
	}
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ObjectMetaPath("missing-tag-probe")
	if err != nil {
		t.Fatal(err)
	}
	if err := mgr.AddTag(ctx, "missing-tag-probe", "new-tag"); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("missing add: %v", err)
	}
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatalf("missing tag allocated metadata: %v", err)
	}
}
