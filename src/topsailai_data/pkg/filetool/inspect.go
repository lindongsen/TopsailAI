package filetool

import (
	"os"
	"path/filepath"
	"sort"
)

// Exists reports whether a file or folder exists.
func Exists(path string) bool {
	if path == "" {
		return false
	}
	_, err := os.Stat(path)
	return err == nil
}

// CheckFilesExisting reports existence for each named path.
//
// The returned map keeps the caller's names as keys, so a caller can label the
// checks independently of the paths.
func CheckFilesExisting(files map[string]string) (map[string]bool, error) {
	if len(files) == 0 {
		return nil, invalidParameter("files", files, "must be a non-empty map")
	}
	result := make(map[string]bool, len(files))
	for name, path := range files {
		result[name] = Exists(path)
	}
	return result, nil
}

// ListDir returns the entry names of one folder, sorted for stable output.
func ListDir(path string) ([]string, error) {
	if path == "" {
		return nil, invalidParameter("folder_path", path, "must be a non-empty string")
	}
	entries, err := os.ReadDir(path)
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
	if len(paths) == 0 {
		return nil, invalidParameter("dirs", paths, "must be a non-empty list")
	}
	result := make(map[string][]string, len(paths))
	for _, path := range paths {
		names, err := ListDir(path)
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
	if path == "" {
		return 0, invalidParameter("file_path", path, "must be a non-empty string")
	}
	info, err := os.Stat(path)
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
	if len(dirs) == 0 {
		return invalidParameter("dirs", dirs, "must be a non-empty list")
	}
	for _, dir := range dirs {
		if dir == "" {
			return invalidParameter("dirs", dirs, "must contain non-empty paths")
		}
		if !filepath.IsAbs(dir) {
			return invalidParameter("dirs", dirs, "require absolute path: "+dir)
		}
	}
	for _, dir := range dirs {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	return nil
}
