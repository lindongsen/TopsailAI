package task

import (
	"fmt"
	"path/filepath"
)

// Source is the seam for discovering tasks.
//
// The daemon reads tasks through this interface, so a different discovery
// mechanism such as a database or a remote registry can replace the filesystem
// scan without touching scheduling or execution.
type Source interface {
	// Load returns the current tasks and one error per rejected task file.
	Load() ([]Task, []LoadError, error)
}

// FilesystemSource discovers tasks by scanning a folder tree.
type FilesystemSource struct {
	// Root is the tasks folder. A relative path is resolved against the working
	// directory on every load, so a changed working directory is honoured.
	Root string
	// MinContentRunes is the shortest accepted task content, counted in runes
	// after trimming whitespace. It is a field rather than a constant so the
	// policy comes from configuration instead of being compiled in.
	MinContentRunes int
}

// NewFilesystemSource returns a source scanning root.
func NewFilesystemSource(root string, minContentRunes int) FilesystemSource {
	return FilesystemSource{Root: root, MinContentRunes: minContentRunes}
}

// Load scans the tasks folder.
func (s FilesystemSource) Load() ([]Task, []LoadError, error) {
	root := s.Root
	if root == "" {
		return nil, nil, fmt.Errorf("tasks root must not be empty")
	}
	if !filepath.IsAbs(root) {
		absolute, err := filepath.Abs(root)
		if err != nil {
			return nil, nil, fmt.Errorf("resolve tasks root %q: %w", root, err)
		}
		root = absolute
	}
	return Load(root, s.MinContentRunes)
}
