// Package local implements the local filesystem adapter for topsailai_data.
package local

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/topsailai/topsailai_data/pkg/errors"
)

// commentPrefixes lists the line prefixes that are treated as comments in a
// .tags file. A line is a comment if it starts with any of these prefixes
// after leading whitespace has been removed.
var commentPrefixes = []string{"#", ";", "//", "--"}

// ReadTagsFile reads a single .tags file and returns the tags it contains.
// If the file does not exist, an empty slice and a nil error are returned.
// Empty lines and comment lines are ignored. Each tag is trimmed of leading
// and trailing whitespace.
func ReadTagsFile(path string) ([]string, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return []string{}, nil
		}
		return nil, fmt.Errorf("open tags file %q: %w", path, err)
	}
	defer f.Close()

	var tags []string
	scanner := bufio.NewScanner(f)
	lineNo := 0
	for scanner.Scan() {
		lineNo++
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		if isCommentLine(line) {
			continue
		}
		if err := ValidateTag(line); err != nil {
			return nil, fmt.Errorf("tags file %q line %d: %w", path, lineNo, err)
		}
		tags = append(tags, line)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("read tags file %q: %w", path, err)
	}
	return tags, nil
}

// CollectTags merges tags inherited from classify directories along the path
// from root to objectPath, plus the object's own tags file.
//
// The merge order is from the root toward the object: tags from ancestor
// classify directories come first, followed by tags from directories closer
// to the object, and finally the object's own tags. Duplicates are removed
// while preserving this order.
func CollectTags(root, objectPath string) ([]string, error) {
	root = filepath.Clean(root)
	objectPath = filepath.Clean(objectPath)

	if !filepath.IsAbs(root) {
		return nil, fmt.Errorf("%w: root must be absolute", errors.ErrInvalidPath)
	}

	fullObjectPath := objectPath
	if !filepath.IsAbs(objectPath) {
		fullObjectPath = filepath.Join(root, objectPath)
	}

	// Verify the object path is inside the root.
	rel, err := filepath.Rel(root, fullObjectPath)
	if err != nil {
		return nil, fmt.Errorf("relate object path to root: %w", err)
	}
	if strings.HasPrefix(rel, "..") {
		return nil, fmt.Errorf("%w: object path %q is outside root %q", errors.ErrInvalidPath, objectPath, root)
	}

	// Walk each directory level from root to the object folder and collect
	// inherited classify tags. The object folder itself is included so its own
	// .tags file is read last.
	segments := splitPath(rel)
	var merged []string
	current := root
	for _, seg := range segments {
		current = filepath.Join(current, seg)
		tagsFile := filepath.Join(current, seg+".tags")
		tags, err := ReadTagsFile(tagsFile)
		if err != nil {
			return nil, fmt.Errorf("collect tags at %q: %w", current, err)
		}
		merged = MergeTags(merged, tags)
	}

	return merged, nil
}

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

// isCommentLine reports whether line is a comment line after trimming leading
// whitespace. The caller is expected to have trimmed the line already.
func isCommentLine(line string) bool {
	for _, prefix := range commentPrefixes {
		if strings.HasPrefix(line, prefix) {
			return true
		}
	}
	return false
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

// splitPath splits a clean relative path into its segments.
func splitPath(path string) []string {
	path = filepath.ToSlash(path)
	path = strings.Trim(path, "/")
	if path == "" {
		return nil
	}
	return strings.Split(path, "/")
}

// WriteTagsFile writes tags to a .tags file, one per line. If tags is empty,
// any existing file at path is removed. Tags are validated before writing.
func WriteTagsFile(path string, tags []string) error {
	if len(tags) == 0 {
		if err := os.Remove(path); err != nil && !os.IsNotExist(err) {
			return fmt.Errorf("remove empty tags file %q: %w", path, err)
		}
		return nil
	}
	content := ""
	for _, tag := range tags {
		if err := ValidateTag(tag); err != nil {
			return fmt.Errorf("%w: %q", errors.ErrInvalidTag, tag)
		}
		content += tag + "\n"
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		return fmt.Errorf("write tags file %q: %w", path, err)
	}
	return nil
}
