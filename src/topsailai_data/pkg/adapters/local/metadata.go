// Package local implements a pure-local metadata adapter for topsailai_data.
package local

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// MetadataAdapter stores object metadata as JSON files alongside the actual
// data directories. It is safe for concurrent use within a single process
// because advisory locks are acquired by the manager layer.
type MetadataAdapter struct {
	root string
}

// NewMetadataAdapter creates a new local metadata adapter rooted at root.
func NewMetadataAdapter(root string) *MetadataAdapter {
	return &MetadataAdapter{root: root}
}

// Init ensures the root directory exists.
func (a *MetadataAdapter) Init(ctx context.Context) error {
	return os.MkdirAll(a.root, 0o755)
}

// metadataFile returns the path to the metadata.json file inside an object
// directory.
func (a *MetadataAdapter) metadataFile(objectDir string) string {
	return filepath.Join(objectDir, "metadata.json")
}

// Create writes the initial metadata file for a new object.
func (a *MetadataAdapter) Create(ctx context.Context, obj *models.Object) error {
	objectDir := filepath.Join(a.root, string(obj.Path))
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		return fmt.Errorf("create object directory: %w", err)
	}

	metaPath := a.metadataFile(objectDir)
	if _, err := os.Stat(metaPath); err == nil {
		return fmt.Errorf("%w: %s", errors.ErrObjectExists, obj.ID)
	}

	if obj.SchemaVersion == 0 {
		obj.SchemaVersion = 1
	}
	data, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal metadata: %w", err)
	}
	if err := os.WriteFile(metaPath, data, 0o644); err != nil {
		return fmt.Errorf("write metadata: %w", err)
	}
	return nil
}

// Get retrieves an object's metadata. Active objects are returned by default.
// Creating, deleted and ceased objects are only returned when includeDeleted is
// true, allowing recovery and administrative tools to locate them.
func (a *MetadataAdapter) Get(ctx context.Context, id models.ObjectID, includeDeleted bool) (*models.Object, error) {
	obj, objectDir, err := a.findObject(id)
	if err != nil {
		return nil, err
	}

	// Merge tags from .tags files so that show reflects the same effective
	// tags as list and search.
	inherited, err := CollectTags(a.root, objectDir)
	if err != nil {
		return nil, fmt.Errorf("collect tags for %q: %w", objectDir, err)
	}
	obj.Tags = mergeTags(inherited, obj.Tags)

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

// findObject locates the metadata file for an object by ID anywhere under the
// root. It returns the parsed object and its directory.
func (a *MetadataAdapter) findObject(id models.ObjectID) (*models.Object, string, error) {
	var found *models.Object
	var foundDir string

	err := filepath.WalkDir(a.root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() {
			return nil
		}

		// Determine the expected object name from the directory name.
		name := filepath.Base(path)
		if name != string(id) {
			return nil
		}

		metaPath := a.metadataFile(path)
		data, err := os.ReadFile(metaPath)
		if err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}

		var obj models.Object
		if err := json.Unmarshal(data, &obj); err != nil {
			return fmt.Errorf("%w: %q: %v", errors.ErrCorruptedMetadata, metaPath, err)
		}
		if obj.ID != id {
			return nil
		}

		obj.DataRef = path
		found = &obj
		foundDir = path
		// Stop at the first match. The manager ensures unique IDs.
		return filepath.SkipAll
	})
	if err != nil {
		return nil, "", err
	}
	if found == nil {
		return nil, "", fmt.Errorf("%w: %s", errors.ErrObjectNotFound, id)
	}
	return found, foundDir, nil
}

// Update replaces the metadata file with the provided object.
func (a *MetadataAdapter) Update(ctx context.Context, obj *models.Object) error {
	_, objectDir, err := a.findObject(obj.ID)
	if err != nil {
		return err
	}

	obj.UpdatedAt = time.Now()
	data, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal metadata: %w", err)
	}
	if err := os.WriteFile(a.metadataFile(objectDir), data, 0o644); err != nil {
		return fmt.Errorf("write metadata: %w", err)
	}
	return nil
}

