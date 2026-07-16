// Package manager orchestrates metadata and actual-data adapters to provide
// the high-level object lifecycle operations used by the topsailai_data CLI.
package manager

import (
	"context"
	stderrors "errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters"
	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/config"
	"github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// Manager combines a MetadataAdapter and an ActualDataAdapter to implement the
// complete object lifecycle.
type Manager struct {
	cfg      *config.Config
	meta     adapters.MetadataAdapter
	actual   adapters.ActualDataAdapter
	metaRoot string
}

// New creates a Manager from configuration. It initializes both adapters and
// registers the built-in local factories if they have not been registered yet.
func New(cfg *config.Config) (*Manager, error) {
	if cfg == nil {
		return nil, fmt.Errorf("%w: nil config", errors.ErrInvalidArgument)
	}

	// Register local factories if not already present.
	registerLocalFactories()

	adapterCfg := make(map[string]string, len(cfg.AdapterConfig)+1)
	for k, v := range cfg.AdapterConfig {
		adapterCfg[k] = v
	}
	adapterCfg["root"] = cfg.Root

	ctx := context.Background()
	meta, err := adapters.NewMetadataAdapter(ctx, cfg.MetadataAdapter, adapterCfg)
	if err != nil {
		return nil, fmt.Errorf("create metadata adapter: %w", err)
	}
	actual, err := adapters.NewActualDataAdapter(ctx, cfg.ActualDataAdapter, adapterCfg)
	if err != nil {
		return nil, fmt.Errorf("create actual-data adapter: %w", err)
	}

	if err := meta.Init(ctx); err != nil {
		return nil, fmt.Errorf("init metadata adapter: %w", err)
	}
	if err := actual.Init(ctx); err != nil {
		return nil, fmt.Errorf("init actual-data adapter: %w", err)
	}

	return &Manager{
		cfg:      cfg,
		meta:     meta,
		actual:   actual,
		metaRoot: cfg.Root,
	}, nil
}

// Root returns the configured root directory.
func (m *Manager) Root() string {
	return m.metaRoot
}

var localFactoriesRegistered bool

func registerLocalFactories() {
	if localFactoriesRegistered {
		return
	}
	adapters.RegisterMetadataAdapter("local", func(ctx context.Context, cfg map[string]string) (adapters.MetadataAdapter, error) {
		root := cfg["root"]
		if root == "" {
			return nil, fmt.Errorf("%w: local metadata adapter requires root", errors.ErrAdapterConfig)
		}
		return local.NewMetadataAdapter(root), nil
	})
	adapters.RegisterActualDataAdapter("local", func(ctx context.Context, cfg map[string]string) (adapters.ActualDataAdapter, error) {
		root := cfg["root"]
		if root == "" {
			return nil, fmt.Errorf("%w: local actual-data adapter requires root", errors.ErrAdapterConfig)
		}
		return local.NewActualDataAdapter(root), nil
	})
	localFactoriesRegistered = true
}

// Close releases resources held by the underlying adapters.
func (m *Manager) Close() error {
	var errs []error
	if err := m.meta.Close(); err != nil {
		errs = append(errs, fmt.Errorf("close metadata adapter: %w", err))
	}
	if err := m.actual.Close(); err != nil {
		errs = append(errs, fmt.Errorf("close actual-data adapter: %w", err))
	}
	if len(errs) > 0 {
		return errs[0]
	}
	return nil
}

// CreateObjectOptions controls optional behavior for CreateObject.
type CreateObjectOptions struct {
	Classify []string
	Tags     []string
	Data     io.Reader
}

// CreateObject creates a new object, writes optional initial actual data, and
// transitions the object from creating to active.
//
// If Data is nil, the object is created with an empty actual-data folder.
// If Data is non-nil it is interpreted as a tar archive stream.
func (m *Manager) CreateObject(ctx context.Context, name string, opts CreateObjectOptions) (*models.Object, error) {
	if err := local.ValidateObjectName(name); err != nil {
		return nil, fmt.Errorf("%w: %v", errors.ErrInvalidName, err)
	}

	id := models.ObjectID(name)
	// The local adapter uses the object name as its stable ID. Reject creation
	// if an active, creating, or deleted object already uses this ID. A ceased
	// object may be overwritten by purging it first.
	if existing, err := m.meta.Get(ctx, id, true); err == nil {
		switch existing.Status {
		case models.ObjectStatusCeased:
			if err := m.meta.Purge(ctx, id); err != nil {
				return nil, fmt.Errorf("purge ceased object: %w", err)
			}
		default:
			return nil, fmt.Errorf("%w: %s", errors.ErrObjectExists, id)
		}
	} else if !stderrors.Is(err, errors.ErrObjectNotFound) {
		return nil, fmt.Errorf("check existing object: %w", err)
	}

	now := time.Now()
	objectPath, err := local.BuildObjectPath(now, opts.Classify, name)
	if err != nil {
		return nil, err
	}

	objectDir := filepath.Join(m.metaRoot, objectPath)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCreating,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}

	// Step 1: create metadata in creating state.
	if err := m.meta.Create(ctx, obj); err != nil {
		return nil, fmt.Errorf("create metadata: %w", err)
	}
	lock, err := local.AcquireWriteLock(objectDir)
	if err != nil {
		_ = os.RemoveAll(objectDir)
		return nil, fmt.Errorf("acquire object lock: %w", err)
	}

	success := false
	defer func() {
		if !success {
			_ = os.RemoveAll(objectDir)
		}
		lock.Release()
	}()

	// Step 3: write the required {name}.md marker file.
	markerPath := filepath.Join(objectDir, name+".md")
	if err := os.WriteFile(markerPath, []byte{}, 0o644); err != nil {
		return nil, fmt.Errorf("create object marker file: %w", err)
	}

	// Step 4: write initial tags.
	if len(opts.Tags) > 0 {
		tagsFile := filepath.Join(objectDir, name+".tags")
		if err := local.WriteTagsFile(tagsFile, opts.Tags); err != nil {
			return nil, fmt.Errorf("write tags: %w", err)
		}
	}

	// Step 5: write actual data if provided.
	if opts.Data != nil {
		if _, err := m.actual.WriteArchive(ctx, obj.DataRef, opts.Data); err != nil {
			return nil, fmt.Errorf("write actual data: %w", err)
		}
	}

	// Step 6: promote to active.
	obj.Status = models.ObjectStatusActive
	obj.UpdatedAt = time.Now()
	if err := m.meta.Update(ctx, obj); err != nil {
		return nil, fmt.Errorf("activate object: %w", err)
	}

	success = true
	return m.GetObject(ctx, id, false)
}

