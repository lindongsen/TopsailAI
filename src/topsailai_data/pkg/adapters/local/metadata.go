// Package local implements a pure-local metadata adapter for topsailai_data.
package local

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// MetadataAdapter stores hash-addressed records and independent tag files
// separately from payload directories. It is safe for concurrent use within a single process
// because advisory locks are acquired by the manager layer.
type MetadataAdapter struct {
	root string
}

// NewMetadataAdapter creates a new local metadata adapter rooted at root.
func NewMetadataAdapter(root string) *MetadataAdapter {
	return &MetadataAdapter{root: root}
}

// Init validates or creates the object/meta store layout.
func (a *MetadataAdapter) Init(ctx context.Context) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	root, err := filepath.Abs(a.root)
	if err != nil {
		return fmt.Errorf("resolve store root: %w", err)
	}
	a.root = root
	layout, err := NewStoreLayout(root)
	if err != nil {
		return err
	}
	return layout.Init()
}

// metadataFile returns the record path inside a hash-addressed metadata directory.
func (a *MetadataAdapter) metadataFile(objectDir string) string {
	return filepath.Join(objectDir, "metadata.json")
}

// Create writes the initial metadata file for a new object.
func (a *MetadataAdapter) Create(ctx context.Context, obj *models.Object) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if obj == nil {
		return fmt.Errorf("nil metadata: %w", errors.ErrInvalidArgument)
	}
	if obj.SchemaVersion == 0 {
		obj.SchemaVersion = models.CurrentSchemaVersion
	}
	data, err := encodeMetadataRecord(obj)
	if err != nil {
		return err
	}
	for _, tag := range obj.Tags {
		if err := validateStoredTag(tag); err != nil {
			return err
		}
	}
	layout, err := NewStoreLayout(a.root)
	if err != nil {
		return err
	}
	dir, err := layout.ResolveObjectMetaPath(obj.ID)
	if err != nil {
		return err
	}
	path := a.metadataFile(dir)
	if _, err := os.Lstat(path); err == nil {
		return fmt.Errorf("%w: %s", errors.ErrObjectExists, obj.ID)
	} else if !os.IsNotExist(err) {
		return fmt.Errorf("inspect initial metadata: %w", err)
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("create metadata directory: %w", err)
	}
	if err := writeObjectTags(dir, obj.Tags); err != nil {
		return err
	}
	return publishMetadataRecord(path, data)
}

// Get retrieves an object's metadata. Active objects are returned by default.
// Creating, deleted and ceased objects are only returned when includeDeleted is
// true, allowing recovery and administrative tools to locate them.
func (a *MetadataAdapter) Get(ctx context.Context, id models.ObjectID, includeDeleted bool) (*models.Object, error) {
	obj, _, err := a.findObject(id)
	if err != nil {
		return nil, err
	}

	switch obj.Status {
	case models.ObjectStatusActive:
		return obj, nil
	case models.ObjectStatusCreating:
		if includeDeleted {
			return obj, nil
		}
		return nil, fmt.Errorf("%w: %s", errors.ErrObjectNotFound, id)
	case models.ObjectStatusDeleted, models.ObjectStatusCeased:
		if includeDeleted {
			return obj, nil
		}
		return nil, fmt.Errorf("%w: %s", errors.ErrObjectNotFound, id)
	default:
		return nil, fmt.Errorf("%w: unknown status %q", errors.ErrCorruptedMetadata, obj.Status)
	}
}

// findObject loads metadata and tags directly from the ID hash directory.
func (a *MetadataAdapter) findObject(id models.ObjectID) (*models.Object, string, error) {
	layout, err := NewStoreLayout(a.root)
	if err != nil {
		return nil, "", err
	}
	obj, err := layout.readMetadataRecord(id)
	if err != nil {
		return nil, "", err
	}
	dir, err := layout.ResolveObjectMetaPath(id)
	if err != nil {
		return nil, "", err
	}
	obj.Tags, err = readObjectTags(dir)
	if err != nil {
		return nil, "", err
	}
	return obj, dir, nil
}

// Update replaces the metadata file with the provided object.
func (a *MetadataAdapter) Update(ctx context.Context, obj *models.Object) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if obj == nil {
		return fmt.Errorf("nil metadata: %w", errors.ErrInvalidArgument)
	}
	if _, _, err := a.findObject(obj.ID); err != nil {
		return err
	}
	obj.UpdatedAt = time.Now()
	layout, err := NewStoreLayout(a.root)
	if err != nil {
		return err
	}
	return layout.writeMetadataRecord(obj)
}

// findObjectDir resolves the stable metadata directory; moves do not change it.
func (a *MetadataAdapter) findObjectDir(id models.ObjectID, pathHint string) (string, error) {
	_, dir, err := a.findObject(id)
	return dir, err
}

// Delete marks an active object as deleted.
func (a *MetadataAdapter) Delete(ctx context.Context, id models.ObjectID) error {
	obj, _, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusActive {
		return fmt.Errorf("%w: object %s is %s", errors.ErrObjectNotActive, id, obj.Status)
	}

	obj.Status = models.ObjectStatusDeleted
	obj.DeletedAt = ptr(time.Now())
	obj.UpdatedAt = *obj.DeletedAt
	layout, err := NewStoreLayout(a.root)
	if err != nil {
		return err
	}
	return layout.writeMetadataRecord(obj)
}

