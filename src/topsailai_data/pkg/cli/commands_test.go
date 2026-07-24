package cli

import (
	"archive/tar"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/config"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
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
		CeasedRetentionDays: 30,
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
func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	fn()
	w.Close()
	os.Stdout = old
	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	return buf.String()
}

// buildTarArchive creates a tar archive containing the given files.
func buildTarArchive(t *testing.T, files map[string][]byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	w := tar.NewWriter(&buf)
	for name, data := range files {
		hdr := &tar.Header{
			Name: name,
			Mode: 0o644,
			Size: int64(len(data)),
		}
		if err := w.WriteHeader(hdr); err != nil {
			t.Fatalf("write tar header: %v", err)
		}
		if _, err := w.Write(data); err != nil {
			t.Fatalf("write tar body: %v", err)
		}
	}
	if err := w.Close(); err != nil {
		t.Fatalf("close tar writer: %v", err)
	}
	return buf.Bytes()
}

func TestNoArgsPrintsUsage(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, nil); err != nil {
			t.Fatalf("expected no error when printing usage, got %v", err)
		}
	})

	if !strings.Contains(out, "Usage: topsailai_data") {
		t.Fatalf("expected usage output, got %s", out)
	}
	if !strings.Contains(out, "create") {
		t.Fatalf("expected usage to list commands, got %s", out)
	}
}

func TestCreateAndShow(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "hello", "--classify", "demo", "--tag", "a,b", "--description", "Hello description"}); err != nil {
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
	if !strings.Contains(out, "Description:   Hello description") {
		t.Fatalf("show output missing description: %s", out)
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
		t.Fatalf("get after first delete: %v", err)
	}
	if got.Status != models.ObjectStatusDeleted {
		t.Fatalf("expected status deleted after first delete, got %s", got.Status)
	}

	if err := Run(ctx, mgr, []string{"delete", string(obj.ID)}); err != nil {
		t.Fatalf("finalize delete: %v", err)
	}

	got, err = mgr.GetObject(ctx, obj.ID, true)
	if err != nil {
		t.Fatalf("get after finalize: %v", err)
	}
	if got.Status != models.ObjectStatusCeased {
		t.Fatalf("expected status ceased after second delete, got %s", got.Status)
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

func TestRecoverRestoresDeletedObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "recoverable", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("delete: %v", err)
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

func TestRecoverRejectsNonDeleted(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	cases := []struct {
		name  string
		setup func() (models.ObjectID, error)
	}{
		{
			name: "active",
			setup: func() (models.ObjectID, error) {
				obj, err := mgr.CreateObject(ctx, "active-obj", manager.CreateObjectOptions{})
				if err != nil {
					return "", err
				}
				return obj.ID, nil
			},
		},
		{
			name: "creating",
			setup: func() (models.ObjectID, error) {
				obj, err := mgr.CreateObject(ctx, "creating-obj", manager.CreateObjectOptions{})
				if err != nil {
					return "", err
				}
				metaPath := filepath.Join(mgr.Root(), obj.Path, "metadata.json")
				metaBytes, err := os.ReadFile(metaPath)
				if err != nil {
					return "", err
				}
				metaBytes = bytes.ReplaceAll(metaBytes, []byte(`"active"`), []byte(`"creating"`))
				if err := os.WriteFile(metaPath, metaBytes, 0644); err != nil {
					return "", err
				}
				return obj.ID, nil
			},
		},
		{
			name: "ceased",
			setup: func() (models.ObjectID, error) {
				obj, err := mgr.CreateObject(ctx, "ceased-obj", manager.CreateObjectOptions{})
				if err != nil {
					return "", err
				}
				if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
					return "", err
				}
				if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
					return "", err
				}
				return obj.ID, nil
			},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			id, err := tc.setup()
			if err != nil {
				t.Fatalf("setup: %v", err)
			}
			if err := Run(ctx, mgr, []string{"recover", string(id)}); err == nil {
				t.Fatalf("expected error recovering %s object", tc.name)
			}
		})
	}
}

func TestRecoverRestoresDeletedWithFrom(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "restore-from", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}

	// Write a fresh archive to restore as the object's actual data.
	archivePath := filepath.Join(tmp, "restore.tar")
	if err := os.WriteFile(archivePath, buildTarArchive(t, map[string][]byte{
		"restore-from.md": []byte("restored content"),
	}), 0644); err != nil {
		t.Fatalf("write archive: %v", err)
	}

	if err := Run(ctx, mgr, []string{"recover", string(obj.ID), "--from", archivePath}); err != nil {
		t.Fatalf("recover --from: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get after recover: %v", err)
	}
	if got.Status != models.ObjectStatusActive {
		t.Fatalf("expected status active, got %s", got.Status)
	}
}

func TestRecoverRejectsActiveObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "activeobj"}); err != nil {
		t.Fatalf("create: %v", err)
	}

	err := Run(ctx, mgr, []string{"recover", "activeobj"})
	if err == nil {
		t.Fatalf("expected error recovering active object")
	}
	if !strings.Contains(err.Error(), "already active") {
		t.Fatalf("expected already active error, got %v", err)
	}
}

func TestRecoverRejectsCeasedObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "ceasedobj"}); err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := Run(ctx, mgr, []string{"delete", "ceasedobj"}); err != nil {
		t.Fatalf("delete: %v", err)
	}
	if err := Run(ctx, mgr, []string{"gc", "--status", "deleted"}); err != nil {
		t.Fatalf("gc deleted: %v", err)
	}

	err := Run(ctx, mgr, []string{"recover", "ceasedobj"})
	if err == nil {
		t.Fatalf("expected error recovering ceased object")
	}
	if !strings.Contains(err.Error(), "ceased") {
		t.Fatalf("expected ceased error, got %v", err)
	}
}

func TestRecoverRestoresDeletedWithFromArchive(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "restorearchive"}); err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := Run(ctx, mgr, []string{"delete", "restorearchive"}); err != nil {
		t.Fatalf("delete: %v", err)
	}

	var tarBuf bytes.Buffer
	tw := tar.NewWriter(&tarBuf)
	marker := []byte("restored from archive")
	hdr := &tar.Header{
		Name: "restorearchive.md",
		Mode: 0o644,
		Size: int64(len(marker)),
	}
	if err := tw.WriteHeader(hdr); err != nil {
		t.Fatalf("write header: %v", err)
	}
	if _, err := tw.Write(marker); err != nil {
		t.Fatalf("write body: %v", err)
	}
	if err := tw.Close(); err != nil {
		t.Fatalf("close tar: %v", err)
	}

	archivePath := filepath.Join(t.TempDir(), "restore.tar")
	if err := os.WriteFile(archivePath, tarBuf.Bytes(), 0o644); err != nil {
		t.Fatalf("write archive: %v", err)
	}

	if err := Run(ctx, mgr, []string{"recover", "restorearchive", "--from", archivePath}); err != nil {
		t.Fatalf("recover from archive: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "restorearchive", false)
	if err != nil {
		t.Fatalf("get after recover: %v", err)
	}
	if obj.Status != models.ObjectStatusActive {
		t.Fatalf("expected active, got %s", obj.Status)
	}

	content, err := os.ReadFile(filepath.Join(mgr.Root(), string(obj.Path), "restorearchive.md"))
	if err != nil {
		t.Fatalf("read restored file: %v", err)
	}
	if string(content) != string(marker) {
		t.Fatalf("expected restored content %q, got %q", marker, content)
	}
}

func TestGCStatusDeletedFinalizesObjects(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	// Create and delete an object; first delete transitions to deleted.
	obj, err := mgr.CreateObject(ctx, "stale", manager.CreateObjectOptions{Classify: []string{"demo"}})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("delete: %v", err)
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
func TestGCStatusCeasedDeletesImmediately(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "fresh-ceased", manager.CreateObjectOptions{Classify: []string{"demo"}})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("finalize delete: %v", err)
	}

	// Default gc should keep the ceased object because retention window has not passed.
	if err := Run(ctx, mgr, []string{"gc"}); err != nil {
		t.Fatalf("default gc: %v", err)
	}
	if _, err := mgr.GetObject(ctx, obj.ID, true); err != nil {
		t.Fatalf("ceased object should still exist after default gc: %v", err)
	}

	// Explicit --status ceased must delete immediately, ignoring retention.
	if err := Run(ctx, mgr, []string{"gc", "--status", "ceased"}); err != nil {
		t.Fatalf("gc --status ceased: %v", err)
	}
	if _, err := mgr.GetObject(ctx, obj.ID, true); err == nil {
		t.Fatalf("ceased object should be gone after explicit gc --status ceased")
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
func TestListOutputFormatAndPagination(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	for i := 1; i <= 5; i++ {
		name := fmt.Sprintf("obj%d", i)
		if _, err := mgr.CreateObject(ctx, name, manager.CreateObjectOptions{
			Description: fmt.Sprintf("description%d", i),
			Classify:    []string{"demo"},
			Tags:        []string{fmt.Sprintf("tag%d", i)},
		}); err != nil {
			t.Fatalf("create %s: %v", name, err)
		}
	}

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"list"}); err != nil {
			t.Fatalf("list: %v", err)
		}
	})
	if !strings.Contains(out, "id:") {
		t.Fatalf("list output missing YAML id field: %s", out)
	}
	if !strings.Contains(out, "description: description1") {
		t.Fatalf("list output missing YAML description field: %s", out)
	}
	if !strings.Contains(out, "obj1") || !strings.Contains(out, "obj5") {
		t.Fatalf("list output missing objects: %s", out)
	}
	if strings.Contains(out, "|") {
		t.Fatalf("list output should not use table separators: %s", out)
	}

	// Test offset/limit.
	out = captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"list", "--offset", "1", "--limit", "2"}); err != nil {
			t.Fatalf("list offset/limit: %v", err)
		}
	})
	if !strings.Contains(out, "obj2") || !strings.Contains(out, "obj3") {
		t.Fatalf("offset/limit output missing expected objects: %s", out)
	}
	if strings.Contains(out, "obj1") || strings.Contains(out, "obj5") {
		t.Fatalf("offset/limit output should not contain out-of-range objects: %s", out)
	}
}

