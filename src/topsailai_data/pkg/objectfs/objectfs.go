// Package objectfs adapts a topsailai_data object's actual data to the
// filetool.FS interface, so the file and folder capabilities can operate
// directly on files inside a data object.
//
// Every read and write is routed through the manager, which means the advisory
// object lock, atomic file replacement, and usage statistics apply exactly as
// they do for the get and put commands. Nothing is reimplemented here.
package objectfs

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/topsailai/topsailai_data/pkg/filetool"
	"github.com/topsailai/topsailai_data/pkg/manager"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// ObjectFS exposes one object's actual data as a file system.
//
// Paths are interpreted relative to the object folder. A leading slash is
// ignored so callers may write either "notes/a.md" or "/notes/a.md".
type ObjectFS struct {
	ctx context.Context
	mgr *manager.Manager
	id  models.ObjectID
}

// New returns a file system backed by one object's actual data.
func New(ctx context.Context, mgr *manager.Manager, id models.ObjectID) (*ObjectFS, error) {
	if mgr == nil {
		return nil, fmt.Errorf("objectfs: manager is required")
	}
	if id == "" {
		return nil, fmt.Errorf("objectfs: object id is required")
	}
	return &ObjectFS{ctx: ctx, mgr: mgr, id: id}, nil
}

// normalize converts a caller path into an object-relative path.
//
// Absolute paths and leading slashes are accepted for convenience, but a path
// that escapes the object folder is rejected so a caller cannot reach outside
// the object. An empty path is rejected because a file operation needs a name.
func normalize(p string) (string, error) {
	if p == "" {
		return "", fmt.Errorf("objectfs: path is empty")
	}
	return normalizeAllowRoot(p)
}

// normalizeAllowRoot converts a caller path into an object-relative path and
// accepts an empty result, which denotes the object root. Folder operations use
// it so the root can be listed and inspected.
func normalizeAllowRoot(p string) (string, error) {
	cleaned := path.Clean("/" + filepath.ToSlash(p))
	cleaned = strings.TrimPrefix(cleaned, "/")
	if cleaned == "" || cleaned == "." {
		return "", nil
	}
	if cleaned == ".." || strings.HasPrefix(cleaned, "../") {
		return "", fmt.Errorf("objectfs: path %q escapes the object", p)
	}
	return cleaned, nil
}

// Open returns a seekable reader over one file inside the object.
//
// The adapter stream is forwarded directly when it is seekable, which is the
// case for the local adapter because it returns an operating-system file. The
// read paths seek backwards to detect encoding and to honour a negative offset,
// so forwarding the stream keeps memory use constant regardless of file size.
//
// Only a non-seekable adapter stream is buffered, because the read paths cannot
// seek it. The local adapter never takes that path.
func (f *ObjectFS) Open(p string) (filetool.ReadSeekCloser, error) {
	name, err := normalize(p)
	if err != nil {
		return nil, err
	}
	if name == "" {
		return nil, fmt.Errorf("objectfs: cannot open the object root as a file")
	}

	rc, err := f.mgr.ReadActualFile(f.ctx, f.id, name)
	if err != nil {
		return nil, err
	}
	if seeker, ok := rc.(io.ReadSeeker); ok {
		return &streamFile{ReadSeeker: seeker, closer: rc}, nil
	}

	data, err := io.ReadAll(rc)
	_ = rc.Close()
	if err != nil {
		return nil, fmt.Errorf("objectfs: read %q: %w", name, err)
	}
	return &memoryFile{Reader: bytes.NewReader(data)}, nil
}

// ReadFile returns the complete content of one file inside the object.
func (f *ObjectFS) ReadFile(p string) ([]byte, error) {
	name, err := normalize(p)
	if err != nil {
		return nil, err
	}
	if name == "" {
		return nil, fmt.Errorf("objectfs: cannot read the object root as a file")
	}

	rc, err := f.mgr.ReadActualFile(f.ctx, f.id, name)
	if err != nil {
		return nil, err
	}
	defer rc.Close()

	data, err := io.ReadAll(rc)
	if err != nil {
		return nil, fmt.Errorf("objectfs: read %q: %w", name, err)
	}
	return data, nil
}

