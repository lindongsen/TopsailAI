// Package manager orchestrates metadata and actual-data adapters to provide
// the high-level object lifecycle operations used by the topsailai_data CLI.
package manager

import (
	"archive/tar"
	"bytes"
	"context"
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
	"gopkg.in/yaml.v3"
)

// Manager combines a MetadataAdapter and an ActualDataAdapter to implement the
// complete object lifecycle.
type Manager struct {
	// TrackStat controls best-effort object stat recording. It defaults to true.
	TrackStat bool
	// StatFlush records the configured stat persistence mode. Async currently
	// uses the synchronous best-effort writer until buffered flushing is added.
	StatFlush string
	cfg       *config.Config
	meta      adapters.MetadataAdapter
	actual    adapters.ActualDataAdapter
	metaRoot  string
}

// New creates a Manager from configuration. It initializes both adapters and
// registers the built-in local factories if they have not been registered yet.
func New(cfg *config.Config) (*Manager, error) {
	if cfg == nil {
		return nil, fmt.Errorf("%w: nil config", errors.ErrInvalidArgument)
	}

	statFlush := cfg.StatFlush
	if statFlush == "" {
		statFlush = config.DefaultStatFlush
	}

	// Register local factories if not already present.
	registerLocalFactories()

	adapterCfg := make(map[string]string, len(cfg.AdapterConfig)+1)
	for k, v := range cfg.AdapterConfig {
		adapterCfg[k] = v
	}
	storeRoot := cfg.Root
	if storeRoot != "" {
		resolvedRoot, err := filepath.Abs(storeRoot)
		if err != nil {
			return nil, fmt.Errorf("resolve store root: %w", err)
		}
		storeRoot = resolvedRoot
	}
	adapterCfg["root"] = storeRoot

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
		TrackStat: cfg.TrackStat,
		StatFlush: statFlush,
		cfg:       cfg,
		meta:      meta,
		actual:    actual,
		metaRoot:  storeRoot,
	}, nil
}

// Root returns the configured root directory.
func (m *Manager) Root() string {
	return m.metaRoot
}

// Config returns the configuration the manager was created with.
//
// It lets CLI commands read boundary configuration such as the file read limit
// without re-reading process-wide environment variables deeper in the call
// stack.
func (m *Manager) Config() *config.Config {
	return m.cfg
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
	Description string
	Classify    []string
	Tags        []string
	Data        io.Reader
}

// CreateObject creates a new object, writes initial actual data, and
// transitions the object from creating to active.
//
// Data must be non-nil and must contain a file named {name}.md. A description
// must be provided either in opts.Description or in the YAML frontmatter of
// {name}.md; otherwise the object is not created.
func (m *Manager) CreateObject(ctx context.Context, name string, opts CreateObjectOptions) (*models.Object, error) {
	if err := local.ValidateObjectName(name); err != nil {
		return nil, fmt.Errorf("%w: %v", errors.ErrInvalidName, err)
	}
	if opts.Data == nil {
		return nil, errors.ErrMissingMarkdown
	}

	// Read the actual-data stream into memory so we can validate its contents
	// and reuse it for writing.
	dataBytes, err := io.ReadAll(opts.Data)
	if err != nil {
		return nil, fmt.Errorf("read actual data: %w", err)
	}
	if len(dataBytes) == 0 {
		return nil, errors.ErrMissingMarkdown
	}

	markerName := name + ".md"
	extractedDescription, err := extractDescriptionFromArchive(dataBytes, markerName)
	if err != nil {
		return nil, err
	}

	description := opts.Description
	if description == "" {
		description = extractedDescription
	}
	if description == "" {
		return nil, errors.ErrMissingDescription
	}

	return m.publishCreatedObject(ctx, name, description, opts, dataBytes)
}

// GetObject retrieves an active object by ID. Deleted and ceased objects are
// only returned when includeDeleted is true.
func (m *Manager) GetObject(ctx context.Context, id models.ObjectID, includeDeleted bool) (*models.Object, error) {
	if m.cfg.ReadLock {
		lock, err := m.acquireExistingObjectLock(id, false)
		if err != nil {
			return nil, err
		}
		defer releaseNamespaceLock(lock)
	}
	return m.meta.Get(ctx, id, includeDeleted)
}

