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

// FileInfo describes one path inside an object's actual data.
//
// It is deliberately smaller than os.FileInfo: an existence check needs to know
// whether the path is present, whether it is a folder, and how large a file is,
// and nothing else. Keeping the type minimal lets a remote adapter answer
// without materializing a full file-system entry.
type FileInfo struct {
	// Size is the byte length of a file. It is zero for a folder.
	Size int64

	// IsDir reports whether the path is a folder.
	IsDir bool
}

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

	// Delete transitions an active metadata record to deleted without removing payload.
	Delete(ctx context.Context, id models.ObjectID) error

	// FinalizeDelete transitions deleted metadata to ceased after payload removal.
	FinalizeDelete(ctx context.Context, id models.ObjectID) error

	// Purge permanently removes a ceased object's metadata and associated
	// metadata files. Payload removal is coordinated separately by the manager.
	// Only objects in the "ceased" state may be purged.
	Purge(ctx context.Context, id models.ObjectID) error

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
	// can clean them up. The recover CLI command no longer resumes creating
	// objects; this method is retained for the gc command.
	Recover(ctx context.Context) ([]*models.Object, error)

	// Restore transitions a deleted object back to active.
	// It is used by the recover CLI command to restore soft-deleted objects.
	Restore(ctx context.Context, id models.ObjectID) error

	// GC returns objects that are eligible for permanent metadata cleanup, such
	// as ceased objects whose retention period has expired. When force is true,
	// all ceased objects are returned regardless of retention.
	GC(ctx context.Context, retention time.Duration, force bool) ([]*models.Object, error)

	// Close releases any resources held by the adapter.
	Close() error
}

// ActualDataAdapter manages the actual payload data of objects.
//
// All location-aware methods accept an adapter-specific reference string (ref)
// rather than an ObjectID. For the local adapter ref is a canonical relative
// path beneath the store's object directory; remote adapters may use a bucket
// key or other opaque handle. Write methods return the ref so the manager can store it
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

	// AppendFile appends to a single file in the object's actual data, creating
	// it when missing. It returns the adapter-specific reference to the stored
	// payload. An adapter must append without rewriting the existing content so
	// a large file is never read back into memory.
	AppendFile(ctx context.Context, ref string, filename string, r io.Reader) (string, error)

	// ReadFile returns a stream that reads a single file from the object's actual data.
	ReadFile(ctx context.Context, ref string, filename string) (io.ReadCloser, error)

	// StatFile reports whether one file or folder exists inside the object's
	// actual data and, for a file, its byte length. It exists so an existence
	// check does not enumerate the whole payload: a caller that only needs to
	// know whether a path is present must not pay a cost proportional to the
	// object size. A missing path returns errors.ErrObjectNotFound.
	StatFile(ctx context.Context, ref string, filename string) (FileInfo, error)

	// ListFiles returns the relative paths of all regular payload files without
	// reading their contents. Reserved adapter-internal files are excluded.
	ListFiles(ctx context.Context, ref string) ([]string, error)

	// Move relocates the actual data for an object to a new adapter-specific reference.
	// For local adapters newRef is the new relative payload path; source cleanup
	// is coordinated by the manager after metadata publication.
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
