package manager

import (
	"context"
	"fmt"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// acquireExistingObjectLock never creates metadata directories for absent records.
func (m *Manager) acquireExistingObjectLock(id models.ObjectID, exclusive bool) (*local.Lock, error) {
	layout, err := local.NewStoreLayout(m.metaRoot)
	if err != nil {
		return nil, err
	}
	return layout.AcquireExistingMetadataLock(id, exclusive)
}

// lockActiveObject revalidates lifecycle and reference after acquiring write custody.
func (m *Manager) lockActiveObject(ctx context.Context, id models.ObjectID) (*models.Object, *local.Lock, error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	lock, err := m.acquireExistingObjectLock(id, true)
	if err != nil {
		return nil, nil, err
	}
	obj, err := m.meta.Get(ctx, id, true)
	if err == nil && obj.Status != models.ObjectStatusActive {
		err = fmt.Errorf("object %q is not active: %w", id, apperrors.ErrObjectNotActive)
	}
	if err != nil {
		releaseNamespaceLock(lock)
		return nil, nil, err
	}
	return obj, lock, nil
}

// readActiveObject optionally retains shared custody until the returned stream closes.
func (m *Manager) readActiveObject(ctx context.Context, id models.ObjectID) (*models.Object, *local.Lock, error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	var lock *local.Lock
	if m.cfg.ReadLock {
		var err error
		lock, err = m.acquireExistingObjectLock(id, false)
		if err != nil {
			return nil, nil, err
		}
	}
	obj, err := m.requireActive(ctx, id)
	if err != nil && lock != nil {
		releaseNamespaceLock(lock)
	}
	return obj, lock, err
}
