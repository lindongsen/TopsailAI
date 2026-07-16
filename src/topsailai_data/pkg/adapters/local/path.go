// Package local implements the local filesystem adapter for topsailai_data.
package local

import (
	"fmt"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

const (
	// MaxDepth is the maximum number of directory levels from the root to the
	// object folder, inclusive. The root itself is level 0.
	MaxDepth = 11

	// TimePrefixDepth is the number of levels consumed by the time prefix
	// (YYYY/MMDD/HHMM).
	TimePrefixDepth = 3
)

// reservedNames lists file names that are not allowed as object or classify
// names because they are reserved by the operating system or by this project.
var reservedNames = map[string]bool{
	".":   true,
	"..":  true,
	"CON": true,
	"PRN": true,
	"AUX": true,
	"NUL": true,
	"COM1": true,
	"COM2": true,
	"COM3": true,
	"COM4": true,
	"COM5": true,
	"COM6": true,
	"COM7": true,
	"COM8": true,
	"COM9": true,
	"LPT1": true,
	"LPT2": true,
	"LPT3": true,
	"LPT4": true,
	"LPT5": true,
	"LPT6": true,
	"LPT7": true,
	"LPT8": true,
	"LPT9": true,
}

// TimePath returns the time prefix for an object created at time t.
// The prefix uses local time and has the form "YYYY/MMDD/HHMM".
func TimePath(t time.Time) string {
	year, month, day := t.Date()
	hour, minute := t.Hour(), t.Minute()
	return fmt.Sprintf("%04d/%02d%02d/%02d%02d", year, month, day, hour, minute)
}

// BuildObjectPath builds the full relative path for an object.
// It combines the time prefix, optional classify directories, and the object
// name. The total depth must not exceed MaxDepth.
func BuildObjectPath(t time.Time, classify []string, name string) (string, error) {
	if err := ValidateObjectName(name); err != nil {
		return "", fmt.Errorf("invalid object name %q: %w", name, err)
	}
	for i, seg := range classify {
		if err := ValidateClassifySegment(seg); err != nil {
			return "", fmt.Errorf("invalid classify segment at index %d: %w", i, err)
		}
	}

	parts := make([]string, 0, TimePrefixDepth+len(classify)+1)
	parts = append(parts, TimePath(t))
	parts = append(parts, classify...)
	parts = append(parts, name)

	path := filepath.Join(parts...)
	if Depth(path) > MaxDepth {
		return "", fmt.Errorf("%w: %d levels (max %d)", errors.ErrDepthExceeded, Depth(path), MaxDepth)
	}
	return path, nil
}

// Depth returns the number of path segments in a relative path.
// An empty path has depth 0.
func Depth(path string) int {
	path = strings.TrimSpace(path)
	if path == "" {
		return 0
	}
	path = filepath.ToSlash(path)
	path = strings.Trim(path, "/")
	if path == "" {
		return 0
	}
	return len(strings.Split(path, "/"))
}

// ParseObjectIDFromPath extracts the object ID from a full object path.
// In the local adapter the object ID equals the object folder name.
func ParseObjectIDFromPath(objectPath string) (models.ObjectID, error) {
	objectPath = strings.TrimSpace(objectPath)
	if objectPath == "" {
		return "", fmt.Errorf("%w: empty object path", errors.ErrInvalidPath)
	}
	objectPath = filepath.ToSlash(objectPath)
	objectPath = strings.Trim(objectPath, "/")
	name := filepath.Base(objectPath)
	if name == "." || name == "/" || name == "" {
		return "", fmt.Errorf("%w: cannot extract object name from %q", errors.ErrInvalidPath, objectPath)
	}
	return models.ObjectID(name), nil
}

// ExtractTimePrefix extracts the YYYY/MMDD/HHMM prefix from an object path.
// It returns the three segments and a boolean indicating whether a valid time
// prefix was found. The path uses forward slashes regardless of the host OS.
func ExtractTimePrefix(objectPath string) (year, monthDay, hourMinute string, ok bool) {
	objectPath = strings.TrimSpace(objectPath)
	if objectPath == "" {
		return "", "", "", false
	}
	objectPath = filepath.ToSlash(objectPath)
	objectPath = strings.Trim(objectPath, "/")
	segments := strings.Split(objectPath, "/")
	if len(segments) < 3 {
		return "", "", "", false
	}
	if !isTimePrefixSegments(segments[0], segments[1], segments[2]) {
		return "", "", "", false
	}
	return segments[0], segments[1], segments[2], true
}

// isTimePrefixSegments reports whether the three segments look like a time
// prefix produced by TimePath: YYYY/MMDD/HHMM.
func isTimePrefixSegments(year, monthDay, hourMinute string) bool {
	if len(year) != 4 || len(monthDay) != 4 || len(hourMinute) != 4 {
		return false
	}
	for _, s := range []string{year, monthDay, hourMinute} {
		for _, r := range s {
			if r < '0' || r > '9' {
				return false
			}
		}
	}
	return true
}

// ValidateObjectName checks whether name is a valid object name.
// Object names must be non-empty, valid UTF-8, not reserved, and must not
// contain path separators or control characters.
func ValidateObjectName(name string) error {
	if err := validateSegment(name, true); err != nil {
		return err
	}
	if strings.HasSuffix(name, ".tags") || strings.HasSuffix(name, ".lock") ||
		strings.HasSuffix(name, ".deleted") || strings.HasSuffix(name, ".ceased") {
		return fmt.Errorf("%w: name must not use a reserved marker suffix", errors.ErrInvalidName)
	}
	return nil
}

// ValidateClassifySegment checks whether seg is a valid classify directory name.
func ValidateClassifySegment(seg string) error {
	return validateSegment(seg, false)
}

// validateSegment performs common validation for object and classify names.
func validateSegment(seg string, isObject bool) error {
	if seg == "" {
		return fmt.Errorf("%w: empty segment", errors.ErrInvalidName)
	}
	if !utf8.ValidString(seg) {
		return fmt.Errorf("%w: invalid UTF-8", errors.ErrInvalidName)
	}
	if strings.ContainsAny(seg, `/\`) {
		return fmt.Errorf("%w: segment contains path separator", errors.ErrInvalidName)
	}
	if strings.ContainsRune(seg, 0) {
		return fmt.Errorf("%w: segment contains null byte", errors.ErrInvalidName)
	}
	upper := strings.ToUpper(seg)
	if reservedNames[upper] {
		return fmt.Errorf("%w: reserved name %q", errors.ErrInvalidName, seg)
	}
	if strings.HasPrefix(seg, " ") || strings.HasSuffix(seg, " ") {
		return fmt.Errorf("%w: leading or trailing space", errors.ErrInvalidName)
	}
	if seg == "." || seg == ".." {
		return fmt.Errorf("%w: relative path segment", errors.ErrInvalidName)
	}
	for _, r := range seg {
		if r < 32 {
			return fmt.Errorf("%w: control character", errors.ErrInvalidName)
		}
	}
	if isObject && seg == "" {
		return fmt.Errorf("%w: empty object name", errors.ErrInvalidName)
	}
	return nil
}
