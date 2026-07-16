package local

import (
	"errors"
	"strings"
	"testing"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

func TestValidateObjectName(t *testing.T) {
	valid := []string{"hello", "hello-world", "note_1", "a", "with space inside"}
	for _, name := range valid {
		t.Run(name, func(t *testing.T) {
			if err := ValidateObjectName(name); err != nil {
				t.Fatalf("expected %q to be valid, got %v", name, err)
			}
		})
	}

	invalid := []struct {
		name    string
		wantErr error
	}{
		{"", apperrors.ErrInvalidName},
		{"hello/world", apperrors.ErrInvalidName},
		{"hello\\world", apperrors.ErrInvalidName},
		{"hello\x00world", apperrors.ErrInvalidName},
		{" leading", apperrors.ErrInvalidName},
		{"trailing ", apperrors.ErrInvalidName},
		{".", apperrors.ErrInvalidName},
		{"..", apperrors.ErrInvalidName},
		{"CON", apperrors.ErrInvalidName},
		{"NUL", apperrors.ErrInvalidName},
		{"hello.tags", apperrors.ErrInvalidName},
		{"hello.lock", apperrors.ErrInvalidName},
		{"hello.deleted", apperrors.ErrInvalidName},
		{"hello.ceased", apperrors.ErrInvalidName},
	}

	for _, tc := range invalid {
		t.Run(tc.name, func(t *testing.T) {
			err := ValidateObjectName(tc.name)
			if err == nil {
				t.Fatalf("expected %q to be invalid", tc.name)
			}
			if tc.wantErr != nil && !errors.Is(err, tc.wantErr) {
				t.Fatalf("expected error %v, got %v", tc.wantErr, err)
			}
		})
	}
}

func TestValidateClassifySegment(t *testing.T) {
	valid := []string{"work", "2026", "project-alpha"}
	for _, seg := range valid {
		t.Run(seg, func(t *testing.T) {
			if err := ValidateClassifySegment(seg); err != nil {
				t.Fatalf("expected %q to be valid, got %v", seg, err)
			}
		})
	}

	invalid := []string{"", "a/b", "a\\b", "a\x00b", " leading", "trailing ", ".", "..", "CON"}
	for _, seg := range invalid {
		t.Run(seg, func(t *testing.T) {
			if err := ValidateClassifySegment(seg); err == nil {
				t.Fatalf("expected %q to be invalid", seg)
			}
		})
	}
}

func TestBuildObjectPath(t *testing.T) {
	now := time.Date(2026, 7, 14, 23, 23, 0, 0, time.UTC)

	cases := []struct {
		name     string
		classify []string
		wantTail string
	}{
		{"hello", nil, "2026/0714/2323/hello"},
		{"hello", []string{"work"}, "2026/0714/2323/work/hello"},
		{"hello", []string{"work", "2026"}, "2026/0714/2323/work/2026/hello"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			path, err := BuildObjectPath(now, tc.classify, tc.name)
			if err != nil {
				t.Fatalf("BuildObjectPath failed: %v", err)
			}
			if !strings.HasSuffix(path, strings.ReplaceAll(tc.wantTail, "/", string(filepathSeparator()))) {
				t.Fatalf("expected path to end with %q, got %q", tc.wantTail, path)
			}
		})
	}
}

func filepathSeparator() byte {
	return '/'
}

func TestBuildObjectPathDepthExceeded(t *testing.T) {
	now := time.Date(2026, 7, 14, 23, 23, 0, 0, time.UTC)

	// Time prefix (3) + object (1) + 8 classify = 12 > 11.
	classify := []string{"a", "b", "c", "d", "e", "f", "g", "h"}
	_, err := BuildObjectPath(now, classify, "obj")
	if err == nil {
		t.Fatal("expected depth-exceeded error")
	}
	if !errors.Is(err, apperrors.ErrDepthExceeded) {
		t.Fatalf("expected ErrDepthExceeded, got %v", err)
	}
}

func TestBuildObjectPathInvalidClassify(t *testing.T) {
	now := time.Date(2026, 7, 14, 23, 23, 0, 0, time.UTC)

	_, err := BuildObjectPath(now, []string{"bad/name"}, "obj")
	if err == nil {
		t.Fatal("expected error for invalid classify segment")
	}
}

func TestBuildObjectPathInvalidName(t *testing.T) {
	now := time.Date(2026, 7, 14, 23, 23, 0, 0, time.UTC)
	_, err := BuildObjectPath(now, nil, "bad/name")
	if err == nil {
		t.Fatal("expected error for invalid object name")
	}
}

func TestParseObjectIDFromPath(t *testing.T) {
	cases := []struct {
		path string
		want models.ObjectID
	}{
		{"2026/0714/2323/hello", "hello"},
		{"2026/0714/2323/work/hello", "hello"},
		{"hello", "hello"},
		{"/2026/0714/2323/hello/", "hello"},
	}

	for _, tc := range cases {
		t.Run(tc.path, func(t *testing.T) {
			got, err := ParseObjectIDFromPath(tc.path)
			if err != nil {
				t.Fatalf("ParseObjectIDFromPath failed: %v", err)
			}
			if got != tc.want {
				t.Fatalf("expected %q, got %q", tc.want, got)
			}
		})
	}
}

func TestParseObjectIDFromPathInvalid(t *testing.T) {
	invalid := []string{"", "/"}
	for _, path := range invalid {
		t.Run(path, func(t *testing.T) {
			_, err := ParseObjectIDFromPath(path)
			if err == nil {
				t.Fatalf("expected error for path %q", path)
			}
			if !errors.Is(err, apperrors.ErrInvalidPath) {
				t.Fatalf("expected ErrInvalidPath, got %v", err)
			}
		})
	}
}

func TestDepth(t *testing.T) {
	cases := []struct {
		path string
		want int
	}{
		{"", 0},
		{"hello", 1},
		{"2026/0714/2323/hello", 4},
		{"2026/0714/2323/a/b/c/d/e/f/g/hello", 11},
		{"/2026/0714/2323/hello/", 4},
		{"   2026/0714/2323/hello   ", 4},
	}

	for _, tc := range cases {
		t.Run(tc.path, func(t *testing.T) {
			got := Depth(tc.path)
			if got != tc.want {
				t.Fatalf("expected depth %d, got %d", tc.want, got)
			}
		})
	}
}

func TestTimePath(t *testing.T) {
	now := time.Date(2026, 7, 14, 23, 23, 0, 0, time.UTC)
	got := TimePath(now)
	want := "2026/0714/2323"
	if got != want {
		t.Fatalf("expected %q, got %q", want, got)
	}
}
