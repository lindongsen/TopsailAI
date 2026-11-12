package filetool

import (
	"io"
	"os"
	"path/filepath"
)

// ReadSeekCloser combines the reader, seeker, and closer capabilities that the
// read paths need. An operating-system file satisfies it directly, and an
// object-backed implementation forwards the adapter stream when it is seekable
// so a large file is never buffered in memory.
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

	// WriteFileFrom replaces the content of a file from a stream, creating it
	// when missing. It exists so a large source is copied instead of being
	// buffered in memory.
	WriteFileFrom(path string, r io.Reader, perm os.FileMode) error

	// AppendFrom appends a stream to a file, creating it when missing. It exists
	// so a large source is copied instead of being buffered in memory.
	AppendFrom(path string, r io.Reader, perm os.FileMode) error

	// WriteAt inserts or overwrites a stream at a byte offset resolved against
	// the current file size. Negative offsets count from the end.
	WriteAt(path string, r io.Reader, seek int64, insert bool, perm os.FileMode) error

	// UpdateFile performs a lock-protected read-modify-write. The callback
	// receives the current content and whether the file exists, and returns the
	// replacement content. An implementation must hold exclusive custody for the
	// whole read and write so a cooperating process cannot interleave its own
	// update and silently discard this one.
	UpdateFile(path string, fn func(existing []byte, exists bool) ([]byte, error)) error

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

// AppendFrom appends a stream to an operating-system file.
func (OSFS) AppendFrom(path string, r io.Reader, perm os.FileMode) error {
	fd, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, perm)
	if err != nil {
		return err
	}
	defer fd.Close()
	if _, err := io.Copy(fd, r); err != nil {
		return err
	}
	return fd.Sync()
}

// WriteFileFrom replaces an operating-system file from a stream.
func (OSFS) WriteFileFrom(path string, r io.Reader, perm os.FileMode) error {
	fd, err := os.OpenFile(path, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, perm)
	if err != nil {
		return err
	}
	defer fd.Close()
	if _, err := io.Copy(fd, r); err != nil {
		return err
	}
	return fd.Sync()
}

// WriteAt inserts or overwrites a stream at a byte offset.
func (OSFS) WriteAt(path string, r io.Reader, seek int64, insert bool, perm os.FileMode) error {
	old, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return OSFS{}.WriteFileFrom(path, r, perm)
		}
		return err
	}
	defer old.Close()
	info, err := old.Stat()
	if err != nil {
		return err
	}
	position := resolvePosition64(seek, info.Size(), insert)
	tmp, err := os.CreateTemp(filepath.Dir(path), ".topsailai-file-write-*")
	if err != nil {
		return err
	}
	tmpPath := tmp.Name()
	cleanup := true
	defer func() {
		_ = tmp.Close()
		if cleanup {
			_ = os.Remove(tmpPath)
		}
	}()
	if err := tmp.Chmod(info.Mode().Perm()); err != nil {
		return err
	}
	if _, err := io.CopyN(tmp, old, position); err != nil {
		return err
	}
	written, err := io.Copy(tmp, r)
	if err != nil {
		return err
	}
	suffixOffset := position
	if !insert {
		suffixOffset += written
	}
	if suffixOffset < info.Size() {
		if _, err := old.Seek(suffixOffset, io.SeekStart); err != nil {
			return err
		}
		if _, err := io.Copy(tmp, old); err != nil {
			return err
		}
	}
	if err := tmp.Sync(); err != nil {
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpPath, path); err != nil {
		return err
	}
	cleanup = false
	return nil
}

// UpdateFile performs a read-modify-write on an operating-system file.
//
// The operating-system implementation has no advisory lock to hold, so it reads
// and writes directly. Callers that need cross-process serialization must use an
// implementation that provides it.
func (OSFS) UpdateFile(path string, fn func(existing []byte, exists bool) ([]byte, error)) error {
	existing, err := os.ReadFile(path)
	exists := true
	if err != nil {
		if !os.IsNotExist(err) {
			return err
		}
		existing = nil
		exists = false
	}
	updated, err := fn(existing, exists)
	if err != nil {
		return err
	}
	return os.WriteFile(path, updated, 0o644)
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
