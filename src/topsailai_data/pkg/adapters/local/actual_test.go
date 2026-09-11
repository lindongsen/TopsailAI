package local

import (
	"archive/tar"
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

func TestActualDataAdapterInitCreatesRoot(t *testing.T) {
	root := filepath.Join(t.TempDir(), "data-root")
	adapter := NewActualDataAdapter(root)
	if err := adapter.Init(context.Background()); err != nil {
		t.Fatalf("Init failed: %v", err)
	}
	if _, err := os.Stat(root); err != nil {
		t.Fatalf("root directory not created: %v", err)
	}
}

func TestActualDataAdapterExists(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)

	exists, err := adapter.Exists(ctx, ref)
	if err != nil {
		t.Fatalf("Exists returned error for empty dir: %v", err)
	}
	if exists {
		t.Fatal("Exists should be false for empty object directory")
	}

	// Only metadata markers should not count as actual data.
	_ = os.WriteFile(filepath.Join(ref, "metadata.json"), []byte("{}"), 0o644)
	_ = os.WriteFile(filepath.Join(ref, "obj.tags"), []byte("tag\n"), 0o644)
	exists, err = adapter.Exists(ctx, ref)
	if err != nil {
		t.Fatalf("Exists returned error for metadata-only dir: %v", err)
	}
	if exists {
		t.Fatal("Exists should be false when only metadata markers are present")
	}

	// Actual data file makes Exists true.
	_ = os.WriteFile(filepath.Join(ref, "obj.md"), []byte("hello"), 0o644)
	exists, err = adapter.Exists(ctx, ref)
	if err != nil {
		t.Fatalf("Exists returned error for dir with object.md: %v", err)
	}
	if !exists {
		t.Fatal("Exists should be true when object.md is present")
	}

	// Subdirectory also counts as actual data.
	_ = os.Remove(filepath.Join(ref, "obj.md"))
	_ = os.MkdirAll(filepath.Join(ref, "assets"), 0o755)
	exists, err = adapter.Exists(ctx, ref)
	if err != nil {
		t.Fatalf("Exists returned error for dir with subdirectory: %v", err)
	}
	if !exists {
		t.Fatal("Exists should be true when a subdirectory is present")
	}

	// Missing directory returns false without error.
	missing := filepath.Join(root, "missing")
	exists, err = adapter.Exists(ctx, missing)
	if err != nil {
		t.Fatalf("Exists returned error for missing dir: %v", err)
	}
	if exists {
		t.Fatal("Exists should be false for missing directory")
	}
}

func TestActualDataAdapterExistsRejectsEmptyRef(t *testing.T) {
	ctx := context.Background()
	adapter := NewActualDataAdapter(t.TempDir())
	_, err := adapter.Exists(ctx, "")
	if err == nil {
		t.Fatal("expected error for empty ref")
	}
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument, got %v", err)
	}
}

func TestActualDataAdapterWriteArchiveRoundTrip(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)

	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	files := map[string]string{
		"obj.md":      "# Hello",
		"note.txt":    "plain text",
		"assets/data": "nested data",
	}
	for name, content := range files {
		hdr := &tar.Header{
			Name:     name,
			Mode:     0o644,
			Size:     int64(len(content)),
			Typeflag: tar.TypeReg,
		}
		if err := tw.WriteHeader(hdr); err != nil {
			t.Fatalf("write header: %v", err)
		}
		if _, err := tw.Write([]byte(content)); err != nil {
			t.Fatalf("write body: %v", err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatalf("close tar writer: %v", err)
	}

	newRef, err := adapter.WriteArchive(ctx, ref, bytes.NewReader(buf.Bytes()))
	if err != nil {
		t.Fatalf("WriteArchive failed: %v", err)
	}
	if newRef != ref {
		t.Fatalf("expected ref %q, got %q", ref, newRef)
	}

	for name, want := range files {
		got, err := os.ReadFile(filepath.Join(ref, name))
		if err != nil {
			t.Fatalf("read %q: %v", name, err)
		}
		if string(got) != want {
			t.Fatalf("%q content mismatch: got %q, want %q", name, got, want)
		}
	}
}

func TestActualDataAdapterWriteArchivePreservesExistingObjectMD(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)
	_ = os.WriteFile(filepath.Join(ref, "obj.md"), []byte("preserved"), 0o644)

	// Archive without obj.md should preserve existing obj.md.
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	content := "extra"
	hdr := &tar.Header{Name: "extra.txt", Mode: 0o644, Size: int64(len(content)), Typeflag: tar.TypeReg}
	_ = tw.WriteHeader(hdr)
	_, _ = tw.Write([]byte(content))
	_ = tw.Close()

	if _, err := adapter.WriteArchive(ctx, ref, bytes.NewReader(buf.Bytes())); err != nil {
		t.Fatalf("WriteArchive failed: %v", err)
	}

	got, err := os.ReadFile(filepath.Join(ref, "obj.md"))
	if err != nil {
		t.Fatalf("read obj.md: %v", err)
	}
	if string(got) != "preserved" {
		t.Fatalf("obj.md was not preserved: got %q", got)
	}
}

