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