func TestListFormatJSON(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if _, err := mgr.CreateObject(ctx, "jsonobj", manager.CreateObjectOptions{
		Description: "JSON description",
		Classify:    []string{"demo"},
		Tags:        []string{"alpha", "beta"},
	}); err != nil {
		t.Fatalf("create: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"list", "--format", "json"}); err != nil {
			t.Fatalf("list json: %v", err)
		}
	})

	var results []map[string]interface{}
	if err := json.Unmarshal([]byte(out), &results); err != nil {
		t.Fatalf("list json output is not valid JSON: %v\n%s", err, out)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result, got %d", len(results))
	}
	if results[0]["id"] != "jsonobj" {
		t.Fatalf("expected id jsonobj, got %v", results[0]["id"])
	}
	if results[0]["name"] != "jsonobj" {
		t.Fatalf("expected name jsonobj, got %v", results[0]["name"])
	}
	if results[0]["description"] != "JSON description" {
		t.Fatalf("expected description JSON description, got %v", results[0]["description"])
	}
	if results[0]["status"] != "active" {
		t.Fatalf("expected status active, got %v", results[0]["status"])
	}
	tags, ok := results[0]["tags"].([]interface{})
	if !ok || len(tags) != 2 {
		t.Fatalf("expected 2 tags, got %v", results[0]["tags"])
	}
}

func TestListEmpty(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"list"}); err != nil {
			t.Fatalf("list: %v", err)
		}
	})

	if strings.Contains(out, "|") {
		t.Fatalf("empty list should not print table: %s", out)
	}
	if strings.TrimSpace(out) != "[]" {
		t.Fatalf("empty list yaml should be [], got %s", out)
	}

	out = captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"list", "--format", "json"}); err != nil {
			t.Fatalf("list json empty: %v", err)
		}
	})
	if strings.TrimSpace(out) != "[]" {
		t.Fatalf("empty list json should be [], got %s", out)
	}
}

