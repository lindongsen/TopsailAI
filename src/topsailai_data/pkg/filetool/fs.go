package filetool

import (
	"io"
	"os"
)

// ReadSeekCloser combines the reader, seeker, and closer capabilities that the
// read paths need. An operating-system file satisfies it directly; an
// object-backed implementation buffers content and satisfies it in memory.
type ReadSeekCloser interface {
	io.Reader
	io.Seeker
	io.Closer
}

// FS abstracts the file-system operations used by this package.
//
// The seam exists so the same capabilities can run against an operating-system
// directory or against the actual data of a topsailai_data object. Every
// operation takes a path that is meaningful to the implementation: an absolute
// or relative operating-system path for OSFS, or a path inside the object for an
// object-backed implementation.
type FS interface {
	// Open opens a file for reading and seeking.
	Open(path string) (ReadSeekCloser, error)

	// ReadFile returns the complete content of a file.
	ReadFile(path string) ([]byte, error)

	// WriteFile replaces the content of a file, creating it when missing.
	WriteFile(path string, data []byte, perm os.FileMode) error

	// AppendFile appends data to a file, creating it when missing.
	AppendFile(path string, data []byte, perm os.FileMode) error

	// Stat reports file information.
	Stat(path string) (os.FileInfo, error)

	// ReadDir returns the entries of a folder.
	ReadDir(path string) ([]os.DirEntry, error)

	// MkdirAll creates a folder and any missing parents.
	MkdirAll(path string, perm os.FileMode) error
}

// OSFS implements FS over the operating-system file system.
//
// It is the default implementation, so callers that pass no FS keep the
// original behaviour of operating on real paths.
type OSFS struct{}

// Open opens an operating-system file.
func (OSFS) Open(path string) (ReadSeekCloser, error) {
	return os.Open(path)
}

// ReadFile reads an operating-system file.
func (OSFS) ReadFile(path string) ([]byte, error) {
	return os.ReadFile(path)
}

// WriteFile writes an operating-system file.
func (OSFS) WriteFile(path string, data []byte, perm os.FileMode) error {
	return os.WriteFile(path, data, perm)
}

// AppendFile appends to an operating-system file.
func (OSFS) AppendFile(path string, data []byte, perm os.FileMode) error {
	fd, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, perm)
	if err != nil {
		return err
	}
	defer fd.Close()
	if _, err := fd.Write(data); err != nil {
		return err
	}
	return fd.Sync()
}

// Stat stats an operating-system path.
func (OSFS) Stat(path string) (os.FileInfo, error) {
	return os.Stat(path)
}

// ReadDir lists an operating-system folder.
func (OSFS) ReadDir(path string) ([]os.DirEntry, error) {
	return os.ReadDir(path)
}

// MkdirAll creates an operating-system folder.
func (OSFS) MkdirAll(path string, perm os.FileMode) error {
	return os.MkdirAll(path, perm)
}

// resolveFS returns the effective file system, falling back to OSFS when the
// caller supplied none.
func resolveFS(fs FS) FS {
	if fs == nil {
		return OSFS{}
	}
	return fs
}
