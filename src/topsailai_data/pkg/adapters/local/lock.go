// Package local implements the local filesystem adapter for topsailai_data.
package local

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// Lock represents an advisory lock held on an object folder.
type Lock struct {
	path string
	file *os.File
}

// AcquireLock opens or creates the object lock file and acquires an advisory
// lock. If exclusive is true, an exclusive (write) lock is acquired; otherwise
// a shared (read) lock is acquired. If the lock cannot be acquired immediately,
// ErrObjectLocked is returned.
func AcquireLock(objectPath string, exclusive bool) (*Lock, error) {
	name := filepath.Base(objectPath)
	lockPath := filepath.Join(objectPath, name+".lock")

	if err := os.MkdirAll(objectPath, 0o755); err != nil {
		return nil, fmt.Errorf("create object directory for lock: %w", err)
	}

	f, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return nil, fmt.Errorf("open lock file %q: %w", lockPath, err)
	}

	if err := flockAcquire(f, exclusive); err != nil {
		_ = f.Close()
		if err == errors.ErrObjectLocked {
			return nil, err
		}
		return nil, fmt.Errorf("acquire lock on %q: %w", lockPath, err)
	}

	return &Lock{
		path: lockPath,
		file: f,
	}, nil
}

// AcquireWriteLock is a convenience wrapper for an exclusive advisory lock.
func AcquireWriteLock(objectPath string) (*Lock, error) {
	return AcquireLock(objectPath, true)
}

// AcquireReadLock is a convenience wrapper for a shared advisory lock.
func AcquireReadLock(objectPath string) (*Lock, error) {
	return AcquireLock(objectPath, false)
}

// Release unlocks and closes the underlying lock file.
func (l *Lock) Release() error {
	if l.file == nil {
		return nil
	}
	if err := flockRelease(l.file); err != nil {
		_ = l.file.Close()
		return fmt.Errorf("release lock %q: %w", l.path, err)
	}
	if err := l.file.Close(); err != nil {
		return fmt.Errorf("close lock file %q: %w", l.path, err)
	}
	l.file = nil
	return nil
}

// Path returns the absolute path of the lock file.
func (l *Lock) Path() string {
	return l.path
}

// objectPathFromID returns the object folder path for the given ObjectID.
// It is a helper used by callers that store the object path in metadata.
func objectPathFromID(root string, id models.ObjectID) string {
	return filepath.Join(root, string(id))
}
