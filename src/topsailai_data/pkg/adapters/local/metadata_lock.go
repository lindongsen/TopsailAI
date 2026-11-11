package local

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// AcquireMetadataLock gates lock opening against metadata directory removal.
// Namespace mutations use AcquireMetadataLockUnderNamespace instead and retain
// namespace custody until all directory removal or replacement is complete.
func (l StoreLayout) AcquireMetadataLock(id models.ObjectID, exclusive bool) (*Lock, error) {
	return l.acquireGatedMetadataLock(id, exclusive, false)
}

// AcquireExistingMetadataLock never creates directories for absent records.
// Callers re-read status and reference after acquisition before using the object.
func (l StoreLayout) AcquireExistingMetadataLock(id models.ObjectID, exclusive bool) (*Lock, error) {
	return l.acquireGatedMetadataLock(id, exclusive, true)
}

// acquireGatedMetadataLock validates existence while namespace custody is held.
func (l StoreLayout) acquireGatedMetadataLock(id models.ObjectID, exclusive, existing bool) (*Lock, error) {
	if _, err := l.ObjectMetaPath(id); err != nil {
		return nil, err
	}
	gate, err := AcquireNamespaceLock(l.storeRoot)
	if err != nil {
		return nil, err
	}
	var lock *Lock
	var acquireErr error
	if existing {
		_, acquireErr = l.readMetadataRecord(id)
	}
	if acquireErr == nil {
		lock, acquireErr = l.AcquireMetadataLockUnderNamespace(id, exclusive)
	}
	if err := gate.Release(); err != nil {
		if lock != nil {
			err = errors.Join(err, lock.Release())
		}
		return nil, errors.Join(acquireErr, err)
	}
	return lock, acquireErr
}

// AcquireMetadataLockUnderNamespace requires the caller to hold the store gate.
// All cooperating directory removers must hold that gate and the exclusive lock.
// Missing metadata directories are created for object creation; callers must
// re-read the record under the acquired lock before acting on an existing ID.
func (l StoreLayout) AcquireMetadataLockUnderNamespace(id models.ObjectID, exclusive bool) (*Lock, error) {
	dir, err := l.ResolveObjectMetaPath(id)
	if err != nil {
		return nil, err
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("create metadata lock directory: %w", err)
	}
	path := filepath.Join(dir, "lock")
	if info, err := os.Lstat(path); err == nil {
		if !info.Mode().IsRegular() {
			return nil, fmt.Errorf("metadata lock must be a regular file: %w", apperrors.ErrInvalidPath)
		}
	} else if !os.IsNotExist(err) {
		return nil, fmt.Errorf("inspect metadata lock: %w", err)
	}
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return nil, fmt.Errorf("open metadata lock: %w", err)
	}
	if err := flockAcquire(f, exclusive); err != nil {
		return nil, errors.Join(fmt.Errorf("acquire metadata lock: %w", err), f.Close())
	}
	return &Lock{path: path, file: f}, nil
}