func TestShowReadsMarkdownAndTree(t *testing.T) {
	mgr, root, ctx := setupManager(t)

	content := []byte("# Hello\n\nThis is the object content.\n")
	obj, err := mgr.CreateObject(ctx, "hello", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"greeting"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := mgr.WriteActualFile(ctx, obj.ID, "hello.md", bytes.NewReader(content)); err != nil {
		t.Fatalf("put hello.md: %v", err)
	}

	extraContent := []byte("extra data")
	if err := mgr.WriteActualFile(ctx, obj.ID, "extra.txt", bytes.NewReader(extraContent)); err != nil {
		t.Fatalf("put extra.txt: %v", err)
	}

	subDir := filepath.Join(root, obj.Path, "attachments")
	if err := os.MkdirAll(subDir, 0755); err != nil {
		t.Fatalf("mkdir attachments: %v", err)
	}
	if err := os.WriteFile(filepath.Join(subDir, "note.txt"), []byte("note"), 0644); err != nil {
		t.Fatalf("write note.txt: %v", err)
	}

	var buf bytes.Buffer
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	err = Run(ctx, mgr, []string{"show", string(obj.ID)})
	w.Close()
	os.Stdout = old
	if err != nil {
		t.Fatalf("show: %v", err)
	}
	_, _ = buf.ReadFrom(r)
	out := buf.String()

	if !strings.Contains(out, "ID:") || !strings.Contains(out, "hello") {
		t.Fatalf("show output missing metadata: %s", out)
	}
	if !strings.Contains(out, "# Hello") {
		t.Fatalf("show output missing markdown content: %s", out)
	}
	if !strings.Contains(out, "attachments") || !strings.Contains(out, "note.txt") {
		t.Fatalf("show output missing folder structure: %s", out)
	}
}

func TestShowNoExtraFiles(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	content := []byte("# Minimal\n")
	obj, err := mgr.CreateObject(ctx, "minimal", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if err := mgr.WriteActualFile(ctx, obj.ID, "minimal.md", bytes.NewReader(content)); err != nil {
		t.Fatalf("put minimal.md: %v", err)
	}

	var buf bytes.Buffer
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	err = Run(ctx, mgr, []string{"show", string(obj.ID)})
	w.Close()
	os.Stdout = old
	if err != nil {
		t.Fatalf("show: %v", err)
	}
	_, _ = buf.ReadFrom(r)
	out := buf.String()

	if !strings.Contains(out, "# Minimal") {
		t.Fatalf("show output missing markdown content: %s", out)
	}
	if !strings.Contains(out, "no additional files") {
		t.Fatalf("show should indicate no extra files: %s", out)
	}
}

func TestShowCeasedObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "ceasedobj", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"demo-tag"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}
	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("finalize delete: %v", err)
	}

	var buf bytes.Buffer
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	err = Run(ctx, mgr, []string{"show", string(obj.ID)})
	w.Close()
	os.Stdout = old
	if err != nil {
		t.Fatalf("show: %v", err)
	}
	_, _ = buf.ReadFrom(r)
	out := buf.String()

	if !strings.Contains(out, "ID:") || !strings.Contains(out, "ceasedobj") {
		t.Fatalf("show output missing metadata: %s", out)
	}
	if !strings.Contains(out, "Status:        ceased") {
		t.Fatalf("show output missing ceased status: %s", out)
	}
	if !strings.Contains(out, "Actual data unavailable for ceased object") {
		t.Fatalf("show output missing actual-data unavailable note: %s", out)
	}
	if strings.Contains(out, "--- Markdown ---") {
		t.Fatalf("show should not print markdown section for ceased object: %s", out)
	}
	if strings.Contains(out, "--- folder structure ---") {
		t.Fatalf("show should not print folder structure section for ceased object: %s", out)
	}
}

func TestShowDeletedObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "deletedobj", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"demo-tag"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
		t.Fatalf("delete: %v", err)
	}

	var buf bytes.Buffer
	old := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	err = Run(ctx, mgr, []string{"show", string(obj.ID)})
	w.Close()
	os.Stdout = old
	if err != nil {
		t.Fatalf("show: %v", err)
	}
	_, _ = buf.ReadFrom(r)
	out := buf.String()

	if !strings.Contains(out, "ID:") || !strings.Contains(out, "deletedobj") {
		t.Fatalf("show output missing metadata: %s", out)
	}
	if !strings.Contains(out, "Status:        deleted") {
		t.Fatalf("show output missing deleted status: %s", out)
	}
	if !strings.Contains(out, "Actual data unavailable for deleted object") {
		t.Fatalf("show output missing actual-data unavailable note: %s", out)
	}
	if strings.Contains(out, "--- Markdown ---") {
		t.Fatalf("show should not print markdown section for deleted object: %s", out)
	}
	if strings.Contains(out, "--- folder structure ---") {
		t.Fatalf("show should not print folder structure section for deleted object: %s", out)
	}
}

func TestSearchORLogic(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	alpha, err := mgr.CreateObject(ctx, "alpha", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"first"},
	})
	if err != nil {
		t.Fatalf("create alpha: %v", err)
	}

	beta, err := mgr.CreateObject(ctx, "beta", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"second"},
	})
	if err != nil {
		t.Fatalf("create beta: %v", err)
	}

	gamma, err := mgr.CreateObject(ctx, "gamma", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"third"},
	})
	if err != nil {
		t.Fatalf("create gamma: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"search", "alpha|gamma"}); err != nil {
			t.Fatalf("search: %v", err)
		}
	})

	if !strings.Contains(out, string(alpha.ID)) {
		t.Fatalf("search output missing alpha: %s", out)
	}
	if !strings.Contains(out, string(gamma.ID)) {
		t.Fatalf("search output missing gamma: %s", out)
	}
	if strings.Contains(out, string(beta.ID)) {
		t.Fatalf("search output should not contain beta: %s", out)
	}
}

