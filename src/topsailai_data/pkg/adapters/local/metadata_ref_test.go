package local

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestResolveObjectMetaPath validates missing and complete paths without writes.
func TestResolveObjectMetaPath(t *testing.T) {
	layout, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	want, err := layout.ObjectMetaPath("probe")
	if err != nil {
		t.Fatal(err)
	}
	for _, complete := range []bool{false, true} {
		if complete {
			if err := os.MkdirAll(want, 0o755); err != nil {
				t.Fatal(err)
			}
		}
		got, err := layout.ResolveObjectMetaPath("probe")
		if err != nil || got != want {
			t.Fatalf("complete=%v path=%q error=%v", complete, got, err)
		}
		if !complete {
			if _, err := os.Lstat(layout.MetaRoot()); !os.IsNotExist(err) {
				t.Fatalf("resolver modified metadata tree: %v", err)
			}
		}
	}
	if _, err := layout.ResolveObjectMetaPath("../probe"); !errors.Is(err, apperrors.ErrInvalidName) {
		t.Fatalf("invalid identity: %v", err)
	}
	if _, err := (StoreLayout{}).ResolveObjectMetaPath("probe"); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("zero layout: %v", err)
	}
}

// TestResolveObjectMetaPathUnsafeNodes rejects aliases at every hash directory level.
func TestResolveObjectMetaPathUnsafeNodes(t *testing.T) {
	for depth := 0; depth < 5; depth++ {
		for _, kind := range []string{"file", "symlink"} {
			t.Run(fmt.Sprintf("%d/%s", depth, kind), func(t *testing.T) {
				checkUnsafeMetadataNode(t, depth, kind)
			})
		}
	}
}

// checkUnsafeMetadataNode prepares one unsafe component and verifies rejection.
func checkUnsafeMetadataNode(t *testing.T, depth int, kind string) {
	t.Helper()
	layout, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	path, err := layout.ObjectMetaPath("probe")
	if err != nil {
		t.Fatal(err)
	}
	for i := 4; i > depth; i-- {
		path = filepath.Dir(path)
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if kind == "file" {
		err = os.WriteFile(path, []byte("sentinel"), 0o600)
	} else {
		err = os.Symlink(t.TempDir(), path)
	}
	if err != nil {
		t.Fatal(err)
	}
	if _, err := layout.ResolveObjectMetaPath("probe"); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("unsafe node accepted: %v", err)
	}
	if kind != "file" {
		return
	}
	data, err := os.ReadFile(path)
	if err != nil || string(data) != "sentinel" {
		t.Fatalf("sentinel modified: %q %v", data, err)
	}
}
