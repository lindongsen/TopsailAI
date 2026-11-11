package local

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// TestStoreLayoutRoots verifies root ownership, validation and lexical cleanup.
func TestStoreLayoutRoots(t *testing.T) {
	for _, root := range []string{"", "relative", "."} {
		if _, err := NewStoreLayout(root); !errors.Is(err, apperrors.ErrInvalidPath) {
			t.Fatalf("root %q: got %v", root, err)
		}
	}
	root := t.TempDir()
	layout, err := NewStoreLayout(root + string(filepath.Separator) + ".")
	if err != nil {
		t.Fatal(err)
	}
	if layout.ObjectRoot() != filepath.Join(root, "object") || layout.MetaRoot() != filepath.Join(root, "meta") {
		t.Fatalf("unexpected roots: %q, %q", layout.ObjectRoot(), layout.MetaRoot())
	}
	if _, err := os.Stat(layout.MetaRoot()); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("pure resolver created a tree: %v", err)
	}
}

// TestObjectMetaPathGolden pins exact-byte hashing and the complete shard layout.
func TestObjectMetaPathGolden(t *testing.T) {
	layout, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	const hash = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
	got, err := layout.ObjectMetaPath("abc")
	if err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(layout.MetaRoot(), "ba", "78", "16", hash)
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}
	upper, err := layout.ObjectMetaPath("ABC")
	if err != nil || upper == got {
		t.Fatalf("ID case must be preserved: %q, %v", upper, err)
	}
}

// TestObjectMetaPathInvalid rejects invalid IDs and an uninitialized resolver.
func TestObjectMetaPathInvalid(t *testing.T) {
	layout, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []models.ObjectID{"", "..", "a/b", "a\\b", " leading", "x\x00y"} {
		if _, err := layout.ObjectMetaPath(id); !errors.Is(err, apperrors.ErrInvalidName) {
			t.Fatalf("ID %q: got %v", id, err)
		}
	}
	if _, err := (StoreLayout{}).ObjectMetaPath("abc"); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("zero layout: got %v", err)
	}
}

// TestObjectMetaPathMany verifies bounded pure resolution without store scanning.
func TestObjectMetaPathMany(t *testing.T) {
	root := t.TempDir()
	layout, err := NewStoreLayout(root)
	if err != nil {
		t.Fatal(err)
	}
	seen := make(map[string]bool, 2000)
	for i := 0; i < 2000; i++ {
		id := models.ObjectID(fmt.Sprintf("object-%d", i))
		path, err := layout.ObjectMetaPath(id)
		if err != nil {
			t.Fatal(err)
		}
		rel, err := filepath.Rel(layout.MetaRoot(), path)
		if err != nil {
			t.Fatal(err)
		}
		parts := strings.Split(rel, string(filepath.Separator))
		if len(parts) != 4 || len(parts[3]) != 64 || parts[0]+parts[1]+parts[2] != parts[3][:6] || seen[path] {
			t.Fatalf("invalid or duplicate path %q", path)
		}
		seen[path] = true
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 0 {
		t.Fatalf("resolver changed store: %v, %v", entries, err)
	}
}