func TestSearchByTagOR(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "tagged", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"alpha", "beta"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"search", "alpha|gamma"}); err != nil {
			t.Fatalf("search: %v", err)
		}
	})

	if !strings.Contains(out, string(obj.ID)) {
		t.Fatalf("search output missing object: %s", out)
	}
}

func TestSearchUnsupportedCharacters(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	cases := []struct {
		query string
		want  string
	}{
		{"foo bar", "spaces or tabs"},
		{"foo\tbar", "spaces or tabs"},
		{`foo\bar`, "backslash escapes"},
		{"foo|", "empty term"},
		{"|foo", "empty term"},
		{"foo||bar", "empty term"},
	}

	for _, tc := range cases {
		err := Run(ctx, mgr, []string{"search", tc.query})
		if err == nil {
			t.Fatalf("search %q: expected error, got nil", tc.query)
		}
		if !strings.Contains(err.Error(), tc.want) {
			t.Fatalf("search %q: expected error to contain %q, got %v", tc.query, tc.want, err)
		}
	}
}

func TestGetArchiveSuccess(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	content := []byte("archive marker")
	obj, err := mgr.CreateObject(ctx, "archobj", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Data:     tarBytes("archobj.md", content),
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	extra := []byte("extra content")
	if err := mgr.WriteActualFile(ctx, obj.ID, "extra.txt", bytes.NewReader(extra)); err != nil {
		t.Fatalf("write extra: %v", err)
	}

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"get-archive", string(obj.ID)}); err != nil {
			t.Fatalf("get-archive: %v", err)
		}
	})

	tr := tar.NewReader(bytes.NewReader([]byte(out)))
	found := map[string][]byte{}
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("read tar: %v", err)
		}
		buf, err := io.ReadAll(tr)
		if err != nil {
			t.Fatalf("read tar entry: %v", err)
		}
		found[hdr.Name] = buf
	}

	if !bytes.Equal(found["archobj.md"], content) {
		t.Fatalf("expected marker %q, got %q", content, found["archobj.md"])
	}
	if !bytes.Equal(found["extra.txt"], extra) {
		t.Fatalf("expected extra %q, got %q", extra, found["extra.txt"])
	}
}

func TestGetArchiveMissingObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"get-archive", "missing"})
	if err == nil {
		t.Fatalf("expected error for missing object")
	}
	if !strings.Contains(err.Error(), "get-archive") {
		t.Fatalf("expected get-archive prefix, got %v", err)
	}
}

func TestPutArchiveSuccess(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "putarch", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	var tarBuf bytes.Buffer
	tw := tar.NewWriter(&tarBuf)
	marker := []byte("replaced marker")
	hdr := &tar.Header{
		Name: "putarch.md",
		Mode: 0o644,
		Size: int64(len(marker)),
	}
	if err := tw.WriteHeader(hdr); err != nil {
		t.Fatalf("write header: %v", err)
	}
	if _, err := tw.Write(marker); err != nil {
		t.Fatalf("write marker: %v", err)
	}
	extra := []byte("new extra")
	hdr2 := &tar.Header{
		Name: "new.txt",
		Mode: 0o644,
		Size: int64(len(extra)),
	}
	if err := tw.WriteHeader(hdr2); err != nil {
		t.Fatalf("write header: %v", err)
	}
	if _, err := tw.Write(extra); err != nil {
		t.Fatalf("write extra: %v", err)
	}
	if err := tw.Close(); err != nil {
		t.Fatalf("close tar: %v", err)
	}

	archivePath := filepath.Join(tmp, "archive.tar")
	if err := os.WriteFile(archivePath, tarBuf.Bytes(), 0644); err != nil {
		t.Fatalf("write archive: %v", err)
	}

	if err := Run(ctx, mgr, []string{"put-archive", string(obj.ID), archivePath}); err != nil {
		t.Fatalf("put-archive: %v", err)
	}

	rc, err := mgr.ReadActualFile(ctx, obj.ID, "putarch.md")
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read marker content: %v", err)
	}
	if !bytes.Equal(got, marker) {
		t.Fatalf("expected marker %q, got %q", marker, got)
	}

	rc2, err := mgr.ReadActualFile(ctx, obj.ID, "new.txt")
	if err != nil {
		t.Fatalf("read new.txt: %v", err)
	}
	defer rc2.Close()
	got2, err := io.ReadAll(rc2)
	if err != nil {
		t.Fatalf("read new.txt content: %v", err)
	}
	if !bytes.Equal(got2, extra) {
		t.Fatalf("expected extra %q, got %q", extra, got2)
	}
}