// GetObject retrieves an active object by ID. Deleted and ceased objects are
// only returned when includeDeleted is true.
func (m *Manager) GetObject(ctx context.Context, id models.ObjectID, includeDeleted bool) (*models.Object, error) {
	if m.cfg.ReadLock {
		objectDir, err := m.objectDir(ctx, id)
		if err != nil {
			return nil, err
		}
		lock, err := local.AcquireReadLock(objectDir)
		if err != nil {
			return nil, fmt.Errorf("acquire read lock: %w", err)
		}
		defer lock.Release()
	}
	return m.meta.Get(ctx, id, includeDeleted)
}

// ListObjects returns a paginated list of active objects.
func (m *Manager) ListObjects(ctx context.Context, opts models.ListOptions) ([]*models.Object, error) {
	return m.meta.List(ctx, opts)
}

// SearchObjects searches active objects by name or tags. The terms slice
// follows OR semantics: an object matches if its name or any tag contains at
// least one term as a substring.
func (m *Manager) SearchObjects(ctx context.Context, terms []string, opts models.ListOptions) ([]*models.Object, error) {
	return m.meta.Search(ctx, terms, opts)
}

// UpdateActualData replaces the actual data of an active object with a tar
// archive stream.
func (m *Manager) UpdateActualData(ctx context.Context, id models.ObjectID, r io.Reader) error {
	obj, err := m.requireActive(ctx, id)
	if err != nil {
		return err
	}

	lock, err := local.AcquireWriteLock(obj.DataRef)
	if err != nil {
		return fmt.Errorf("acquire write lock: %w", err)
	}
	defer lock.Release()

	if _, err := m.actual.WriteArchive(ctx, obj.DataRef, r); err != nil {
		return fmt.Errorf("write archive: %w", err)
	}

	obj.UpdatedAt = time.Now()
	return m.meta.Update(ctx, obj)
}

