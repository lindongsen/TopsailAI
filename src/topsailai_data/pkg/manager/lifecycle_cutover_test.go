package manager

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/topsailai/topsailai_data/pkg/adapters"
	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// cutoverFailDelete preserves the real adapter except for injected cleanup failure.
type cutoverFailDelete struct {
	adapters.ActualDataAdapter
	failure error
}

// Delete fails without removing data to verify retry-record preservation.
func (a cutoverFailDelete) Delete(context.Context, string) error { return a.failure }

// TestCutoverDeletionLifecycle separates soft deletion, finalization and purge.
func TestCutoverDeletionLifecycle(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	ctx := context.Background()
	obj, err := mgr.CreateObject(ctx, "probe", CreateObjectOptions{Tags: []string{"retained"}, Data: newMarkdownData(t, "probe", "body")})
	if err != nil {
		t.Fatal(err)
	}
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	payload, err := layout.ResolveObjectRef(obj.DataRef)
	if err != nil {
		t.Fatal(err)
	}
	meta, err := layout.ObjectMetaPath(obj.ID)
	if err != nil {
		t.Fatal(err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(payload, "probe.md")); err != nil {
		t.Fatal(err)
	}
	realActual := mgr.actual
	failure := errors.New("injected deletion failure")
	mgr.actual = cutoverFailDelete{ActualDataAdapter: realActual, failure: failure}
	if err := mgr.DeleteObject(ctx, obj.ID); !errors.Is(err, failure) {
		t.Fatalf("lost failure: %v", err)
	}
	retained, err := mgr.meta.Get(ctx, obj.ID, true)
	if err != nil || retained.Status != models.ObjectStatusDeleted || len(retained.Tags) != 1 {
		t.Fatalf("retry state: %+v %v", retained, err)
	}
	mgr.actual = realActual
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(payload); !os.IsNotExist(err) {
		t.Fatalf("payload survived finalization: %v", err)
	}
	retained, err = mgr.GetObject(ctx, obj.ID, true)
	if err != nil || retained.Status != models.ObjectStatusCeased || len(retained.Tags) != 1 {
		t.Fatalf("ceased metadata: %+v %v", retained, err)
	}
	for _, name := range []string{"metadata.json", "tags", "lock"} {
		if _, err := os.Stat(filepath.Join(meta, name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := mgr.GCObjects(ctx, false); err != nil {
		t.Fatal(err)
	}
	if _, err := mgr.GetObject(ctx, obj.ID, true); err != nil {
		t.Fatalf("retention ignored: %v", err)
	}
	if err := mgr.GCObjects(ctx, true); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(meta); !os.IsNotExist(err) {
		t.Fatalf("metadata survived purge: %v", err)
	}
	if _, err := mgr.GetObject(ctx, obj.ID, true); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("purged lookup: %v", err)
	}
	if _, err := os.Lstat(meta); !os.IsNotExist(err) {
		t.Fatalf("lookup resurrected metadata: %v", err)
	}
}

// TestCutoverCreatingCleanupFailure leaves incomplete metadata until payload removal succeeds.
func TestCutoverCreatingCleanupFailure(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	ctx := context.Background()
	realActual := mgr.actual
	failure := errors.New("injected cleanup failure")
	mgr.actual = cutoverFailArchive{ActualDataAdapter: realActual, failure: failure}
	if _, err := mgr.CreateObject(ctx, "probe", CreateObjectOptions{Tags: []string{"retained"}, Data: newMarkdownData(t, "probe", "body")}); !errors.Is(err, failure) {
		t.Fatal(err)
	}
	mgr.actual = cutoverFailDelete{ActualDataAdapter: realActual, failure: failure}
	if err := mgr.CleanupCreatingObject(ctx, "probe"); !errors.Is(err, failure) {
		t.Fatalf("lost cleanup failure: %v", err)
	}
	obj, err := mgr.meta.Get(ctx, "probe", true)
	if err != nil || obj.Status != models.ObjectStatusCreating || len(obj.Tags) != 1 {
		t.Fatalf("creating state lost: %+v %v", obj, err)
	}
	mgr.actual = realActual
	if err := mgr.GCObjects(ctx, false); err != nil {
		t.Fatal(err)
	}
	if _, err := mgr.meta.Get(ctx, "probe", true); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("creating record survived: %v", err)
	}
}

// TestCutoverStaleCeasedCandidate preserves a currently active record.
func TestCutoverStaleCeasedCandidate(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	ctx := context.Background()
	obj := createTestObject(t, mgr, "probe")
	if err := mgr.gcCeasedObject(ctx, &models.Object{ID: obj.ID, Status: models.ObjectStatusCeased}, true); err != nil {
		t.Fatal(err)
	}
	if _, err := mgr.GetObject(ctx, obj.ID, false); err != nil {
		t.Fatalf("stale candidate removed active object: %v", err)
	}
}

// TestCutoverRecoveryCustody preserves deleted state and archive sources on failure.
func TestCutoverRecoveryCustody(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	ctx := context.Background()
	obj := createTestObject(t, mgr, "probe", "retained")
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if err := mgr.RestoreObject(ctx, obj.ID, nil); err != nil {
		t.Fatal(err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	realActual := mgr.actual
	failure := errors.New("injected recovery failure")
	mgr.actual = cutoverFailArchive{ActualDataAdapter: realActual, failure: failure}
	if err := mgr.RestoreObject(ctx, obj.ID, newMarkdownData(t, "probe", "replacement")); !errors.Is(err, failure) {
		t.Fatalf("lost restore failure: %v", err)
	}
	mgr.actual = realActual
	retained, err := mgr.meta.Get(ctx, obj.ID, true)
	if err != nil || retained.Status != models.ObjectStatusDeleted {
		t.Fatalf("failed restore activated record: %+v %v", retained, err)
	}
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ResolveObjectRef(obj.DataRef)
	if err != nil {
		t.Fatal(err)
	}
	archive, err := os.Create(filepath.Join(dir, "source.tar"))
	if err != nil {
		t.Fatal(err)
	}
	defer archive.Close()
	if _, err := archive.Write([]byte("source sentinel")); err != nil {
		t.Fatal(err)
	}
	if _, err := archive.Seek(0, 0); err != nil {
		t.Fatal(err)
	}
	if err := mgr.RestoreObject(ctx, obj.ID, archive); !errors.Is(err, apperrors.ErrSourceDestinationSameFile) {
		t.Fatalf("overlap not rejected: %v", err)
	}
	data, err := os.ReadFile(archive.Name())
	if err != nil || string(data) != "source sentinel" {
		t.Fatalf("source changed: %q %v", data, err)
	}
	retained, err = mgr.meta.Get(ctx, obj.ID, true)
	if err != nil || retained.Status != models.ObjectStatusDeleted {
		t.Fatalf("overlap changed status: %+v %v", retained, err)
	}
	if err := mgr.RestoreObject(ctx, obj.ID, newMarkdownData(t, "probe", "replacement")); err != nil {
		t.Fatal(err)
	}
	if _, err := mgr.GetObject(ctx, obj.ID, false); err != nil {
		t.Fatal(err)
	}
}