func TestPutArchiveMissingFile(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"put-archive", "missing", "/nonexistent/archive.tar"})
	if err == nil {
		t.Fatalf("expected error for missing archive file")
	}
	if !strings.Contains(err.Error(), "put-archive") {
		t.Fatalf("expected put-archive prefix, got %v", err)
	}
}

func TestPutArchiveMissingObject(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	archivePath := filepath.Join(tmp, "archive.tar")
	if err := os.WriteFile(archivePath, []byte("not a tar"), 0644); err != nil {
		t.Fatalf("write archive: %v", err)
	}

	err := Run(ctx, mgr, []string{"put-archive", "missing", archivePath})
	if err == nil {
		t.Fatalf("expected error for missing object")
	}
}

func TestTagRemoveSuccess(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "tagged", manager.CreateObjectOptions{
		Classify: []string{"demo"},
		Tags:     []string{"alpha", "beta"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := Run(ctx, mgr, []string{"tag", "remove", string(obj.ID), "alpha"}); err != nil {
		t.Fatalf("tag remove: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if len(got.Tags) != 1 || got.Tags[0] != "beta" {
		t.Fatalf("expected tags [beta], got %v", got.Tags)
	}
}

func TestTagRemoveInheritedTagBlocked(t *testing.T) {
	mgr, root, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "inhtest", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	// Create a classify tag file that applies to all objects under the demo/
	// classify directory on the object's actual path.
	classifyDir := filepath.Join(root, obj.Path, "..")
	classifyDir = filepath.Clean(classifyDir)
	if err := os.WriteFile(filepath.Join(classifyDir, "demo.tags"), []byte("inherited\n"), 0644); err != nil {
		t.Fatalf("write classify tags: %v", err)
	}

	got, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if len(got.Tags) != 1 || got.Tags[0] != "inherited" {
		t.Fatalf("expected inherited tag, got %v", got.Tags)
	}

	err = Run(ctx, mgr, []string{"tag", "remove", string(obj.ID), "inherited"})
	if err == nil {
		t.Fatalf("expected error removing inherited tag")
	}
}

func TestTagRemoveMissingTag(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	obj, err := mgr.CreateObject(ctx, "notag", manager.CreateObjectOptions{
		Classify: []string{"demo"},
	})
	if err != nil {
		t.Fatalf("create: %v", err)
	}

	err = Run(ctx, mgr, []string{"tag", "remove", string(obj.ID), "missing"})
	if err == nil {
		t.Fatalf("expected error removing non-existent tag")
	}
}

func TestTagUnknownSubcommand(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"tag", "unknown", "obj", "tag"})
	if err == nil {
		t.Fatalf("expected error for unknown tag subcommand")
	}
	if !strings.Contains(err.Error(), "unknown subcommand") {
		t.Fatalf("expected unknown subcommand error, got %v", err)
	}
}

func TestUnknownCommand(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"unknown"})
	if err == nil {
		t.Fatalf("expected error for unknown command")
	}
	if !strings.Contains(err.Error(), "unknown command") {
		t.Fatalf("expected unknown command error, got %v", err)
	}
}

func TestHelpPrintsUsage(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	out := captureStdout(t, func() {
		if err := Run(ctx, mgr, []string{"help"}); err != nil {
			t.Fatalf("help: %v", err)
		}
	})

	if !strings.Contains(out, "Usage: topsailai_data") {
		t.Fatalf("help output missing usage: %s", out)
	}
	if !strings.Contains(out, "create") {
		t.Fatalf("help output missing commands: %s", out)
	}
}

func TestInvalidListFormat(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"list", "--format", "table"})
	if err == nil {
		t.Fatalf("expected error for invalid list format")
	}
	if !strings.Contains(err.Error(), "unsupported format") {
		t.Fatalf("expected unsupported format error, got %v", err)
	}
}

func TestInvalidSearchFormat(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"search", "query", "--format", "xml"})
	if err == nil {
		t.Fatalf("expected error for invalid search format")
	}
}