// Delete marks an active object as deleted.
func (a *MetadataAdapter) Delete(ctx context.Context, id models.ObjectID) error {
	obj, objectDir, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusActive {
		return fmt.Errorf("%w: object %s is %s", errors.ErrObjectNotActive, id, obj.Status)
	}

	obj.Status = models.ObjectStatusDeleted
	obj.DeletedAt = ptr(time.Now())
	obj.UpdatedAt = *obj.DeletedAt
	data, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal metadata: %w", err)
	}
	if err := os.WriteFile(a.metadataFile(objectDir), data, 0o644); err != nil {
		return fmt.Errorf("write metadata: %w", err)
	}
	return nil
}

// FinalizeDelete transitions a deleted object to ceased.
func (a *MetadataAdapter) FinalizeDelete(ctx context.Context, id models.ObjectID) error {
	obj, objectDir, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusDeleted {
		return fmt.Errorf("%w: object %s is %s, expected deleted", errors.ErrObjectNotActive, id, obj.Status)
	}

	obj.Status = models.ObjectStatusCeased
	obj.CeasedAt = ptr(time.Now())
	obj.UpdatedAt = *obj.CeasedAt
	data, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal metadata: %w", err)
	}
	if err := os.WriteFile(a.metadataFile(objectDir), data, 0o644); err != nil {
		return fmt.Errorf("write metadata: %w", err)
	}
	return nil
}
// Purge permanently removes a ceased object and its entire directory.
// Only objects in the "ceased" state may be purged.
func (a *MetadataAdapter) Purge(ctx context.Context, id models.ObjectID) error {
	obj, objectDir, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusCeased {
		return fmt.Errorf("%w: object %s is %s, expected ceased", errors.ErrObjectNotActive, id, obj.Status)
	}

	if err := os.RemoveAll(objectDir); err != nil {
		return fmt.Errorf("purge object directory %q: %w", objectDir, err)
	}
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
	var creating []*models.Object

	err := filepath.WalkDir(a.root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		if d.Name() != "metadata.json" {
			return nil
		}

		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		var obj models.Object
		if err := json.Unmarshal(data, &obj); err != nil {
			return fmt.Errorf("%w: %q: %v", errors.ErrCorruptedMetadata, path, err)
		}
		if obj.Status != models.ObjectStatusCreating {
			return nil
		}

		// Collect inherited tags based on the object directory.
		objectDir := filepath.Dir(path)
		inherited, err := CollectTags(a.root, objectDir)
		if err != nil {
			return fmt.Errorf("collect tags for %q: %w", objectDir, err)
		}
		obj.Tags = mergeTags(inherited, obj.Tags)

		creating = append(creating, &obj)
		return nil
	})
	if err != nil {
		return nil, err
	}

	SortObjectsByTimePath(creating, false)
	return creating, nil
}

// GC returns ceased objects whose retention period has expired.
func (a *MetadataAdapter) GC(ctx context.Context, retention time.Duration) ([]*models.Object, error) {
	objects, err := a.scanObjects(ctx, true)
	if err != nil {
		return nil, err
	}

	var candidates []*models.Object
	cutoff := time.Now().Add(-retention)
	for _, obj := range objects {
		if obj.Status != models.ObjectStatusCeased {
			continue
		}
		if obj.CeasedAt != nil && obj.CeasedAt.Before(cutoff) {
			candidates = append(candidates, obj)
		}
	}
	return candidates, nil
}

// AddTag appends a tag to an active object if it is not already present.
func (a *MetadataAdapter) AddTag(ctx context.Context, id models.ObjectID, tag string) error {
	obj, objectDir, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusActive {
		return fmt.Errorf("%w: object %s is %s", errors.ErrObjectNotActive, id, obj.Status)
	}

	// Read current effective tags from .tags files and merge with metadata tags.
	inherited, err := CollectTags(a.root, objectDir)
	if err != nil {
		return fmt.Errorf("collect tags for %q: %w", objectDir, err)
	}
	ownTagsFile := filepath.Join(objectDir, string(id)+".tags")
	ownTags, err := ReadTagsFile(ownTagsFile)
	if err != nil {
		return fmt.Errorf("read object tags: %w", err)
	}
	effective := mergeTags(inherited, ownTags)

	for _, existing := range effective {
		if existing == tag {
			return nil
		}
	}

	// Persist the new tag to the object's own .tags file and update metadata.
	ownTags = append(ownTags, tag)
	if err := WriteTagsFile(ownTagsFile, ownTags); err != nil {
		return fmt.Errorf("write object tags: %w", err)
	}
	obj.Tags = mergeTags(inherited, ownTags)
	return a.Update(ctx, obj)
}