// WriteFile replaces one file inside the object.
//
// The manager acquires the advisory write lock, replaces the file atomically,
// and records write statistics, so a failed write leaves the previous content
// unchanged.
func (f *ObjectFS) WriteFile(p string, data []byte, _ os.FileMode) error {
	name, err := normalize(p)
	if err != nil {
		return err
	}
	if name == "" {
		return fmt.Errorf("objectfs: cannot write the object root as a file")
	}
	return f.mgr.WriteActualFile(f.ctx, f.id, name, bytes.NewReader(data))
}

// WriteFileFrom replaces one file inside the object from a stream.
//
// The manager holds exclusive object custody for the whole write and the
// adapter copies the stream, so a large source is never buffered in memory and
// a cooperating process cannot interleave its own write.
func (f *ObjectFS) WriteFileFrom(p string, r io.Reader, _ os.FileMode) error {
	name, err := normalize(p)
	if err != nil {
		return err
	}
	if name == "" {
		return fmt.Errorf("objectfs: cannot write the object root as a file")
	}
	return f.mgr.WriteActualFile(f.ctx, f.id, name, r)
}

// AppendFile appends to one file inside the object.
//
// The manager holds exclusive object custody for the whole append and the
// adapter appends in place, so a cooperating process cannot interleave its own
// write and the existing content is never read back into memory.
func (f *ObjectFS) AppendFile(p string, data []byte, _ os.FileMode) error {
	return f.AppendFrom(p, bytes.NewReader(data), 0o644)
}

// AppendFrom appends a stream to one file inside the object.
//
// The stream is copied by the adapter, so a large source is never buffered in
// memory.
func (f *ObjectFS) AppendFrom(p string, r io.Reader, _ os.FileMode) error {
	name, err := normalize(p)
	if err != nil {
		return err
	}
	if name == "" {
		return fmt.Errorf("objectfs: cannot append to the object root as a file")
	}
	return f.mgr.AppendActualFile(f.ctx, f.id, name, r)
}

// WriteAt inserts or overwrites a stream under exclusive object custody.
func (f *ObjectFS) WriteAt(p string, r io.Reader, seek int64, insert bool, _ os.FileMode) error {
	name, err := normalize(p)
	if err != nil {
		return err
	}
	if name == "" {
		return fmt.Errorf("objectfs: cannot update the object root as a file")
	}
	return f.mgr.WriteActualFileAt(f.ctx, f.id, name, r, seek, insert)
}

// EditFile plans and publishes a byte-range replacement under object custody.
func (f *ObjectFS) EditFile(p string, planner filetool.FileEditPlanner, _ os.FileMode) error {
	name, err := normalize(p)
	if err != nil {
		return err
	}
	if name == "" {
		return fmt.Errorf("objectfs: cannot update the object root as a file")
	}
	return f.mgr.EditActualFile(f.ctx, f.id, name, func(current io.Reader, exists bool) (manager.FileEdit, error) {
		edit, err := planner(current, exists)
		return manager.FileEdit{Start: edit.Start, End: edit.End, Replacement: edit.Replacement}, err
	})
}

// UpdateFile performs a lock-protected read-modify-write on one file.
//
// Exclusive object custody is acquired once and held across both the read and
// the write, so a cooperating process cannot interleave its own update between
// them. The callback receives the current content and whether the file exists.
func (f *ObjectFS) UpdateFile(p string, fn func(existing []byte, exists bool) ([]byte, error)) error {
	name, err := normalize(p)
	if err != nil {
		return err
	}
	if name == "" {
		return fmt.Errorf("objectfs: cannot update the object root as a file")
	}
	return f.mgr.UpdateActualFile(f.ctx, f.id, name, fn)
}

