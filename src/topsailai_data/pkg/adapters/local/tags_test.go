package local

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

func TestReadTagsFileMissingReturnsEmpty(t *testing.T) {
	tags, err := ReadTagsFile(filepath.Join(t.TempDir(), "missing.tags"))
	if err != nil {
		t.Fatalf("expected no error for missing file, got %v", err)
	}
	if len(tags) != 0 {
		t.Fatalf("expected empty tags, got %v", tags)
	}
}

func TestReadTagsFileCommentsAndTrimming(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obj.tags")
	content := "  # comment\n\n  alpha  \n; semicolon\n// c++ style\n-- dash\nbeta\n# trailing\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write tags file: %v", err)
	}

	tags, err := ReadTagsFile(path)
	if err != nil {
		t.Fatalf("ReadTagsFile failed: %v", err)
	}
	want := []string{"alpha", "beta"}
	if len(tags) != len(want) {
		t.Fatalf("expected %v, got %v", want, tags)
	}
	for i := range want {
		if tags[i] != want[i] {
			t.Fatalf("tag mismatch at %d: got %q, want %q", i, tags[i], want[i])
		}
	}
}

func TestReadTagsFileInvalidTag(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obj.tags")
	if err := os.WriteFile(path, []byte("bad/tag\n"), 0o644); err != nil {
		t.Fatalf("write tags file: %v", err)
	}

	_, err := ReadTagsFile(path)
	if err == nil {
		t.Fatal("expected error for invalid tag")
	}
	if !errors.Is(err, apperrors.ErrInvalidTag) {
		t.Fatalf("expected ErrInvalidTag, got %v", err)
	}
}

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

func TestCollectTagsRecursiveInheritance(t *testing.T) {
	root := t.TempDir()
	// Layout: root/2026/0714/2323/projects/demo/obj
	segments := []string{"2026", "0714", "2323", "projects", "demo", "obj"}
	current := root
	for _, seg := range segments[:len(segments)-1] {
		current = filepath.Join(current, seg)
		_ = os.MkdirAll(current, 0o755)
		tags := []string{seg + "-tag"}
		if err := WriteTagsFile(filepath.Join(current, seg+".tags"), tags); err != nil {
			t.Fatalf("write classify tags: %v", err)
		}
	}
	objectDir := filepath.Join(current, "obj")
	_ = os.MkdirAll(objectDir, 0o755)
	if err := WriteTagsFile(filepath.Join(objectDir, "obj.tags"), []string{"own"}); err != nil {
		t.Fatalf("write object tags: %v", err)
	}

	relPath := filepath.Join(segments...)
	tags, err := CollectTags(root, relPath)
	if err != nil {
		t.Fatalf("CollectTags failed: %v", err)
	}
	want := []string{"2026-tag", "0714-tag", "2323-tag", "projects-tag", "demo-tag", "own"}
	if len(tags) != len(want) {
		t.Fatalf("expected %v, got %v", want, tags)
	}
	for i := range want {
		if tags[i] != want[i] {
			t.Fatalf("tag mismatch at %d: got %q, want %q", i, tags[i], want[i])
		}
	}
}

func TestCollectTagsDeduplicatesAcrossLevels(t *testing.T) {
	root := t.TempDir()
	_ = os.MkdirAll(filepath.Join(root, "a", "b", "obj"), 0o755)
	_ = WriteTagsFile(filepath.Join(root, "a", "a.tags"), []string{"shared", "a-only"})
	_ = WriteTagsFile(filepath.Join(root, "a", "b", "b.tags"), []string{"shared", "b-only"})
	_ = WriteTagsFile(filepath.Join(root, "a", "b", "obj", "obj.tags"), []string{"shared", "obj-only"})

	tags, err := CollectTags(root, filepath.Join("a", "b", "obj"))
	if err != nil {
		t.Fatalf("CollectTags failed: %v", err)
	}
	want := []string{"shared", "a-only", "b-only", "obj-only"}
	if len(tags) != len(want) {
		t.Fatalf("expected %v, got %v", want, tags)
	}
	for i := range want {
		if tags[i] != want[i] {
			t.Fatalf("tag mismatch at %d: got %q, want %q", i, tags[i], want[i])
		}
	}
}

func TestCollectTagsRejectsRelativeRoot(t *testing.T) {
	_, err := CollectTags("relative/path", "obj")
	if err == nil {
		t.Fatal("expected error for relative root")
	}
	if !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("expected ErrInvalidPath, got %v", err)
	}
}

func TestCollectTagsRejectsOutsideRoot(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	_, err := CollectTags(root, outside)
	if err == nil {
		t.Fatal("expected error for object path outside root")
	}
	if !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("expected ErrInvalidPath, got %v", err)
	}
}

func TestWriteTagsFileRoundTripAndDelete(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obj.tags")
	tags := []string{"alpha", "beta", "gamma"}
	if err := WriteTagsFile(path, tags); err != nil {
		t.Fatalf("WriteTagsFile failed: %v", err)
	}

	read, err := ReadTagsFile(path)
	if err != nil {
		t.Fatalf("ReadTagsFile failed: %v", err)
	}
	if len(read) != len(tags) {
		t.Fatalf("expected %v, got %v", tags, read)
	}
	for i := range tags {
		if read[i] != tags[i] {
			t.Fatalf("tag mismatch at %d: got %q, want %q", i, read[i], tags[i])
		}
	}

	// Empty tag list should delete the file.
	if err := WriteTagsFile(path, []string{}); err != nil {
		t.Fatalf("WriteTagsFile empty failed: %v", err)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatal("expected tags file to be removed")
	}
}

func TestWriteTagsFileValidatesTags(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obj.tags")
	err := WriteTagsFile(path, []string{"bad/tag"})
	if err == nil {
		t.Fatal("expected error for invalid tag")
	}
	if !errors.Is(err, apperrors.ErrInvalidTag) {
		t.Fatalf("expected ErrInvalidTag, got %v", err)
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

func TestIsCommentLine(t *testing.T) {
	cases := []struct {
		line string
		want bool
	}{
		{"# comment", true},
		{"; comment", true},
		{"// comment", true},
		{"-- comment", true},
		{"not a comment", false},
		{"#", true},
	}

	for _, tc := range cases {
		t.Run(tc.line, func(t *testing.T) {
			if got := isCommentLine(tc.line); got != tc.want {
				t.Fatalf("isCommentLine(%q) = %v, want %v", tc.line, got, tc.want)
			}
		})
	}
}
