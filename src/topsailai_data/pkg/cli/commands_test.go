package cli

import (
	"archive/tar"
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/config"
	"github.com/topsailai/topsailai_data/pkg/manager"
	"github.com/topsailai/topsailai_data/pkg/models"
)

func setupManager(t *testing.T) (*manager.Manager, string, context.Context) {
	t.Helper()
	tmp := t.TempDir()
	cfg := &config.Config{
		Root:                tmp,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		ReadLock:            false,
		IncludeDeleted:      false,
		CeasedRetentionDays: 0,
		LogLevel:            "ERROR",
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
	return mgr, tmp, ctx
}

func TestRunNoArgsEntersInteractiveMode(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	// With no arguments and no stdin input, Run enters interactive mode and
	// returns cleanly when stdin reaches EOF.
	if err := Run(ctx, mgr, nil); err != nil {
		t.Fatalf("expected no error when entering interactive mode, got %v", err)
	}
}

func TestInteractiveMode(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	oldStdin := os.Stdin
	r, w, _ := os.Pipe()
	os.Stdin = r
	done := make(chan struct{})
	var runErr error
	go func() {
		defer close(done)
		runErr = Run(ctx, mgr, nil)
	}()

	_, _ = w.WriteString("create hello --classify demo --tag a,b\nlist\nexit\n")
	_ = w.Close()
	<-done
	os.Stdin = oldStdin

	if runErr != nil {
		t.Fatalf("interactive mode: %v", runErr)
	}

	objects, err := mgr.ListObjects(ctx, models.ListOptions{})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(objects) != 1 {
		t.Fatalf("expected 1 object, got %d", len(objects))
	}
}

func TestCreateAndShow(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "hello", "--classify", "demo", "--tag", "a,b"}); err != nil {
		t.Fatalf("create: %v", err)
	}

	objects, err := mgr.ListObjects(ctx, models.ListOptions{})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(objects) != 1 {
		t.Fatalf("expected 1 object, got %d", len(objects))
	}
	id := objects[0].ID

	var buf bytes.Buffer
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	err = Run(ctx, mgr, []string{"show", string(id)})
	w.Close()
	os.Stdout = old
	if err != nil {
		t.Fatalf("show: %v", err)
	}
	_, _ = buf.ReadFrom(r)
	out := buf.String()
	if !strings.Contains(out, "Name:          hello") {
		t.Fatalf("show output missing name: %s", out)
	}
	if !strings.Contains(out, "Status:        active") {
		t.Fatalf("show output missing active status: %s", out)
	}
}

func TestWriteAndReadActualFile(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "doc", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	content := []byte("hello actual data")
	src := filepath.Join(tmp, "input.txt")
	if err := os.WriteFile(src, content, 0644); err != nil {
		t.Fatalf("write input: %v", err)
	}

	if err := Run(ctx, mgr, []string{"put", string(obj.ID), "notes.txt", "--from", src}); err != nil {
		t.Fatalf("put: %v", err)
	}

	var buf bytes.Buffer
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	err = Run(ctx, mgr, []string{"get", string(obj.ID), "notes.txt"})
	w.Close()
	os.Stdout = old
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	_, _ = buf.ReadFrom(r)
	if !bytes.Equal(buf.Bytes(), content) {
		t.Fatalf("expected %q, got %q", content, buf.Bytes())
	}
}

func TestTagAddAndSearch(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "tagged", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"alpha"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := Run(ctx, mgr, []string{"tag", "add", string(obj.ID), "beta"}); err != nil {
		t.Fatalf("tag add: %v", err)
	}

	var buf bytes.Buffer
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	err = Run(ctx, mgr, []string{"search", "beta"})
	w.Close()
	os.Stdout = old
	if err != nil {
		t.Fatalf("search: %v", err)
	}
	_, _ = buf.ReadFrom(r)
	out := buf.String()
	if !strings.Contains(out, string(obj.ID)) {
		t.Fatalf("search output missing object id: %s", out)
	}
}