// Stat reports information about one file or folder inside the object.
//
// A folder is reported as a directory entry so existence checks can confirm a
// folder created by MkdirAll. The folder test runs only after the file lookup
// fails, so a file always wins when a name is ambiguous.
func (f *ObjectFS) Stat(p string) (os.FileInfo, error) {
	name, err := normalizeAllowRoot(p)
	if err != nil {
		return nil, err
	}

	if name == "" {
		return objectInfo{name: f.objectName(), dir: true}, nil
	}

	info, err := f.mgr.StatActualFile(f.ctx, f.id, name)
	if err != nil {
		return nil, err
	}
	if info.IsDir {
		return objectInfo{name: path.Base(name), dir: true}, nil
	}
	return objectInfo{name: path.Base(name), size: info.Size}, nil
}

// fileSize reports the byte length of one file without reading its content.
//
// The size comes from the underlying file information when the adapter stream
// exposes it, so a large file is never loaded into memory just to report its
// length and a folder is never mistaken for an empty file. A stream without
// file information falls back to seeking to the end.
func (f *ObjectFS) fileSize(name string) (int64, error) {
	fd, err := f.Open(name)
	if err != nil {
		return 0, err
	}
	defer fd.Close()

	if statter, ok := fd.(interface{ Stat() (os.FileInfo, error) }); ok {
		info, statErr := statter.Stat()
		if statErr != nil {
			return 0, fmt.Errorf("objectfs: size %q: %w", name, statErr)
		}
		if info.IsDir() {
			return 0, fmt.Errorf("objectfs: size %q: is a folder", name)
		}
		return info.Size(), nil
	}

	size, err := fd.Seek(0, io.SeekEnd)
	if err != nil {
		return 0, fmt.Errorf("objectfs: size %q: %w", name, err)
	}
	return size, nil
}

// isDir reports whether a path is a folder inside the object.
//
// Object storage keeps no folder entries, so a folder exists only when some
// archived file lives below it.
func (f *ObjectFS) isDir(name string) (bool, error) {
	info, err := f.mgr.StatActualFile(f.ctx, f.id, name)
	if err != nil {
		return false, err
	}
	return info.IsDir, nil
}

// ReadDir lists the immediate entries of one folder inside the object.
//
// The listing comes from the adapter's names-only index so large file bodies
// are never streamed merely to discover paths.
func (f *ObjectFS) ReadDir(p string) ([]os.DirEntry, error) {
	name, err := normalizeAllowRoot(p)
	if err != nil {
		return nil, err
	}

	entries, err := f.listAll()
	if err != nil {
		return nil, err
	}

	prefix := ""
	if name != "" {
		prefix = name + "/"
	}

	seen := make(map[string]bool)
	var result []os.DirEntry
	for _, entry := range entries {
		if !strings.HasPrefix(entry, prefix) {
			continue
		}
		remainder := strings.TrimPrefix(entry, prefix)
		if remainder == "" {
			continue
		}
		parts := strings.SplitN(remainder, "/", 2)
		child := parts[0]
		if seen[child] {
			continue
		}
		seen[child] = true
		result = append(result, objectDirEntry{name: child, dir: len(parts) > 1})
	}

	if len(result) == 0 {
		if name == "" {
			return nil, fmt.Errorf("objectfs: object %q has no files", f.id)
		}
		return nil, fmt.Errorf("objectfs: folder %q does not exist in object %q", name, f.id)
	}

	sort.Slice(result, func(i, j int) bool { return result[i].Name() < result[j].Name() })
	return result, nil
}

// agentsFileName is the marker file written into every folder that MkdirAll
// creates. Object storage has no empty folder, so a folder is visible only when
// it contains a file; this marker makes a new folder immediately discoverable.
const agentsFileName = "AGENTS.md"

// agentsFileContent is the default content of the marker file.
const agentsFileContent = `# AGENTS

This folder was created by the topsailai-data file mkdirs command.

Record instructions for agents working in this folder here.
`

