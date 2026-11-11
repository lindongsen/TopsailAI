package manager

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// publishCreatedObject retains namespace custody through boundary and record publication.
func (m *Manager) publishCreatedObject(ctx context.Context, name, description string, opts CreateObjectOptions, data []byte) (*models.Object, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	now := time.Now()
	ref, err := local.BuildObjectPath(now, opts.Classify, name)
	if err != nil {
		return nil, err
	}
	tags, err := normalizeTags(opts.Tags)
	if err != nil {
		return nil, err
	}
	layout, err := local.NewStoreLayout(m.metaRoot)
	if err != nil {
		return nil, err
	}
	gate, err := local.AcquireNamespaceLock(m.metaRoot)
	if err != nil {
		return nil, err
	}
	defer releaseNamespaceLock(gate)
	id := models.ObjectID(name)
	dir, err := layout.ResolveObjectRef(ref)
	if err != nil {
		return nil, err
	}
	if err := local.CheckNamespaceDestination(layout.ObjectRoot(), dir); err != nil {
		return nil, err
	}
	if err := m.purgeReplacedObject(ctx, layout, id); err != nil {
		return nil, err
	}
	lock, err := layout.AcquireMetadataLockUnderNamespace(id, true)
	if err != nil {
		return nil, err
	}
	defer releaseNamespaceLock(lock)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, fmt.Errorf("create payload boundary directory: %w", err)
	}
	marker, err := os.OpenFile(filepath.Join(dir, name+".md"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0o644)
	if err != nil {
		return nil, fmt.Errorf("reserve payload boundary: %w", err)
	}
	if err := marker.Close(); err != nil {
		return nil, fmt.Errorf("close payload boundary: %w", err)
	}
	obj := &models.Object{ID: id, Name: name, Path: ref, DataRef: ref,
		Status: models.ObjectStatusCreating, SchemaVersion: models.CurrentSchemaVersion,
		CreatedAt: now, UpdatedAt: now, Description: description, Tags: tags}
	if err := m.meta.Create(ctx, obj); err != nil {
		return nil, fmt.Errorf("publish creating metadata: %w", err)
	}
	if _, err := m.actual.WriteArchive(ctx, ref, bytes.NewReader(data)); err != nil {
		return nil, fmt.Errorf("write creating payload: %w", err)
	}
	obj.Status = models.ObjectStatusActive
	obj.UpdatedAt = time.Now()
	if err := m.meta.Update(ctx, obj); err != nil {
		return nil, fmt.Errorf("activate object: %w", err)
	}
	m.recordWrite(ctx, obj)
	return m.meta.Get(ctx, id, false)
}

// purgeReplacedObject serializes ceased-ID removal before opening its replacement lock.
// The caller retains namespace custody across removal and replacement.
func (m *Manager) purgeReplacedObject(ctx context.Context, layout local.StoreLayout, id models.ObjectID) error {
	existing, err := m.meta.Get(ctx, id, true)
	if errors.Is(err, apperrors.ErrObjectNotFound) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("check existing object: %w", err)
	}
	if existing.Status != models.ObjectStatusCeased {
		return fmt.Errorf("%w: %s", apperrors.ErrObjectExists, id)
	}
	lock, err := layout.AcquireMetadataLockUnderNamespace(id, true)
	if err != nil {
		return err
	}
	defer releaseNamespaceLock(lock)
	if err := m.actual.Delete(ctx, existing.DataRef); err != nil {
		return fmt.Errorf("remove ceased payload before replacement: %w", err)
	}
	if err := m.meta.Purge(ctx, id); err != nil {
		return fmt.Errorf("purge ceased object: %w", err)
	}
	return nil
}
