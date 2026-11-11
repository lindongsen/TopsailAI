package local

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestLayoutInitFreshAndReopen verifies fresh initialization and bounded reopen.
func TestLayoutInitFreshAndReopen(t *testing.T) {
	root := filepath.Join(t.TempDir(), "store")
	layout, err := NewStoreLayout(root)
	if err != nil {
		t.Fatal(err)
	}
	if err := layout.Init(); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{layout.ObjectRoot(), layout.MetaRoot()} {
		if err := requireLayoutDirectory(path); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(layout.ObjectRoot(), "payload"), []byte("keep"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := layout.Init(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(layout.ObjectRoot(), "payload"))
	if err != nil || string(data) != "keep" {
		t.Fatalf("reopen changed data: %q, %v", data, err)
	}
}

// TestLayoutInitLegacyRefusal verifies unmarked data is never adopted or changed.
func TestLayoutInitLegacyRefusal(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "2026")
	if err := os.Mkdir(path, 0o755); err != nil {
		t.Fatal(err)
	}
	layout, err := NewStoreLayout(root)
	if err != nil {
		t.Fatal(err)
	}
	if err := layout.Init(); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("legacy root: %v", err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, layoutMarkerName)); !os.IsNotExist(err) {
		t.Fatalf("legacy root was marked: %v", err)
	}
}

// TestLayoutInitInvalidMarker verifies bounded parsing and version refusal.
func TestLayoutInitInvalidMarker(t *testing.T) {
	for _, data := range []string{"{", strings.Repeat("x", 4097), `{"layout":"unknown","layout_version":1,"schema_version":2}`, `{"layout":"object-meta","layout_version":2,"schema_version":2}`, `{"layout":"object-meta","layout_version":1,"schema_version":999}`} {
		t.Run(data[:1], func(t *testing.T) {
			root := t.TempDir()
			if err := os.WriteFile(filepath.Join(root, layoutMarkerName), []byte(data), 0o644); err != nil {
				t.Fatal(err)
			}
			layout, err := NewStoreLayout(root)
			if err != nil {
				t.Fatal(err)
			}
			if err := layout.Init(); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
				t.Fatalf("invalid marker accepted: %v", err)
			}
		})
	}
}

// TestLayoutInitSymlinkAndContention rejects unsafe trees and shared initialization.
func TestLayoutInitSymlinkAndContention(t *testing.T) {
	layout, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := layout.Init(); err != nil {
		t.Fatal(err)
	}
	// A marked store with a symlink at a tree root must be rejected.
	other, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	marker, err := os.ReadFile(filepath.Join(layout.storeRoot, layoutMarkerName))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(other.storeRoot, layoutMarkerName), marker, 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(layout.ObjectRoot(), other.ObjectRoot()); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	if err := other.Init(); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("symlink tree accepted: %v", err)
	}
	lock, err := AcquireNamespaceLock(layout.storeRoot)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Release()
	if err := layout.Init(); !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("initialization ignored lock: %v", err)
	}
	if err := (StoreLayout{}).Init(); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("zero layout accepted: %v", err)
	}
}
