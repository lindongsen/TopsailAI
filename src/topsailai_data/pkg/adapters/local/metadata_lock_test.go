package local

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// metadataLockLayout initializes an isolated store for lock protocol checks.
func metadataLockLayout(t *testing.T) StoreLayout {
	t.Helper()
	layout, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := layout.Init(); err != nil {
		t.Fatal(err)
	}
	return layout
}

// TestMetadataLockContention checks shared readers and exclusive writers by ID.
func TestMetadataLockContention(t *testing.T) {
	layout := metadataLockLayout(t)
	first, err := layout.AcquireMetadataLock("probe", false)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Release()
	second, err := layout.AcquireMetadataLock("probe", false)
	if err != nil {
		t.Fatal(err)
	}
	defer second.Release()
	if lock, err := layout.AcquireMetadataLock("probe", true); !errors.Is(err, apperrors.ErrObjectLocked) {
		if lock != nil {
			lock.Release()
		}
		t.Fatalf("writer did not conflict: %v", err)
	}
	other, err := layout.AcquireMetadataLock("other", true)
	if err != nil {
		t.Fatal(err)
	}
	if err := other.Release(); err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ObjectMetaPath("probe")
	if err != nil || first.Path() != filepath.Join(dir, "lock") {
		t.Fatalf("unexpected lock path: %s %v", first.Path(), err)
	}
}

// TestMetadataLockNamespaceGate checks lock opening is gated and owners avoid reentry.
func TestMetadataLockNamespaceGate(t *testing.T) {
	layout := metadataLockLayout(t)
	gate, err := AcquireNamespaceLock(layout.storeRoot)
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Release()
	if lock, err := layout.AcquireMetadataLock("probe", true); !errors.Is(err, apperrors.ErrObjectLocked) {
		if lock != nil {
			lock.Release()
		}
		t.Fatalf("ungated acquisition: %v", err)
	}
	lock, err := layout.AcquireMetadataLockUnderNamespace("probe", true)
	if err != nil {
		t.Fatal(err)
	}
	if err := lock.Release(); err != nil {
		t.Fatal(err)
	}
	if _, err := (StoreLayout{}).AcquireMetadataLock("probe", true); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("zero layout: %v", err)
	}
}

// TestMetadataLockUnsafeLeaf rejects a directory or alias instead of a lock file.
func TestMetadataLockUnsafeLeaf(t *testing.T) {
	for _, kind := range []string{"directory", "symlink"} {
		t.Run(kind, func(t *testing.T) {
			checkMetadataLockUnsafeLeaf(t, kind)
		})
	}
}

// checkMetadataLockUnsafeLeaf verifies an unsafe leaf does not retain the gate.
func checkMetadataLockUnsafeLeaf(t *testing.T, kind string) {
	t.Helper()
	layout := metadataLockLayout(t)
	dir, err := layout.ObjectMetaPath("probe")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "lock")
	if kind == "directory" {
		err = os.Mkdir(path, 0o755)
	} else {
		err = os.Symlink(filepath.Join(t.TempDir(), "missing"), path)
	}
	if err != nil {
		t.Fatal(err)
	}
	if lock, err := layout.AcquireMetadataLock("probe", true); !errors.Is(err, apperrors.ErrInvalidPath) {
		if lock != nil {
			lock.Release()
		}
		t.Fatalf("unsafe lock accepted: %v", err)
	}
	gate, err := AcquireNamespaceLock(layout.storeRoot)
	if err != nil {
		t.Fatalf("namespace gate leaked: %v", err)
	}
	if err := gate.Release(); err != nil {
		t.Fatal(err)
	}
}

// TestMetadataLockPurgeCustody checks removal cannot bypass an existing reader.
func TestMetadataLockPurgeCustody(t *testing.T) {
	layout := metadataLockLayout(t)
	reader, err := layout.AcquireMetadataLock("probe", false)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Release()
	gate, err := AcquireNamespaceLock(layout.storeRoot)
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Release()
	if lock, err := layout.AcquireMetadataLockUnderNamespace("probe", true); !errors.Is(err, apperrors.ErrObjectLocked) {
		if lock != nil {
			lock.Release()
		}
		t.Fatalf("purge bypassed reader: %v", err)
	}
	if err := reader.Release(); err != nil {
		t.Fatal(err)
	}
	writer, err := layout.AcquireMetadataLockUnderNamespace("probe", true)
	if err != nil {
		t.Fatal(err)
	}
	if err := writer.Release(); err != nil {
		t.Fatal(err)
	}
}

