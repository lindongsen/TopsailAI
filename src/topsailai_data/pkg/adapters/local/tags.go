// Package local implements the local filesystem adapter for topsailai_data.
package local

import (
	"fmt"
	"strings"

	"github.com/topsailai/topsailai_data/pkg/errors"
)

// MergeTags returns a new slice containing all tags from base followed by any
// tags from extra that are not already present. Order is preserved and
// duplicates are removed.
func MergeTags(base, extra []string) []string {
	seen := make(map[string]struct{}, len(base)+len(extra))
	result := make([]string, 0, len(base)+len(extra))

	for _, t := range base {
		if _, ok := seen[t]; ok {
			continue
		}
		seen[t] = struct{}{}
		result = append(result, t)
	}
	for _, t := range extra {
		if _, ok := seen[t]; ok {
			continue
		}
		seen[t] = struct{}{}
		result = append(result, t)
	}
	return result
}

// ValidateTag checks that a tag is non-empty and does not contain forbidden
// characters.
func ValidateTag(tag string) error {
	if tag == "" {
		return fmt.Errorf("%w: empty tag", errors.ErrInvalidTag)
	}
	if strings.ContainsAny(tag, `/\`) {
		return fmt.Errorf("%w: tag contains path separator", errors.ErrInvalidTag)
	}
	if strings.ContainsRune(tag, 0) {
		return fmt.Errorf("%w: tag contains null byte", errors.ErrInvalidTag)
	}
	if strings.HasPrefix(tag, " ") || strings.HasSuffix(tag, " ") {
		return fmt.Errorf("%w: leading or trailing space", errors.ErrInvalidTag)
	}
	return nil
}