// FinalizeDelete transitions a deleted object to ceased.
func (a *MetadataAdapter) FinalizeDelete(ctx context.Context, id models.ObjectID) error {
	obj, _, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusDeleted {
		return fmt.Errorf("%w: object %s is %s, expected deleted", errors.ErrObjectNotActive, id, obj.Status)
	}

	obj.Status = models.ObjectStatusCeased
	obj.CeasedAt = ptr(time.Now())
	obj.UpdatedAt = *obj.CeasedAt
	layout, err := NewStoreLayout(a.root)
	if err != nil {
		return err
	}
	return layout.writeMetadataRecord(obj)
}

// Purge removes ceased metadata after the caller has cleaned the payload.
// Only objects in the "ceased" state may be purged.
func (a *MetadataAdapter) Purge(ctx context.Context, id models.ObjectID) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	obj, dir, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusCeased {
		return fmt.Errorf("%w: object %s is %s, expected ceased", errors.ErrObjectNotActive, id, obj.Status)
	}
	if err := os.RemoveAll(dir); err != nil {
		return fmt.Errorf("purge metadata directory %q: %w", dir, err)
	}
	slog.Info("purged object metadata directory", "id", id, "path", dir)
	return nil
}

// List returns active objects, optionally including deleted/ceased ones.
func (a *MetadataAdapter) List(ctx context.Context, opts models.ListOptions) ([]*models.Object, error) {
	objects, err := a.scanObjects(ctx, opts.IncludeDeleted)
	if err != nil {
		return nil, err
	}

	// Apply tag filtering.
	if len(opts.Tags) > 0 {
		objects = filterByTags(objects, opts.Tags)
	}

	// Apply sorting. Default to descending by time path (newest first).
	if opts.Sort != "" {
		if err := applySort(objects, opts.Sort); err != nil {
			return nil, err
		}
	} else {
		SortObjectsByTimePath(objects, false)
	}

	// Apply pagination.
	if opts.Offset < 0 {
		opts.Offset = 0
	}
	if opts.Limit < 0 {
		opts.Limit = 0
	}
	if opts.Offset >= len(objects) {
		return []*models.Object{}, nil
	}
	end := len(objects)
	if opts.Limit > 0 && opts.Offset+opts.Limit < end {
		end = opts.Offset + opts.Limit
	}
	return objects[opts.Offset:end], nil
}

// Search returns active objects whose name, tags, or classify path match any
// of the provided query terms. Terms are combined with OR semantics: an object
// matches if its name, any tag, or its path contains at least one term as a
// substring. An empty terms slice matches all objects.
func (a *MetadataAdapter) Search(ctx context.Context, terms []string, opts models.ListOptions) ([]*models.Object, error) {
	objects, err := a.scanObjects(ctx, opts.IncludeDeleted)
	if err != nil {
		return nil, err
	}

	var matches []*models.Object
	for _, obj := range objects {
		if obj.Status != models.ObjectStatusActive && !opts.IncludeDeleted {
			continue
		}
		if matchesSearchTerms(obj, terms) {
			matches = append(matches, obj)
		}
	}

	if opts.Sort != "" {
		if err := applySort(matches, opts.Sort); err != nil {
			return nil, err
		}
	} else {
		SortObjectsByTimePath(matches, false)
	}

	if opts.Offset >= len(matches) {
		return []*models.Object{}, nil
	}
	end := len(matches)
	if opts.Limit > 0 && opts.Offset+opts.Limit < end {
		end = opts.Offset + opts.Limit
	}
	return matches[opts.Offset:end], nil
}

// GC returns objects eligible for permanent cleanup.
//
// It returns creating objects (which never became active) and ceased objects.
// Creating objects are always returned so incomplete objects can be cleaned
// up. Ceased objects are returned when force is true or when their retention
// period has expired.
func (a *MetadataAdapter) GC(ctx context.Context, retention time.Duration, force bool) ([]*models.Object, error) {
	// Find creating objects using Recover, which locates metadata.json files
	// directly and does not require the mandatory object marker file.
	creating, err := a.Recover(ctx)
	if err != nil {
		return nil, err
	}

	// Find ceased objects through metadata enumeration, independent of payload markers.
	objects, err := a.scanObjects(ctx, true)
	if err != nil {
		return nil, err
	}

	var candidates []*models.Object
	candidates = append(candidates, creating...)

	cutoff := time.Now().Add(-retention)
	for _, obj := range objects {
		if obj.Status == models.ObjectStatusCeased {
			if force || (obj.CeasedAt != nil && obj.CeasedAt.Before(cutoff)) {
				candidates = append(candidates, obj)
			}
		}
	}
	return candidates, nil
}

