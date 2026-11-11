package manager

import (
	"context"
	"fmt"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// lockLifecycleObject retains namespace custody while locking an existing hash leaf.
func (m *Manager) lockLifecycleObject(ctx context.Context, id models.ObjectID) (*models.Object, func(), error) {
	if err := ctx.Err(); err != nil {
		return nil, nil, err
	}
	layout, err := local.NewStoreLayout(m.metaRoot)
	if err != nil {
		return nil, nil, err
	}
	gate, err := local.AcquireNamespaceLock(m.metaRoot)
	if err != nil {
		return nil, nil, err
	}
	if _, err := m.meta.Get(ctx, id, true); err != nil {
		releaseNamespaceLock(gate)
		return nil, nil, err
	}
	lock, err := layout.AcquireMetadataLockUnderNamespace(id, true)
	if err != nil {
		releaseNamespaceLock(gate)
		return nil, nil, err
	}
	release := func() { releaseNamespaceLock(lock); releaseNamespaceLock(gate) }
	obj, err := m.meta.Get(ctx, id, true)
	if err != nil {
		release()
		return nil, nil, err
	}
	if err := ctx.Err(); err != nil {
		release()
		return nil, nil, err
	}
	return obj, release, nil
}

// DeleteObject preserves payload on soft delete and metadata on finalization.
func (m *Manager) DeleteObject(ctx context.Context, id models.ObjectID) error {
	obj, release, err := m.lockLifecycleObject(ctx, id)
	if err != nil {
		return err
	}
	defer release()
	switch obj.Status {
	case models.ObjectStatusActive:
		if err := m.meta.Delete(ctx, id); err != nil {
			return fmt.Errorf("mark metadata deleted: %w", err)
		}
		return nil
	case models.ObjectStatusDeleted:
		if err := m.actual.Delete(ctx, obj.DataRef); err != nil {
			return fmt.Errorf("delete actual data: %w", err)
		}
		if err := m.meta.FinalizeDelete(ctx, id); err != nil {
			return fmt.Errorf("finalize delete: %w", err)
		}
		return nil
	case models.ObjectStatusCeased:
		return fmt.Errorf("%w: object %s is already ceased", apperrors.ErrObjectNotFound, id)
	default:
		return fmt.Errorf("%w: object %s is %s; use gc for creating objects", apperrors.ErrObjectNotActive, id, obj.Status)
	}
}

// CleanupCreatingObject removes partial data before retiring its recovery record.
func (m *Manager) CleanupCreatingObject(ctx context.Context, id models.ObjectID) error {
	return m.cleanupCreatingObject(ctx, &models.Object{ID: id})
}

// cleanupCreatingObject revalidates a candidate under namespace and object custody.
func (m *Manager) cleanupCreatingObject(ctx context.Context, candidate *models.Object) error {
	obj, release, err := m.lockLifecycleObject(ctx, candidate.ID)
	if err != nil {
		return err
	}
	defer release()
	if obj.Status != models.ObjectStatusCreating {
		return fmt.Errorf("%w: object %s is %s, expected creating", apperrors.ErrObjectNotActive, obj.ID, obj.Status)
	}
	if err := m.actual.Delete(ctx, obj.DataRef); err != nil {
		return fmt.Errorf("remove creating payload: %w", err)
	}
	now := time.Now()
	obj.Status = models.ObjectStatusCeased
	obj.CeasedAt = &now
	if err := m.meta.Update(ctx, obj); err != nil {
		return fmt.Errorf("retire creating record: %w", err)
	}
	if err := m.meta.Purge(ctx, obj.ID); err != nil {
		return fmt.Errorf("purge retired creating record: %w", err)
	}
	return nil
}

// GC cleans incomplete records and ceased records after their retention period.
func (m *Manager) GC(ctx context.Context) error { return m.GCObjects(ctx, false) }

// GCObjects revalidates every candidate while retaining its removal custody.
func (m *Manager) GCObjects(ctx context.Context, force bool) error {
	candidates, err := m.meta.GC(ctx, m.cfg.CeasedRetentionDuration(), force)
	if err != nil {
		return fmt.Errorf("list gc candidates: %w", err)
	}
	for _, obj := range candidates {
		if obj.Status == models.ObjectStatusCreating {
			if err := m.cleanupCreatingObject(ctx, obj); err != nil {
				return fmt.Errorf("cleanup creating object %s: %w", obj.ID, err)
			}
			continue
		}
		if err := m.gcCeasedObject(ctx, obj, force); err != nil {
			return err
		}
	}
	return nil
}

// gcCeasedObject does not trust the status or retention timestamp of a stale snapshot.
func (m *Manager) gcCeasedObject(ctx context.Context, candidate *models.Object, force bool) error {
	obj, release, err := m.lockLifecycleObject(ctx, candidate.ID)
	if err != nil {
		return err
	}
	defer release()
	if obj.Status != models.ObjectStatusCeased {
		return nil
	}
	cutoff := time.Now().Add(-m.cfg.CeasedRetentionDuration())
	if !force && (obj.CeasedAt == nil || !obj.CeasedAt.Before(cutoff)) {
		return nil
	}
	if err := m.actual.Delete(ctx, obj.DataRef); err != nil {
		return fmt.Errorf("remove ceased payload %s: %w", obj.ID, err)
	}
	if err := m.meta.Purge(ctx, obj.ID); err != nil {
		return fmt.Errorf("purge ceased record %s: %w", obj.ID, err)
	}
	return nil
}