// WriteActualFile writes a single file into the object's actual data.
func (m *Manager) WriteActualFile(ctx context.Context, id models.ObjectID, filename string, r io.Reader) error {
	obj, err := m.requireActive(ctx, id)
	if err != nil {
		return err
	}

	lock, err := local.AcquireWriteLock(obj.DataRef)
	if err != nil {
		return fmt.Errorf("acquire write lock: %w", err)
	}
	defer lock.Release()

	if _, err := m.actual.WriteFile(ctx, obj.DataRef, filename, r); err != nil {
		return fmt.Errorf("write file: %w", err)
	}

	obj.UpdatedAt = time.Now()
	return m.meta.Update(ctx, obj)
}

// ReadActualArchive returns a tar archive stream of the object's actual data.
func (m *Manager) ReadActualArchive(ctx context.Context, id models.ObjectID) (io.ReadCloser, error) {
	obj, err := m.requireActive(ctx, id)
	if err != nil {
		return nil, err
	}

	if m.cfg.ReadLock {
		lock, err := local.AcquireReadLock(obj.DataRef)
		if err != nil {
			return nil, fmt.Errorf("acquire read lock: %w", err)
		}
		archiveReader, err := m.actual.ReadArchive(ctx, obj.DataRef)
		if err != nil {
			_ = lock.Release()
			return nil, err
		}
		// Wrap the reader so the lock is released when the stream is closed.
		return &lockedReadCloser{
			ReadCloser: archiveReader,
			lock:       lock,
		}, nil
	}

	return m.actual.ReadArchive(ctx, obj.DataRef)
}

// ReadActualFile returns a stream for a single file from the object's actual data.
func (m *Manager) ReadActualFile(ctx context.Context, id models.ObjectID, filename string) (io.ReadCloser, error) {
	obj, err := m.requireActive(ctx, id)
	if err != nil {
		return nil, err
	}

	if m.cfg.ReadLock {
		lock, err := local.AcquireReadLock(obj.DataRef)
		if err != nil {
			return nil, fmt.Errorf("acquire read lock: %w", err)
		}
		f, err := m.actual.ReadFile(ctx, obj.DataRef, filename)
		if err != nil {
			_ = lock.Release()
			return nil, err
		}
		return &lockedReadCloser{ReadCloser: f, lock: lock}, nil
	}

	return m.actual.ReadFile(ctx, obj.DataRef, filename)
}

// DeleteObject soft-deletes an active object or finalizes a deleted object.
//
// For an active object, the metadata is marked as deleted and the actual data
// is preserved so the object can be recovered. The object is not visible to
// normal list/get operations after this call.
//
// For an already-deleted object, the actual data is removed and the metadata
// is transitioned to ceased. If actual-data removal fails, the object remains
// in the deleted state and can be retried.
//
// Ceased objects are treated as not found. Creating objects must be handled
// through RecoverObject.
func (m *Manager) DeleteObject(ctx context.Context, id models.ObjectID) error {
	obj, err := m.meta.Get(ctx, id, true)
	if err != nil {
		return err
	}

	switch obj.Status {
	case models.ObjectStatusActive:
		lock, err := local.AcquireWriteLock(obj.DataRef)
		if err != nil {
			return fmt.Errorf("acquire write lock: %w", err)
		}
		defer lock.Release()

		if err := m.meta.Delete(ctx, id); err != nil {
			return fmt.Errorf("mark metadata deleted: %w", err)
		}
		return nil

	case models.ObjectStatusDeleted:
		lock, err := local.AcquireWriteLock(obj.DataRef)
		if err != nil {
			return fmt.Errorf("acquire write lock: %w", err)
		}
		defer lock.Release()

		if err := m.actual.Delete(ctx, obj.DataRef); err != nil {
			return fmt.Errorf("delete actual data: %w", err)
		}

		if err := m.meta.FinalizeDelete(ctx, id); err != nil {
			return fmt.Errorf("finalize delete: %w", err)
		}

		// The object has ceased; remove the advisory lock file and clean up
		// any empty parent directories.
		_ = os.Remove(lock.Path())
		_ = local.RemoveEmptyParents(obj.DataRef, m.metaRoot)
		return nil

	case models.ObjectStatusCreating:
		return fmt.Errorf("%w: object %s is %s, use RecoverObject", errors.ErrObjectNotActive, id, obj.Status)
	case models.ObjectStatusCeased:
		return fmt.Errorf("%w: object %s is already ceased", errors.ErrObjectNotFound, id)
	default:
		return fmt.Errorf("%w: object %s has unexpected status %s", errors.ErrObjectNotActive, id, obj.Status)
	}
}