func TestActualDataAdapterWriteArchiveRejectsMissingObjectMD(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)

	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	content := "extra"
	hdr := &tar.Header{Name: "extra.txt", Mode: 0o644, Size: int64(len(content)), Typeflag: tar.TypeReg}
	_ = tw.WriteHeader(hdr)
	_, _ = tw.Write([]byte(content))
	_ = tw.Close()

	_, err := adapter.WriteArchive(ctx, ref, bytes.NewReader(buf.Bytes()))
	if !errors.Is(err, apperrors.ErrMissingMarkdown) {
		t.Fatalf("expected ErrMissingMarkdown, got %v", err)
	}
}

func TestActualDataAdapterWriteArchiveRejectsObjectMDDirectory(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)

	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	_ = tw.WriteHeader(&tar.Header{Name: "obj.md", Mode: 0o755, Typeflag: tar.TypeDir})
	_ = tw.Close()

	_, err := adapter.WriteArchive(ctx, ref, bytes.NewReader(buf.Bytes()))
	if !errors.Is(err, apperrors.ErrMissingMarkdown) {
		t.Fatalf("expected ErrMissingMarkdown, got %v", err)
	}
}

func TestActualDataAdapterReadArchiveRoundTrip(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)
	_ = os.WriteFile(filepath.Join(ref, "obj.md"), []byte("# Hello"), 0o644)
	_ = os.WriteFile(filepath.Join(ref, "note.txt"), []byte("plain text"), 0o644)
	_ = os.MkdirAll(filepath.Join(ref, "assets"), 0o755)
	_ = os.WriteFile(filepath.Join(ref, "assets/data"), []byte("nested"), 0o644)
	_ = os.WriteFile(filepath.Join(ref, "obj.tags"), []byte("tag\n"), 0o644)
	_ = os.WriteFile(filepath.Join(ref, "metadata.json"), []byte("{}"), 0o644)

	reader, err := adapter.ReadArchive(ctx, ref)
	if err != nil {
		t.Fatalf("ReadArchive failed: %v", err)
	}
	defer reader.Close()

	tr := tar.NewReader(reader)
	found := make(map[string]string)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("read tar header: %v", err)
		}
		if hdr.Typeflag == tar.TypeDir {
			continue
		}
		data, err := io.ReadAll(tr)
		if err != nil {
			t.Fatalf("read tar body: %v", err)
		}
		found[hdr.Name] = string(data)
	}

	if _, ok := found["obj.md"]; !ok {
		t.Fatal("obj.md missing from archive")
	}
	if found["obj.md"] != "# Hello" {
		t.Fatalf("obj.md content mismatch: %q", found["obj.md"])
	}
	if found["note.txt"] != "plain text" {
		t.Fatalf("note.txt content mismatch: %q", found["note.txt"])
	}
	if found["assets/data"] != "nested" {
		t.Fatalf("assets/data content mismatch: %q", found["assets/data"])
	}
	if _, ok := found["obj.tags"]; ok {
		t.Fatal("metadata marker obj.tags should not appear in archive")
	}
	if _, ok := found["metadata.json"]; ok {
		t.Fatal("metadata marker metadata.json should not appear in archive")
	}
}

func TestActualDataAdapterWriteArchiveRejectsTraversal(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)

	cases := []struct {
		name string
		hdr  *tar.Header
	}{
		{
			name: "dotdot prefix",
			hdr:  &tar.Header{Name: "../escape.txt", Typeflag: tar.TypeReg, Size: 4, Mode: 0o644},
		},
		{
			name: "dotdot in middle",
			hdr:  &tar.Header{Name: "sub/../../escape.txt", Typeflag: tar.TypeReg, Size: 4, Mode: 0o644},
		},
		{
			name: "absolute path",
			hdr:  &tar.Header{Name: "/etc/passwd", Typeflag: tar.TypeReg, Size: 4, Mode: 0o644},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			tw := tar.NewWriter(&buf)
			_ = tw.WriteHeader(tc.hdr)
			_, _ = tw.Write([]byte("data"))
			_ = tw.Close()

			_, err := adapter.WriteArchive(ctx, ref, bytes.NewReader(buf.Bytes()))
			if err == nil {
				t.Fatal("expected error for traversal tar entry")
			}
			if !errors.Is(err, apperrors.ErrInvalidPath) {
				t.Fatalf("expected ErrInvalidPath, got %v", err)
			}
		})
	}
}

