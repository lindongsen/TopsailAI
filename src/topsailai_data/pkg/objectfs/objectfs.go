// Package objectfs adapts a topsailai_data object's actual data to the
// filetool.FS interface, so the file and folder capabilities can operate
// directly on files inside a data object.
//
// Every read and write is routed through the manager, which means the advisory
// object lock, atomic file replacement, and usage statistics apply exactly as
// they do for the get and put commands. Nothing is reimplemented here.
package objectfs

import (
	"archive/tar"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
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
// The content is buffered because the read paths seek backwards to detect
// encoding and to honour a negative offset. Object files are bounded by the
// truncation limit on the read paths, so buffering stays small.
func (f *ObjectFS) Open(p string) (filetool.ReadSeekCloser, error) {
	name, err := normalize(p)
	if err != nil {
		return nil, err
	}
	if name == "" {
		return nil, fmt.Errorf("objectfs: cannot open the object root as a file")
	}

	data, err := f.ReadFile(name)
	if err != nil {
		return nil, err
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

// AppendFile appends to one file inside the object.
//
// The existing content is read first and the combined content is written back
// through the manager, so the append is atomic and lock-protected. A missing
// file is treated as empty content.
func (f *ObjectFS) AppendFile(p string, data []byte, perm os.FileMode) error {
	existing, err := f.ReadFile(p)
	if err != nil {
		if !errors.Is(err, apperrors.ErrObjectNotFound) {
			return err
		}
		existing = nil
	}
	combined := make([]byte, 0, len(existing)+len(data))
	combined = append(combined, existing...)
	combined = append(combined, data...)
	return f.WriteFile(p, combined, perm)
}

// Stat reports information about one file inside the object.
func (f *ObjectFS) Stat(p string) (os.FileInfo, error) {
	name, err := normalizeAllowRoot(p)
	if err != nil {
		return nil, err
	}

	if name == "" {
		return objectInfo{name: f.objectName(), dir: true}, nil
	}

	data, err := f.ReadFile(name)
	if err != nil {
		return nil, err
	}
	return objectInfo{name: path.Base(name), size: int64(len(data))}, nil
}

// ReadDir lists the immediate entries of one folder inside the object.
//
// The listing is derived from the object's tar archive so it stays
// adapter-agnostic instead of assuming a local directory layout.
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

// MkdirAll is a no-op because object storage has no meaningful empty folder.
//
// Writing "a/b/c.txt" creates the implied path, so an explicit folder creation
// has nothing to do.
func (f *ObjectFS) MkdirAll(string, os.FileMode) error { return nil }

// listAll returns every file path inside the object, excluding metadata
// markers that the adapter already filters from the archive.
func (f *ObjectFS) listAll() ([]string, error) {
	rc, err := f.mgr.ReadActualArchive(f.ctx, f.id)
	if err != nil {
		return nil, err
	}
	defer rc.Close()

	reader := tar.NewReader(rc)
	var paths []string
	for {
		header, err := reader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("objectfs: read archive: %w", err)
		}
		if header.Typeflag != tar.TypeReg {
			continue
		}
		cleaned := path.Clean(strings.TrimPrefix(header.Name, "./"))
		if cleaned == "" || cleaned == "." {
			continue
		}
		paths = append(paths, cleaned)
	}
	return paths, nil
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
