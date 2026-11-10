package filetool

import (
	"os"
	"path/filepath"
	"sort"
	"time"
)

// Exists reports whether a file or folder exists.
func Exists(path string) bool {
	return ExistsWithFS(path, nil)
}

// ExistsWithFS reports whether a file or folder exists through the given file
// system. A nil file system uses the operating system file system.
func ExistsWithFS(path string, fs FS) bool {
	if path == "" {
		return false
	}
	_, err := resolveFS(fs).Stat(path)
	return err == nil
}

// CheckFilesExisting reports existence for each named path.
//
// The returned map keeps the caller's names as keys, so a caller can label the
// checks independently of the paths.
func CheckFilesExisting(files map[string]string) (map[string]bool, error) {
	return CheckFilesExistingWithFS(files, nil)
}

// CheckFilesExistingWithFS reports existence for each named path through the
// given file system. A nil file system uses the operating system file system.
func CheckFilesExistingWithFS(files map[string]string, fs FS) (map[string]bool, error) {
	if len(files) == 0 {
		return nil, invalidParameter("files", files, "must be a non-empty map")
	}
	result := make(map[string]bool, len(files))
	for name, path := range files {
		result[name] = ExistsWithFS(path, fs)
	}
	return result, nil
}

// ListDir returns the entry names of one folder, sorted for stable output.
func ListDir(path string) ([]string, error) {
	return ListDirWithFS(path, nil)
}

// ListDirWithFS returns the entry names of one folder through the given file
// system. A nil file system uses the operating system file system.
func ListDirWithFS(path string, fs FS) ([]string, error) {
	if path == "" {
		// An object-backed file system has a meaningful root, so an empty path
		// addresses the object folder itself. The operating-system file system
		// has no such default and keeps rejecting an empty path.
		if fs == nil {
			return nil, invalidParameter("folder_path", path, "must be a non-empty string")
		}
		path = "."
	}
	entries, err := resolveFS(fs).ReadDir(path)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	sort.Strings(names)
	return names, nil
}

// ListDirs returns a folder-to-entry-names map for several folders.
//
// A folder that cannot be listed is recorded as a single error entry so one
// failure does not hide the others.
func ListDirs(paths []string) (map[string][]string, error) {
	return ListDirsWithFS(paths, nil)
}

// ListDirsWithFS returns a folder-to-entry-names map through the given file
// system. A nil file system uses the operating system file system.
func ListDirsWithFS(paths []string, fs FS) (map[string][]string, error) {
	if len(paths) == 0 {
		return nil, invalidParameter("dirs", paths, "must be a non-empty list")
	}
	result := make(map[string][]string, len(paths))
	for _, path := range paths {
		names, err := ListDirWithFS(path, fs)
		if err != nil {
			result[path] = []string{"Error: " + err.Error()}
			continue
		}
		result[path] = names
	}
	return result, nil
}

// FileSize returns the size of a file in bytes.
func FileSize(path string) (int64, error) {
	return FileSizeWithFS(path, nil)
}

// FileSizeWithFS returns the size of a file in bytes through the given file
// system. A nil file system uses the operating system file system.
func FileSizeWithFS(path string, fs FS) (int64, error) {
	if path == "" {
		return 0, invalidParameter("file_path", path, "must be a non-empty string")
	}
	info, err := resolveFS(fs).Stat(path)
	if err != nil {
		return 0, err
	}
	return info.Size(), nil
}

// MakeDirs creates every folder in the list, including missing parents.
//
// Every path must be absolute; a relative path is rejected so a tool call cannot
// silently create folders relative to an unexpected working directory.
func MakeDirs(dirs []string) error {
	return MakeDirsWithFS(dirs, nil)
}

// MakeDirsWithFS creates every folder in the list through the given file
// system. A nil file system uses the operating system file system.
//
// The absolute-path requirement applies only to the operating system file
// system. An object-backed file system has no meaningful absolute path, so its
// paths are accepted as given.
func MakeDirsWithFS(dirs []string, fs FS) error {
	if len(dirs) == 0 {
		return invalidParameter("dirs", dirs, "must be a non-empty list")
	}
	for _, dir := range dirs {
		if dir == "" {
			return invalidParameter("dirs", dirs, "must contain non-empty paths")
		}
		if fs == nil && !filepath.IsAbs(dir) {
			return invalidParameter("dirs", dirs, "require absolute path: "+dir)
		}
	}
	target := resolveFS(fs)
	for _, dir := range dirs {
		if err := target.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	return nil
}

// dirEntry is a minimal os.DirEntry used by file systems that synthesize
// entries instead of reading a real directory.
type dirEntry struct {
	name  string
	isDir bool
}

// Name returns the entry name.
func (e dirEntry) Name() string { return e.name }

// IsDir reports whether the entry is a folder.
func (e dirEntry) IsDir() bool { return e.isDir }

// Type returns the entry mode type bits.
func (e dirEntry) Type() os.FileMode {
	if e.isDir {
		return os.ModeDir
	}
	return 0
}

// Info returns file information for the entry.
func (e dirEntry) Info() (os.FileInfo, error) {
	return syntheticFileInfo{name: e.name, dir: e.isDir}, nil
}

// syntheticFileInfo is an os.FileInfo for content that has no real file behind
// it, such as a file inside an object.
type syntheticFileInfo struct {
	name string
	size int64
	dir  bool
}

// Name returns the base name.
func (i syntheticFileInfo) Name() string { return i.name }

// Size returns the content length in bytes.
func (i syntheticFileInfo) Size() int64 { return i.size }

// Mode returns the file mode.
func (i syntheticFileInfo) Mode() os.FileMode {
	if i.dir {
		return os.ModeDir | 0o755
	}
	return 0o644
}

// ModTime reports a zero modification time because object content carries no
// per-file timestamp.
func (i syntheticFileInfo) ModTime() time.Time { return time.Time{} }

// IsDir reports whether the entry is a folder.
func (i syntheticFileInfo) IsDir() bool { return i.dir }

// Sys returns no underlying system information.
func (i syntheticFileInfo) Sys() any { return nil }