func TestActualDataAdapterWriteArchiveRejectsSymlinkAndUnsupportedTypes(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)

	cases := []struct {
		name string
		hdr  *tar.Header
	}{
		{
			name: "symlink",
			hdr:  &tar.Header{Name: "link", Typeflag: tar.TypeSymlink, Linkname: "obj.md"},
		},
		{
			name: "hard link",
			hdr:  &tar.Header{Name: "hardlink", Typeflag: tar.TypeLink, Linkname: "obj.md"},
		},
		{
			name: "char device",
			hdr:  &tar.Header{Name: "dev", Typeflag: tar.TypeChar},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var buf bytes.Buffer
			tw := tar.NewWriter(&buf)
			_ = tw.WriteHeader(tc.hdr)
			_ = tw.Close()

			_, err := adapter.WriteArchive(ctx, ref, bytes.NewReader(buf.Bytes()))
			if err == nil {
				t.Fatal("expected error for unsupported tar entry")
			}
		})
	}
}

func TestActualDataAdapterWriteFileAndReadFile(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)

	// Binary payload with null bytes.
	payload := []byte{0x00, 0x01, 0x02, 0xff, 0xfe}
	newRef, err := adapter.WriteFile(ctx, ref, "binary.bin", bytes.NewReader(payload))
	if err != nil {
		t.Fatalf("WriteFile failed: %v", err)
	}
	if newRef != ref {
		t.Fatalf("expected ref %q, got %q", ref, newRef)
	}

	reader, err := adapter.ReadFile(ctx, ref, "binary.bin")
	if err != nil {
		t.Fatalf("ReadFile failed: %v", err)
	}
	defer reader.Close()
	got, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatalf("binary content mismatch")
	}

	// Nested file path.
	_, err = adapter.WriteFile(ctx, ref, "nested/dir/file.txt", strings.NewReader("nested text"))
	if err != nil {
		t.Fatalf("WriteFile nested failed: %v", err)
	}
	reader, err = adapter.ReadFile(ctx, ref, "nested/dir/file.txt")
	if err != nil {
		t.Fatalf("ReadFile nested failed: %v", err)
	}
	defer reader.Close()
	got, _ = io.ReadAll(reader)
	if string(got) != "nested text" {
		t.Fatalf("nested content mismatch: %q", got)
	}
}

func TestActualDataAdapterReadFileNotFound(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)

	_, err := adapter.ReadFile(ctx, ref, "missing.txt")
	if err == nil {
		t.Fatal("expected error for missing file")
	}
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

func TestActualDataAdapterDeletePreservesMarkers(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	ref := filepath.Join(root, "obj")
	_ = os.MkdirAll(ref, 0o755)
	_ = os.WriteFile(filepath.Join(ref, "obj.md"), []byte("marker"), 0o644)
	_ = os.WriteFile(filepath.Join(ref, "metadata.json"), []byte("{}"), 0o644)
	_ = os.WriteFile(filepath.Join(ref, "obj.tags"), []byte("tag\n"), 0o644)
	_ = os.WriteFile(filepath.Join(ref, "data.txt"), []byte("data"), 0o644)
	_ = os.MkdirAll(filepath.Join(ref, "extra"), 0o755)
	_ = os.WriteFile(filepath.Join(ref, "extra/file"), []byte("x"), 0o644)

	if err := adapter.Delete(ctx, ref); err != nil {
		t.Fatalf("Delete failed: %v", err)
	}

	if _, err := os.Stat(filepath.Join(ref, "obj.md")); err != nil {
		t.Fatalf("obj.md should be preserved: %v", err)
	}
	if _, err := os.Stat(filepath.Join(ref, "metadata.json")); err != nil {
		t.Fatalf("metadata.json should be preserved: %v", err)
	}
	if _, err := os.Stat(filepath.Join(ref, "obj.tags")); err != nil {
		t.Fatalf("obj.tags should be preserved: %v", err)
	}
	if _, err := os.Stat(filepath.Join(ref, "data.txt")); !os.IsNotExist(err) {
		t.Fatal("data.txt should be removed")
	}
	if _, err := os.Stat(filepath.Join(ref, "extra")); !os.IsNotExist(err) {
		t.Fatal("extra directory should be removed")
	}
}