// TestMetadataLockUnsafeDirectory checks aliases cannot redirect lock storage.
func TestMetadataLockUnsafeDirectory(t *testing.T) {
	layout := metadataLockLayout(t)
	dir, err := layout.ObjectMetaPath("probe")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(dir), 0o755); err != nil {
		t.Fatal(err)
	}
	target := t.TempDir()
	if err := os.Symlink(target, dir); err != nil {
		t.Fatal(err)
	}
	if lock, err := layout.AcquireMetadataLock("probe", true); !errors.Is(err, apperrors.ErrInvalidPath) {
		if lock != nil {
			lock.Release()
		}
		t.Fatalf("directory alias accepted: %v", err)
	}
	entries, err := os.ReadDir(target)
	if err != nil || len(entries) != 0 {
		t.Fatalf("alias target changed: %v %v", entries, err)
	}
}

// TestMetadataLockRequiresStore rejects acquisition before store initialization.
func TestMetadataLockRequiresStore(t *testing.T) {
	root := filepath.Join(t.TempDir(), "missing")
	layout, err := NewStoreLayout(root)
	if err != nil {
		t.Fatal(err)
	}
	if lock, err := layout.AcquireMetadataLock("probe", true); err == nil {
		if lock != nil {
			lock.Release()
		}
		t.Fatal("uninitialized store accepted")
	}
	if _, err := os.Lstat(root); !os.IsNotExist(err) {
		t.Fatalf("lock created store root: %v", err)
	}
}

// TestExistingMetadataLockMissing avoids query-driven hash directory growth.
func TestExistingMetadataLockMissing(t *testing.T) {
	layout := metadataLockLayout(t)
	for _, id := range []string{"missing-one", "missing-two", "missing-three"} {
		lock, err := layout.AcquireExistingMetadataLock(models.ObjectID(id), false)
		if lock != nil {
			_ = lock.Release()
			t.Fatal("missing record acquired")
		}
		if !errors.Is(err, apperrors.ErrObjectNotFound) {
			t.Fatalf("missing ID: %v", err)
		}
	}
	entries, err := os.ReadDir(layout.MetaRoot())
	if err != nil || len(entries) != 0 {
		t.Fatalf("query created metadata directories: %v %v", entries, err)
	}
	gate, err := AcquireNamespaceLock(layout.storeRoot)
	if err != nil {
		t.Fatalf("failed lookup retained gate: %v", err)
	}
	if err := gate.Release(); err != nil {
		t.Fatal(err)
	}
}

// TestExistingMetadataLockRecord validates records before creating lock leaves.
func TestExistingMetadataLockRecord(t *testing.T) {
	layout := metadataLockLayout(t)
	dir, err := layout.ObjectMetaPath("probe")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	lock, err := layout.AcquireExistingMetadataLock("probe", true)
	if lock != nil || !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("lock-only leaf: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(dir, "lock")); !os.IsNotExist(err) {
		t.Fatalf("lookup created lock: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "metadata.json"), []byte("{"), 0o600); err != nil {
		t.Fatal(err)
	}
	lock, err = layout.AcquireExistingMetadataLock("probe", true)
	if lock != nil || !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("corrupt record: %v", err)
	}
	if _, err := os.Lstat(filepath.Join(dir, "lock")); !os.IsNotExist(err) {
		t.Fatalf("corrupt lookup created lock: %v", err)
	}
	obj := &models.Object{ID: "probe", Name: "probe", Path: "2026/1111/0900/probe", DataRef: "2026/1111/0900/probe", Status: models.ObjectStatusActive, SchemaVersion: models.CurrentSchemaVersion}
	if err := layout.writeMetadataRecord(obj); err != nil {
		t.Fatal(err)
	}
	reader, err := layout.AcquireExistingMetadataLock("probe", false)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Release()
	writer, err := layout.AcquireExistingMetadataLock("probe", true)
	if writer != nil || !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("writer bypassed existing reader: %v", err)
	}
}
