package local

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// AcquireNamespaceLock serializes namespace-changing operations before object
// locking. The persistent lock file must never be unlinked on release.
func AcquireNamespaceLock(root string) (*Lock, error) {
	path := filepath.Join(root, ".topsailai-data-namespace.lock")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open namespace lock %q: %w", path, err)
	}
	if err := flockAcquire(f, true); err != nil {
		_ = f.Close()
		return nil, fmt.Errorf("acquire namespace lock %q: %w", path, err)
	}
	return &Lock{path: path, file: f}, nil
}

// CheckNamespaceDestination rejects nesting and occupied destinations without
// scanning the store. Callers must hold the namespace lock through mutation.
// Filesystem writers that ignore that lock are outside this advisory contract.
func CheckNamespaceDestination(root, destination string) error {
	rel, err := filepath.Rel(root, destination)
	if err != nil || rel == "." || !filepath.IsLocal(rel) {
		return fmt.Errorf("destination %q is outside payload root: %w", destination, apperrors.ErrInvalidPath)
	}
	current := root
	parts := strings.Split(rel, string(filepath.Separator))
	for _, part := range parts[:len(parts)-1] {
		current = filepath.Join(current, part)
		if err := checkNamespaceAncestor(current); err != nil {
			return err
		}
	}
	info, err := os.Lstat(destination)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect destination %q: %w", destination, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("destination %q is not a directory: %w", destination, apperrors.ErrObjectExists)
	}
	dir, err := os.Open(destination)
	if err != nil {
		return fmt.Errorf("open destination %q: %w", destination, err)
	}
	defer dir.Close()
	_, err = dir.Readdirnames(1)
	if err == io.EOF {
		return nil
	}
	if err != nil {
		return fmt.Errorf("read destination %q: %w", destination, err)
	}
	return fmt.Errorf("destination %q is not empty: %w", destination, apperrors.ErrObjectExists)
}

// checkNamespaceAncestor refuses symlinks and object boundaries in a target path.
func checkNamespaceAncestor(path string) error {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect ancestor %q: %w", path, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("ancestor %q is not a directory: %w", path, apperrors.ErrInvalidPath)
	}
	for _, marker := range []string{"metadata.json", filepath.Base(path) + ".md"} {
		if _, err := os.Lstat(filepath.Join(path, marker)); err == nil {
			return fmt.Errorf("ancestor %q is an object boundary: %w", path, apperrors.ErrObjectExists)
		} else if !os.IsNotExist(err) {
			return fmt.Errorf("inspect ancestor marker %q: %w", path, err)
		}
	}
	return nil
}