func TestActualDataAdapterMove(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	oldRef := filepath.Join(root, "old", "obj")
	_ = os.MkdirAll(oldRef, 0o755)
	_ = os.WriteFile(filepath.Join(oldRef, "obj.md"), []byte("data"), 0o644)
	_ = os.WriteFile(filepath.Join(oldRef, "extra.txt"), []byte("extra"), 0o644)

	newRef := filepath.Join(root, "new", "obj")
	movedRef, err := adapter.Move(ctx, oldRef, newRef)
	if err != nil {
		t.Fatalf("Move failed: %v", err)
	}
	if movedRef != newRef {
		t.Fatalf("expected moved ref %q, got %q", newRef, movedRef)
	}
	// Move copies the object directory; the caller is responsible for deleting
	// the old reference and cleaning up empty parent directories.
	if _, err := os.Stat(oldRef); err != nil {
		t.Fatalf("old ref should still exist after copy-only Move: %v", err)
	}
	if _, err := os.Stat(filepath.Join(newRef, "obj.md")); err != nil {
		t.Fatalf("moved object.md not found: %v", err)
	}
	if _, err := os.Stat(filepath.Join(newRef, "extra.txt")); err != nil {
		t.Fatalf("moved extra.txt not found: %v", err)
	}

	// Moving to existing target should fail.
	otherRef := filepath.Join(root, "other", "obj")
	_ = os.MkdirAll(otherRef, 0o755)
	_, err = adapter.Move(ctx, newRef, otherRef)
	if err == nil {
		t.Fatal("expected error moving to existing target")
	}
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("expected ErrObjectExists, got %v", err)
	}
}

func TestActualDataAdapterMoveCopiesDirectoryTree(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	oldRef := filepath.Join(root, "old", "obj")
	_ = os.MkdirAll(filepath.Join(oldRef, "subdir"), 0o755)
	_ = os.WriteFile(filepath.Join(oldRef, "obj.md"), []byte("data"), 0o644)
	_ = os.WriteFile(filepath.Join(oldRef, "subdir", "file.txt"), []byte("nested"), 0o644)

	newRef := filepath.Join(root, "new", "obj")
	if _, err := adapter.Move(ctx, oldRef, newRef); err != nil {
		t.Fatalf("Move failed: %v", err)
	}

	if _, err := os.Stat(filepath.Join(newRef, "subdir", "file.txt")); err != nil {
		t.Fatalf("nested file not copied: %v", err)
	}
}

