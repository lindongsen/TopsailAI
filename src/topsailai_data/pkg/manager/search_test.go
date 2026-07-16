package manager

import (
	"errors"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

func TestParseSearchQuery(t *testing.T) {
	cases := []struct {
		input string
		terms []string
	}{
		{"hello", []string{"hello"}},
		{"foo|bar", []string{"foo", "bar"}},
		{"FOO|bar|baz", []string{"foo", "bar", "baz"}},
		{"dup|dup|unique", []string{"dup", "unique"}},
	}

	for _, tc := range cases {
		t.Run(tc.input, func(t *testing.T) {
			terms, err := ParseSearchQuery(tc.input)
			if err != nil {
				t.Fatalf("ParseSearchQuery failed: %v", err)
			}
			if len(terms) != len(tc.terms) {
				t.Fatalf("expected %v, got %v", tc.terms, terms)
			}
			for i, term := range tc.terms {
				if terms[i] != term {
					t.Fatalf("expected term %q at index %d, got %q", term, i, terms[i])
				}
			}
		})
	}
}

func TestParseSearchQueryInvalid(t *testing.T) {
	invalid := []string{
		"",
		"hello world",
		"  spaces  | around ",
		"hello\tworld",
		"hello\\world",
		"|",
	}

	for _, input := range invalid {
		t.Run(input, func(t *testing.T) {
			_, err := ParseSearchQuery(input)
			if err == nil {
				t.Fatalf("expected error for query %q", input)
			}
			if !errors.Is(err, apperrors.ErrInvalidSearchQuery) {
				t.Fatalf("expected ErrInvalidSearchQuery, got %v", err)
			}
		})
	}
}
