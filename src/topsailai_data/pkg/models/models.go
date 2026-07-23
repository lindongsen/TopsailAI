package models

import (
	"time"
)

// ObjectID is a stable identifier for an object.
// In the local adapter it equals the object name; in database adapters it is
// typically the primary key value.
type ObjectID string

// String returns the string representation of the object ID.
func (id ObjectID) String() string {
	return string(id)
}

// ObjectStatus represents the lifecycle state of an object.
type ObjectStatus string

const (
	// ObjectStatusCreating indicates the object metadata has been created but
	// actual data has not yet been successfully written.
	ObjectStatusCreating ObjectStatus = "creating"
	// ObjectStatusActive indicates a fully created object that supports all
	// operations.
	ObjectStatusActive ObjectStatus = "active"
	// ObjectStatusDeleted indicates a soft-deleted object whose actual data is
	// being or has been removed.
	ObjectStatusDeleted ObjectStatus = "deleted"
	// ObjectStatusCeased indicates an object whose metadata is retained but no
	// actual data operations are permitted.
	ObjectStatusCeased ObjectStatus = "ceased"
)

// IsFinal reports whether the status is a terminal lifecycle state.
func (s ObjectStatus) IsFinal() bool {
	return s == ObjectStatusCeased
}

// Object is the core data model shared by all adapters and the manager.
type Object struct {
	// ID is the stable object identifier.
	ID ObjectID
	// Name is the object name, equal to the object folder name.
	Name string
	// Path is the full relative path of the object folder from the root.
	Path string
	// Description is a short human-readable summary of the object. It may be
	// supplied explicitly or extracted from YAML frontmatter in object.md.
	Description string
	// Tags is the merged set of inherited classify tags and object-specific tags.
	Tags []string
	// Status is the current lifecycle state.
	Status ObjectStatus
	// SchemaVersion is the persistent storage format version of this record.
	SchemaVersion int
	// CreatedAt is the object creation timestamp.
	CreatedAt time.Time
	// UpdatedAt is the last modification timestamp.
	UpdatedAt time.Time
	// DeletedAt is set when the object transitions to deleted status.
	DeletedAt *time.Time
	// CeasedAt is set when the object transitions to ceased status.
	CeasedAt *time.Time
	// DataRef is an adapter-specific reference to the object's actual data.
	// The metadata adapter stores it but does not interpret it.
	DataRef string
}

// Clone returns a deep copy of the object.
func (o Object) Clone() Object {
	cloned := o
	if o.Tags != nil {
		cloned.Tags = make([]string, len(o.Tags))
		copy(cloned.Tags, o.Tags)
	}
	if o.DeletedAt != nil {
		t := *o.DeletedAt
		cloned.DeletedAt = &t
	}
	if o.CeasedAt != nil {
		t := *o.CeasedAt
		cloned.CeasedAt = &t
	}
	return cloned
}

// SortOrder represents the ordering direction for list/search results.
type SortOrder string

const (
	// SortOrderDesc sorts results in descending order (newest first).
	SortOrderDesc SortOrder = "desc"
	// SortOrderAsc sorts results in ascending order (oldest first).
	SortOrderAsc SortOrder = "asc"
)

// ListOptions controls the behavior of metadata list and search operations.
type ListOptions struct {
	// Tags filters the results to objects that have all of the specified tags.
	// An empty slice disables tag filtering.
	Tags []string
	// Offset is the number of results to skip before returning entries.
	Offset int
	// Limit is the maximum number of results to return. Zero or negative means
	// no limit.
	Limit int
	// IncludeDeleted includes objects whose status is deleted or ceased when
	// true.
	IncludeDeleted bool
	// Sort controls the result ordering. The default empty value keeps the
	// existing behavior (descending by creation time). Supported values are
	// "time:desc" and "time:asc", which sort by the YYYY/MMDD/HHMM prefix
	// extracted from Object.Path.
	Sort string
}

// AdapterConfig holds key-value configuration for an adapter factory.
type AdapterConfig map[string]string
