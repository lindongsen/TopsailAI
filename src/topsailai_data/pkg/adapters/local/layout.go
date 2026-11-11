package local

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"path/filepath"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// StoreLayout resolves the new sibling trees without creating or inspecting files.
// Its root is always the store container, never an object or metadata tree root.
type StoreLayout struct {
	storeRoot string
}

// NewStoreLayout accepts an absolute store container path; callers resolve
// configuration-relative paths before calling it. It does not resolve symlinks.
func NewStoreLayout(storeRoot string) (StoreLayout, error) {
	if !filepath.IsAbs(storeRoot) {
		return StoreLayout{}, fmt.Errorf("store root must be absolute: %w", apperrors.ErrInvalidPath)
	}
	return StoreLayout{storeRoot: filepath.Clean(storeRoot)}, nil
}

// ObjectRoot returns the payload tree beneath the store container.
func (l StoreLayout) ObjectRoot() string {
	return filepath.Join(l.storeRoot, "object")
}

// MetaRoot returns the metadata tree beneath the store container.
func (l StoreLayout) MetaRoot() string {
	return filepath.Join(l.storeRoot, "meta")
}

// ObjectMetaPath hashes the exact local object ID, independent of classify path.
// The returned lexical path does not establish filesystem or symlink containment.
func (l StoreLayout) ObjectMetaPath(id models.ObjectID) (string, error) {
	if l.storeRoot == "" {
		return "", fmt.Errorf("uninitialized store layout: %w", apperrors.ErrInvalidPath)
	}
	if err := ValidateObjectName(string(id)); err != nil {
		return "", fmt.Errorf("metadata path for object %q: %w", id, err)
	}
	digest := sha256.Sum256([]byte(id))
	hash := hex.EncodeToString(digest[:])
	return filepath.Join(l.MetaRoot(), hash[:2], hash[2:4], hash[4:6], hash), nil
}
