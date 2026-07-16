// Package adapters defines the adapter interfaces used by topsailai_data.
package adapters

import (
	"context"
	"fmt"
	"io"
	"time"

	"github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// MetadataAdapter manages object metadata.
type MetadataAdapter interface {
	// Init prepares the adapter for use (creates directories, tables, etc.).
	Init(ctx context.Context) error

	// Create stores initial metadata for a new object.
	// The object status is typically set to "creating" by the caller.
	Create(ctx context.Context, obj *models.Object) error

	// Get retrieves metadata for an object by ID.
	// If includeDeleted is true, objects with status "deleted" or "ceased" may be returned.
	Get(ctx context.Context, id models.ObjectID, includeDeleted bool) (*models.Object, error)

	// Update replaces the stored metadata for an object.
	Update(ctx context.Context, obj *models.Object) error

	// Delete removes metadata for an object.
	// For local adapters this may rename the metadata marker to a deleted/ceased state.
	Delete(ctx context.Context, id models.ObjectID) error

	// FinalizeDelete permanently transitions a deleted object to ceased.
	// For local adapters this renames the deleted marker to a ceased marker.
	FinalizeDelete(ctx context.Context, id models.ObjectID) error

	// List returns metadata matching the provided options.
	List(ctx context.Context, opts models.ListOptions) ([]*models.Object, error)

	// Search returns metadata whose name or tags match any of the provided
	// query terms. Terms are combined with OR semantics: an object matches if
	// its name or any tag contains at least one term as a substring.
	Search(ctx context.Context, terms []string, opts models.ListOptions) ([]*models.Object, error)

	// AddTag appends a tag to an object's metadata if it is not already present.
	AddTag(ctx context.Context, id models.ObjectID, tag string) error

	// RemoveTag removes a tag from an object's metadata.
	RemoveTag(ctx context.Context, id models.ObjectID, tag string) error

	// Recover lists objects that are in the "creating" state so that a manager
	// can either resume creation or clean them up.
	Recover(ctx context.Context) ([]*models.Object, error)

	// GC returns objects that are eligible for permanent metadata cleanup, such
	// as ceased objects whose retention period has expired.
	GC(ctx context.Context, retention time.Duration) ([]*models.Object, error)

	// Close releases any resources held by the adapter.
	Close() error
}

// ActualDataAdapter manages the actual payload data of objects.
//
// All location-aware methods accept an adapter-specific reference string (ref)
// rather than an ObjectID. For the local adapter ref is the absolute object
// folder path; for remote adapters it may be a bucket key or other opaque
// handle. Write methods return the resolved ref so the manager can store it
// in metadata.
type ActualDataAdapter interface {
	// Init prepares the adapter for use (creates directories, buckets, etc.).
	Init(ctx context.Context) error

	// WriteArchive replaces the actual data of an object with the contents of a tar archive.
	// It returns the adapter-specific reference to the stored payload.
	WriteArchive(ctx context.Context, ref string, r io.Reader) (string, error)

	// ReadArchive returns a stream that reads the object's actual data as a tar archive.
	ReadArchive(ctx context.Context, ref string) (io.ReadCloser, error)

	// WriteFile writes a single file into the object's actual data.
	// It returns the adapter-specific reference to the stored payload.
	WriteFile(ctx context.Context, ref string, filename string, r io.Reader) (string, error)

	// ReadFile returns a stream that reads a single file from the object's actual data.
	ReadFile(ctx context.Context, ref string, filename string) (io.ReadCloser, error)

	// Move relocates the actual data for an object to a new adapter-specific reference.
	// For local adapters newRef is the new full folder path.
	// It returns the adapter-specific reference after the move.
	Move(ctx context.Context, oldRef string, newRef string) (string, error)

	// Delete removes the actual data for an object.
	Delete(ctx context.Context, ref string) error

	// Exists reports whether actual data exists for the object.
	Exists(ctx context.Context, ref string) (bool, error)

	// Close releases any resources held by the adapter.
	Close() error
}

// MetadataAdapterFactory creates a new MetadataAdapter from configuration.
type MetadataAdapterFactory func(ctx context.Context, cfg map[string]string) (MetadataAdapter, error)

// ActualDataAdapterFactory creates a new ActualDataAdapter from configuration.
type ActualDataAdapterFactory func(ctx context.Context, cfg map[string]string) (ActualDataAdapter, error)

var (
	metadataFactories   = make(map[string]MetadataAdapterFactory)
	actualDataFactories = make(map[string]ActualDataAdapterFactory)
)

// RegisterMetadataAdapter registers a metadata adapter factory under the given name.
func RegisterMetadataAdapter(name string, factory MetadataAdapterFactory) {
	metadataFactories[name] = factory
}

// RegisterActualDataAdapter registers an actual-data adapter factory under the given name.
func RegisterActualDataAdapter(name string, factory ActualDataAdapterFactory) {
	actualDataFactories[name] = factory
}

// NewMetadataAdapter creates a MetadataAdapter by registered name.
func NewMetadataAdapter(ctx context.Context, name string, cfg map[string]string) (MetadataAdapter, error) {
	factory, ok := metadataFactories[name]
	if !ok {
		return nil, fmt.Errorf("%w: metadata adapter %q", errors.ErrAdapterNotFound, name)
	}
	return factory(ctx, cfg)
}

// NewActualDataAdapter creates an ActualDataAdapter by registered name.
func NewActualDataAdapter(ctx context.Context, name string, cfg map[string]string) (ActualDataAdapter, error) {
	factory, ok := actualDataFactories[name]
	if !ok {
		return nil, fmt.Errorf("%w: actual-data adapter %q", errors.ErrAdapterNotFound, name)
	}
	return factory(ctx, cfg)
}