func TestRemoveEmptyParents(t *testing.T) {
	root := t.TempDir()

	// Build a deep path: root/2026/0714/2323/demo/obj
	objDir := filepath.Join(root, "2026", "0714", "2323", "demo", "obj")
	if err := os.MkdirAll(objDir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	_ = os.WriteFile(filepath.Join(objDir, "obj.md"), []byte("data"), 0o644)

	// Remove the object directory contents and then the directory itself.
	_ = os.Remove(filepath.Join(objDir, "obj.md"))
	_ = os.Remove(objDir)

	if err := RemoveEmptyParents(objDir, root); err != nil {
		t.Fatalf("RemoveEmptyParents failed: %v", err)
	}

	// All parent directories should be removed because they are empty.
	for _, dir := range []string{
		filepath.Join(root, "2026", "0714", "2323", "demo"),
		filepath.Join(root, "2026", "0714", "2323"),
		filepath.Join(root, "2026", "0714"),
		filepath.Join(root, "2026"),
	} {
		if _, err := os.Stat(dir); !os.IsNotExist(err) {
			t.Fatalf("expected %q to be removed", dir)
		}
	}
}

func TestRemoveEmptyParentsStopsAtRoot(t *testing.T) {
	root := t.TempDir()

	objDir := filepath.Join(root, "2026", "0714", "2323", "obj")
	if err := os.MkdirAll(objDir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	// Leave a sibling directory so 2026/0714/2323 is not empty.
	sibling := filepath.Join(root, "2026", "0714", "2323", "other")
	if err := os.MkdirAll(sibling, 0o755); err != nil {
		t.Fatalf("mkdir sibling: %v", err)
	}
	_ = os.WriteFile(filepath.Join(objDir, "obj.md"), []byte("data"), 0o644)

	_ = os.Remove(filepath.Join(objDir, "obj.md"))
	_ = os.Remove(objDir)

	if err := RemoveEmptyParents(objDir, root); err != nil {
		t.Fatalf("RemoveEmptyParents failed: %v", err)
	}

	if _, err := os.Stat(sibling); err != nil {
		t.Fatalf("sibling directory should remain: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "2026", "0714", "2323")); err != nil {
		t.Fatalf("parent with sibling should remain: %v", err)
	}
}

func TestActualDataAdapterMoveRejectsEmptyRefs(t *testing.T) {
	ctx := context.Background()
	adapter := NewActualDataAdapter(t.TempDir())

	_, err := adapter.Move(ctx, "", "dst")
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument for empty oldRef, got %v", err)
	}

	_, err = adapter.Move(ctx, "src", "")
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument for empty newRef, got %v", err)
	}
}

func TestValidateActualFilename(t *testing.T) {
	cases := []struct {
		name     string
		filename string
		wantErr  error
	}{
		{"empty", "", apperrors.ErrInvalidArgument},
		{"absolute", "/etc/passwd", apperrors.ErrInvalidArgument},
		{"dotdot prefix", "../escape.txt", apperrors.ErrInvalidPath},
		{"dotdot in middle", "sub/../../escape.txt", apperrors.ErrInvalidPath},
		{"reserved metadata marker", "obj.tags", apperrors.ErrInvalidName},
		{"reserved metadata marker json", "metadata.json", apperrors.ErrInvalidName},
		{"valid nested", "nested/file.txt", nil},
		{"valid object md", "obj.md", nil},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := validateActualFilename(tc.filename)
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

func TestActualDataAdapterWriteFileRejectsInvalidFilename(t *testing.T) {
	ctx := context.Background()
	adapter := NewActualDataAdapter(t.TempDir())
	ref := filepath.Join(t.TempDir(), "obj")
	_ = os.MkdirAll(ref, 0o755)

	_, err := adapter.WriteFile(ctx, ref, "../escape.txt", strings.NewReader("x"))
	if !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("expected ErrInvalidPath, got %v", err)
	}
}

func TestRemoveEmptyParentsNeverRemovesRoot(t *testing.T) {
	root := t.TempDir()

	objDir := filepath.Join(root, "2026", "0714", "2323", "obj")
	if err := os.MkdirAll(objDir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	_ = os.WriteFile(filepath.Join(objDir, "obj.md"), []byte("data"), 0o644)

	_ = os.Remove(filepath.Join(objDir, "obj.md"))
	_ = os.Remove(objDir)

	if err := RemoveEmptyParents(objDir, root); err != nil {
		t.Fatalf("RemoveEmptyParents failed: %v", err)
	}

	// The adapter root must always survive, even when it becomes empty.
	if _, err := os.Stat(root); err != nil {
		t.Fatalf("adapter root should never be removed: %v", err)
	}
}

func TestActualDataAdapterMovePreservesMetadataMarkers(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	_ = adapter.Init(ctx)

	oldRef := filepath.Join(root, "old", "obj")
	_ = os.MkdirAll(oldRef, 0o755)
	_ = os.WriteFile(filepath.Join(oldRef, "obj.md"), []byte("data"), 0o644)
	_ = os.WriteFile(filepath.Join(oldRef, "obj.tags"), []byte("tag\n"), 0o644)
	_ = os.WriteFile(filepath.Join(oldRef, "metadata.json"), []byte("{}"), 0o644)

	newRef := filepath.Join(root, "new", "obj")
	if _, err := adapter.Move(ctx, oldRef, newRef); err != nil {
		t.Fatalf("Move failed: %v", err)
	}

	for _, name := range []string{"obj.md", "obj.tags", "metadata.json"} {
		if _, err := os.Stat(filepath.Join(newRef, name)); err != nil {
			t.Fatalf("%s not copied: %v", name, err)
		}
	}
}

func TestActualDataAdapterWriteFileRejectsSameFileAliases(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatalf("Init failed: %v", err)
	}

	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatalf("mkdir object: %v", err)
	}
	destination := filepath.Join(ref, "obj.md")
	original := []byte("original marker content\n")
	if err := os.WriteFile(destination, original, 0o644); err != nil {
		t.Fatalf("write destination: %v", err)
	}

	tests := []struct {
		name       string
		prepareSrc func(t *testing.T) string
	}{
		{
			name: "exact path",
			prepareSrc: func(t *testing.T) string {
				return destination
			},
		},
		{
			name: "symlink alias",
			prepareSrc: func(t *testing.T) string {
				alias := filepath.Join(t.TempDir(), "source-link")
				if err := os.Symlink(destination, alias); err != nil {
					t.Skipf("symlinks unsupported: %v", err)
				}
				return alias
			},
		},
		{
			name: "hard-link alias",
			prepareSrc: func(t *testing.T) string {
				alias := filepath.Join(t.TempDir(), "source-hard-link")
				if err := os.Link(destination, alias); err != nil {
					t.Skipf("hard links unsupported: %v", err)
				}
				return alias
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			sourcePath := tc.prepareSrc(t)
			source, err := os.Open(sourcePath)
			if err != nil {
				t.Fatalf("open source: %v", err)
			}
			defer source.Close()

			_, err = adapter.WriteFile(ctx, ref, "obj.md", source)
			if !errors.Is(err, apperrors.ErrSourceDestinationSameFile) {
				t.Fatalf("expected ErrSourceDestinationSameFile, got %v", err)
			}
			got, readErr := os.ReadFile(destination)
			if readErr != nil {
				t.Fatalf("read destination: %v", readErr)
			}
			if !bytes.Equal(got, original) {
				t.Fatalf("destination changed: got %q, want %q", got, original)
			}
		})
	}
}

func TestActualDataAdapterWriteFileDistinctSourceSucceeds(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatalf("Init failed: %v", err)
	}

	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatalf("mkdir object: %v", err)
	}
	destination := filepath.Join(ref, "obj.md")
	original := []byte("original\n")
	replacement := []byte{0x00, 0x01, 0xff, 0xfe}
	if err := os.WriteFile(destination, original, 0o644); err != nil {
		t.Fatalf("write destination: %v", err)
	}
	sourcePath := filepath.Join(root, "source.bin")
	if err := os.WriteFile(sourcePath, replacement, 0o644); err != nil {
		t.Fatalf("write source: %v", err)
	}
	source, err := os.Open(sourcePath)
	if err != nil {
		t.Fatalf("open source: %v", err)
	}
	defer source.Close()

	if _, err := adapter.WriteFile(ctx, ref, "obj.md", source); err != nil {
		t.Fatalf("WriteFile failed: %v", err)
	}
	got, err := os.ReadFile(destination)
	if err != nil {
		t.Fatalf("read destination: %v", err)
	}
	if !bytes.Equal(got, replacement) {
		t.Fatalf("destination content: got %v, want %v", got, replacement)
	}
	sourceBytes, err := os.ReadFile(sourcePath)
	if err != nil {
		t.Fatalf("read source: %v", err)
	}
	if !bytes.Equal(sourceBytes, replacement) {
		t.Fatalf("source content changed: got %v, want %v", sourceBytes, replacement)
	}
}