// UpdateObjectOptions controls which metadata fields to update.
type UpdateObjectOptions struct {
	Description *string
}

// UpdateObject updates mutable metadata fields of an active object.
func (m *Manager) UpdateObject(ctx context.Context, id models.ObjectID, opts UpdateObjectOptions) (*models.Object, error) {
	obj, lock, err := m.lockActiveObject(ctx, id)
	if err != nil {
		return nil, err
	}
	defer releaseNamespaceLock(lock)

	updated := false
	if opts.Description != nil {
		obj.Description = *opts.Description
		updated = true
	} else if obj.Description == "" {
		// Description was not provided; try to extract it from the marker file's
		// YAML frontmatter. This is best-effort; failures are ignored.
		layout, err := local.NewStoreLayout(m.metaRoot)
		if err != nil {
			return nil, err
		}
		objectDir, err := layout.ResolveObjectRef(obj.DataRef)
		if err != nil {
			return nil, err
		}
		markerPath := filepath.Join(objectDir, string(id)+".md")
		if extracted := extractDescriptionFromMarkdown(markerPath); extracted != "" {
			obj.Description = extracted
			updated = true
		}
	}
	if updated {
		obj.UpdatedAt = time.Now()
		if err := m.meta.Update(ctx, obj); err != nil {
			return nil, fmt.Errorf("update metadata: %w", err)
		}
	}

	m.recordWrite(ctx, obj)
	return obj, nil
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
	obj, lock, err := m.lockActiveObject(ctx, id)
	if err != nil {
		return err
	}
	defer releaseNamespaceLock(lock)

	if _, err := m.actual.WriteArchive(ctx, obj.DataRef, r); err != nil {
		return fmt.Errorf("write archive: %w", err)
	}

	obj.UpdatedAt = time.Now()
	if err := m.meta.Update(ctx, obj); err != nil {
		return err
	}
	m.recordWrite(ctx, obj)
	return nil
}

// WriteActualFile writes a single file into the object's actual data.
func (m *Manager) WriteActualFile(ctx context.Context, id models.ObjectID, filename string, r io.Reader) error {
	obj, lock, err := m.lockActiveObject(ctx, id)
	if err != nil {
		return err
	}
	defer releaseNamespaceLock(lock)

	if _, err := m.actual.WriteFile(ctx, obj.DataRef, filename, r); err != nil {
		return fmt.Errorf("write file: %w", err)
	}

	obj.UpdatedAt = time.Now()
	if err := m.meta.Update(ctx, obj); err != nil {
		return err
	}
	m.recordWrite(ctx, obj)
	return nil
}

// ReadActualArchive returns a tar archive stream of the object's actual data.
func (m *Manager) ReadActualArchive(ctx context.Context, id models.ObjectID) (io.ReadCloser, error) {
	obj, lock, err := m.readActiveObject(ctx, id)
	if err != nil {
		return nil, err
	}
	reader, err := m.actual.ReadArchive(ctx, obj.DataRef)
	if err != nil {
		if lock != nil {
			releaseNamespaceLock(lock)
		}
		return nil, err
	}
	m.recordRead(ctx, obj, lock)
	if lock != nil {
		return &lockedReadCloser{ReadCloser: reader, lock: lock}, nil
	}
	return reader, nil
}

// ReadActualFile returns a stream for a single file from the object's actual data.
func (m *Manager) ReadActualFile(ctx context.Context, id models.ObjectID, filename string) (io.ReadCloser, error) {
	obj, lock, err := m.readActiveObject(ctx, id)
	if err != nil {
		return nil, err
	}
	reader, err := m.actual.ReadFile(ctx, obj.DataRef, filename)
	if err != nil {
		if lock != nil {
			releaseNamespaceLock(lock)
		}
		return nil, err
	}
	m.recordRead(ctx, obj, lock)
	if lock != nil {
		return &lockedReadCloser{ReadCloser: reader, lock: lock}, nil
	}
	return reader, nil
}

