// Package manager provides search query parsing for topsailai_data.
package manager

import (
	"fmt"
	"strings"

	"github.com/topsailai/topsailai_data/pkg/errors"
)

// ParseSearchQuery splits a raw search query into OR terms using '|' as the
// delimiter. It rejects queries that contain unsupported characters such as
// spaces, tabs, or backslash escape sequences, as well as empty terms.
//
// The returned terms are lower-cased and trimmed. If no valid terms remain,
// an error is returned.
func ParseSearchQuery(query string) ([]string, error) {
	if strings.ContainsRune(query, ' ') {
		return nil, fmt.Errorf("%w: search query must not contain spaces; use '|' for OR logic", errors.ErrInvalidSearchQuery)
	}
	if strings.ContainsRune(query, '\t') {
		return nil, fmt.Errorf("%w: search query must not contain tabs; use '|' for OR logic", errors.ErrInvalidSearchQuery)
	}
	if strings.ContainsRune(query, '\\') {
		return nil, fmt.Errorf("%w: search query must not contain backslash escape sequences", errors.ErrInvalidSearchQuery)
	}

	rawTerms := strings.Split(query, "|")
	terms := make([]string, 0, len(rawTerms))
	seen := make(map[string]struct{}, len(rawTerms))
	for _, term := range rawTerms {
		term = strings.TrimSpace(term)
		if term == "" {
			return nil, fmt.Errorf("%w: search query contains an empty term", errors.ErrInvalidSearchQuery)
		}
		lower := strings.ToLower(term)
		if _, ok := seen[lower]; ok {
			continue
		}
		seen[lower] = struct{}{}
		terms = append(terms, lower)
	}

	if len(terms) == 0 {
		return nil, fmt.Errorf("%w: search query is empty", errors.ErrInvalidSearchQuery)
	}
	return terms, nil
}
