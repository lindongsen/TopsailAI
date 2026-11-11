package local

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// ResolveObjectMetaPath checks hash directory containment without creating files.
// Callers serialize mutations and initialize the store container first. Like
// payload resolution, this does not prevent uncooperative filesystem replacement.
func (l StoreLayout) ResolveObjectMetaPath(id models.ObjectID) (string, error) {
	path, err := l.ObjectMetaPath(id)
	if err != nil {
		return "", err
	}
	rel, err := filepath.Rel(l.MetaRoot(), path)
	if err != nil {
		return "", fmt.Errorf("relative metadata directory: %w", err)
	}
	current := l.MetaRoot()
	if err := checkMetadataDirectory(current); err != nil {
		return "", err
	}
	for _, part := range strings.Split(rel, string(filepath.Separator)) {
		current = filepath.Join(current, part)
		if err := checkMetadataDirectory(current); err != nil {
			return "", err
		}
	}
	return path, nil
}

// checkMetadataDirectory accepts absent paths and rejects symlinks or other nodes.
func checkMetadataDirectory(path string) error {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect metadata directory %q: %w", path, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("metadata path %q is not a directory: %w", path, apperrors.ErrInvalidPath)
	}
	return nil
}
