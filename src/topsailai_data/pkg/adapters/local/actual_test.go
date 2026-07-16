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

	newRef := filepath.Join(root, "new", "obj")
	movedRef, err := adapter.Move(ctx, oldRef, newRef)
	if err != nil {
		t.Fatalf("Move failed: %v", err)
	}
	if movedRef != newRef {
		t.Fatalf("expected moved ref %q, got %q", newRef, movedRef)
	}
	if _, err := os.Stat(oldRef); !os.IsNotExist(err) {
		t.Fatal("old ref should no longer exist")
	}
	if _, err := os.Stat(filepath.Join(newRef, "obj.md")); err != nil {
		t.Fatalf("moved object.md not found: %v", err)
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
