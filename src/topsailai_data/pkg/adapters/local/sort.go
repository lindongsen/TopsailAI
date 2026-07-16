package local

import (
	"fmt"
	"strings"

	"github.com/topsailai/topsailai_data/pkg/models"
)

// SortObjectsByTimePath sorts objects by the YYYY/MMDD/HHMM prefix extracted
// from Object.Path. When ascending is true the oldest time prefix comes first;
// when false (the default) the newest time prefix comes first.
//
// The sort is stable: objects with identical time prefixes keep their original
// relative order.
func SortObjectsByTimePath(objects []*models.Object, ascending bool) {
	if len(objects) < 2 {
		return
	}

	// Use a stable sort so equal time prefixes keep input order.
	for i := 0; i < len(objects)-1; i++ {
		for j := i + 1; j < len(objects); j++ {
			cmp := compareTimePath(objects[i].Path, objects[j].Path)
			if ascending && cmp > 0 {
				objects[i], objects[j] = objects[j], objects[i]
			} else if !ascending && cmp < 0 {
				objects[i], objects[j] = objects[j], objects[i]
			}
		}
	}
}

// compareTimePath compares the time prefixes of two object paths.
// It returns -1 if a < b, 0 if equal, and 1 if a > b.
// If a path has no valid time prefix, it is treated as greater than any valid
// prefix so that malformed paths sort to the end.
func compareTimePath(a, b string) int {
	aPrefix, aOK := timePrefixKey(a)
	bPrefix, bOK := timePrefixKey(b)
	if aOK && bOK {
		if aPrefix < bPrefix {
			return -1
		}
		if aPrefix > bPrefix {
			return 1
		}
		return 0
	}
	if aOK && !bOK {
		return -1
	}
	if !aOK && bOK {
		return 1
	}
	return 0
}

// timePrefixKey extracts a comparable string from the time prefix of an object
// path. It returns the key and a boolean indicating whether a valid prefix was
// found.
func timePrefixKey(objectPath string) (string, bool) {
	year, monthDay, hourMinute, ok := ExtractTimePrefix(objectPath)
	if !ok {
		return "", false
	}
	return year + "/" + monthDay + "/" + hourMinute, true
}

// ParseSortOption parses a sort option string into a boolean indicating
// ascending order. It returns an error for unsupported values.
// Supported values: "time:desc" (default, newest first) and "time:asc"
// (oldest first). An empty string defaults to descending.
func ParseSortOption(sort string) (ascending bool, err error) {
	sort = strings.ToLower(strings.TrimSpace(sort))
	switch sort {
	case "", "time:desc":
		return false, nil
	case "time:asc":
		return true, nil
	default:
		return false, fmt.Errorf("unsupported sort option %q (expected time:asc or time:desc)", sort)
	}
}
