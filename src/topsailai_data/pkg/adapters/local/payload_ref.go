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
	parts, err := validateObjectRef(ref)
	if err != nil {
		return "", err
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

// validateObjectRef checks canonical local reference syntax without filesystem access.
func validateObjectRef(ref string) ([]string, error) {
	if ref == "" || strings.ContainsAny(ref, `\:`) || filepath.IsAbs(ref) {
		return nil, fmt.Errorf("non-relative object reference %q: %w", ref, apperrors.ErrInvalidPath)
	}
	parts := strings.Split(ref, "/")
	if len(parts) < TimePrefixDepth+1 || len(parts) > MaxDepth {
		return nil, fmt.Errorf("object reference depth %d: %w", len(parts), apperrors.ErrInvalidPath)
	}
	if !isTimePrefixSegments(parts[0], parts[1], parts[2]) {
		return nil, fmt.Errorf("invalid time prefix in reference %q: %w", ref, apperrors.ErrInvalidPath)
	}
	for _, part := range parts {
		if err := ValidateClassifySegment(part); err != nil {
			return nil, fmt.Errorf("invalid reference segment: %w: %v", apperrors.ErrInvalidPath, err)
		}
	}
	if err := ValidateObjectName(parts[len(parts)-1]); err != nil {
		return nil, fmt.Errorf("invalid reference name: %w: %v", apperrors.ErrInvalidPath, err)
	}
	return parts, nil
}

// resolvePayloadFile rejects interior aliases and special nodes before file access.
// Caller custody is required against cooperative mutations during validation/use.
func resolvePayloadFile(dir, filename string) (string, error) {
	if err := validateActualFilename(filename); err != nil {
		return "", err
	}
	parts := strings.Split(filepath.ToSlash(filepath.Clean(filename)), "/")
	current := dir
	for i, part := range parts {
		current = filepath.Join(current, part)
		info, err := os.Lstat(current)
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return "", fmt.Errorf("inspect payload entry %q: %w", current, err)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return "", fmt.Errorf("payload alias %q: %w", current, apperrors.ErrInvalidPath)
		}
		if i < len(parts)-1 && !info.IsDir() {
			return "", fmt.Errorf("payload parent %q is not a directory: %w", current, apperrors.ErrInvalidPath)
		}
		if !info.IsDir() && !info.Mode().IsRegular() {
			return "", fmt.Errorf("special payload entry %q: %w", current, apperrors.ErrInvalidPath)
		}
	}
	return current, nil
}
