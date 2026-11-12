package objectfs

import (
	"archive/tar"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/config"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/filetool"
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

// TestMkdirAllCreatesDiscoverableFolders proves every created level receives an
// AGENTS.md marker, so the folder is visible through ReadDir.
func TestMkdirAllCreatesDiscoverableFolders(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.MkdirAll("some/relative/dir", 0o755); err != nil {
		t.Fatalf("mkdirs: %v", err)
	}

	entries, err := fs.ReadDir("some")
	if err != nil {
		t.Fatalf("expected the created folder to be listable: %v", err)
	}
	if !hasEntry(entries, "relative") {
		t.Fatalf("expected relative in some, got %v", entryNames(entries))
	}

	deep, err := fs.ReadDir("some/relative/dir")
	if err != nil {
		t.Fatalf("expected the deepest folder to be listable: %v", err)
	}
	if !hasEntry(deep, "AGENTS.md") {
		t.Fatalf("expected AGENTS.md in the deepest folder, got %v", entryNames(deep))
	}

	data, err := fs.ReadFile("some/relative/dir/AGENTS.md")
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	if !strings.Contains(string(data), "AGENTS") {
		t.Fatalf("expected marker content, got %q", string(data))
	}
}

// TestMkdirAllPreservesExistingContent proves an existing AGENTS.md is never
// overwritten and a populated folder receives no marker.
func TestMkdirAllPreservesExistingContent(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":         "markdown",
		"notes/AGENTS.md": "custom",
		"notes/keep.txt":  "keep",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.MkdirAll("notes", 0o755); err != nil {
		t.Fatalf("mkdirs: %v", err)
	}

	data, err := fs.ReadFile("notes/AGENTS.md")
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	if strings.TrimSpace(string(data)) != "custom" {
		t.Fatalf("expected the existing marker to survive, got %q", string(data))
	}

	kept, err := fs.ReadFile("notes/keep.txt")
	if err != nil {
		t.Fatalf("read kept file: %v", err)
	}
	if strings.TrimSpace(string(kept)) != "keep" {
		t.Fatalf("expected the existing file to survive, got %q", string(kept))
	}
}

// TestMkdirAllSkipsObjectRoot proves the object root never receives a marker.
func TestMkdirAllSkipsObjectRoot(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.MkdirAll("", 0o755); err != nil {
		t.Fatalf("mkdirs on the root: %v", err)
	}
	if err := fs.MkdirAll(".", 0o755); err != nil {
		t.Fatalf("mkdirs on the root: %v", err)
	}

	entries, err := fs.ReadDir("")
	if err != nil {
		t.Fatalf("list root: %v", err)
	}
	if hasEntry(entries, "AGENTS.md") {
		t.Fatalf("expected no marker at the object root, got %v", entryNames(entries))
	}
}

// TestStatReportsCreatedFolder proves a folder created by MkdirAll is
// discoverable through Stat, which is what the exists command relies on.
func TestStatReportsCreatedFolder(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.MkdirAll("nested/a/b/c", 0o755); err != nil {
		t.Fatalf("mkdirs: %v", err)
	}

	for _, dir := range []string{"nested", "nested/a", "nested/a/b", "nested/a/b/c"} {
		info, err := fs.Stat(dir)
		if err != nil {
			t.Fatalf("stat %q: %v", dir, err)
		}
		if !info.IsDir() {
			t.Fatalf("expected %q to be reported as a folder", dir)
		}
	}
}

// TestStatReportsMissingPath proves a missing path still fails.
func TestStatReportsMissingPath(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if _, err := fs.Stat("missing"); err == nil {
		t.Fatal("expected a missing path to fail")
	}
}

// TestMkdirAllKeepsTraversalInsideObject proves a traversal path is clamped
// into the object instead of reaching outside it, matching normalize.
func TestMkdirAllKeepsTraversalInsideObject(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	if err := fs.MkdirAll("../outside", 0o755); err != nil {
		t.Fatalf("mkdirs: %v", err)
	}

	entries, err := fs.ReadDir("")
	if err != nil {
		t.Fatalf("list root: %v", err)
	}
	if !hasEntry(entries, "outside") {
		t.Fatalf("expected the clamped folder inside the object, got %v", entryNames(entries))
	}

	marker, err := fs.ReadFile("outside/AGENTS.md")
	if err != nil {
		t.Fatalf("expected the marker inside the object: %v", err)
	}
	if !strings.Contains(string(marker), "AGENTS") {
		t.Fatalf("expected marker content, got %q", string(marker))
	}
}

// hasEntry reports whether entries holds a name.
func hasEntry(entries []os.DirEntry, want string) bool {
	for _, entry := range entries {
		if entry.Name() == want {
			return true
		}
	}
	return false
}

// entryNames returns the entry names for failure messages.
func entryNames(entries []os.DirEntry) []string {
	names := make([]string, 0, len(entries))
	for _, entry := range entries {
		names = append(names, entry.Name())
	}
	return names
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

// TestWriteFileAllowsMarkerNames keeps user files separate from the internal lock.
func TestWriteFileAllowsMarkerNames(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ObjectMetaPath("demo")
	if err != nil {
		t.Fatal(err)
	}
	before, err := os.Stat(filepath.Join(dir, "lock"))
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"demo.lock", "stat.json", "metadata.json"} {
		if err := fs.WriteFile(name, []byte("user content"), 0o644); err != nil {
			t.Fatal(err)
		}
		data, err := fs.ReadFile(name)
		if err != nil || string(data) != "user content" {
			t.Fatalf("read %s: %q %v", name, data, err)
		}
	}
	after, err := os.Stat(filepath.Join(dir, "lock"))
	if err != nil {
		t.Fatal(err)
	}
	if !os.SameFile(before, after) {
		t.Fatal("user write replaced internal lock")
	}
	entries, err := fs.ReadDir("")
	if err != nil {
		t.Fatal(err)
	}
	found := map[string]bool{}
	for _, entry := range entries {
		found[entry.Name()] = true
	}
	for _, name := range []string{"demo.lock", "stat.json", "metadata.json"} {
		if !found[name] {
			t.Fatalf("user file missing from listing: %s", name)
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
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ObjectMetaPath(obj.ID)
	if err != nil {
		t.Fatal(err)
	}
	stat, err := local.ReadStat(dir)
	if err != nil {
		t.Fatalf("read stat for %s: %v", id, err)
	}
	return stat
}

// allocatedBytes reports the cumulative bytes allocated by the process so far.
// The counter is monotonic, so a difference measures the allocation of one
// operation even when earlier allocations have already been collected.
func allocatedBytes() uint64 {
	var stats runtime.MemStats
	runtime.ReadMemStats(&stats)
	return stats.TotalAlloc
}

// TestReadFileLargeFileUsesBoundedMemory proves that reading a file far larger
// than the truncation limit does not buffer the whole file.
//
// The object-backed file system forwards the adapter's seekable stream, so the
// read path stops once the limit is reached. Buffering the file first would
// allocate at least the file size, which the assertion below rejects.
func TestReadFileLargeFileUsesBoundedMemory(t *testing.T) {
	const fileSize = 8 << 20
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "markdown",
		"big.log": strings.Repeat("a", fileSize),
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	before := allocatedBytes()
	got, err := filetool.ReadFile("big.log", filetool.ReadFileOptions{
		Size:    -1,
		FS:      fs,
		Options: filetool.Options{TruncateLimit: 1000},
	})
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	grown := allocatedBytes() - before

	want := strings.Repeat("a", 1000) + filetool.TruncateSuffix
	if got != want {
		t.Fatalf("unexpected content: %d bytes", len(got))
	}
	if grown > 2<<20 {
		t.Fatalf("reading a %d-byte file allocated %d bytes, so the stream was buffered", fileSize, grown)
	}
}

// TestStatLargeFileUsesBoundedMemory proves that reporting a file size does not
// read the file content. The size comes from the adapter's own file handle.
func TestStatLargeFileUsesBoundedMemory(t *testing.T) {
	const fileSize = 8 << 20
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "markdown",
		"big.log": strings.Repeat("a", fileSize),
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	before := allocatedBytes()
	info, err := fs.Stat("big.log")
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	grown := allocatedBytes() - before

	if info.Size() != fileSize {
		t.Fatalf("unexpected size: %d", info.Size())
	}
	if grown > 2<<20 {
		t.Fatalf("stating a %d-byte file allocated %d bytes, so the content was read", fileSize, grown)
	}
}

// TestAppendFromStreamsLargeSource proves that appending a large stream copies
// it instead of buffering it in memory.
func TestAppendFromStreamsLargeSource(t *testing.T) {
	const chunk = 8 << 20
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	source := strings.NewReader(strings.Repeat("b", chunk))
	before := allocatedBytes()
	if err := fs.AppendFrom("big.log", source, 0o644); err != nil {
		t.Fatalf("append from: %v", err)
	}
	grown := allocatedBytes() - before

	info, err := fs.Stat("big.log")
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Size() != chunk {
		t.Fatalf("unexpected size: %d", info.Size())
	}
	if grown > 2<<20 {
		t.Fatalf("appending %d bytes allocated %d bytes, so the source was buffered", chunk, grown)
	}
}

// TestWriteFileFromStreamsLargeSource proves that replacing a file from a
// stream does not buffer the source in memory.
//
// The manager holds object custody for the whole write and the adapter copies
// the stream, so memory use stays constant. Buffering the source first would
// allocate at least its size, which the assertion below rejects.
func TestWriteFileFromStreamsLargeSource(t *testing.T) {
	const chunk = 8 << 20
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	source := strings.NewReader(strings.Repeat("c", chunk))
	before := allocatedBytes()
	if err := fs.WriteFileFrom("big.log", source, 0o644); err != nil {
		t.Fatalf("write from: %v", err)
	}
	grown := allocatedBytes() - before

	info, err := fs.Stat("big.log")
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Size() != chunk {
		t.Fatalf("unexpected size: %d", info.Size())
	}
	if grown > 2<<20 {
		t.Fatalf("writing %d bytes allocated %d bytes, so the source was buffered", chunk, grown)
	}
}

// TestConcurrentAppendKeepsEverySuccessfulUpdate rejects an append path that
// reports success and then loses the appended bytes to a concurrent writer.
//
// Scope of this guard: the advisory lock is non-blocking, so a losing writer
// fails with ErrObjectLocked and never reports success. That means this test
// catches an *unlocked* append, where every writer succeeds and the last one
// overwrites the rest, but it does not by itself distinguish a lock-scoped
// append from a read-modify-write that reads outside the lock: in the latter
// case only one writer wins the write lock and the losers fail loudly, so no
// acknowledged update is lost either. Bounded memory on a large existing file
// is what pins the in-place append implementation; see
// TestAppendToLargeExistingFileUsesBoundedMemory.
//
// A start gate releases every writer at the same instant so the race is
// reproducible instead of depending on timing luck.
func TestConcurrentAppendKeepsEverySuccessfulUpdate(t *testing.T) {
	const writers = 16
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "base",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	gate := make(chan struct{})
	var mu sync.Mutex
	succeeded := make([]int, 0, writers)
	var wg sync.WaitGroup
	for i := 0; i < writers; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			<-gate
			marker := fmt.Sprintf("|w%d|", n)
			err := fs.AppendFile("notes.md", []byte(marker), 0o644)
			if err == nil {
				mu.Lock()
				succeeded = append(succeeded, n)
				mu.Unlock()
				return
			}
			if !errors.Is(err, apperrors.ErrObjectLocked) {
				t.Errorf("append %d: unexpected error: %v", n, err)
			}
		}(i)
	}
	close(gate)
	wg.Wait()

	data, err := fs.ReadFile("notes.md")
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if !strings.HasPrefix(string(data), "base") {
		t.Fatalf("original content was lost: %q", data)
	}
	for _, n := range succeeded {
		marker := fmt.Sprintf("|w%d|", n)
		if !strings.Contains(string(data), marker) {
			t.Fatalf("append %d reported success but %q is missing from %q", n, marker, data)
		}
	}
}

// TestConcurrentUpdateFileKeepsEverySuccessfulUpdate proves that the read and
// the write of a read-modify-write run under one custody, so a concurrent
// updater cannot interleave between them and discard an acknowledged update.
//
// The callback records how many updaters are inside it at once. Exclusive
// custody means that number never exceeds one, which is a direct assertion of
// the invariant rather than an inference from the final content.
func TestConcurrentUpdateFileKeepsEverySuccessfulUpdate(t *testing.T) {
	const writers = 16
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "base",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	var inCallback int32
	var maxInCallback int32
	gate := make(chan struct{})
	var mu sync.Mutex
	succeeded := make([]int, 0, writers)
	var wg sync.WaitGroup
	for i := 0; i < writers; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			<-gate
			marker := fmt.Sprintf("|w%d|", n)
			err := fs.UpdateFile("notes.md", func(existing []byte, exists bool) ([]byte, error) {
				current := atomic.AddInt32(&inCallback, 1)
				defer atomic.AddInt32(&inCallback, -1)
				for {
					observed := atomic.LoadInt32(&maxInCallback)
					if current <= observed || atomic.CompareAndSwapInt32(&maxInCallback, observed, current) {
						break
					}
				}
				if !exists {
					return nil, fmt.Errorf("notes.md disappeared")
				}
				// Hold the callback open long enough that a second updater would
				// certainly be observed if custody did not span the read.
				time.Sleep(5 * time.Millisecond)
				updated := append(append([]byte{}, existing...), []byte(marker)...)
				return updated, nil
			})
			if err == nil {
				mu.Lock()
				succeeded = append(succeeded, n)
				mu.Unlock()
				return
			}
			if !errors.Is(err, apperrors.ErrObjectLocked) {
				t.Errorf("update %d: unexpected error: %v", n, err)
			}
		}(i)
	}
	close(gate)
	wg.Wait()

	if got := atomic.LoadInt32(&maxInCallback); got > 1 {
		t.Fatalf("%d updaters ran inside the read-modify-write at once, so custody does not span the read", got)
	}

	data, err := fs.ReadFile("notes.md")
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	for _, n := range succeeded {
		marker := fmt.Sprintf("|w%d|", n)
		if !strings.Contains(string(data), marker) {
			t.Fatalf("update %d reported success but %q is missing from %q", n, marker, data)
		}
	}
}