func TestMissingRequiredArgs(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	cases := []struct {
		args []string
		want string
	}{
		{[]string{"create"}, "expected at least"},
		{[]string{"show"}, "expected"},
		{[]string{"get"}, "expected"},
		{[]string{"put"}, "expected"},
		{[]string{"move"}, "expected"},
		{[]string{"delete"}, "expected"},
		{[]string{"recover"}, "expected"},
		{[]string{"tag"}, "expected"},
		{[]string{"tag", "add"}, "expected"},
		{[]string{"put-archive"}, "expected"},
	}

	for _, tc := range cases {
		err := Run(ctx, mgr, tc.args)
		if err == nil {
			t.Fatalf("%v: expected error", tc.args)
		}
		if !strings.Contains(err.Error(), tc.want) {
			t.Fatalf("%v: expected error to contain %q, got %v", tc.args, tc.want, err)
		}
	}
}

func TestGetMissingObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"get", "missing", "file.txt"})
	if err == nil {
		t.Fatalf("expected error for missing object")
	}
	if !strings.Contains(err.Error(), "get:") {
		t.Fatalf("expected get prefix, got %v", err)
	}
}

func TestDeleteMissingObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"delete", "missing"})
	if err == nil {
		t.Fatalf("expected error for missing object")
	}
	if !strings.Contains(err.Error(), "delete:") {
		t.Fatalf("expected delete prefix, got %v", err)
	}
}

func TestShowMissingObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"show", "missing"})
	if err == nil {
		t.Fatalf("expected error for missing object")
	}
	if !strings.Contains(err.Error(), "show:") {
		t.Fatalf("expected show prefix, got %v", err)
	}
}

func TestMoveMissingObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"move", "missing", "new"})
	if err == nil {
		t.Fatalf("expected error for missing object")
	}
	if !strings.Contains(err.Error(), "move:") {
		t.Fatalf("expected move prefix, got %v", err)
	}
}

func TestGCInvalidStatus(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"gc", "--status", "active"})
	if err == nil {
		t.Fatalf("expected error for invalid gc status")
	}
	if !strings.Contains(err.Error(), "invalid status") {
		t.Fatalf("expected invalid status error, got %v", err)
	}
}

func TestRecoverMissingObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"recover", "missing"})
	if err == nil {
		t.Fatalf("expected error for missing object")
	}
	if !strings.Contains(err.Error(), "recover:") {
		t.Fatalf("expected recover prefix, got %v", err)
	}
}

func TestCreateInvalidName(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	err := Run(ctx, mgr, []string{"create", "../escape"})
	if err == nil {
		t.Fatalf("expected error for invalid object name")
	}
}

func TestListTagFlagFilters(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "alpha-obj", "--tag", "alpha"}); err != nil {
		t.Fatalf("create alpha-obj: %v", err)
	}
	if err := Run(ctx, mgr, []string{"create", "beta-obj", "--tag", "beta"}); err != nil {
		t.Fatalf("create beta-obj: %v", err)
	}

	var buf bytes.Buffer
	orig := os.Stdout
	r, w, _ := os.Pipe()
	os.Stdout = w
	errCh := make(chan error, 1)
	go func() {
		_, err := io.Copy(&buf, r)
		errCh <- err
	}()

	err := Run(ctx, mgr, []string{"list", "--tag", "alpha", "--format", "json"})

	w.Close()
	os.Stdout = orig
	if copyErr := <-errCh; copyErr != nil {
		t.Fatalf("copy stdout: %v", copyErr)
	}
	if err != nil {
		t.Fatalf("list --tag alpha: %v", err)
	}

	var results []map[string]any
	if err := json.Unmarshal(buf.Bytes(), &results); err != nil {
		t.Fatalf("unmarshal list output: %v\noutput: %s", err, buf.String())
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result for tag alpha, got %d", len(results))
	}
	if results[0]["id"] != "alpha-obj" {
		t.Fatalf("expected alpha-obj, got %v", results[0]["id"])
	}
}

func TestUpdateDescriptionActiveObject(t *testing.T) {
	mgr, _, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "updatable"}); err != nil {
		t.Fatalf("create: %v", err)
	}

	if err := Run(ctx, mgr, []string{"update", "updatable", "--description", "new description"}); err != nil {
		t.Fatalf("update: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "updatable", false)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if obj.Description != "new description" {
		t.Fatalf("expected description %q, got %q", "new description", obj.Description)
	}
}