func TestDeleteAndFinalize(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "removeme", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := Run(ctx, mgr, []string{"delete", string(obj.ID)}); err != nil {
		t.Fatalf("delete: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, true)
	if err != nil {
		t.Fatalf("get after delete: %v", err)
	}
	if got.Status != models.ObjectStatusCeased {
		t.Fatalf("expected status ceased, got %s", got.Status)
	}
}

func TestMoveObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "movable", manager.CreateObjectOptions{
		Classify: []string{"old"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := Run(ctx, mgr, []string{"move", string(obj.ID), "new", "nested"}); err != nil {
		t.Fatalf("move: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get after move: %v", err)
	}
	want := "new/nested/movable"
	if !strings.HasSuffix(got.Path, want) {
		t.Fatalf("expected path to end with %q, got %q", want, got.Path)
	}
}

func TestMoveObjectSlashPath(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "movable", manager.CreateObjectOptions{
		Classify: []string{"old"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := Run(ctx, mgr, []string{"move", string(obj.ID), "new/nested"}); err != nil {
		t.Fatalf("move: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get after move: %v", err)
	}
	want := "new/nested/movable"
	if !strings.HasSuffix(got.Path, want) {
		t.Fatalf("expected path to end with %q, got %q", want, got.Path)
	}
}

func TestCreateFromPlainFile(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	content := []byte("hello from plain file")
	src := filepath.Join(tmp, "input.txt")
	if err := os.WriteFile(src, content, 0644); err != nil {
		t.Fatalf("write input: %v", err)
	}

	if err := Run(ctx, mgr, []string{"create", "plaindoc", "--from", src}); err != nil {
		t.Fatalf("create from file: %v", err)
	}

	objects, err := mgr.ListObjects(ctx, models.ListOptions{})
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(objects) != 1 {
		t.Fatalf("expected 1 object, got %d", len(objects))
	}
	id := objects[0].ID

	var buf bytes.Buffer
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	err = Run(ctx, mgr, []string{"get", string(id), "plaindoc.md"})
	w.Close()
	os.Stdout = old
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	_, _ = buf.ReadFrom(r)
	if !bytes.Equal(buf.Bytes(), content) {
		t.Fatalf("expected %q, got %q", content, buf.Bytes())
	}
}

func TestRecoverAutoActivate(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "recoverable", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	// Simulate a crash by reverting the metadata to creating without touching actual data.
	metaPath := filepath.Join(tmp, obj.Path, "metadata.json")
	metaBytes, err := os.ReadFile(metaPath)
	if err != nil {
		t.Fatalf("read metadata: %v", err)
	}
	metaBytes = bytes.ReplaceAll(metaBytes, []byte(`"active"`), []byte(`"creating"`))
	if err := os.WriteFile(metaPath, metaBytes, 0644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}

	if err := Run(ctx, mgr, []string{"recover", string(obj.ID)}); err != nil {
		t.Fatalf("recover: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get after recover: %v", err)
	}
	if got.Status != models.ObjectStatusActive {
		t.Fatalf("expected status active, got %s", got.Status)
	}
}

func TestRecoverCleanupWhenNoActualData(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "orphan", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	// Remove actual data and revert metadata to creating.
	if err := os.RemoveAll(filepath.Join(tmp, obj.Path, obj.Name+".md")); err != nil {
		t.Fatalf("remove marker: %v", err)
	}
	metaPath := filepath.Join(tmp, obj.Path, "metadata.json")
	metaBytes, err := os.ReadFile(metaPath)
	if err != nil {
		t.Fatalf("read metadata: %v", err)
	}
	metaBytes = bytes.ReplaceAll(metaBytes, []byte(`"active"`), []byte(`"creating"`))
	if err := os.WriteFile(metaPath, metaBytes, 0644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}

	if err := Run(ctx, mgr, []string{"recover", string(obj.ID)}); err != nil {
		t.Fatalf("recover: %v", err)
	}

	_, err = mgr.GetObject(ctx, obj.ID, false)
	if err == nil {
		t.Fatalf("expected object to be gone after cleanup")
	}
}

func TestRecoverResumeRequiresFromWhenNoData(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "resume", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	// Revert to creating and remove actual data.
	metaPath := filepath.Join(mgr.Root(), obj.Path, "metadata.json")
	metaBytes, err := os.ReadFile(metaPath)
	if err != nil {
		t.Fatalf("read metadata: %v", err)
	}
	metaBytes = bytes.ReplaceAll(metaBytes, []byte(`"active"`), []byte(`"creating"`))
	if err := os.WriteFile(metaPath, metaBytes, 0644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}
	if err := os.RemoveAll(filepath.Join(mgr.Root(), obj.Path, obj.Name+".md")); err != nil {
		t.Fatalf("remove marker: %v", err)
	}

	err = Run(ctx, mgr, []string{"recover", "--resume", string(obj.ID)})
	if err == nil {
		t.Fatalf("expected error when --resume without --from and no actual data")
	}
	if !strings.Contains(err.Error(), "from") {
		t.Fatalf("expected error to mention --from, got %v", err)
	}
}

func TestRecoverResumeWithoutFromActivatesExistingData(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "resume", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	// Revert metadata to creating while leaving actual data intact.
	metaPath := filepath.Join(tmp, obj.Path, "metadata.json")
	metaBytes, err := os.ReadFile(metaPath)
	if err != nil {
		t.Fatalf("read metadata: %v", err)
	}
	metaBytes = bytes.ReplaceAll(metaBytes, []byte(`"active"`), []byte(`"creating"`))
	if err := os.WriteFile(metaPath, metaBytes, 0644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}

	if err := Run(ctx, mgr, []string{"recover", "--resume", string(obj.ID)}); err != nil {
		t.Fatalf("recover --resume without --from: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get after recover: %v", err)
	}
	if got.Status != models.ObjectStatusActive {
		t.Fatalf("expected status active, got %s", got.Status)
	}
}

func TestGCDefaultScansCreatingAndCeased(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	// Create an active object.
	activeObj, err := mgr.CreateObject(ctx, "active", manager.CreateObjectOptions{Classify: []string{"demo"}})
	if err != nil {
		t.Fatalf("create active: %v", err)
	}

	// Create a creating object without actual data (will be cleaned up).
	creatingObj, err := mgr.CreateObject(ctx, "creating", manager.CreateObjectOptions{Classify: []string{"demo"}})
	if err != nil {
		t.Fatalf("create creating: %v", err)
	}
	metaPath := filepath.Join(tmp, creatingObj.Path, "metadata.json")
	metaBytes, err := os.ReadFile(metaPath)
	if err != nil {
		t.Fatalf("read metadata: %v", err)
	}
	metaBytes = bytes.ReplaceAll(metaBytes, []byte(`"active"`), []byte(`"creating"`))
	if err := os.WriteFile(metaPath, metaBytes, 0644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}
	if err := os.RemoveAll(filepath.Join(tmp, creatingObj.Path, creatingObj.Name+".md")); err != nil {
		t.Fatalf("remove marker: %v", err)
	}

	// Create a ceased object.
	ceasedObj, err := mgr.CreateObject(ctx, "ceased", manager.CreateObjectOptions{Classify: []string{"demo"}})
	if err != nil {
		t.Fatalf("create ceased: %v", err)
	}
	if err := mgr.DeleteObject(ctx, ceasedObj.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}

	if err := Run(ctx, mgr, []string{"gc"}); err != nil {
		t.Fatalf("gc: %v", err)
	}

	// Active object must remain.
	if _, err := mgr.GetObject(ctx, activeObj.ID, false); err != nil {
		t.Fatalf("active object should remain: %v", err)
	}

	// Creating object without data must be gone.
	if _, err := mgr.GetObject(ctx, creatingObj.ID, false); err == nil {
		t.Fatalf("creating object should be cleaned up")
	}

	// Ceased object must be gone.
	if _, err := mgr.GetObject(ctx, ceasedObj.ID, true); err == nil {
		t.Fatalf("ceased object should be cleaned up")
	}
}

func TestCreateClassifySlashPath(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "slashdoc", "--classify", "photos/2024"}); err != nil {
		t.Fatalf("create with slash classify: %v", err)
	}

	got, err := mgr.GetObject(ctx, "slashdoc", false)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	wantSuffix := "photos/2024/slashdoc"
	if !strings.HasSuffix(got.Path, wantSuffix) {
		t.Fatalf("expected path to end with %q, got %q", wantSuffix, got.Path)
	}
}

func TestGCStatusDeletedFinalizesObjects(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	// Create and delete an object; in the local adapter this goes straight to ceased.
	obj, err := mgr.CreateObject(ctx, "stale", manager.CreateObjectOptions{Classify: []string{"demo"}})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}

	// Simulate a stale deleted object by reverting the status from ceased to deleted.
	metaPath := filepath.Join(tmp, obj.Path, "metadata.json")
	metaBytes, err := os.ReadFile(metaPath)
	if err != nil {
		t.Fatalf("read metadata: %v", err)
	}
	metaBytes = bytes.ReplaceAll(metaBytes, []byte(`"ceased"`), []byte(`"deleted"`))
	if err := os.WriteFile(metaPath, metaBytes, 0644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}

	if err := Run(ctx, mgr, []string{"gc", "--status", "deleted"}); err != nil {
		t.Fatalf("gc --status deleted: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, true)
	if err != nil {
		t.Fatalf("get after gc: %v", err)
	}
	if got.Status != models.ObjectStatusCeased {
		t.Fatalf("expected status ceased, got %s", got.Status)
	}
}

func TestCreateFromStdin(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	content := []byte("hello from stdin")
	oldStdin := os.Stdin
	r, w, _ := os.Pipe()
	os.Stdin = r
	done := make(chan struct{})
	go func() {
		defer close(done)
		_, _ = w.Write(content)
		_ = w.Close()
	}()

	err := Run(ctx, mgr, []string{"create", "stdinobj"})
	<-done
	os.Stdin = oldStdin
	if err != nil {
		t.Fatalf("create from stdin: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "stdinobj", false)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if obj.Status != models.ObjectStatusActive {
		t.Fatalf("expected status active, got %s", obj.Status)
	}

	rc, err := mgr.ReadActualFile(ctx, "stdinobj", "stdinobj.md")
	if err != nil {
		t.Fatalf("read actual file: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read content: %v", err)
	}
	if !bytes.Equal(got, content) {
		t.Fatalf("expected %q, got %q", content, got)
	}
}

func TestCreateFromStdinEmpty(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	oldStdin := os.Stdin
	r, w, _ := os.Pipe()
	os.Stdin = r
	_ = w.Close()

	err := Run(ctx, mgr, []string{"create", "emptyobj"})
	os.Stdin = oldStdin
	if err != nil {
		t.Fatalf("create from empty stdin: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "emptyobj", false)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if obj.Status != models.ObjectStatusActive {
		t.Fatalf("expected status active, got %s", obj.Status)
	}

	rc, err := mgr.ReadActualFile(ctx, "emptyobj", "emptyobj.md")
	if err != nil {
		t.Fatalf("read actual file: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read content: %v", err)
	}
	if len(got) != 0 {
		t.Fatalf("expected empty object.md, got %q", got)
	}
}

func TestCreateFromStdinTarArchive(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	var tarBuf bytes.Buffer
	tw := tar.NewWriter(&tarBuf)
	markerContent := []byte("archive marker content")
	hdr := &tar.Header{
		Name: "stdinarchive.md",
		Mode: 0o644,
		Size: int64(len(markerContent)),
	}
	if err := tw.WriteHeader(hdr); err != nil {
		t.Fatalf("write tar header: %v", err)
	}
	if _, err := tw.Write(markerContent); err != nil {
		t.Fatalf("write tar content: %v", err)
	}
	extraContent := []byte("extra file content")
	hdr2 := &tar.Header{
		Name: "extra.txt",
		Mode: 0o644,
		Size: int64(len(extraContent)),
	}
	if err := tw.WriteHeader(hdr2); err != nil {
		t.Fatalf("write tar header: %v", err)
	}
	if _, err := tw.Write(extraContent); err != nil {
		t.Fatalf("write tar content: %v", err)
	}
	if err := tw.Close(); err != nil {
		t.Fatalf("close tar writer: %v", err)
	}

	oldStdin := os.Stdin
	r, w, _ := os.Pipe()
	os.Stdin = r
	done := make(chan struct{})
	go func() {
		defer close(done)
		_, _ = w.Write(tarBuf.Bytes())
		_ = w.Close()
	}()

	err := Run(ctx, mgr, []string{"create", "stdinarchive"})
	<-done
	os.Stdin = oldStdin
	if err != nil {
		t.Fatalf("create from stdin tar: %v", err)
	}

	rc, err := mgr.ReadActualFile(ctx, "stdinarchive", "stdinarchive.md")
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read marker content: %v", err)
	}
	if !bytes.Equal(got, markerContent) {
		t.Fatalf("expected marker %q, got %q", markerContent, got)
	}

	rc2, err := mgr.ReadActualFile(ctx, "stdinarchive", "extra.txt")
	if err != nil {
		t.Fatalf("read extra: %v", err)
	}
	defer rc2.Close()
	got2, err := io.ReadAll(rc2)
	if err != nil {
		t.Fatalf("read extra content: %v", err)
	}
	if !bytes.Equal(got2, extraContent) {
		t.Fatalf("expected extra %q, got %q", extraContent, got2)
	}
}