type failingReader struct {
	data []byte
	read bool
}

func (r *failingReader) Read(p []byte) (int, error) {
	if r.read {
		return 0, errors.New("injected read failure")
	}
	r.read = true
	n := copy(p, r.data)
	return n, errors.New("injected read failure")
}

func TestActualDataAdapterWriteFileFailureCleansTemporaryFile(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatal(err)
	}
	destination := filepath.Join(ref, "data.txt")
	original := []byte("original")
	if err := os.WriteFile(destination, original, 0o644); err != nil {
		t.Fatal(err)
	}

	_, err := adapter.WriteFile(ctx, ref, "data.txt", &failingReader{data: []byte("partial")})
	if err == nil {
		t.Fatal("expected injected read failure")
	}
	got, err := os.ReadFile(destination)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Fatalf("destination changed: got %q, want %q", got, original)
	}
	entries, err := os.ReadDir(ref)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), writeTempPrefix) {
			t.Fatalf("temporary artifact remains: %s", entry.Name())
		}
	}
}

func TestActualDataAdapterReadArchiveAndExistsHideWriteTemporaryFiles(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(ref, "obj.md"), []byte("marker"), 0o644); err != nil {
		t.Fatal(err)
	}
	tmpPath := filepath.Join(ref, writeTempPrefix+"visible-partial")
	if err := os.WriteFile(tmpPath, []byte("partial"), 0o644); err != nil {
		t.Fatal(err)
	}

	exists, err := adapter.Exists(ctx, ref)
	if err != nil {
		t.Fatal(err)
	}
	if !exists {
		t.Fatal("object.md should count as actual data")
	}
	reader, err := adapter.ReadArchive(ctx, ref)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	tr := tar.NewReader(reader)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(hdr.Name, writeTempPrefix) {
			t.Fatalf("temporary artifact exposed in archive: %s", hdr.Name)
		}
	}
}

