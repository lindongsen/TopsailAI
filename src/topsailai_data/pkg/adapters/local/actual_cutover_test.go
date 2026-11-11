package local

import (
	"archive/tar"
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// TestActualCutoverReferences verifies relative references and user-owned names.
func TestActualCutoverReferences(t *testing.T) {
	root := t.TempDir()
	a := NewActualDataAdapter(root)
	ctx := context.Background()
	if err := a.Init(ctx); err != nil {
		t.Fatal(err)
	}
	ref := "2026/1111/0604/probe"
	for _, name := range []string{"probe.md", ".hidden", "metadata.json", "stat.json", "work.tags", "user.lock", "meta/explanation.md"} {
		got, err := a.WriteFile(ctx, ref, name, strings.NewReader(name))
		if err != nil {
			t.Fatalf("write %s: %v", name, err)
		}
		if got != ref {
			t.Fatalf("returned reference %q", got)
		}
		r, err := a.ReadFile(ctx, ref, name)
		if err != nil {
			t.Fatal(err)
		}
		data, readErr := io.ReadAll(r)
		closeErr := r.Close()
		if readErr != nil || closeErr != nil || string(data) != name {
			t.Fatalf("read %s: %q %v %v", name, data, readErr, closeErr)
		}
	}
	if _, err := a.WriteFile(ctx, filepath.Join(root, "outside"), "x", strings.NewReader("x")); err == nil {
		t.Fatal("accepted absolute reference")
	}
	meta := filepath.Join(root, "meta", "sentinel")
	if err := os.WriteFile(meta, []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := a.Delete(ctx, ref); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "object", filepath.FromSlash(ref))); !os.IsNotExist(err) {
		t.Fatalf("payload remains: %v", err)
	}
	if data, err := os.ReadFile(meta); err != nil || string(data) != "keep" {
		t.Fatalf("metadata changed: %q %v", data, err)
	}
}

// TestActualCutoverDotfileExists verifies that a dotfile is actual payload.
func TestActualCutoverDotfileExists(t *testing.T) {
	a := NewActualDataAdapter(t.TempDir())
	ctx := context.Background()
	if err := a.Init(ctx); err != nil {
		t.Fatal(err)
	}
	ref := "2026/1111/0604/hidden"
	if _, err := a.WriteFile(ctx, ref, ".hidden", strings.NewReader("payload")); err != nil {
		t.Fatal(err)
	}
	exists, err := a.Exists(ctx, ref)
	if err != nil || !exists {
		t.Fatalf("dotfile not counted: %v %v", exists, err)
	}
}