// RemoveTag removes a tag from an active object.
func (a *MetadataAdapter) RemoveTag(ctx context.Context, id models.ObjectID, tag string) error {
	obj, objectDir, err := a.findObject(id)
	if err != nil {
		return err
	}
	if obj.Status != models.ObjectStatusActive {
		return fmt.Errorf("%w: object %s is %s", errors.ErrObjectNotActive, id, obj.Status)
	}

	ownTagsFile := filepath.Join(objectDir, string(id)+".tags")
	ownTags, err := ReadTagsFile(ownTagsFile)
	if err != nil {
		return fmt.Errorf("read object tags: %w", err)
	}

	// Tags inherited from classify directories cannot be removed at the object level.
	// Collect tags from ancestor directories only (exclude the object folder itself).
	inherited, err := CollectTags(a.root, filepath.Dir(objectDir))
	if err != nil {
		return fmt.Errorf("collect inherited tags for %q: %w", objectDir, err)
	}
	for _, inheritedTag := range inherited {
		if inheritedTag == tag {
			return fmt.Errorf("%w: tag %q is inherited and cannot be removed from object", errors.ErrInvalidArgument, tag)
		}
	}

	var updated []string
	found := false
	for _, existing := range ownTags {
		if existing == tag {
			found = true
			continue
		}
		updated = append(updated, existing)
	}
	if !found {
		return fmt.Errorf("%w: tag %q not found", errors.ErrTagNotFound, tag)
	}

	if err := WriteTagsFile(ownTagsFile, updated); err != nil {
		return fmt.Errorf("write object tags: %w", err)
	}
	obj.Tags = mergeTags(inherited, updated)
	return a.Update(ctx, obj)
}

// Close is a no-op for the local metadata adapter.
func (a *MetadataAdapter) Close() error {
	return nil
}

// scanObjects walks the root and returns all objects with metadata files.
func (a *MetadataAdapter) scanObjects(ctx context.Context, includeDeleted bool) ([]*models.Object, error) {
	var objects []*models.Object

	err := filepath.WalkDir(a.root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() {
			return nil
		}

		// Object boundary rule: a directory is an object if it contains a
		// markdown file with the same name as the directory.
		name := filepath.Base(path)
		marker := filepath.Join(path, name+".md")
		if _, err := os.Stat(marker); err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}

		metaPath := a.metadataFile(path)
		data, err := os.ReadFile(metaPath)
		if err != nil {
			if os.IsNotExist(err) {
				return nil
			}
			return err
		}

		var obj models.Object
		if err := json.Unmarshal(data, &obj); err != nil {
			return fmt.Errorf("%w: %q: %v", errors.ErrCorruptedMetadata, metaPath, err)
		}

		// Collect inherited tags from ancestor .tags files.
		inherited, err := CollectTags(a.root, path)
		if err != nil {
			return fmt.Errorf("collect tags for %q: %w", path, err)
		}
		obj.Tags = mergeTags(inherited, obj.Tags)

		if obj.Status == models.ObjectStatusActive || includeDeleted {
			objects = append(objects, &obj)
		}

		// Do not recurse into object directories.
		return filepath.SkipDir
	})
	if err != nil {
		return nil, err
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

// mergeTags combines inherited and explicit tags without duplicates.
func mergeTags(inherited, explicit []string) []string {
	seen := make(map[string]struct{}, len(inherited)+len(explicit))
	var result []string
	for _, tag := range inherited {
		if _, ok := seen[tag]; ok {
			continue
		}
		seen[tag] = struct{}{}
		result = append(result, tag)
	}
	for _, tag := range explicit {
		if _, ok := seen[tag]; ok {
			continue
		}
		seen[tag] = struct{}{}
		result = append(result, tag)
	}
	return result
}

func ptr(t time.Time) *time.Time {
	return &t
}
