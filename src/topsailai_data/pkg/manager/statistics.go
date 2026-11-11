package manager

import (
	"context"
	stderrors "errors"
	"log/slog"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

const statReadDebounce = time.Minute

// recordRead counts an opened stream under existing or short-lived shared custody.
func (m *Manager) recordRead(ctx context.Context, obj *models.Object, held *local.Lock) {
	if !m.TrackStat || obj == nil || obj.Status != models.ObjectStatusActive {
		return
	}
	if held == nil {
		lock, err := m.acquireStatisticCustody(ctx, obj.ID)
		if err != nil {
			slog.Warn("cannot acquire read statistic custody", "object_id", obj.ID, "error", err)
			return
		}
		defer releaseNamespaceLock(lock)
		current, err := m.meta.Get(ctx, obj.ID, true)
		if err != nil {
			slog.Warn("cannot revalidate read statistic", "object_id", obj.ID, "error", err)
			return
		}
		if current.Status != models.ObjectStatusActive {
			return
		}
		obj = current
	}
	m.recordStat(ctx, obj, false)
}

// recordWrite counts a successful mutation while its caller retains object custody.
func (m *Manager) recordWrite(ctx context.Context, obj *models.Object) {
	if !m.TrackStat || obj == nil || obj.Status != models.ObjectStatusActive {
		return
	}
	m.recordStat(ctx, obj, true)
}

// recordStat resolves statistics by identity and serializes the entire increment.
func (m *Manager) recordStat(ctx context.Context, obj *models.Object, write bool) {
	layout, err := local.NewStoreLayout(m.metaRoot)
	if err != nil {
		slog.Warn("cannot resolve statistic layout", "object_id", obj.ID, "error", err)
		return
	}
	dir, err := layout.ObjectMetaPath(obj.ID)
	if err != nil {
		slog.Warn("cannot resolve statistic identity", "object_id", obj.ID, "error", err)
		return
	}
	if err := local.RecordStat(ctx, dir, write, time.Now(), statReadDebounce); err != nil {
		slog.Warn("failed to record object statistic", "object_id", obj.ID, "write", write, "error", err)
	}
}

// acquireStatisticCustody waits for transient contention without losing read events.
func (m *Manager) acquireStatisticCustody(ctx context.Context, id models.ObjectID) (*local.Lock, error) {
	for {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		lock, err := m.acquireExistingObjectLock(id, false)
		if !stderrors.Is(err, apperrors.ErrObjectLocked) {
			return lock, err
		}
		timer := time.NewTimer(5 * time.Millisecond)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil, ctx.Err()
		case <-timer.C:
		}
	}
}