// MoveObject moves an active object to a new classify path. The object name
// does not change. If classify begins with the object's time prefix, that
// prefix is stripped so users may pass either a classify path or a full path.
// If the trailing segment equals the object name, it is also stripped.
func (m *Manager) MoveObject(ctx context.Context, id models.ObjectID, classify []string) error {
	obj, err := m.requireActive(ctx, id)
	if err != nil {
		return err
	}

	classify = normalizeClassifyForMove(obj.CreatedAt, obj.Name, classify)

	newPath, err := local.BuildObjectPath(obj.CreatedAt, classify, obj.Name)
	if err != nil {
		return err
	}
	newRef := filepath.Join(m.metaRoot, newPath)
	if newRef == obj.DataRef {
		return nil
	}

	// Safety: refuse to move a directory into a subdirectory of itself.
	if strings.HasPrefix(newRef+string(filepath.Separator), obj.DataRef+string(filepath.Separator)) {
		return fmt.Errorf("destination is inside the source object folder")
	}

	lock, err := local.AcquireWriteLock(obj.DataRef)
	if err != nil {
		return fmt.Errorf("acquire write lock: %w", err)
	}
	defer lock.Release()

	// Ensure destination parent directories exist before moving.
	if err := os.MkdirAll(filepath.Dir(newRef), 0o755); err != nil {
		return fmt.Errorf("create destination parent: %w", err)
	}

	oldRef := obj.DataRef
	movedRef, err := m.actual.Move(ctx, oldRef, newRef)
	if err != nil {
		return fmt.Errorf("move actual data: %w", err)
	}

	obj.Path = newPath
	obj.DataRef = movedRef
	obj.UpdatedAt = time.Now()
	if err := m.meta.Update(ctx, obj); err != nil {
		// Best-effort rollback: move actual data back to the original reference.
		_, _ = m.actual.Move(ctx, movedRef, oldRef)
		return fmt.Errorf("update metadata after move: %w", err)
	}

	// After successful metadata update, remove the old directory and clean up
	// any empty parent directories.
	_ = os.RemoveAll(oldRef)
	_ = local.RemoveEmptyParents(oldRef, m.metaRoot)
	return nil
}

// normalizeClassifyForMove strips a leading time-prefix-like segment sequence
// (YYYY/MMDD/HHMM) from classify segments when the user supplied a full path,
// and also strips a trailing segment that equals the object name. The object's
// own creation time is always used as the time prefix, so any leading
// time-prefix pattern in the user input is discarded.
func normalizeClassifyForMove(createdAt time.Time, name string, classify []string) []string {
	if len(classify) >= 3 && isTimePrefix(classify[0], classify[1], classify[2]) {
		classify = classify[3:]
	}
	if len(classify) > 0 && classify[len(classify)-1] == name {
		classify = classify[:len(classify)-1]
	}
	return classify
}

// isTimePrefix reports whether the three segments look like a time prefix
// produced by local.TimePath: YYYY/MMDD/HHMM.
func isTimePrefix(year, monthDay, hourMinute string) bool {
	if len(year) != 4 || len(monthDay) != 4 || len(hourMinute) != 4 {
		return false
	}
	for _, s := range []string{year, monthDay, hourMinute} {
		for _, r := range s {
			if r < '0' || r > '9' {
				return false
			}
		}
	}
	return true
}