// TestUpdateFileReportsMissingFile proves that the callback learns a file is
// absent instead of receiving an error. The object-backed implementation reports
// a missing file through the exists flag, so a caller can create it.
func TestUpdateFileReportsMissingFile(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{"demo.md": "markdown"})
	fs := newObjectFS(t, ctx, mgr, "demo")

	var seenExists bool
	err := fs.UpdateFile("fresh.md", func(existing []byte, exists bool) ([]byte, error) {
		seenExists = exists
		if len(existing) != 0 {
			t.Fatalf("expected no existing content, got %q", existing)
		}
		return []byte("created"), nil
	})
	if err != nil {
		t.Fatalf("update file: %v", err)
	}
	if seenExists {
		t.Fatal("a missing file was reported as existing")
	}

	data, err := fs.ReadFile("fresh.md")
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(data) != "created" {
		t.Fatalf("unexpected content: %q", data)
	}
}

// TestUpdateFileAbortsWithoutChangingContent proves that a callback error leaves
// the stored content untouched.
func TestUpdateFileAbortsWithoutChangingContent(t *testing.T) {
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": "first",
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	sentinel := errors.New("abort the update")
	err := fs.UpdateFile("notes.md", func(existing []byte, exists bool) ([]byte, error) {
		return nil, sentinel
	})
	if !errors.Is(err, sentinel) {
		t.Fatalf("expected the callback error, got %v", err)
	}

	data, err := fs.ReadFile("notes.md")
	if err != nil {
		t.Fatalf("read back: %v", err)
	}
	if string(data) != "first" {
		t.Fatalf("content changed after an aborted update: %q", data)
	}
}