// MoveObject moves an active object to a new classify path. The object name
// does not change. If classify begins with the object's time prefix, that
// prefix is stripped so users may pass either a classify path or a full path.
// If the trailing segment equals the object name, it is also stripped.
func (m *Manager) MoveObject(ctx context.Context, id models.ObjectID, classify []string) error {
	obj, release, err := m.lockLifecycleObject(ctx, id)
	if err != nil {
		return err
	}
	defer release()
	if obj.Status != models.ObjectStatusActive {
		return fmt.Errorf("%w: object %s is %s", errors.ErrObjectNotActive, id, obj.Status)
	}
	classify = normalizeClassifyForMove(obj.CreatedAt, obj.Name, classify)
	newRef, err := local.BuildObjectPath(obj.CreatedAt, classify, obj.Name)
	if err != nil {
		return err
	}
	if newRef == obj.DataRef {
		return nil
	}
	layout, err := local.NewStoreLayout(m.metaRoot)
	if err != nil {
		return err
	}
	destination, err := layout.ResolveObjectRef(newRef)
	if err != nil {
		return err
	}
	if err := local.CheckNamespaceDestination(layout.ObjectRoot(), destination); err != nil {
		return err
	}
	oldRef := obj.DataRef
	movedRef, err := m.actual.Move(ctx, oldRef, newRef)
	if err != nil {
		return fmt.Errorf("copy move target; source remains authoritative: %w", err)
	}
	obj.Path = newRef
	obj.DataRef = movedRef
	obj.UpdatedAt = time.Now()
	if err := m.meta.Update(ctx, obj); err != nil {
		return fmt.Errorf("publish move metadata; source and target retained: %w", err)
	}
	if err := m.actual.Delete(ctx, oldRef); err != nil {
		return fmt.Errorf("move published at %q but old payload %q cleanup failed: %w", movedRef, oldRef, err)
	}
	m.recordWrite(ctx, obj)
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

// RestoreObject restores a soft-deleted object back to active.
//
// Only objects whose status is "deleted" can be restored. If r is provided,
// it is written as the object's actual data before the status is changed. If
// r is nil, the object is only restored when its actual data still exists.
func (m *Manager) RestoreObject(ctx context.Context, id models.ObjectID, r io.Reader) error {
	obj, release, err := m.lockLifecycleObject(ctx, id)
	if err != nil {
		return err
	}
	defer release()

	if obj.Status != models.ObjectStatusDeleted {
		switch obj.Status {
		case models.ObjectStatusActive:
			return fmt.Errorf("%w: object %s is already active", errors.ErrObjectExists, id)
		case models.ObjectStatusCreating:
			return fmt.Errorf("%w: object %s is still being created; use gc to clean up creating objects", errors.ErrObjectCreating, id)
		case models.ObjectStatusCeased:
			return fmt.Errorf("%w: object %s has ceased and cannot be restored", errors.ErrObjectCeased, id)
		default:
			return fmt.Errorf("%w: object %s has unexpected status %s", errors.ErrInvalidStatus, id, obj.Status)
		}
	}

	if r != nil {
		if _, err := m.actual.WriteArchive(ctx, obj.DataRef, r); err != nil {
			return fmt.Errorf("restore write actual data: %w", err)
		}
	} else {
		exists, err := m.actual.Exists(ctx, obj.DataRef)
		if err != nil {
			return fmt.Errorf("restore check actual data: %w", err)
		}
		if !exists {
			return fmt.Errorf("%w: object %s actual data is missing; provide --from to restore", errors.ErrInvalidArgument, id)
		}
	}

	obj.Status = models.ObjectStatusActive
	obj.DeletedAt = nil
	obj.UpdatedAt = time.Now()
	if err := m.meta.Update(ctx, obj); err != nil {
		return fmt.Errorf("restore deleted object: %w", err)
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

// normalizeTags validates every tag and removes duplicates while preserving
// the caller's order.
func normalizeTags(tags []string) ([]string, error) {
	if len(tags) == 0 {
		return nil, nil
	}
	for _, tag := range tags {
		if err := local.ValidateTag(tag); err != nil {
			return nil, fmt.Errorf("%w: %v", errors.ErrInvalidTag, err)
		}
	}
	return local.MergeTags(nil, tags), nil
}

// AddTag adds a tag to an active object.
func (m *Manager) AddTag(ctx context.Context, id models.ObjectID, tag string) error {
	if err := local.ValidateTag(tag); err != nil {
		return fmt.Errorf("%w: %v", errors.ErrInvalidTag, err)
	}
	obj, lock, err := m.lockActiveObject(ctx, id)
	if err != nil {
		return err
	}
	defer releaseNamespaceLock(lock)
	if err := m.meta.AddTag(ctx, id, tag); err != nil {
		return err
	}
	m.recordWrite(ctx, obj)
	return nil
}

// RemoveTag removes a tag from an active object.
func (m *Manager) RemoveTag(ctx context.Context, id models.ObjectID, tag string) error {
	if err := local.ValidateTag(tag); err != nil {
		return fmt.Errorf("%w: %v", errors.ErrInvalidTag, err)
	}
	obj, lock, err := m.lockActiveObject(ctx, id)
	if err != nil {
		return err
	}
	defer releaseNamespaceLock(lock)
	if err := m.meta.RemoveTag(ctx, id, tag); err != nil {
		return err
	}
	m.recordWrite(ctx, obj)
	return nil
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

// extractDescriptionFromMarkdown attempts to read a YAML frontmatter block
// from the beginning of path and return the value of the "description" key.
// Any error (missing frontmatter, invalid YAML, missing key, non-string value)
// results in an empty string.
func extractDescriptionFromMarkdown(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()

	const maxFrontmatterSize = 8 * 1024
	buf := make([]byte, maxFrontmatterSize)
	n, err := f.Read(buf)
	if err != nil && err != io.EOF {
		return ""
	}
	return parseDescriptionFromFrontmatter(buf[:n])
}

// extractDescriptionFromArchive inspects a tar archive represented by data and
// returns the value of the "description" key from the YAML frontmatter of the
// file named markerName. It also validates that the archive contains the
// required marker file. Any error parsing the archive or missing marker file
// results in an error.
func extractDescriptionFromArchive(data []byte, markerName string) (string, error) {
	tr := tar.NewReader(bytes.NewReader(data))
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return "", fmt.Errorf("parse archive: %w", err)
		}
		if hdr.Typeflag != tar.TypeReg && hdr.Typeflag != tar.TypeRegA {
			continue
		}
		cleanName := filepath.Clean(hdr.Name)
		if cleanName == filepath.Clean(markerName) {
			const maxFrontmatterSize = 8 * 1024
			buf := make([]byte, maxFrontmatterSize)
			n, err := tr.Read(buf)
			if err != nil && err != io.EOF {
				return "", fmt.Errorf("read %s from archive: %w", markerName, err)
			}
			return parseDescriptionFromFrontmatter(buf[:n]), nil
		}
	}
	return "", fmt.Errorf("%w: archive must contain %s", errors.ErrMissingMarkdown, markerName)
}

// parseDescriptionFromFrontmatter attempts to read a YAML frontmatter block
// from the beginning of content and return the value of the "description" key.
// Any error results in an empty string.
func parseDescriptionFromFrontmatter(content []byte) string {
	text := strings.ReplaceAll(string(content), "\r\n", "\n")
	if !strings.HasPrefix(text, "---\n") {
		return ""
	}
	frontmatterContent := text[4:]
	end := strings.Index(frontmatterContent, "\n---\n")
	if end < 0 && strings.HasSuffix(frontmatterContent, "\n---") {
		end = len(frontmatterContent) - len("\n---")
	}
	if end < 0 {
		return ""
	}
	frontmatter := frontmatterContent[:end+1]

	var meta map[string]interface{}
	if err := yaml.Unmarshal([]byte(frontmatter), &meta); err != nil {
		return ""
	}
	v, ok := meta["description"]
	if !ok {
		return ""
	}
	s, ok := v.(string)
	if !ok {
		return ""
	}
	return strings.TrimSpace(s)
}