// RecoverObject attempts to resume or clean up a creating object, or restore
// a soft-deleted object back to active.
//
// Default behavior (resume=false):
//   - For creating objects: if actual data already exists, the object is
//     activated; otherwise the object and any partial data are removed.
//   - For deleted objects: the object is restored to active. Actual data is
//     preserved.
//   - For ceased objects: an error is returned because ceased objects cannot
//     be recovered.
//
// When resume=true:
//   - If r is provided, it is written as the object's actual data and the
//     object is activated.
//   - If r is nil and actual data exists, the object is activated.
//   - If r is nil and actual data does not exist, an error is returned so the
//     caller can supply data with --from.
func (m *Manager) RecoverObject(ctx context.Context, id models.ObjectID, resume bool, r io.Reader) error {
	// Creating objects are not visible through Get; load via Recover list.
	creating, err := m.meta.Recover(ctx)
	if err != nil {
		return fmt.Errorf("list creating objects: %w", err)
	}
	for _, candidate := range creating {
		if candidate.ID == id {
			return m.recoverCreatingObject(ctx, candidate, resume, r)
		}
	}

	// Not a creating object; resolve through metadata (including deleted/ceased).
	obj, err := m.meta.Get(ctx, id, true)
	if err != nil {
		return err
	}

	switch obj.Status {
	case models.ObjectStatusDeleted:
		objectDir := filepath.Join(m.metaRoot, obj.Path)
		lock, err := local.AcquireWriteLock(objectDir)
		if err != nil {
			return fmt.Errorf("acquire write lock: %w", err)
		}
		defer lock.Release()

		obj.Status = models.ObjectStatusActive
		obj.DeletedAt = nil
		obj.UpdatedAt = time.Now()
		if err := m.meta.Update(ctx, obj); err != nil {
			return fmt.Errorf("restore deleted object: %w", err)
		}
		return nil

	case models.ObjectStatusCeased:
		return fmt.Errorf("%w: object %s has ceased and cannot be recovered", errors.ErrObjectCeased, id)
	case models.ObjectStatusActive:
		return fmt.Errorf("%w: object %s is already active", errors.ErrObjectExists, id)
	case models.ObjectStatusCreating:
		// Should not happen because we checked the Recover list above.
		return fmt.Errorf("%w: object %s is still being created", errors.ErrObjectCreating, id)
	default:
		return fmt.Errorf("%w: object %s has unexpected status %s", errors.ErrInvalidStatus, id, obj.Status)
	}
}

// recoverCreatingObject resumes or cleans up a single creating object.
func (m *Manager) recoverCreatingObject(ctx context.Context, obj *models.Object, resume bool, r io.Reader) error {
	objectDir := filepath.Join(m.metaRoot, obj.Path)
	lock, err := local.AcquireWriteLock(objectDir)
	if err != nil {
		return fmt.Errorf("acquire write lock: %w", err)
	}
	defer lock.Release()

	// Explicit resume with provided data: write the archive and activate.
	if resume && r != nil {
		if _, err := m.actual.WriteArchive(ctx, obj.DataRef, r); err != nil {
			return fmt.Errorf("recover write actual data: %w", err)
		}
		obj.Status = models.ObjectStatusActive
		obj.UpdatedAt = time.Now()
		return m.meta.Update(ctx, obj)
	}

	exists, err := m.actual.Exists(ctx, obj.DataRef)
	if err != nil {
		return fmt.Errorf("check actual data: %w", err)
	}

	if exists {
		obj.Status = models.ObjectStatusActive
		obj.UpdatedAt = time.Now()
		return m.meta.Update(ctx, obj)
	}

	if resume {
		return fmt.Errorf("%w: object %s has no actual data; provide --from to resume creation", errors.ErrInvalidArgument, obj.ID)
	}

	// Default cleanup: creating object never became active, remove it entirely.
	_ = m.actual.Delete(ctx, obj.DataRef)
	_ = os.RemoveAll(objectDir)
	_ = local.RemoveEmptyParents(objectDir, m.metaRoot)
	return nil
}

