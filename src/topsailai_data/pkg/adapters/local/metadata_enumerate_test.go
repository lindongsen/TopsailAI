package local

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// TestScanHashMetadataRecords checks all lifecycle states and independent tags.
func TestScanHashMetadataRecords(t *testing.T) {
	layout := metadataLockLayout(t)
	objects, err := layout.scanMetadataRecords(context.Background())
	if err != nil || len(objects) != 0 {
		t.Fatalf("empty scan: %v %v", objects, err)
	}
	states := []models.ObjectStatus{models.ObjectStatusCreating, models.ObjectStatusActive, models.ObjectStatusDeleted, models.ObjectStatusCeased}
	for _, status := range states {
		writeEnumerationFixture(t, layout, string(status), status)
	}
	lock, err := layout.AcquireMetadataLock("lock-only", true)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Release()
	// An invalid payload-side metadata file must never be inspected.
	if err := os.WriteFile(filepath.Join(layout.ObjectRoot(), "metadata.json"), []byte("broken"), 0600); err != nil {
		t.Fatal(err)
	}
	objects, err = layout.scanMetadataRecords(context.Background())
	if err != nil || len(objects) != len(states) {
		t.Fatalf("scan: %d %v", len(objects), err)
	}
	seen := map[models.ObjectStatus]bool{}
	for _, obj := range objects {
		seen[obj.Status] = true
		if len(obj.Tags) != 1 || obj.Tags[0] != obj.Name {
			t.Fatalf("tags not read independently: %#v", obj)
		}
	}
	if len(seen) != len(states) {
		t.Fatalf("lost lifecycle states: %v", seen)
	}
}

// writeEnumerationFixture publishes an isolated record under its object lock.
func writeEnumerationFixture(t *testing.T, layout StoreLayout, name string, status models.ObjectStatus) {
	t.Helper()
	lock, err := layout.AcquireMetadataLock(models.ObjectID(name), true)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Release()
	ref := "2026/1111/0900/" + name
	obj := &models.Object{ID: models.ObjectID(name), Name: name, Path: ref, DataRef: ref, Status: status, SchemaVersion: models.CurrentSchemaVersion}
	if err := layout.writeMetadataRecord(obj); err != nil {
		t.Fatal(err)
	}
	if err := writeObjectTags(filepath.Dir(lock.Path()), []string{name}); err != nil {
		t.Fatal(err)
	}
}

// TestScanHashMetadataRejectsCorruption checks directory shape and record placement.
func TestScanHashMetadataRejectsCorruption(t *testing.T) {
	layout := metadataLockLayout(t)
	writeEnumerationFixture(t, layout, "probe", models.ObjectStatusActive)
	dir, err := layout.ObjectMetaPath("probe")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "metadata.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	other, err := layout.ObjectMetaPath("other")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(other, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(other, "metadata.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	if objects, err := layout.scanMetadataRecords(context.Background()); !errors.Is(err, apperrors.ErrCorruptedMetadata) || objects != nil {
		t.Fatalf("misplaced identity accepted: %v %v", objects, err)
	}
	bad := metadataLockLayout(t)
	if err := os.Mkdir(filepath.Join(bad.MetaRoot(), "zz"), 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := bad.scanMetadataRecords(context.Background()); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("bad shard accepted: %v", err)
	}
}

// TestScanHashMetadataCanceledAndAliases checks cancellation and no alias traversal.
func TestScanHashMetadataCanceledAndAliases(t *testing.T) {
	layout := metadataLockLayout(t)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := layout.scanMetadataRecords(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("canceled scan: %v", err)
	}
	if err := os.Symlink(t.TempDir(), filepath.Join(layout.MetaRoot(), "ab")); err != nil {
		t.Fatal(err)
	}
	if _, err := layout.scanMetadataRecords(context.Background()); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("alias traversed: %v", err)
	}
	if _, err := (StoreLayout{}).scanMetadataRecords(context.Background()); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("zero layout: %v", err)
	}
}

// TestScanHashMetadataShardPrefix rejects hash leaves placed under wrong shards.
func TestScanHashMetadataShardPrefix(t *testing.T) {
	layout := metadataLockLayout(t)
	path := filepath.Join(layout.MetaRoot(), "00", "00", "00", "1111111111111111111111111111111111111111111111111111111111111111")
	if err := os.MkdirAll(path, 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := layout.scanMetadataRecords(context.Background()); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("wrong prefix accepted: %v", err)
	}
}
