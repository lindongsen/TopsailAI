package local

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestScannerScan(t *testing.T) {
	root := t.TempDir()
	now := time.Date(2026, 7, 14, 23, 23, 0, 0, time.UTC)

	// Create two objects: alpha and beta.
	alphaPath, err := BuildObjectPath(now, nil, "alpha")
	if err != nil {
		t.Fatalf("BuildObjectPath alpha failed: %v", err)
	}
	alphaDir := filepath.Join(root, alphaPath)
	if err := os.MkdirAll(alphaDir, 0o755); err != nil {
		t.Fatalf("mkdir alpha failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(alphaDir, "alpha.md"), []byte("alpha"), 0o644); err != nil {
		t.Fatalf("write alpha.md failed: %v", err)
	}

	betaPath, err := BuildObjectPath(now, []string{"work"}, "beta")
	if err != nil {
		t.Fatalf("BuildObjectPath beta failed: %v", err)
	}
	betaDir := filepath.Join(root, betaPath)
	if err := os.MkdirAll(betaDir, 0o755); err != nil {
		t.Fatalf("mkdir beta failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(betaDir, "beta.md"), []byte("beta"), 0o644); err != nil {
		t.Fatalf("write beta.md failed: %v", err)
	}

	// Nested object.md inside alpha should NOT create a separate object.
	if err := os.MkdirAll(filepath.Join(alphaDir, "nested"), 0o755); err != nil {
		t.Fatalf("mkdir nested failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(alphaDir, "nested", "alpha.md"), []byte("nested"), 0o644); err != nil {
		t.Fatalf("write nested alpha.md failed: %v", err)
	}

	scanner := NewScanner(root)
	objects, err := scanner.Scan(context.Background())
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	if len(objects) != 2 {
		t.Fatalf("expected 2 objects, got %d", len(objects))
	}

	names := make(map[string]bool)
	for _, obj := range objects {
		names[obj.Name] = true
	}
	if !names["alpha"] || !names["beta"] {
		t.Fatalf("expected alpha and beta, got %v", names)
	}
}

func TestScannerCreatedAtFromObjectPath(t *testing.T) {
	root := t.TempDir()
	now := time.Date(2026, 7, 14, 23, 23, 0, 0, time.UTC)

	path, err := BuildObjectPath(now, []string{"work"}, "obj")
	if err != nil {
		t.Fatalf("BuildObjectPath failed: %v", err)
	}
	objectDir := filepath.Join(root, path)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("mkdir object failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, "obj.md"), []byte("data"), 0o644); err != nil {
		t.Fatalf("write obj.md failed: %v", err)
	}

	scanner := NewScanner(root)
	objects, err := scanner.Scan(context.Background())
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	if len(objects) != 1 {
		t.Fatalf("expected 1 object, got %d", len(objects))
	}

	got := objects[0].CreatedAt
	if got.Year() != 2026 || got.Month() != 7 || got.Day() != 14 {
		t.Fatalf("expected 2026-07-14, got %v", got)
	}
	if got.Hour() != 23 || got.Minute() != 23 {
		t.Fatalf("expected 23:23, got %v", got)
	}
}

func TestScannerEmptyRoot(t *testing.T) {
	root := t.TempDir()
	scanner := NewScanner(root)
	objects, err := scanner.Scan(context.Background())
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	if len(objects) != 0 {
		t.Fatalf("expected 0 objects, got %d", len(objects))
	}
}

func TestScannerIgnoresNonObjectDirectories(t *testing.T) {
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "not-an-object"), 0o755); err != nil {
		t.Fatalf("mkdir failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(root, "not-an-object", "random.txt"), []byte("data"), 0o644); err != nil {
		t.Fatalf("write random.txt failed: %v", err)
	}

	scanner := NewScanner(root)
	objects, err := scanner.Scan(context.Background())
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	if len(objects) != 0 {
		t.Fatalf("expected 0 objects, got %d", len(objects))
	}
}

func TestScannerTagInheritance(t *testing.T) {
	root := t.TempDir()
	now := time.Date(2026, 7, 14, 23, 23, 0, 0, time.UTC)

	path, err := BuildObjectPath(now, []string{"work"}, "obj")
	if err != nil {
		t.Fatalf("BuildObjectPath failed: %v", err)
	}
	objectDir := filepath.Join(root, path)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("mkdir object failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, "obj.md"), []byte("data"), 0o644); err != nil {
		t.Fatalf("write obj.md failed: %v", err)
	}

	// Add classify tag.
	classifyDir := filepath.Join(root, filepath.Dir(path))
	if err := os.MkdirAll(classifyDir, 0o755); err != nil {
		t.Fatalf("mkdir classify failed: %v", err)
	}
	if err := WriteTagsFile(filepath.Join(classifyDir, "work.tags"), []string{"work-tag"}); err != nil {
		t.Fatalf("write classify tags failed: %v", err)
	}

	// Add object tag.
	if err := WriteTagsFile(filepath.Join(objectDir, "obj.tags"), []string{"own-tag"}); err != nil {
		t.Fatalf("write object tags failed: %v", err)
	}

	scanner := NewScanner(root)
	objects, err := scanner.Scan(context.Background())
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	if len(objects) != 1 {
		t.Fatalf("expected 1 object, got %d", len(objects))
	}

	tags := objects[0].Tags
	if len(tags) != 2 {
		t.Fatalf("expected 2 tags, got %v", tags)
	}
	if tags[0] != "work-tag" || tags[1] != "own-tag" {
		t.Fatalf("unexpected tag order: %v", tags)
	}
}

func TestCreatedAtFromObjectPathInvalid(t *testing.T) {
	cases := []string{
		"",
		"hello",
		"2026/0714/2323",
		"2026/xx14/2323/obj",
		"2026/0714/232/obj",
		"20/0714/2323/obj",
	}
	for _, path := range cases {
		t.Run(path, func(t *testing.T) {
			_, err := createdAtFromObjectPath(path)
			if err == nil {
				t.Fatalf("expected error for path %q", path)
			}
		})
	}
}

func TestCreatedAtFromObjectPathValid(t *testing.T) {
	got, err := createdAtFromObjectPath("2026/0714/2323/obj")
	if err != nil {
		t.Fatalf("createdAtFromObjectPath failed: %v", err)
	}
	want := time.Date(2026, 7, 14, 23, 23, 0, 0, time.Local)
	if !got.Equal(want) {
		t.Fatalf("expected %v, got %v", want, got)
	}
}