// GC permanently removes ceased objects whose retention period has expired.
func (m *Manager) GC(ctx context.Context) error {
	candidates, err := m.meta.GC(ctx, m.cfg.CeasedRetentionDuration())
	if err != nil {
		return fmt.Errorf("list gc candidates: %w", err)
	}

	for _, obj := range candidates {
		objectDir := filepath.Join(m.metaRoot, obj.Path)
		lock, err := local.AcquireWriteLock(objectDir)
		if err != nil {
			return fmt.Errorf("acquire lock for gc %s: %w", obj.ID, err)
		}

		// Remove actual data if any remains.
		_ = m.actual.Delete(ctx, obj.DataRef)

		// Remove metadata and the entire object folder.
		if err := os.RemoveAll(objectDir); err != nil {
			_ = lock.Release()
			return fmt.Errorf("remove object directory %q: %w", objectDir, err)
		}
		_ = lock.Release()

		// Clean up any empty parent directories, stopping at the adapter root.
		_ = local.RemoveEmptyParents(objectDir, m.metaRoot)
	}

	return nil
}

// ListCreatingObjects returns objects that are still in the "creating" state.
// These objects are not visible to normal list/get operations and are intended
// for recovery or cleanup tools.
func (m *Manager) ListCreatingObjects(ctx context.Context) ([]*models.Object, error) {
	return m.meta.Recover(ctx)
}

// ListDeletedObjects returns objects whose status is "deleted".
func (m *Manager) ListDeletedObjects(ctx context.Context) ([]*models.Object, error) {
	all, err := m.meta.List(ctx, models.ListOptions{IncludeDeleted: true})
	if err != nil {
		return nil, err
	}
	var out []*models.Object
	for _, obj := range all {
		if obj.Status == models.ObjectStatusDeleted {
			out = append(out, obj)
		}
	}
	return out, nil
}

// AddTag adds a tag to an active object.
func (m *Manager) AddTag(ctx context.Context, id models.ObjectID, tag string) error {
	if err := local.ValidateTag(tag); err != nil {
		return fmt.Errorf("%w: %v", errors.ErrInvalidTag, err)
	}
	if _, err := m.requireActive(ctx, id); err != nil {
		return err
	}
	return m.meta.AddTag(ctx, id, tag)
}

// RemoveTag removes a tag from an active object.
func (m *Manager) RemoveTag(ctx context.Context, id models.ObjectID, tag string) error {
	if err := local.ValidateTag(tag); err != nil {
		return fmt.Errorf("%w: %v", errors.ErrInvalidTag, err)
	}
	if _, err := m.requireActive(ctx, id); err != nil {
		return err
	}
	return m.meta.RemoveTag(ctx, id, tag)
}

// requireActive returns the active object or an error if it is not active.
func (m *Manager) requireActive(ctx context.Context, id models.ObjectID) (*models.Object, error) {
	obj, err := m.meta.Get(ctx, id, false)
	if err != nil {
		return nil, err
	}
	if obj.Status != models.ObjectStatusActive {
		return nil, fmt.Errorf("%w: object %s is %s", errors.ErrObjectNotActive, id, obj.Status)
	}
	return obj, nil
}

// objectDir resolves the absolute object directory for an ID.
func (m *Manager) objectDir(ctx context.Context, id models.ObjectID) (string, error) {
	obj, err := m.meta.Get(ctx, id, true)
	if err != nil {
		return "", err
	}
	return filepath.Join(m.metaRoot, obj.Path), nil
}

// lockedReadCloser wraps an io.ReadCloser so that an advisory lock is released
// when the stream is closed.
type lockedReadCloser struct {
	io.ReadCloser
	lock *local.Lock
}

// Close releases the lock after closing the underlying reader.
func (l *lockedReadCloser) Close() error {
	err := l.ReadCloser.Close()
	if lockErr := l.lock.Release(); lockErr != nil && err == nil {
		err = lockErr
	}
	return err
}