// TestActualCutoverInteriorAlias preserves content outside the object boundary.
func TestActualCutoverInteriorAlias(t *testing.T) {
	root := t.TempDir()
	a := NewActualDataAdapter(root)
	ctx := context.Background()
	if err := a.Init(ctx); err != nil {
		t.Fatal(err)
	}
	ref := "2026/1111/0604/probe"
	if _, err := a.WriteFile(ctx, ref, "probe.md", strings.NewReader("original")); err != nil {
		t.Fatal(err)
	}
	outside := t.TempDir()
	sentinel := filepath.Join(outside, "sentinel")
	if err := os.WriteFile(sentinel, []byte("keep"), 0600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(root, "object", filepath.FromSlash(ref), "alias")
	if err := os.Symlink(outside, link); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	if _, err := a.WriteFile(ctx, ref, "alias/sentinel", strings.NewReader("replace")); err == nil {
		t.Fatal("write followed interior alias")
	}
	if r, err := a.ReadFile(ctx, ref, "alias/sentinel"); err == nil {
		r.Close()
		t.Fatal("read followed interior alias")
	}
	if data, err := os.ReadFile(sentinel); err != nil || string(data) != "keep" {
		t.Fatalf("outside changed: %q %v", data, err)
	}
}

// TestActualCutoverArchive verifies ordinary payload names survive archive access.
func TestActualCutoverArchive(t *testing.T) {
	a := NewActualDataAdapter(t.TempDir())
	ctx := context.Background()
	if err := a.Init(ctx); err != nil {
		t.Fatal(err)
	}
	ref := "2026/1111/0604/probe"
	var archive bytes.Buffer
	tw := tar.NewWriter(&archive)
	for _, name := range []string{"probe.md", "metadata.json", ".hidden", "user.lock", "meta/notes.md"} {
		if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0600, Size: int64(len(name))}); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write([]byte(name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	got, err := a.WriteArchive(ctx, ref, &archive)
	if err != nil || got != ref {
		t.Fatalf("write archive: %q %v", got, err)
	}
	r, err := a.ReadArchive(ctx, ref)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	tr := tar.NewReader(r)
	seen := make(map[string]bool)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		seen[h.Name] = true
	}
	for _, name := range []string{"probe.md", "metadata.json", ".hidden", "user.lock", "meta/notes.md"} {
		if !seen[name] {
			t.Errorf("archive omitted %s", name)
		}
	}
}

// TestActualCutoverArchiveMarkerAlias rejects a marker alias before clearing data.
func TestActualCutoverArchiveMarkerAlias(t *testing.T) {
	root := t.TempDir()
	a := NewActualDataAdapter(root)
	ctx := context.Background()
	if err := a.Init(ctx); err != nil {
		t.Fatal(err)
	}
	ref := "2026/1111/0604/probe"
	if _, err := a.WriteFile(ctx, ref, "keep.txt", strings.NewReader("keep")); err != nil {
		t.Fatal(err)
	}
	outside := filepath.Join(t.TempDir(), "sentinel")
	if err := os.WriteFile(outside, []byte("outside"), 0600); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(root, "object", filepath.FromSlash(ref))
	if err := os.Symlink(outside, filepath.Join(dir, "probe.md")); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	if _, err := a.WriteArchive(ctx, ref, bytes.NewReader(nil)); err == nil {
		t.Fatal("archive accepted marker alias")
	}
	if data, err := os.ReadFile(filepath.Join(dir, "keep.txt")); err != nil || string(data) != "keep" {
		t.Fatalf("payload changed before rejection: %q %v", data, err)
	}
	if data, err := os.ReadFile(outside); err != nil || string(data) != "outside" {
		t.Fatalf("outside changed: %q %v", data, err)
	}
}

// TestActualCutoverMoveFailure retains source and establishes a target boundary first.
func TestActualCutoverMoveFailure(t *testing.T) {
	root := t.TempDir()
	a := NewActualDataAdapter(root)
	ctx := context.Background()
	if err := a.Init(ctx); err != nil {
		t.Fatal(err)
	}
	ref := "2026/1111/0604/probe"
	if _, err := a.WriteFile(ctx, ref, "probe.md", strings.NewReader("boundary")); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(root, "object", filepath.FromSlash(ref))
	outside := filepath.Join(t.TempDir(), "sentinel")
	if err := os.WriteFile(outside, []byte("outside"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(dir, "a-alias")); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	newRef := "2026/1111/0604/work/probe"
	if _, err := a.Move(ctx, ref, newRef); err == nil {
		t.Fatal("copy accepted alias")
	}
	for _, path := range []string{filepath.Join(dir, "probe.md"), filepath.Join(root, "object", filepath.FromSlash(newRef), "probe.md")} {
		if data, err := os.ReadFile(path); err != nil || string(data) != "boundary" {
			t.Fatalf("boundary missing: %q %v", data, err)
		}
	}
	if _, err := os.Lstat(filepath.Join(root, "object", filepath.FromSlash(newRef), "a-alias")); !os.IsNotExist(err) {
		t.Fatalf("unsafe entry copied: %v", err)
	}
}

// TestActualCutoverMove preserves the source until manager publication completes.
func TestActualCutoverMove(t *testing.T) {
	root := t.TempDir()
	a := NewActualDataAdapter(root)
	ctx := context.Background()
	if err := a.Init(ctx); err != nil {
		t.Fatal(err)
	}
	oldRef := "2026/1111/0604/probe"
	newRef := "2026/1111/0604/work/probe"
	for _, name := range []string{"probe.md", "meta/notes.md", ".hidden"} {
		if _, err := a.WriteFile(ctx, oldRef, name, strings.NewReader(name)); err != nil {
			t.Fatal(err)
		}
	}
	got, err := a.Move(ctx, oldRef, newRef)
	if err != nil || got != newRef {
		t.Fatalf("move: %q %v", got, err)
	}
	for _, ref := range []string{oldRef, newRef} {
		r, err := a.ReadFile(ctx, ref, "meta/notes.md")
		if err != nil {
			t.Fatal(err)
		}
		data, readErr := io.ReadAll(r)
		closeErr := r.Close()
		if readErr != nil || closeErr != nil || string(data) != "meta/notes.md" {
			t.Fatalf("copy mismatch: %q %v %v", data, readErr, closeErr)
		}
	}
}

// TestActualCutoverArchiveSourceOverlap rejects sources before resetting payload.
func TestActualCutoverArchiveSourceOverlap(t *testing.T) {
	root := t.TempDir()
	a := NewActualDataAdapter(root)
	ctx := context.Background()
	if err := a.Init(ctx); err != nil {
		t.Fatal(err)
	}
	ref := "2026/1111/0604/probe"
	for _, name := range []string{"probe.md", "source.tar"} {
		if _, err := a.WriteFile(ctx, ref, name, strings.NewReader("keep")); err != nil {
			t.Fatal(err)
		}
	}
	sourcePath := filepath.Join(root, "object", filepath.FromSlash(ref), "source.tar")
	f, err := os.Open(sourcePath)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if _, err := a.WriteArchive(ctx, ref, f); err == nil {
		t.Fatal("accepted archive source in target")
	}
	if data, err := os.ReadFile(sourcePath); err != nil || string(data) != "keep" {
		t.Fatalf("source changed: %q %v", data, err)
	}
}
