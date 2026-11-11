package local

import (
	"errors"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

func TestMergeTagsPreservesOrderAndDeduplicates(t *testing.T) {
	base := []string{"a", "b", "c"}
	extra := []string{"b", "d", "a"}
	got := MergeTags(base, extra)
	want := []string{"a", "b", "c", "d"}
	if len(got) != len(want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("tag mismatch at %d: got %q, want %q", i, got[i], want[i])
		}
	}
}

func TestValidateTag(t *testing.T) {
	cases := []struct {
		tag     string
		wantErr error
	}{
		{"valid", nil},
		{"with space inside", nil},
		{"", apperrors.ErrInvalidTag},
		{" leading", apperrors.ErrInvalidTag},
		{"trailing ", apperrors.ErrInvalidTag},
		{"a/b", apperrors.ErrInvalidTag},
		{"a\\b", apperrors.ErrInvalidTag},
		{"a\x00b", apperrors.ErrInvalidTag},
	}

	for _, tc := range cases {
		t.Run(tc.tag, func(t *testing.T) {
			err := ValidateTag(tc.tag)
			if tc.wantErr == nil {
				if err != nil {
					t.Fatalf("expected no error, got %v", err)
				}
				return
			}
			if err == nil {
				t.Fatalf("expected error %v, got nil", tc.wantErr)
			}
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("expected error %v, got %v", tc.wantErr, err)
			}
		})
	}
}