// MkdirAll creates every missing folder level and writes an AGENTS.md marker
// into each one.
//
// Object storage has no empty folder: a folder becomes visible only when it
// contains a file. Writing the marker makes a new folder immediately
// discoverable through ReadDir, exists, and list-dirs, so mkdirs is not a
// silent no-op.
//
// A level that already exists is left untouched, so an existing AGENTS.md is
// never overwritten and no marker is added to a folder that already holds
// content. The object root always exists and is never modified.
func (f *ObjectFS) MkdirAll(p string, _ os.FileMode) error {
	name, err := normalizeAllowRoot(p)
	if err != nil {
		return err
	}
	if name == "" {
		return nil
	}

	existing, err := f.listAll()
	if err != nil {
		return err
	}
	present := make(map[string]bool)
	for _, entry := range existing {
		for dir := path.Dir(entry); dir != "." && dir != "/" && dir != ""; dir = path.Dir(dir) {
			present[dir] = true
		}
	}

	current := ""
	for _, segment := range strings.Split(name, "/") {
		if current == "" {
			current = segment
		} else {
			current += "/" + segment
		}
		if present[current] {
			continue
		}
		marker := current + "/" + agentsFileName
		if err := f.WriteFile(marker, []byte(agentsFileContent), 0o644); err != nil {
			return err
		}
		present[current] = true
	}
	return nil
}

// listAll returns every file path inside the object without reading file data.
func (f *ObjectFS) listAll() ([]string, error) {
	return f.mgr.ListActualFiles(f.ctx, f.id)
}

// objectName returns the object identifier used as the root entry name.
func (f *ObjectFS) objectName() string { return string(f.id) }

// memoryFile is an in-memory seekable file.
type memoryFile struct {
	*bytes.Reader
}

// Close releases the in-memory file.
func (m *memoryFile) Close() error { return nil }

// objectInfo is an os.FileInfo for content inside an object.
type objectInfo struct {
	name string
	size int64
	dir  bool
}

// Name returns the base name.
func (i objectInfo) Name() string { return i.name }

// Size returns the content length in bytes.
func (i objectInfo) Size() int64 { return i.size }

// Mode returns the file mode.
func (i objectInfo) Mode() os.FileMode {
	if i.dir {
		return os.ModeDir | 0o755
	}
	return 0o644
}

// ModTime reports a zero time because object content carries no per-file
// timestamp.
func (i objectInfo) ModTime() time.Time { return time.Time{} }

// IsDir reports whether the entry is a folder.
func (i objectInfo) IsDir() bool { return i.dir }

// Sys returns no underlying system information.
func (i objectInfo) Sys() any { return nil }

// objectDirEntry is an os.DirEntry for an entry inside an object.
type objectDirEntry struct {
	name string
	dir  bool
}

// Name returns the entry name.
func (e objectDirEntry) Name() string { return e.name }

// IsDir reports whether the entry is a folder.
func (e objectDirEntry) IsDir() bool { return e.dir }

// Type returns the entry mode type bits.
func (e objectDirEntry) Type() os.FileMode {
	if e.dir {
		return os.ModeDir
	}
	return 0
}

// Info returns file information for the entry.
func (e objectDirEntry) Info() (os.FileInfo, error) {
	return objectInfo{name: e.name, dir: e.dir}, nil
}

// streamFile forwards a seekable adapter stream and closes it on Close.
//
// It exists so a large object file is read directly from the adapter instead of
// being buffered in memory.
type streamFile struct {
	io.ReadSeeker
	closer io.Closer
}

// Close closes the underlying adapter stream.
func (s *streamFile) Close() error { return s.closer.Close() }

// Stat reports the underlying file information when the stream exposes it.
//
// The size and folder flag come from the adapter's own file handle, so a folder
// is never mistaken for an empty file and a large file is never read to measure
// its length.
func (s *streamFile) Stat() (os.FileInfo, error) {
	statter, ok := s.closer.(interface{ Stat() (os.FileInfo, error) })
	if !ok {
		return nil, fmt.Errorf("objectfs: stream does not expose file information")
	}
	return statter.Stat()
}
