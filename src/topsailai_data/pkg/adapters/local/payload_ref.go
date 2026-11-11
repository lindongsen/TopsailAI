package local

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// ResolveObjectRef resolves a canonical local reference beneath the payload tree.
// Existing components must be directories, never symlinks. Missing suffixes are
// allowed for creation. Callers must serialize mutations; this is not a defense
// against uncooperative concurrent filesystem replacement.
func (l StoreLayout) ResolveObjectRef(ref string) (string, error) {
	if l.storeRoot == "" {
		return "", fmt.Errorf("uninitialized store layout: %w", apperrors.ErrInvalidPath)
	}
	if ref == "" || strings.ContainsAny(ref, `\:`) || filepath.IsAbs(ref) {
		return "", fmt.Errorf("non-relative object reference %q: %w", ref, apperrors.ErrInvalidPath)
	}
	parts := strings.Split(ref, "/")
	if len(parts) < TimePrefixDepth+1 || len(parts) > MaxDepth {
		return "", fmt.Errorf("object reference depth %d: %w", len(parts), apperrors.ErrInvalidPath)
	}
	if !isTimePrefixSegments(parts[0], parts[1], parts[2]) {
		return "", fmt.Errorf("invalid time prefix in reference %q: %w", ref, apperrors.ErrInvalidPath)
	}
	for _, part := range parts {
		if err := ValidateClassifySegment(part); err != nil {
			return "", fmt.Errorf("invalid reference segment: %w: %v", apperrors.ErrInvalidPath, err)
		}
	}
	if err := ValidateObjectName(parts[len(parts)-1]); err != nil {
		return "", fmt.Errorf("invalid reference name: %w: %v", apperrors.ErrInvalidPath, err)
	}
	current := l.ObjectRoot()
	if err := checkPayloadDirectory(current); err != nil {
		return "", err
	}
	for _, part := range parts {
		current = filepath.Join(current, part)
		if err := checkPayloadDirectory(current); err != nil {
			return "", err
		}
	}
	return current, nil
}

// checkPayloadDirectory accepts missing directories but rejects unsafe existing nodes.
func checkPayloadDirectory(path string) error {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("inspect payload path %q: %w", path, err)
	}
	if !info.IsDir() {
		return fmt.Errorf("payload path %q is not a directory: %w", path, apperrors.ErrInvalidPath)
	}
	return nil
}