// TestReadFileFullContentAllocatesFileSize is the sensitivity control for the
// bounded-memory assertions above.
//
// ReadFile returns the complete content by contract, so it must allocate at
// least the file size. This test proves the allocation counter really observes a
// full-file buffer; without it, a bounded-memory assertion could pass simply
// because the counter never moved.
func TestReadFileFullContentAllocatesFileSize(t *testing.T) {
	const fileSize = 8 << 20
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md": "markdown",
		"big.log": strings.Repeat("a", fileSize),
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	before := allocatedBytes()
	data, err := fs.ReadFile("big.log")
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	grown := allocatedBytes() - before

	if len(data) != fileSize {
		t.Fatalf("unexpected content length: %d", len(data))
	}
	if grown < fileSize {
		t.Fatalf("reading %d bytes allocated only %d bytes, so the counter is not observing the buffer", fileSize, grown)
	}
}

// TestAppendToLargeExistingFileUsesBoundedMemory proves that appending to a large
// existing file does not read that file back into memory.
//
// This is the deterministic guard for the read-modify-write defect: an
// implementation that reads the existing content, concatenates, and writes it
// back must allocate at least the existing file size. An in-place append
// allocates only its copy buffer.
func TestAppendToLargeExistingFileUsesBoundedMemory(t *testing.T) {
	const fileSize = 8 << 20
	mgr, ctx := newTestManager(t)
	createObject(t, ctx, mgr, "demo", map[string]string{
		"demo.md":  "markdown",
		"notes.md": strings.Repeat("x", fileSize),
	})
	fs := newObjectFS(t, ctx, mgr, "demo")

	before := allocatedBytes()
	if err := fs.AppendFile("notes.md", []byte("tail"), 0o644); err != nil {
		t.Fatalf("append file: %v", err)
	}
	grown := allocatedBytes() - before

	info, err := fs.Stat("notes.md")
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	if info.Size() != fileSize+4 {
		t.Fatalf("unexpected size: %d", info.Size())
	}
	if grown > 2<<20 {
		t.Fatalf("appending to a %d-byte file allocated %d bytes, so the existing content was read back", fileSize, grown)
	}
}
