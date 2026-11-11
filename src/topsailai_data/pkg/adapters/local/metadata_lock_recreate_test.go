package local

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestMetadataLockRecreation verifies custody across removal of a lock directory.
func TestMetadataLockRecreation(t *testing.T) {
	layout := metadataLockLayout(t)
	reader, err := layout.AcquireMetadataLock("probe", false)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Release()
	oldInfo, err := os.Stat(reader.Path())
	if err != nil {
		t.Fatal(err)
	}
	gate, err := AcquireNamespaceLock(layout.storeRoot)
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Release()
	assertMetadataLockConflict(t, func() (*Lock, error) {
		return layout.AcquireMetadataLockUnderNamespace("probe", true)
	})
	if _, err := os.Stat(reader.Path()); err != nil {
		t.Fatalf("blocked purge changed lock: %v", err)
	}
	if err := reader.Release(); err != nil {
		t.Fatal(err)
	}
	purger, err := layout.AcquireMetadataLockUnderNamespace("probe", true)
	if err != nil {
		t.Fatal(err)
	}
	defer purger.Release()
	removeTestLockDirectory(t, purger.Path())
	assertMetadataLockConflict(t, func() (*Lock, error) {
		return layout.AcquireMetadataLock("probe", true)
	})
	if _, err := os.Lstat(filepath.Dir(purger.Path())); !os.IsNotExist(err) {
		t.Fatalf("blocked opener recreated directory: %v", err)
	}
	// Keep the unlinked inode open until replacement is checked to prevent reuse.
	recreated, err := layout.AcquireMetadataLockUnderNamespace("probe", true)
	if err != nil {
		t.Fatal(err)
	}
	defer recreated.Release()
	newInfo, err := os.Stat(recreated.Path())
	if err != nil {
		t.Fatal(err)
	}
	if os.SameFile(oldInfo, newInfo) {
		t.Fatal("recreated lock unexpectedly retains deleted inode")
	}
	if err := purger.Release(); err != nil {
		t.Fatal(err)
	}
	if err := gate.Release(); err != nil {
		t.Fatal(err)
	}
	assertMetadataLockConflict(t, func() (*Lock, error) {
		return layout.AcquireMetadataLock("probe", true)
	})
	assertMetadataLockConflict(t, func() (*Lock, error) {
		return layout.AcquireMetadataLock("probe", false)
	})
	if err := recreated.Release(); err != nil {
		t.Fatal(err)
	}
	last, err := layout.AcquireMetadataLock("probe", true)
	if err != nil {
		t.Fatalf("recreated lock unusable after release: %v", err)
	}
	if err := last.Release(); err != nil {
		t.Fatal(err)
	}
}

// assertMetadataLockConflict closes unexpected acquisitions before reporting them.
func assertMetadataLockConflict(t *testing.T, acquire func() (*Lock, error)) {
	t.Helper()
	lock, err := acquire()
	if lock != nil {
		if closeErr := lock.Release(); closeErr != nil {
			t.Error(closeErr)
		}
	}
	if !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("expected lock conflict, got %v", err)
	}
}

// removeTestLockDirectory removes only the known leaf and empty fixture directory.
func removeTestLockDirectory(t *testing.T, path string) {
	t.Helper()
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	t.Logf("deleted isolated test lock %s", path)
	if err := os.Remove(filepath.Dir(path)); err != nil {
		t.Fatal(err)
	}
	t.Logf("deleted isolated test directory %s", filepath.Dir(path))
}
