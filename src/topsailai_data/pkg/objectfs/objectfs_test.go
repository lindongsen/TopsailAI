package objectfs

import (
	"archive/tar"
	"bytes"
	"context"
	"errors"
	"io"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/config"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/manager"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// newTestManager returns a manager rooted in a temporary directory.
func newTestManager(t *testing.T) (*manager.Manager, context.Context) {
	t.Helper()
	cfg := &config.Config{
		Root:                     t.TempDir(),
		MetadataAdapter:          "local",
		ActualDataAdapter:        "local",
		CeasedRetentionDays:      30,
		LogLevel:                 "ERROR",
		TrackStat:                true,
		StatFlush:                config.DefaultStatFlush,
		FileMaxBytes:             30000,
		FileNoTruncateExtensions: nil,
	}
	mgr, err := manager.New(cfg)
	if err != nil {
		t.Fatalf("new manager: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	t.Cleanup(func() {
		cancel()
		_ = mgr.Close()
	})
	return mgr, ctx
}

// createObject creates one active object containing the given files.
func createObject(t *testing.T, ctx context.Context, mgr *manager.Manager, name string, files map[string]string) {
	t.Helper()

	var buf bytes.Buffer
	writer := tar.NewWriter(&buf)
	for path, content := range files {
		header := &tar.Header{Name: path, Mode: 0o644, Size: int64(len(content))}
		if err := writer.WriteHeader(header); err != nil {
			t.Fatalf("write header %s: %v", path, err)
		}
		if _, err := writer.Write([]byte(content)); err != nil {
			t.Fatalf("write body %s: %v", path, err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatalf("close tar: %v", err)
	}

	if _, err := mgr.CreateObject(ctx, name, manager.CreateObjectOptions{
		Description: "object " + name,
		Data:        &buf,
	}); err != nil {
		t.Fatalf("create object %s: %v", name, err)
	}
}

// newObjectFS returns an object-backed file system for one object.
func newObjectFS(t *testing.T, ctx context.Context, mgr *manager.Manager, id string) *ObjectFS {
	t.Helper()
	fs, err := New(ctx, mgr, models.ObjectID(id))
	if err != nil {
		t.Fatalf("new object fs: %v", err)
	}
	return fs
}

// TestNewRejectsMissingInputs rejects a nil manager and an empty id.
func TestNewRejectsMissingInputs(t *testing.T) {
	ctx := context.Background()

	if _, err := New(ctx, nil, "demo"); err == nil {
		t.Fatal("expected an error for a nil manager")
	}
	mgr, ctx2 := newTestManager(t)
	if _, err := New(ctx2, mgr, ""); err == nil {
		t.Fatal("expected an error for an empty object id")
	}
}

// TestReadFileReturnsStoredContent reads a file inside an object.
func TestReadFileReturnsStoredContent(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "note body",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	data, err := fs.ReadFile("notes.md")
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "note body" {
		t.Fatalf("unexpected content: %q", data)
	}
}

// TestReadFileAcceptsLeadingSlash treats an absolute-looking path as
// object-relative.
func TestReadFileAcceptsLeadingSlash(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "note body",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	data, err := fs.ReadFile("/notes.md")
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if string(data) != "note body" {
		t.Fatalf("unexpected content: %q", data)
	}
}

// TestReadFileRejectsMissingFile reports a missing file as an object error.
func TestReadFileRejectsMissingFile(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	_, err := fs.ReadFile("ghost.md")
	if err == nil {
		t.Fatal("expected an error for a missing file")
	}
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("unexpected error: %v", err)
	}
}

// TestReadFileRejectsEmptyPath rejects an empty path.
func TestReadFileRejectsEmptyPath(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if _, err := fs.ReadFile(""); err == nil {
		t.Fatal("expected an error for an empty path")
	}
}

// TestReadFileRejectsObjectRoot rejects reading the object root as a file.
func TestReadFileRejectsObjectRoot(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if _, err := fs.ReadFile("/"); err == nil {
		t.Fatal("expected an error when reading the object root")
	}
}

// TestNormalizeKeepsTraversalInsideObject normalises a traversal path into the
// object instead of escaping it.
func TestNormalizeKeepsTraversalInsideObject(t *testing.T) {
	got, err := normalize("../../etc/passwd")
	if err != nil {
		t.Fatalf("normalize: %v", err)
	}
	if got != "etc/passwd" {
		t.Fatalf("unexpected normalised path: %q", got)
	}
}

// TestNormalizeRejectsEmptyPath rejects an empty path.
func TestNormalizeRejectsEmptyPath(t *testing.T) {
	if _, err := normalize(""); err == nil {
		t.Fatal("expected an error for an empty path")
	}
}

// TestWriteFileStoresContent writes a new file into an object.
func TestWriteFileStoresContent(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.WriteFile("notes/new.md", []byte("fresh"), 0o644); err != nil {
		t.Fatalf("write file: %v", err)
	}
	data, err := fs.ReadFile("notes/new.md")
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(data) != "fresh" {
		t.Fatalf("unexpected content: %q", data)
	}
}

// TestWriteFileReplacesExistingContent replaces an existing file.
func TestWriteFileReplacesExistingContent(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "old",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.WriteFile("notes.md", []byte("new"), 0o644); err != nil {
		t.Fatalf("write file: %v", err)
	}
	data, err := fs.ReadFile("notes.md")
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(data) != "new" {
		t.Fatalf("unexpected content: %q", data)
	}
}

// TestWriteFileRejectsObjectRoot rejects writing the object root as a file.
func TestWriteFileRejectsObjectRoot(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.WriteFile("/", []byte("x"), 0o644); err == nil {
		t.Fatal("expected an error when writing the object root")
	}
}

// TestAppendFileAppendsToExistingContent appends to an existing file.
func TestAppendFileAppendsToExistingContent(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "first",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.AppendFile("notes.md", []byte(" second"), 0o644); err != nil {
		t.Fatalf("append file: %v", err)
	}
	data, err := fs.ReadFile("notes.md")
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(data) != "first second" {
		t.Fatalf("unexpected content: %q", data)
	}
}

// TestAppendFileCreatesMissingFile treats a missing file as empty content.
func TestAppendFileCreatesMissingFile(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.AppendFile("fresh.md", []byte("created"), 0o644); err != nil {
		t.Fatalf("append file: %v", err)
	}
	data, err := fs.ReadFile("fresh.md")
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(data) != "created" {
		t.Fatalf("unexpected content: %q", data)
	}
}

// TestStatReportsFileSize reports the size of a file inside an object.
func TestStatReportsFileSize(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "12345",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	info, err := fs.Stat("notes.md")
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Size() != 5 {
		t.Fatalf("unexpected size: %d", info.Size())
	}
	if info.Name() != "notes.md" {
		t.Fatalf("unexpected name: %q", info.Name())
	}
	if info.IsDir() {
		t.Fatal("file reported as a directory")
	}
}

// TestStatReportsObjectRootAsDirectory reports the object root as a directory.
func TestStatReportsObjectRootAsDirectory(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	info, err := fs.Stat("")
	if err != nil {
		t.Fatalf("stat root: %v", err)
	}
	if !info.IsDir() {
		t.Fatal("object root not reported as a directory")
	}
	if info.Name() != "demo" {
		t.Fatalf("unexpected root name: %q", info.Name())
	}
}

// TestStatRejectsMissingFile reports a missing file as an error.
func TestStatRejectsMissingFile(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if _, err := fs.Stat("ghost.md"); err == nil {
		t.Fatal("expected an error for a missing file")
	}
}

// TestReadDirListsRootEntries lists the immediate entries of the object root.
func TestReadDirListsRootEntries(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":      "markdown",
		"top.md":       "top",
		"notes/a.md":   "a",
		"notes/b.md":   "b",
		"notes/deep/c": "c",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	entries, err := fs.ReadDir("")
	if err != nil {
		t.Fatalf("read dir: %v", err)
	}

	names := make(map[string]bool, len(entries))
	for _, entry := range entries {
		names[entry.Name()] = entry.IsDir()
	}
	if _, ok := names["demo.md"]; !ok {
		t.Fatalf("demo.md missing from listing: %v", names)
	}
	if _, ok := names["top.md"]; !ok {
		t.Fatalf("top.md missing from listing: %v", names)
	}
	if isDir, ok := names["notes"]; !ok || !isDir {
		t.Fatalf("notes not reported as a directory: %v", names)
	}
	if _, ok := names["a.md"]; ok {
		t.Fatalf("nested file leaked into the root listing: %v", names)
	}
}

// TestReadDirListsSubfolderEntries lists a subfolder.
func TestReadDirListsSubfolderEntries(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":      "markdown",
		"notes/a.md":   "a",
		"notes/b.md":   "b",
		"notes/deep/c": "c",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	entries, err := fs.ReadDir("notes")
	if err != nil {
		t.Fatalf("read dir: %v", err)
	}

	names := make(map[string]bool, len(entries))
	for _, entry := range entries {
		names[entry.Name()] = entry.IsDir()
	}
	if _, ok := names["a.md"]; !ok {
		t.Fatalf("a.md missing: %v", names)
	}
	if _, ok := names["b.md"]; !ok {
		t.Fatalf("b.md missing: %v", names)
	}
	if isDir, ok := names["deep"]; !ok || !isDir {
		t.Fatalf("deep not reported as a directory: %v", names)
	}
}

// TestReadDirRejectsMissingFolder reports a missing folder as an error.
func TestReadDirRejectsMissingFolder(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if _, err := fs.ReadDir("ghost"); err == nil {
		t.Fatal("expected an error for a missing folder")
	}
}

// TestMkdirAllIsNoOp succeeds without creating anything.
func TestMkdirAllIsNoOp(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.MkdirAll("some/relative/dir", 0o755); err != nil {
		t.Fatalf("mkdirs: %v", err)
	}
	if _, err := fs.ReadDir("some"); err == nil {
		t.Fatal("mkdirs created a folder, but object storage has no empty folders")
	}
}

// TestOpenSupportsSeeking reads through the seekable interface.
func TestOpenSupportsSeeking(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "0123456789",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	file, err := fs.Open("notes.md")
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer file.Close()

	if _, err := file.Seek(3, io.SeekStart); err != nil {
		t.Fatalf("seek: %v", err)
	}
	buf := make([]byte, 4)
	if _, err := io.ReadFull(file, buf); err != nil {
		t.Fatalf("read: %v", err)
	}
	if string(buf) != "3456" {
		t.Fatalf("unexpected content: %q", buf)
	}
}

// TestOpenRejectsObjectRoot rejects opening the object root as a file.
func TestOpenRejectsObjectRoot(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if _, err := fs.Open("/"); err == nil {
		t.Fatal("expected an error when opening the object root")
	}
}

// TestOpenRejectsMissingFile reports a missing file as an error.
func TestOpenRejectsMissingFile(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if _, err := fs.Open("ghost.md"); err == nil {
		t.Fatal("expected an error for a missing file")
	}
}

// TestWriteFileRecordsStatistics verifies that object-scoped writes update the
// usage statistics through the manager.
func TestWriteFileRecordsStatistics(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "body",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	before := statOf(t, ctx, mgr, "demo")
	if err := fs.WriteFile("notes.md", []byte("changed"), 0o644); err != nil {
		t.Fatalf("write file: %v", err)
	}
	after := statOf(t, ctx, mgr, "demo")

	if after.WriteCount <= before.WriteCount {
		t.Fatalf("write count did not increase: before=%d after=%d", before.WriteCount, after.WriteCount)
	}
}

// TestReadFileRecordsStatistics verifies that object-scoped reads update the
// usage statistics through the manager.
func TestReadFileRecordsStatistics(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "body",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	before := statOf(t, ctx, mgr, "demo")
	if _, err := fs.ReadFile("notes.md"); err != nil {
		t.Fatalf("read file: %v", err)
	}
	after := statOf(t, ctx, mgr, "demo")

	if after.ReadCount <= before.ReadCount {
		t.Fatalf("read count did not increase: before=%d after=%d", before.ReadCount, after.ReadCount)
	}
}

// TestWriteFileRejectsMetadataMarker keeps a caller from overwriting the
// object's own metadata files.
func TestWriteFileRejectsMetadataMarker(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.WriteFile("demo.lock", []byte("x"), 0o644); err == nil {
		t.Fatal("expected an error when writing a metadata marker")
	}
}

// TestReadDirSkipsMetadataMarkers keeps metadata files out of listings.
func TestReadDirSkipsMetadataMarkers(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "body",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	entries, err := fs.ReadDir("")
	if err != nil {
		t.Fatalf("read dir: %v", err)
	}
	for _, entry := range entries {
		name := entry.Name()
		if strings.HasSuffix(name, ".lock") || strings.HasSuffix(name, ".stat.json") || name == "metadata.json" {
			t.Fatalf("metadata marker leaked into listing: %q", name)
		}
	}
}

// statOf loads the usage statistics of one object.
func statOf(t *testing.T, ctx context.Context, mgr *manager.Manager, id string) *models.ObjectStat {
	t.Helper()
	obj, err := mgr.GetObject(ctx, models.ObjectID(id), false)
	if err != nil {
		t.Fatalf("get object %s: %v", id, err)
	}
	stat, err := readStat(obj)
	if err != nil {
		t.Fatalf("read stat for %s: %v", id, err)
	}
	return stat
}

// readStat loads stat data from the object's local reference.
func readStat(obj *models.Object) (*models.ObjectStat, error) {
	if obj == nil || obj.DataRef == "" {
		return &models.ObjectStat{}, nil
	}
	return local.ReadStat(obj.DataRef)
}
