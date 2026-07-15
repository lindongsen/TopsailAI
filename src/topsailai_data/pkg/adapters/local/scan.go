// Package local implements the local filesystem adapter for topsailai_data.
package local

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// ScannedObject holds the metadata discovered by scanning the local filesystem.
type ScannedObject struct {
	// Path is the relative path from the adapter root to the object folder.
	Path string
	// Name is the object name, equal to the object folder name.
	Name string
	// Tags is the merged set of inherited classify tags and object-specific tags.
	Tags []string
	// CreatedAt is the object creation time parsed from the time prefix in Path.
	CreatedAt time.Time
}

// Scanner walks the local filesystem and discovers object folders.
type Scanner struct {
	root string
}

// NewScanner creates a Scanner that scans root for object folders.
func NewScanner(root string) *Scanner {
	return &Scanner{root: root}
}

// Scan walks the root directory recursively and returns all object folders.
// An object folder is identified by the presence of a file named
// {folder-name}.md directly inside the folder. Once an object folder is
// found, its subdirectories are not scanned.
func (s *Scanner) Scan(ctx context.Context) ([]ScannedObject, error) {
	var objects []ScannedObject

	err := filepath.WalkDir(s.root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if !d.IsDir() {
			return nil
		}
		if path == s.root {
			return nil
		}

		name := filepath.Base(path)
		mdFile := filepath.Join(path, name+".md")
		if _, statErr := os.Stat(mdFile); statErr != nil {
			if os.IsNotExist(statErr) {
				return nil
			}
			return fmt.Errorf("stat object marker %q: %w", mdFile, statErr)
		}

		relPath, err := filepath.Rel(s.root, path)
		if err != nil {
			return fmt.Errorf("relate object path %q to root: %w", path, err)
		}

		tags, err := CollectTags(s.root, relPath)
		if err != nil {
			return fmt.Errorf("collect tags for %q: %w", relPath, err)
		}

		createdAt, err := createdAtFromObjectPath(relPath)
		if err != nil {
			info, infoErr := d.Info()
			if infoErr != nil {
				return fmt.Errorf("get info for %q: %w", path, infoErr)
			}
			createdAt = info.ModTime()
		}

		objects = append(objects, ScannedObject{
			Path:      relPath,
			Name:      name,
			Tags:      tags,
			CreatedAt: createdAt,
		})

		return filepath.SkipDir
	})

	if err != nil {
		return nil, err
	}
	return objects, nil
}

// createdAtFromObjectPath parses the creation time from the time prefix of an
// object path. The expected format is "YYYY/MMDD/HHMM/...". If the prefix is
// missing or malformed, an error is returned.
func createdAtFromObjectPath(objectPath string) (time.Time, error) {
	objectPath = filepath.ToSlash(objectPath)
	objectPath = strings.Trim(objectPath, "/")
	parts := strings.Split(objectPath, "/")
	if len(parts) < 4 {
		return time.Time{}, fmt.Errorf("path %q does not contain a time prefix", objectPath)
	}

	yearStr := parts[0]
	monthDayStr := parts[1]
	hourMinuteStr := parts[2]

	if len(yearStr) != 4 || len(monthDayStr) != 4 || len(hourMinuteStr) != 4 {
		return time.Time{}, fmt.Errorf("invalid time prefix in path %q", objectPath)
	}

	year, err := strconv.Atoi(yearStr)
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid year %q: %w", yearStr, err)
	}
	month, err := strconv.Atoi(monthDayStr[:2])
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid month %q: %w", monthDayStr[:2], err)
	}
	day, err := strconv.Atoi(monthDayStr[2:])
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid day %q: %w", monthDayStr[2:], err)
	}
	hour, err := strconv.Atoi(hourMinuteStr[:2])
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid hour %q: %w", hourMinuteStr[:2], err)
	}
	minute, err := strconv.Atoi(hourMinuteStr[2:])
	if err != nil {
		return time.Time{}, fmt.Errorf("invalid minute %q: %w", hourMinuteStr[2:], err)
	}

	return time.Date(year, time.Month(month), day, hour, minute, 0, 0, time.Local), nil
}