// matchesSearchTerms reports whether an object's name, tags, or classify path
// match any of the provided terms. Matching is case-insensitive substring. An
// empty terms slice matches everything.
func matchesSearchTerms(obj *models.Object, terms []string) bool {
	if len(terms) == 0 {
		return true
	}
	name := strings.ToLower(obj.Name)
	path := strings.ToLower(obj.Path)
	for _, term := range terms {
		if term == "" {
			continue
		}
		lowerTerm := strings.ToLower(term)
		if strings.Contains(name, lowerTerm) {
			return true
		}
		if strings.Contains(path, lowerTerm) {
			return true
		}
		for _, tag := range obj.Tags {
			if strings.Contains(strings.ToLower(tag), lowerTerm) {
				return true
			}
		}
	}
	return false
}

// Recover returns objects in the creating state.
//
// Unlike normal scans, this method does not require the mandatory object
// marker file ({name}.md) to be present. A creating object may have crashed
func (a *MetadataAdapter) Recover(ctx context.Context) ([]*models.Object, error) {
	layout, err := NewStoreLayout(a.root)
	if err != nil {
		return nil, err
	}
	objects, err := layout.scanMetadataRecords(ctx)
	if err != nil {
		return nil, err
	}
	creating := []*models.Object{}
	for _, obj := range objects {
		if obj.Status == models.ObjectStatusCreating {
			creating = append(creating, obj)
		}
	}
	SortObjectsByTimePath(creating, false)
	return creating, nil
}

// Restore transitions a deleted object back to active.
func (a *MetadataAdapter) Restore(ctx context.Context, id models.ObjectID) error {
	obj, _, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusDeleted {
		return fmt.Errorf("%w: object %s is %s, expected deleted", errors.ErrObjectNotActive, id, obj.Status)
	}

	obj.Status = models.ObjectStatusActive
	obj.DeletedAt = nil
	obj.UpdatedAt = time.Now()
	layout, err := NewStoreLayout(a.root)
	if err != nil {
		return err
	}
	return layout.writeMetadataRecord(obj)
}

// AddTag appends a tag to an active object if it is not already present.
// Tags are stored only in the independent object tag file.
func (a *MetadataAdapter) AddTag(ctx context.Context, id models.ObjectID, tag string) error {
	if err := validateStoredTag(tag); err != nil {
		return err
	}
	obj, dir, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusActive {
		return fmt.Errorf("%w: object %s is %s", errors.ErrObjectNotActive, id, obj.Status)
	}

	for _, existing := range obj.Tags {
		if existing == tag {
			return nil
		}
	}

	obj.Tags = append(obj.Tags, tag)
	if err := writeObjectTags(dir, obj.Tags); err != nil {
		return err
	}
	return a.Update(ctx, obj)
}

// RemoveTag removes a tag from the independent file of an active object.
func (a *MetadataAdapter) RemoveTag(ctx context.Context, id models.ObjectID, tag string) error {
	obj, dir, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusActive {
		return fmt.Errorf("%w: object %s is %s", errors.ErrObjectNotActive, id, obj.Status)
	}

	var updated []string
	found := false
	for _, existing := range obj.Tags {
		if existing == tag {
			found = true
			continue
		}
		updated = append(updated, existing)
	}
	if !found {
		return fmt.Errorf("%w: tag %q not found", errors.ErrTagNotFound, tag)
	}

	obj.Tags = updated
	if err := writeObjectTags(dir, obj.Tags); err != nil {
		return err
	}
	return a.Update(ctx, obj)
}

// Close is a no-op for the local metadata adapter.
func (a *MetadataAdapter) Close() error {
	return nil
}

// scanObjects enumerates metadata records without traversing payloads.
func (a *MetadataAdapter) scanObjects(ctx context.Context, includeDeleted bool) ([]*models.Object, error) {
	layout, err := NewStoreLayout(a.root)
	if err != nil {
		return nil, err
	}
	all, err := layout.scanMetadataRecords(ctx)
	if err != nil {
		return nil, err
	}
	objects := []*models.Object{}
	for _, obj := range all {
		if obj.Status == models.ObjectStatusCreating {
			continue
		}
		if obj.Status == models.ObjectStatusActive || includeDeleted {
			objects = append(objects, obj)
		}
	}
	SortObjectsByTimePath(objects, false)
	return objects, nil
}

// applySort applies the requested sort order to a slice of objects.
// It returns an error for unsupported sort values.
func applySort(objects []*models.Object, sortOpt string) error {
	ascending, err := ParseSortOption(sortOpt)
	if err != nil {
		return err
	}
	SortObjectsByTimePath(objects, ascending)
	return nil
}

// filterByTags returns only objects whose Tags contain all required tags.
func filterByTags(objects []*models.Object, required []string) []*models.Object {
	var matches []*models.Object
	for _, obj := range objects {
		if hasAllTags(obj.Tags, required) {
			matches = append(matches, obj)
		}
	}
	return matches
}

// hasAllTags reports whether tags contains every tag in required.
func hasAllTags(tags, required []string) bool {
	set := make(map[string]struct{}, len(tags))
	for _, t := range tags {
		set[t] = struct{}{}
	}
	for _, r := range required {
		if _, ok := set[r]; !ok {
			return false
		}
	}
	return true
}

func ptr(t time.Time) *time.Time {
	return &t
}