func TestCleanupStaleWriteTempsRemovesOnlyExpiredReservedFiles(t *testing.T) {
	dir := t.TempDir()
	stale := filepath.Join(dir, writeTempPrefix+"stale")
	fresh := filepath.Join(dir, writeTempPrefix+"fresh")
	unrelated := filepath.Join(dir, "user-file")
	for _, path := range []string{stale, fresh, unrelated} {
		if err := os.WriteFile(path, []byte("data"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	old := time.Now().Add(-writeTempMaxAge - time.Minute)
	if err := os.Chtimes(stale, old, old); err != nil {
		t.Fatal(err)
	}
	if err := cleanupStaleWriteTemps(dir, time.Now()); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Fatalf("stale temporary file was not removed: %v", err)
	}
	for _, path := range []string{fresh, unrelated} {
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("unexpected removal of %s: %v", path, err)
		}
	}
}

func TestActualDataAdapterExistsIgnoresOnlyWriteTemporaryFiles(t *testing.T) {
	ctx := context.Background()
	adapter := NewActualDataAdapter(t.TempDir())
	ref := filepath.Join(t.TempDir(), "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{writeTempPrefix + "root", "metadata.json", "obj.tags"} {
		if err := os.WriteFile(filepath.Join(ref, name), []byte("internal"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	exists, err := adapter.Exists(ctx, ref)
	if err != nil {
		t.Fatal(err)
	}
	if exists {
		t.Fatal("metadata and temporary files alone must not count as actual data")
	}
}

func TestActualDataAdapterMoveSkipsWriteTemporaryFiles(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	oldRef := filepath.Join(root, "old", "obj")
	if err := os.MkdirAll(filepath.Join(oldRef, "nested"), 0o755); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{
		filepath.Join(oldRef, "obj.md"),
		filepath.Join(oldRef, writeTempPrefix+"root"),
		filepath.Join(oldRef, "nested", writeTempPrefix+"nested"),
	} {
		if err := os.WriteFile(path, []byte("data"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	newRef := filepath.Join(root, "new", "obj")
	if _, err := adapter.Move(ctx, oldRef, newRef); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{
		filepath.Join(newRef, writeTempPrefix+"root"),
		filepath.Join(newRef, "nested", writeTempPrefix+"nested"),
	} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("temporary artifact was copied: %s", path)
		}
	}
}

func TestCleanupStaleWriteTempsRecursiveRemovesRootAndNestedFiles(t *testing.T) {
	root := t.TempDir()
	nested := filepath.Join(root, "nested", "deeper")
	if err := os.MkdirAll(nested, 0o755); err != nil {
		t.Fatal(err)
	}
	staleRoot := filepath.Join(root, writeTempPrefix+"root")
	staleNested := filepath.Join(nested, writeTempPrefix+"nested")
	freshNested := filepath.Join(nested, writeTempPrefix+"fresh")
	unrelated := filepath.Join(nested, "keep.txt")
	for _, path := range []string{staleRoot, staleNested, freshNested, unrelated} {
		if err := os.WriteFile(path, []byte("data"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	old := time.Now().Add(-writeTempMaxAge - time.Minute)
	for _, path := range []string{staleRoot, staleNested} {
		if err := os.Chtimes(path, old, old); err != nil {
			t.Fatal(err)
		}
	}
	if err := cleanupStaleWriteTempsRecursive(root, time.Now()); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{staleRoot, staleNested} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Fatalf("stale temporary file remains: %s", path)
		}
	}
	for _, path := range []string{freshNested, unrelated} {
		if _, err := os.Stat(path); err != nil {
			t.Fatalf("unexpected removal of %s: %v", path, err)
		}
	}
}

func TestActualDataAdapterWriteArchiveRejectsOverlappingSource(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(ref, "obj.md")
	control := filepath.Join(ref, "control.txt")
	if err := os.WriteFile(marker, []byte("original marker"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(control, []byte("original control"), 0o644); err != nil {
		t.Fatal(err)
	}

	archivePath := filepath.Join(ref, "input.tar")
	var archive bytes.Buffer
	tw := tar.NewWriter(&archive)
	content := []byte("replacement")
	if err := tw.WriteHeader(&tar.Header{Name: "obj.md", Mode: 0o644, Size: int64(len(content)), Typeflag: tar.TypeReg}); err != nil {
		t.Fatal(err)
	}
	if _, err := tw.Write(content); err != nil {
		t.Fatal(err)
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(archivePath, archive.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	beforeArchive, err := os.ReadFile(archivePath)
	if err != nil {
		t.Fatal(err)
	}

	source, err := os.Open(archivePath)
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	if _, err := adapter.WriteArchive(ctx, ref, source); !errors.Is(err, apperrors.ErrSourceDestinationSameFile) {
		t.Fatalf("expected ErrSourceDestinationSameFile, got %v", err)
	}

	for path, want := range map[string][]byte{
		marker:  []byte("original marker"),
		control: []byte("original control"),
	} {
		got, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(got, want) {
			t.Fatalf("%s changed: got %q, want %q", path, got, want)
		}
	}
	afterArchive, err := os.ReadFile(archivePath)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(afterArchive, beforeArchive) {
		t.Fatal("overlapping archive source changed")
	}
}

func TestActualDataAdapterWriteArchiveRejectsObjectDirectorySource(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(ref, "obj.md")
	control := filepath.Join(ref, "control.txt")
	if err := os.WriteFile(marker, []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(control, []byte("control"), 0o644); err != nil {
		t.Fatal(err)
	}
	source, err := os.Open(ref)
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	if _, err := adapter.WriteArchive(ctx, ref, source); !errors.Is(err, apperrors.ErrSourceDestinationSameFile) {
		t.Fatalf("expected overlap error, got %v", err)
	}
	assertFileBytes(t, marker, []byte("original"))
	assertFileBytes(t, control, []byte("control"))
}

func TestActualDataAdapterWriteArchiveRejectsSymlinkToObjectDirectory(t *testing.T) {
	if filepath.Separator != '/' {
		t.Skip("directory symlinks are not portable on this platform")
	}
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(ref, "obj.md")
	if err := os.WriteFile(marker, []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	alias := filepath.Join(root, "object-alias")
	if err := os.Symlink(ref, alias); err != nil {
		t.Fatal(err)
	}
	source, err := os.Open(alias)
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	if _, err := adapter.WriteArchive(ctx, ref, source); !errors.Is(err, apperrors.ErrSourceDestinationSameFile) {
		t.Fatalf("expected overlap error, got %v", err)
	}
	assertFileBytes(t, marker, []byte("original"))
}

func TestActualDataAdapterWriteArchiveRejectsNonRegularSourceBeforeMutation(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(ref, "obj.md")
	if err := os.WriteFile(marker, []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	sourceDir := filepath.Join(root, "source")
	if err := os.MkdirAll(sourceDir, 0o755); err != nil {
		t.Fatal(err)
	}
	source, err := os.Open(sourceDir)
	if err != nil {
		t.Fatal(err)
	}
	defer source.Close()
	if _, err := adapter.WriteArchive(ctx, ref, source); !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected invalid source error, got %v", err)
	}
	assertFileBytes(t, marker, []byte("original"))
}

func TestActualDataAdapterWriteArchiveAcceptsRegularFileAliases(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	ref := filepath.Join(root, "obj")
	if err := os.MkdirAll(ref, 0o755); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(ref, "obj.md")
	if err := os.WriteFile(marker, []byte("original"), 0o644); err != nil {
		t.Fatal(err)
	}
	archivePath := filepath.Join(ref, "input.tar")
	archive := buildLocalTar(t, map[string][]byte{"obj.md": []byte("replacement")})
	if err := os.WriteFile(archivePath, archive, 0o644); err != nil {
		t.Fatal(err)
	}
	aliases := []struct {
		name  string
		setup func(string) error
	}{
		{name: "symlink", setup: func(path string) error { return os.Symlink(archivePath, path) }},
		{name: "hard link", setup: func(path string) error { return os.Link(archivePath, path) }},
	}
	for _, alias := range aliases {
		t.Run(alias.name, func(t *testing.T) {
			aliasPath := filepath.Join(root, alias.name+".tar")
			if err := alias.setup(aliasPath); err != nil {
				t.Skipf("alias unsupported: %v", err)
			}
			source, err := os.Open(aliasPath)
			if err != nil {
				t.Fatal(err)
			}
			defer source.Close()
			if _, err := adapter.WriteArchive(ctx, ref, source); !errors.Is(err, apperrors.ErrSourceDestinationSameFile) {
				t.Fatalf("expected overlap error, got %v", err)
			}
			assertFileBytes(t, marker, []byte("original"))
		})
	}
}

func TestActualDataAdapterWriteArchiveCreatesMissingTargetRef(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewActualDataAdapter(root)
	ref := filepath.Join(root, "new-object")
	archive := bytes.NewReader(buildLocalTar(t, map[string][]byte{"new-object.md": []byte("created")}))
	if _, err := adapter.WriteArchive(ctx, ref, archive); err != nil {
		t.Fatalf("expected missing target ref to be created, got %v", err)
	}
	assertFileBytes(t, filepath.Join(ref, "new-object.md"), []byte("created"))
}

func buildLocalTar(t *testing.T, files map[string][]byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	writer := tar.NewWriter(&buf)
	for name, data := range files {
		if err := writer.WriteHeader(&tar.Header{Name: name, Mode: 0o644, Size: int64(len(data)), Typeflag: tar.TypeReg}); err != nil {
			t.Fatal(err)
		}
		if _, err := writer.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func assertFileBytes(t *testing.T, path string, want []byte) {
	t.Helper()
	got, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("%s changed: got %q, want %q", path, got, want)
	}
}
