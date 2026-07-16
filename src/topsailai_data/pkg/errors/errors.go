// Package errors defines sentinel errors used across topsailai_data.
package errors

import "errors"

// Object lifecycle errors.
var (
	// ErrObjectNotFound is returned when the requested object does not exist.
	ErrObjectNotFound = errors.New("object not found")

	// ErrObjectExists is returned when creating an object that already exists.
	ErrObjectExists = errors.New("object already exists")

	// ErrObjectLocked is returned when an operation cannot acquire the object lock.
	ErrObjectLocked = errors.New("object is locked by another process")

	// ErrObjectNotActive is returned when an operation requires an active object.
	ErrObjectNotActive = errors.New("object is not active")

	// ErrObjectDeleted is returned when an operation is not allowed on a deleted object.
	ErrObjectDeleted = errors.New("object has been deleted")

	// ErrObjectCeased is returned when actual-data operations are requested on a ceased object.
	ErrObjectCeased = errors.New("object has ceased")

	// ErrObjectCreating is returned when an operation is not allowed on a creating object.
	ErrObjectCreating = errors.New("object is still being created")
)

// Validation errors.
var (
	// ErrInvalidName is returned when an object name is invalid.
	ErrInvalidName = errors.New("invalid object name")

	// ErrInvalidPath is returned when a path violates project rules.
	ErrInvalidPath = errors.New("invalid path")

	// ErrInvalidStatus is returned when a status value is not recognized.
	ErrInvalidStatus = errors.New("invalid object status")

	// ErrInvalidTag is returned when a tag value is invalid.
	ErrInvalidTag = errors.New("invalid tag")

	// ErrInvalidDepth is returned when the folder depth exceeds the maximum allowed.
	ErrInvalidDepth = errors.New("folder depth exceeds maximum allowed")

	// ErrDepthExceeded is returned when the object path exceeds the maximum depth.
	ErrDepthExceeded = errors.New("object path exceeds maximum depth")

	// ErrInvalidArgument is returned for general argument errors.
	ErrInvalidArgument = errors.New("invalid argument")

	// ErrInvalidSearchQuery is returned when a search query contains unsupported characters.
	ErrInvalidSearchQuery = errors.New("invalid search query")
)

// Adapter errors.
var (
	// ErrAdapterNotFound is returned when the requested adapter is not registered.
	ErrAdapterNotFound = errors.New("adapter not found")

	// ErrMoveNotSupported is returned when an adapter cannot move actual data.
	ErrMoveNotSupported = errors.New("adapter does not support move")

	// ErrAdapterConfig is returned when adapter configuration is invalid.
	ErrAdapterConfig = errors.New("invalid adapter configuration")
)

// Operation errors.
var (
	// ErrNotImplemented is returned for features not yet implemented.
	ErrNotImplemented = errors.New("not implemented")

	// ErrCancelled is returned when an operation is cancelled.
	ErrCancelled = errors.New("operation cancelled")

	// ErrTimeout is returned when a lock or operation times out.
	ErrTimeout = errors.New("operation timed out")

	// ErrCorruptedMetadata is returned when a metadata file cannot be parsed.
	ErrCorruptedMetadata = errors.New("corrupted metadata")

	// ErrTagNotFound is returned when removing a tag that does not exist.
	ErrTagNotFound = errors.New("tag not found")
)
