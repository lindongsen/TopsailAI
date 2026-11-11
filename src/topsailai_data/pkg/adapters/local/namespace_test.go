package local

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestNamespaceLockLifecycle verifies contention and reuse of the same lock file.
func TestNamespaceLockLifecycle(t *testing.T) {
	root := t.TempDir()
	first, err := AcquireNamespaceLock(root)
	if err != nil {
		t.Fatal(err)
	}
	defer first.Release()
	before, err := os.Stat(first.Path())
	if err != nil {
		t.Fatal(err)
	}
	second, err := AcquireNamespaceLock(root)
	if err == nil {
		second.Release()
		t.Fatal("competing namespace lock succeeded")
	}
	if !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatal(err)
	}
	if err := first.Release(); err != nil {
		t.Fatal(err)
	}
	next, err := AcquireNamespaceLock(root)
	if err != nil {
		t.Fatal(err)
	}
	defer next.Release()
	after, err := os.Stat(next.Path())
	if err != nil || !os.SameFile(before, after) {
		t.Fatalf("lock file was replaced: %v", err)
	}
}

// TestNamespaceDestination verifies bounded ancestor and destination checks.
func TestNamespaceDestination(t *testing.T) {
	for _, kind := range []string{"missing", "empty", "occupied", "markdown", "metadata", "symlink", "outside"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			parent := filepath.Join(root, "parent")
			if err := os.Mkdir(parent, 0o755); err != nil {
				t.Fatal(err)
			}
			dest := filepath.Join(parent, "target")
			want := error(nil)
			switch kind {
			case "empty", "occupied":
				if err := os.Mkdir(dest, 0o755); err != nil {
					t.Fatal(err)
				}
				if kind == "occupied" {
					if err := os.WriteFile(filepath.Join(dest, "keep"), []byte("data"), 0o644); err != nil {
						t.Fatal(err)
					}
					want = apperrors.ErrObjectExists
				}
			case "markdown", "metadata":
				name := "parent.md"
				if kind == "metadata" {
					name = "metadata.json"
				}
				if err := os.WriteFile(filepath.Join(parent, name), nil, 0o644); err != nil {
					t.Fatal(err)
				}
				want = apperrors.ErrObjectExists
			case "symlink":
				link := filepath.Join(root, "link")
				if err := os.Symlink(parent, link); err != nil {
					t.Skipf("symlink unavailable: %v", err)
				}
				dest = filepath.Join(link, "target")
				want = apperrors.ErrInvalidPath
			case "outside":
				dest = filepath.Join(root, "..", "outside")
				want = apperrors.ErrInvalidPath
			}
			if err := CheckNamespaceDestination(root, dest); !errors.Is(err, want) {
				t.Fatalf("got %v, want %v", err, want)
			}
		})
	}
}

// TestNamespaceLockRejectsAliases preserves unsafe leaves and their targets.
func TestNamespaceLockRejectsAliases(t *testing.T) {
	for _, kind := range []string{"live", "dangling", "directory"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, ".topsailai-data-namespace.lock")
			target := filepath.Join(root, "target")
			if kind == "directory" {
				if err := os.Mkdir(path, 0o755); err != nil {
					t.Fatal(err)
				}
			} else {
				if kind == "live" {
					if err := os.WriteFile(target, []byte("preserve"), 0o600); err != nil {
						t.Fatal(err)
					}
				}
				if err := os.Symlink(target, path); err != nil {
					t.Skipf("symlink unavailable: %v", err)
				}
			}
			before, err := os.Lstat(path)
			if err != nil {
				t.Fatal(err)
			}
			lock, err := AcquireNamespaceLock(root)
			if lock != nil {
				_ = lock.Release()
				t.Fatal("unsafe namespace leaf acquired")
			}
			if !errors.Is(err, apperrors.ErrInvalidPath) {
				t.Fatalf("got %v, want invalid path", err)
			}
			after, err := os.Lstat(path)
			if err != nil || !os.SameFile(before, after) {
				t.Fatalf("namespace leaf changed: %v", err)
			}
			if kind == "live" {
				data, err := os.ReadFile(target)
				if err != nil || string(data) != "preserve" {
					t.Fatalf("target changed: %q, %v", data, err)
				}
			}
			if kind == "dangling" {
				if _, err := os.Lstat(target); !os.IsNotExist(err) {
					t.Fatalf("dangling target created: %v", err)
				}
			}
		})
	}
}