func TestUpdateDescriptionClearWithEmptyString(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	// Create the object from a plain file that contains YAML frontmatter with a
	// description. The CLI wraps the file content as {name}.md.
	src := filepath.Join(tmp, "with-frontmatter.md")
	content := []byte("---\ndescription: from frontmatter\n---\n\nbody\n")
	if err := os.WriteFile(src, content, 0o644); err != nil {
		t.Fatalf("write source: %v", err)
	}

	if err := Run(ctx, mgr, []string{"create", "frontmatter-obj", "--from", src}); err != nil {
		t.Fatalf("create: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "frontmatter-obj", false)
	if err != nil {
		t.Fatalf("get after create: %v", err)
	}
	if obj.Description != "from frontmatter" {
		t.Fatalf("expected frontmatter description, got %q", obj.Description)
	}

	if err := Run(ctx, mgr, []string{"update", "frontmatter-obj", "--description", ""}); err != nil {
		t.Fatalf("update with empty description: %v", err)
	}

	obj, err = mgr.GetObject(ctx, "frontmatter-obj", false)
	if err != nil {
		t.Fatalf("get after update: %v", err)
	}
	if obj.Description != "" {
		t.Fatalf("expected empty description, got %q", obj.Description)
	}
}

func TestUpdateDescriptionRejectsNonActive(t *testing.T) {
	cases := []struct {
		name       string
		deleteRuns int
	}{
		{name: "deleted", deleteRuns: 1},
		{name: "ceased", deleteRuns: 2},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mgr, _, ctx := setupManager(t)
			id := tc.name + "-cli-update-obj"

			if err := Run(ctx, mgr, []string{"create", id}); err != nil {
				t.Fatalf("create: %v", err)
			}
			for i := 0; i < tc.deleteRuns; i++ {
				if err := Run(ctx, mgr, []string{"delete", id}); err != nil {
					t.Fatalf("delete run %d: %v", i+1, err)
				}
			}

			err := Run(ctx, mgr, []string{"update", id, "--description", "should fail"})
			if !errors.Is(err, apperrors.ErrObjectNotActive) {
				t.Fatalf("expected ErrObjectNotActive, got %v", err)
			}
		})
	}
}

func TestCreateFromObjectMDFile(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	content := []byte("# Hello from object.md\n\nThis is the marker content.\n")
	src := filepath.Join(tmp, "hello.md")
	if err := os.WriteFile(src, content, 0o644); err != nil {
		t.Fatalf("write source: %v", err)
	}

	if err := Run(ctx, mgr, []string{"create", "hello", "--from", src}); err != nil {
		t.Fatalf("create from object.md: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "hello", false)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if obj.Status != models.ObjectStatusActive {
		t.Fatalf("expected status active, got %s", obj.Status)
	}

	rc, err := mgr.ReadActualFile(ctx, "hello", "hello.md")
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read marker content: %v", err)
	}
	if !bytes.Equal(got, content) {
		t.Fatalf("expected marker %q, got %q", content, got)
	}
}

func TestCreateFromObjectMDFileWithFrontmatter(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	content := []byte("---\ndescription: from frontmatter\n---\n\nbody\n")
	src := filepath.Join(tmp, "front.md")
	if err := os.WriteFile(src, content, 0o644); err != nil {
		t.Fatalf("write source: %v", err)
	}

	if err := Run(ctx, mgr, []string{"create", "front", "--from", src}); err != nil {
		t.Fatalf("create from object.md with frontmatter: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "front", false)
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	if obj.Description != "from frontmatter" {
		t.Fatalf("expected frontmatter description, got %q", obj.Description)
	}

	rc, err := mgr.ReadActualFile(ctx, "front", "front.md")
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read marker content: %v", err)
	}
	if !bytes.Equal(got, content) {
		t.Fatalf("expected marker %q, got %q", content, got)
	}
}

func TestPutObjectMDFile(t *testing.T) {
	mgr, tmp, ctx := setupManager(t)

	if err := Run(ctx, mgr, []string{"create", "note"}); err != nil {
		t.Fatalf("create: %v", err)
	}

	content := []byte("# Updated marker\n")
	src := filepath.Join(tmp, "note.md")
	if err := os.WriteFile(src, content, 0o644); err != nil {
		t.Fatalf("write source: %v", err)
	}

	if err := Run(ctx, mgr, []string{"put", "note", "note.md", "--from", src}); err != nil {
		t.Fatalf("put object.md: %v", err)
	}

	rc, err := mgr.ReadActualFile(ctx, "note", "note.md")
	if err != nil {
		t.Fatalf("read marker: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read marker content: %v", err)
	}
	if !bytes.Equal(got, content) {
		t.Fatalf("expected marker %q, got %q", content, got)
	}
}
