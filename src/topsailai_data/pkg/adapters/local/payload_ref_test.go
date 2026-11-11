package local

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestResolveObjectRef verifies canonical references without filesystem mutations.
func TestResolveObjectRef(t *testing.T) {
	layout, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	for _, ref := range []string{"2026/1111/0900/probe", "2026/1111/0900/meta/probe", "2026/1111/0900/a/b/c/d/e/f/g/probe"} {
		got, err := layout.ResolveObjectRef(ref)
		if err != nil || got != filepath.Join(layout.ObjectRoot(), filepath.FromSlash(ref)) {
			t.Fatalf("resolve %q: %q %v", ref, got, err)
		}
		if _, err := os.Stat(got); !os.IsNotExist(err) {
			t.Fatalf("resolver created directories: %v", err)
		}
	}
	if err := os.MkdirAll(filepath.Join(layout.ObjectRoot(), "2026/1111/0900/probe"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err := layout.ResolveObjectRef("2026/1111/0900/probe"); err != nil {
		t.Fatal(err)
	}
	for _, ref := range []string{"", ".", "../meta/probe", "/2026/1111/0900/probe", "C:/2026/1111/0900/probe", `2026\1111\0900\probe`, "2026/1111/0900/../probe", "2026/1111/0900//probe", "2026/1111/0900/probe/", "2026/1111/0900/./probe", "year/1111/0900/probe", "2026/1111/0900/" + strings.Repeat("a/", 8) + "probe"} {
		if _, err := layout.ResolveObjectRef(ref); !errors.Is(err, apperrors.ErrInvalidPath) {
			t.Fatalf("accepted %q: %v", ref, err)
		}
	}
	if _, err := (StoreLayout{}).ResolveObjectRef("2026/1111/0900/probe"); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatal(err)
	}
}

// TestResolveObjectRefUnsafeNodes rejects links at every relevant tree level.
func TestResolveObjectRefUnsafeNodes(t *testing.T) {
	for _, prefix := range []string{"", "2026", "2026/1111/0900/probe"} {
		t.Run(prefix, func(t *testing.T) {
			layout, err := NewStoreLayout(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			outside := t.TempDir()
			sentinel := filepath.Join(outside, "keep")
			if err := os.WriteFile(sentinel, []byte("keep"), 0600); err != nil {
				t.Fatal(err)
			}
			link := filepath.Join(layout.ObjectRoot(), filepath.FromSlash(prefix))
			if err := os.MkdirAll(filepath.Dir(link), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(outside, link); err != nil {
				t.Skipf("symlink unavailable: %v", err)
			}
			if _, err := layout.ResolveObjectRef("2026/1111/0900/probe"); !errors.Is(err, apperrors.ErrInvalidPath) {
				t.Fatalf("unsafe node accepted: %v", err)
			}
			if data, err := os.ReadFile(sentinel); err != nil || string(data) != "keep" {
				t.Fatalf("sentinel changed: %q %v", data, err)
			}
		})
	}
	layout, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(layout.ObjectRoot(), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(layout.ObjectRoot(), "2026"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := layout.ResolveObjectRef("2026/1111/0900/probe"); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("file ancestor accepted: %v", err)
	}
}
