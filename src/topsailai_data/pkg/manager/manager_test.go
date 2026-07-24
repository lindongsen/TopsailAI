package manager

import (
	"archive/tar"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters"
	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/config"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

func newTestManager(t *testing.T) *Manager {
	t.Helper()
	root := t.TempDir()
	cfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
		LogLevel:            "INFO",
		AdapterConfig:       map[string]string{},
	}
	mgr, err := New(cfg)
	if err != nil {
		t.Fatalf("new manager: %v", err)
	}
	t.Cleanup(func() { _ = mgr.Close() })
	return mgr
}

func TestNew(t *testing.T) {
	t.Run("nil config", func(t *testing.T) {
		_, err := New(nil)
		if err == nil {
			t.Fatal("expected error for nil config")
		}
	})

	t.Run("unknown metadata adapter", func(t *testing.T) {
		cfg := &config.Config{
			Root:                t.TempDir(),
			MetadataAdapter:     "unknown",
			ActualDataAdapter:   "local",
			CeasedRetentionDays: 30,
		}
		_, err := New(cfg)
		if err == nil {
			t.Fatal("expected error for unknown metadata adapter")
		}
	})

	t.Run("unknown actual-data adapter", func(t *testing.T) {
		cfg := &config.Config{
			Root:                t.TempDir(),
			MetadataAdapter:     "local",
			ActualDataAdapter:   "unknown",
			CeasedRetentionDays: 30,
		}
		_, err := New(cfg)
		if err == nil {
			t.Fatal("expected error for unknown actual-data adapter")
		}
	})

	t.Run("local adapter requires root", func(t *testing.T) {
		cfg := &config.Config{
			Root:                "",
			MetadataAdapter:     "local",
			ActualDataAdapter:   "local",
			CeasedRetentionDays: 30,
		}
		_, err := New(cfg)
		if err == nil {
			t.Fatal("expected error when local adapter root is empty")
		}
	})
}

func TestCreateObject(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	obj, err := mgr.CreateObject(ctx, "hello", CreateObjectOptions{Tags: []string{"demo"}})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if obj.Name != "hello" {
		t.Fatalf("expected name hello, got %q", obj.Name)
	}
	if obj.Status != models.ObjectStatusActive {
		t.Fatalf("expected status active, got %q", obj.Status)
	}
	if !hasTag(obj.Tags, "demo") {
		t.Fatalf("expected tag demo, got %v", obj.Tags)
	}

	// Duplicate creation should fail.
	_, err = mgr.CreateObject(ctx, "hello", CreateObjectOptions{})
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("expected ErrObjectExists, got %v", err)
	}
}

func TestCreateObjectInvalidName(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	_, err := mgr.CreateObject(ctx, "", CreateObjectOptions{})
	if err == nil {
		t.Fatal("expected error for empty name")
	}
}

func TestCreateObjectOverCeased(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "reuse", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "reuse"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}
	// First delete transitions active -> deleted; finalize to ceased so the
	// recreate path can purge it.
	if err := mgr.DeleteObject(ctx, "reuse"); err != nil {
		t.Fatalf("DeleteObject finalize failed: %v", err)
	}

	// Creating over a ceased object should purge it and succeed.
	obj, err := mgr.CreateObject(ctx, "reuse", CreateObjectOptions{Tags: []string{"new"}})
	if err != nil {
		t.Fatalf("CreateObject over ceased failed: %v", err)
	}
	if !hasTag(obj.Tags, "new") {
		t.Fatalf("expected new tag after recreate, got %v", obj.Tags)
	}
}

func TestGetObject(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "hello", CreateObjectOptions{Tags: []string{"demo"}}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "hello", false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}
	if obj.Name != "hello" {
		t.Fatalf("expected name hello, got %q", obj.Name)
	}

	_, err = mgr.GetObject(ctx, "missing", false)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

func TestGetObjectWithReadLock(t *testing.T) {
	root := t.TempDir()
	createCfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
		LogLevel:            "INFO",
		ReadLock:            false,
		AdapterConfig:       map[string]string{},
	}
	createMgr, err := New(createCfg)
	if err != nil {
		t.Fatalf("new create manager: %v", err)
	}
	t.Cleanup(func() { _ = createMgr.Close() })

	ctx := context.Background()
	if _, err := createMgr.CreateObject(ctx, "locked", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := createMgr.Close(); err != nil {
		t.Fatalf("close create manager: %v", err)
	}

	readCfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
		LogLevel:            "INFO",
		ReadLock:            true,
		AdapterConfig:       map[string]string{},
	}
	readMgr, err := New(readCfg)
	if err != nil {
		t.Fatalf("new read manager: %v", err)
	}
	t.Cleanup(func() { _ = readMgr.Close() })

	obj, err := readMgr.GetObject(ctx, "locked", false)
	if err != nil {
		t.Fatalf("GetObject with read lock failed: %v", err)
	}
	if obj.Name != "locked" {
		t.Fatalf("expected name locked, got %q", obj.Name)
	}
}

func TestListObjects(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	for _, name := range []string{"alpha", "beta", "gamma"} {
		if _, err := mgr.CreateObject(ctx, name, CreateObjectOptions{Tags: []string{"shared", name}}); err != nil {
			t.Fatalf("CreateObject %s failed: %v", name, err)
		}
	}

	all, err := mgr.ListObjects(ctx, models.ListOptions{})
	if err != nil {
		t.Fatalf("ListObjects failed: %v", err)
	}
	if len(all) != 3 {
		t.Fatalf("expected 3 objects, got %d", len(all))
	}

	filtered, err := mgr.ListObjects(ctx, models.ListOptions{Tags: []string{"beta"}})
	if err != nil {
		t.Fatalf("ListObjects with tag failed: %v", err)
	}
	if len(filtered) != 1 || filtered[0].Name != "beta" {
		t.Fatalf("expected 1 beta object, got %v", filtered)
	}

	paginated, err := mgr.ListObjects(ctx, models.ListOptions{Offset: 1, Limit: 1})
	if err != nil {
		t.Fatalf("ListObjects pagination failed: %v", err)
	}
	if len(paginated) != 1 {
		t.Fatalf("expected 1 object with offset 1 limit 1, got %d", len(paginated))
	}
}

func TestSearchObjects(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	for _, name := range []string{"hello-world", "goodbye", "archive"} {
		if _, err := mgr.CreateObject(ctx, name, CreateObjectOptions{Tags: []string{"demo"}}); err != nil {
			t.Fatalf("CreateObject %s failed: %v", name, err)
		}
	}

	results, err := mgr.SearchObjects(ctx, []string{"hello"}, models.ListOptions{})
	if err != nil {
		t.Fatalf("SearchObjects failed: %v", err)
	}
	if len(results) != 1 || results[0].Name != "hello-world" {
		t.Fatalf("expected hello-world, got %v", results)
	}

	results, err = mgr.SearchObjects(ctx, []string{"hello", "arch"}, models.ListOptions{})
	if err != nil {
		t.Fatalf("SearchObjects OR failed: %v", err)
	}
	if len(results) != 2 {
		t.Fatalf("expected 2 results, got %d", len(results))
	}
}

func TestUpdateActualData(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	archive := buildTarArchive(t, map[string][]byte{
		"obj.md":    []byte("updated"),
		"extra.txt": []byte("extra data"),
	})

	if err := mgr.UpdateActualData(ctx, "obj", bytes.NewReader(archive)); err != nil {
		t.Fatalf("UpdateActualData failed: %v", err)
	}

	rc, err := mgr.ReadActualFile(ctx, "obj", "extra.txt")
	if err != nil {
		t.Fatalf("ReadActualFile failed: %v", err)
	}
	defer rc.Close()
	data, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read failed: %v", err)
	}
	if string(data) != "extra data" {
		t.Fatalf("expected extra data, got %q", string(data))
	}
}

func TestWriteAndReadActualFile(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	payload := []byte("binary\x00data")
	if err := mgr.WriteActualFile(ctx, "obj", "bin.dat", bytes.NewReader(payload)); err != nil {
		t.Fatalf("WriteActualFile failed: %v", err)
	}

	rc, err := mgr.ReadActualFile(ctx, "obj", "bin.dat")
	if err != nil {
		t.Fatalf("ReadActualFile failed: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read failed: %v", err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatalf("expected %q, got %q", payload, got)
	}
}

func TestReadActualFileWithReadLock(t *testing.T) {
	root := t.TempDir()
	createCfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
		LogLevel:            "INFO",
		ReadLock:            false,
		AdapterConfig:       map[string]string{},
	}
	createMgr, err := New(createCfg)
	if err != nil {
		t.Fatalf("new create manager: %v", err)
	}
	t.Cleanup(func() { _ = createMgr.Close() })

	ctx := context.Background()
	if _, err := createMgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := createMgr.WriteActualFile(ctx, "obj", "note.txt", strings.NewReader("hello")); err != nil {
		t.Fatalf("WriteActualFile failed: %v", err)
	}
	if err := createMgr.Close(); err != nil {
		t.Fatalf("close create manager: %v", err)
	}

	readCfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
		LogLevel:            "INFO",
		ReadLock:            true,
		AdapterConfig:       map[string]string{},
	}
	readMgr, err := New(readCfg)
	if err != nil {
		t.Fatalf("new read manager: %v", err)
	}
	t.Cleanup(func() { _ = readMgr.Close() })

	rc, err := readMgr.ReadActualFile(ctx, "obj", "note.txt")
	if err != nil {
		t.Fatalf("ReadActualFile with read lock failed: %v", err)
	}
	data, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read failed: %v", err)
	}
	if err := rc.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}
	if string(data) != "hello" {
		t.Fatalf("expected hello, got %q", string(data))
	}
}

func TestReadActualArchive(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.WriteActualFile(ctx, "obj", "note.txt", strings.NewReader("hello")); err != nil {
		t.Fatalf("WriteActualFile failed: %v", err)
	}

	rc, err := mgr.ReadActualArchive(ctx, "obj")
	if err != nil {
		t.Fatalf("ReadActualArchive failed: %v", err)
	}
	defer rc.Close()

	tr := tar.NewReader(rc)
	found := false
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("read tar header: %v", err)
		}
		if hdr.Name == "note.txt" {
			found = true
		}
	}
	if !found {
		t.Fatal("note.txt not found in archive")
	}
}

func TestReadActualArchiveWithReadLock(t *testing.T) {
	root := t.TempDir()
	createCfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
		LogLevel:            "INFO",
		ReadLock:            false,
		AdapterConfig:       map[string]string{},
	}
	createMgr, err := New(createCfg)
	if err != nil {
		t.Fatalf("new create manager: %v", err)
	}
	t.Cleanup(func() { _ = createMgr.Close() })

	ctx := context.Background()
	if _, err := createMgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := createMgr.WriteActualFile(ctx, "obj", "note.txt", strings.NewReader("hello")); err != nil {
		t.Fatalf("WriteActualFile failed: %v", err)
	}
	if err := createMgr.Close(); err != nil {
		t.Fatalf("close create manager: %v", err)
	}

	readCfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
		LogLevel:            "INFO",
		ReadLock:            true,
		AdapterConfig:       map[string]string{},
	}
	readMgr, err := New(readCfg)
	if err != nil {
		t.Fatalf("new read manager: %v", err)
	}
	t.Cleanup(func() { _ = readMgr.Close() })

	rc, err := readMgr.ReadActualArchive(ctx, "obj")
	if err != nil {
		t.Fatalf("ReadActualArchive with read lock failed: %v", err)
	}
	tr := tar.NewReader(rc)
	found := false
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("read tar header: %v", err)
		}
		if hdr.Name == "note.txt" {
			found = true
		}
	}
	if err := rc.Close(); err != nil {
		t.Fatalf("close failed: %v", err)
	}
	if !found {
		t.Fatal("note.txt not found in archive")
	}
}

func TestDeleteObject(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	if err := mgr.DeleteObject(ctx, "obj"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}

	_, err := mgr.GetObject(ctx, "obj", false)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound after delete, got %v", err)
	}

	obj, err := mgr.GetObject(ctx, "obj", true)
	if err != nil {
		t.Fatalf("GetObject include-deleted failed: %v", err)
	}
	if obj.Status != models.ObjectStatusDeleted {
		t.Fatalf("expected status deleted, got %q", obj.Status)
	}
}

func TestDeleteObjectFinalize(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "obj"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "obj"); err != nil {
		t.Fatalf("DeleteObject finalize failed: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "obj", true)
	if err != nil {
		t.Fatalf("GetObject include-deleted failed: %v", err)
	}
	if obj.Status != models.ObjectStatusCeased {
		t.Fatalf("expected status ceased, got %q", obj.Status)
	}
}

func TestDeleteObjectRetry(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "obj"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "obj"); err != nil {
		t.Fatalf("DeleteObject finalize failed: %v", err)
	}

	// Re-deleting a ceased object should return not found.
	err := mgr.DeleteObject(ctx, "obj")
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound re-deleting ceased object, got %v", err)
	}
}

func TestDeleteObjectCreating(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	now := time.Now()
	objectPath := buildObjectPathForTest(t, now, nil, "creating")
	objectDir := filepath.Join(mgr.Root(), objectPath)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("mkdir object dir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, "creating.md"), []byte("data"), 0o644); err != nil {
		t.Fatalf("write creating.md failed: %v", err)
	}

	if err := mgr.meta.Create(ctx, &models.Object{
		ID:        "creating",
		Name:      "creating",
		Path:      objectPath,
		Status:    models.ObjectStatusCreating,
		CreatedAt: now,
		UpdatedAt: now,
		DataRef:   objectDir,
	}); err != nil {
		t.Fatalf("Create metadata failed: %v", err)
	}

	err := mgr.DeleteObject(ctx, "creating")
	if err == nil {
		t.Fatal("expected error deleting creating object")
	}
	if !errors.Is(err, apperrors.ErrObjectNotActive) {
		t.Fatalf("expected ErrObjectNotActive, got %v", err)
	}
}

func TestMoveObject(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	if err := mgr.MoveObject(ctx, "obj", []string{"archive"}); err != nil {
		t.Fatalf("MoveObject failed: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "obj", false)
	if err != nil {
		t.Fatalf("GetObject after move failed: %v", err)
	}
	if !strings.Contains(obj.Path, "archive") {
		t.Fatalf("expected path to contain archive, got %q", obj.Path)
	}
	if obj.Name != "obj" {
		t.Fatalf("expected name to remain obj, got %q", obj.Name)
	}
}

func TestMoveObjectDepthExceeded(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	// Time prefix (3) + object (1) + 8 classify = 12 (exceeds 11).
	classify := []string{"a", "b", "c", "d", "e", "f", "g", "h"}
	err := mgr.MoveObject(ctx, "obj", classify)
	if err == nil {
		t.Fatal("expected depth-exceeded error")
	}
	if !errors.Is(err, apperrors.ErrDepthExceeded) {
		t.Fatalf("expected ErrDepthExceeded, got %v", err)
	}
}

func TestMoveObjectSamePath(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	objBefore, err := mgr.GetObject(ctx, "obj", false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}

	if err := mgr.MoveObject(ctx, "obj", nil); err != nil {
		t.Fatalf("MoveObject to same path failed: %v", err)
	}

	objAfter, err := mgr.GetObject(ctx, "obj", false)
	if err != nil {
		t.Fatalf("GetObject after move failed: %v", err)
	}
	if objAfter.Path != objBefore.Path {
		t.Fatalf("path changed unexpectedly: %q -> %q", objBefore.Path, objAfter.Path)
	}
}

func TestAddAndRemoveTag(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{Classify: []string{"classify"}}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	if err := mgr.AddTag(ctx, "obj", "new-tag"); err != nil {
		t.Fatalf("AddTag failed: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "obj", false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}
	if !hasTag(obj.Tags, "new-tag") {
		t.Fatalf("expected tag new-tag, got %v", obj.Tags)
	}

	if err := mgr.RemoveTag(ctx, "obj", "new-tag"); err != nil {
		t.Fatalf("RemoveTag failed: %v", err)
	}

	obj, err = mgr.GetObject(ctx, "obj", false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}
	if hasTag(obj.Tags, "new-tag") {
		t.Fatalf("expected tag new-tag to be removed, got %v", obj.Tags)
	}
}

func TestAddTagInvalid(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	err := mgr.AddTag(ctx, "obj", "bad/tag")
	if err == nil {
		t.Fatal("expected error for invalid tag")
	}
	if !errors.Is(err, apperrors.ErrInvalidTag) {
		t.Fatalf("expected ErrInvalidTag, got %v", err)
	}
}

func TestRemoveTagInvalid(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	err := mgr.RemoveTag(ctx, "obj", "bad/tag")
	if err == nil {
		t.Fatal("expected error for invalid tag")
	}
	if !errors.Is(err, apperrors.ErrInvalidTag) {
		t.Fatalf("expected ErrInvalidTag, got %v", err)
	}
}

func TestRemoveInheritedTagFails(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	// Create classify tag at the time prefix that will be used by the object.
	now := time.Now()
	classifyTagPath := filepath.Join(mgr.Root(), local.TimePath(now))
	if err := os.MkdirAll(classifyTagPath, 0o755); err != nil {
		t.Fatalf("mkdir classify path: %v", err)
	}
	if err := os.WriteFile(filepath.Join(classifyTagPath, filepath.Base(classifyTagPath)+".tags"), []byte("inherited\n"), 0o644); err != nil {
		t.Fatalf("write classify tags: %v", err)
	}

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	obj, err := mgr.GetObject(ctx, "obj", false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}
	if !hasTag(obj.Tags, "inherited") {
		t.Fatalf("expected inherited tag, got %v", obj.Tags)
	}

	err = mgr.RemoveTag(ctx, "obj", "inherited")
	if err == nil {
		t.Fatal("expected error removing inherited tag")
	}
	if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument, got %v", err)
	}
}
func TestRestoreObject(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	obj, err := mgr.CreateObject(ctx, "restore-me", CreateObjectOptions{})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "restore-me"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}

	// Object is deleted but actual data still exists because DeleteObject only
	// marks it deleted on the first call.
	if err := mgr.RestoreObject(ctx, models.ObjectID("restore-me"), nil); err != nil {
		t.Fatalf("RestoreObject failed: %v", err)
	}

	restored, err := mgr.GetObject(ctx, "restore-me", false)
	if err != nil {
		t.Fatalf("GetObject after restore failed: %v", err)
	}
	if restored.Status != models.ObjectStatusActive {
		t.Fatalf("expected status active, got %q", restored.Status)
	}
	if restored.Path != obj.Path {
		t.Fatalf("expected path %q after restore, got %q", obj.Path, restored.Path)
	}
}
func TestUpdateObject(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	obj, err := mgr.CreateObject(ctx, "update-desc", CreateObjectOptions{Description: "initial"})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if obj.Description != "initial" {
		t.Fatalf("expected initial description, got %q", obj.Description)
	}

	newDesc := "updated"
	updated, err := mgr.UpdateObject(ctx, "update-desc", UpdateObjectOptions{Description: &newDesc})
	if err != nil {
		t.Fatalf("UpdateObject failed: %v", err)
	}
	if updated.Description != "updated" {
		t.Fatalf("expected updated description, got %q", updated.Description)
	}

	got, err := mgr.GetObject(ctx, "update-desc", false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}
	if got.Description != "updated" {
		t.Fatalf("expected persisted updated description, got %q", got.Description)
	}
}

func TestUpdateObjectClearsDescription(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "yaml-clear", CreateObjectOptions{
		Description: "initial",
	}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	frontmatter := "---\ndescription: yaml desc\n---\nbody\n"
	if err := mgr.WriteActualFile(ctx, "yaml-clear", "yaml-clear.md", strings.NewReader(frontmatter)); err != nil {
		t.Fatalf("WriteActualFile failed: %v", err)
	}

	empty := ""
	updated, err := mgr.UpdateObject(ctx, "yaml-clear", UpdateObjectOptions{Description: &empty})
	if err != nil {
		t.Fatalf("UpdateObject failed: %v", err)
	}
	if updated.Description != "" {
		t.Fatalf("expected empty description, got %q", updated.Description)
	}

	got, err := mgr.GetObject(ctx, "yaml-clear", false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}
	if got.Description != "" {
		t.Fatalf("expected persisted empty description, got %q", got.Description)
	}
}

func TestUpdateObjectRejectsNonActive(t *testing.T) {
	cases := []struct {
		name       string
		deleteRuns int
	}{
		{name: "deleted", deleteRuns: 1},
		{name: "ceased", deleteRuns: 2},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			mgr := newTestManager(t)
			ctx := context.Background()
			id := models.ObjectID(tc.name + "-update-obj")

			if _, err := mgr.CreateObject(ctx, string(id), CreateObjectOptions{}); err != nil {
				t.Fatalf("CreateObject failed: %v", err)
			}
			for i := 0; i < tc.deleteRuns; i++ {
				if err := mgr.DeleteObject(ctx, id); err != nil {
					t.Fatalf("DeleteObject run %d failed: %v", i+1, err)
				}
			}

			desc := "should fail"
			_, err := mgr.UpdateObject(ctx, id, UpdateObjectOptions{Description: &desc})
			if !errors.Is(err, apperrors.ErrObjectNotActive) {
				t.Fatalf("expected ErrObjectNotActive, got %v", err)
			}
		})
	}
}

func TestExtractDescriptionFromMarkdown(t *testing.T) {
	cases := []struct {
		name     string
		content  string
		expected string
	}{
		{
			name:     "valid frontmatter",
			content:  "---\ndescription: yaml desc\n---\nbody\n",
			expected: "yaml desc",
		},
		{
			name:     "missing frontmatter",
			content:  "# heading\nbody\n",
			expected: "",
		},
		{
			name:     "malformed yaml",
			content:  "---\ndescription: [unclosed\n---\nbody\n",
			expected: "",
		},
		{
			name:     "missing description key",
			content:  "---\ntitle: note\n---\nbody\n",
			expected: "",
		},
		{
			name:     "non-string description",
			content:  "---\ndescription: 123\n---\nbody\n",
			expected: "",
		},
		{
			name:     "empty file",
			content:  "",
			expected: "",
		},
		{
			name:     "crlf line endings",
			content:  "---\r\ndescription: crlf desc\r\n---\r\nbody\r\n",
			expected: "crlf desc",
		},
		{
			name:     "closing delimiter must occupy complete line",
			content:  "---\ndescription: invalid delimiter\n---invalid\nbody\n",
			expected: "",
		},
		{
			name:     "closing delimiter at eof",
			content:  "---\ndescription: eof delimiter\n---",
			expected: "eof delimiter",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			tmp := t.TempDir()
			path := filepath.Join(tmp, "note.md")
			if err := os.WriteFile(path, []byte(tc.content), 0644); err != nil {
				t.Fatalf("write test file: %v", err)
			}
			got := extractDescriptionFromMarkdown(path)
			if got != tc.expected {
				t.Fatalf("expected %q, got %q", tc.expected, got)
			}
		})
	}
}

func TestRestoreObjectRejectsNonDeleted(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	now := time.Now()
	creatingPath := buildObjectPathForTest(t, now, nil, "creating-obj")
	creatingDir := filepath.Join(mgr.Root(), creatingPath)
	if err := os.MkdirAll(creatingDir, 0o755); err != nil {
		t.Fatalf("mkdir creating object dir: %v", err)
	}

	cases := []struct {
		name  string
		setup func() error
		id    string
	}{
		{
			name: "creating",
			setup: func() error {
				return mgr.meta.Create(ctx, &models.Object{
					ID:        "creating-obj",
					Name:      "creating-obj",
					Path:      creatingPath,
					Status:    models.ObjectStatusCreating,
					CreatedAt: now,
					UpdatedAt: now,
					DataRef:   creatingDir,
				})
			},
			id: "creating-obj",
		},
		{
			name: "active",
			setup: func() error {
				_, err := mgr.CreateObject(ctx, "active-obj", CreateObjectOptions{})
				return err
			},
			id: "active-obj",
		},
		{
			name: "ceased",
			setup: func() error {
				_, err := mgr.CreateObject(ctx, "ceased-obj", CreateObjectOptions{})
				if err != nil {
					return err
				}
				if err := mgr.DeleteObject(ctx, "ceased-obj"); err != nil {
					return err
				}
				return mgr.DeleteObject(ctx, "ceased-obj")
			},
			id: "ceased-obj",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if err := tc.setup(); err != nil {
				t.Fatalf("setup failed: %v", err)
			}
			err := mgr.RestoreObject(ctx, models.ObjectID(tc.id), nil)
			if err == nil {
				t.Fatal("expected error restoring non-deleted object")
			}
		})
	}
}

func TestRestoreObjectMissingData(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	_, err := mgr.CreateObject(ctx, "no-data", CreateObjectOptions{})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "no-data"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}
	// Finalize to delete actual data, then restore should fail.
	if err := mgr.DeleteObject(ctx, "no-data"); err != nil {
		t.Fatalf("DeleteObject finalize failed: %v", err)
	}

	if err := mgr.RestoreObject(ctx, models.ObjectID("no-data"), nil); err == nil {
		t.Fatal("expected error restoring object without actual data")
	}
}

func TestGCZeroRetention(t *testing.T) {
	root := t.TempDir()
	cfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 0,
		LogLevel:            "INFO",
		AdapterConfig:       map[string]string{},
	}
	mgr, err := New(cfg)
	if err != nil {
		t.Fatalf("new manager: %v", err)
	}
	t.Cleanup(func() { _ = mgr.Close() })

	ctx := context.Background()
	_, err = mgr.CreateObject(ctx, "old", CreateObjectOptions{})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "old"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "old"); err != nil {
		t.Fatalf("DeleteObject finalize failed: %v", err)
	}

	// With zero retention, the ceased object should be eligible immediately.
	if err := mgr.GC(ctx); err != nil {
		t.Fatalf("GC failed: %v", err)
	}

	_, err = mgr.GetObject(ctx, "old", true)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound after GC with zero retention, got %v", err)
	}
}

func TestGCForceRemovesCeasedImmediately(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	_, err := mgr.CreateObject(ctx, "fresh-ceased", CreateObjectOptions{})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "fresh-ceased"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "fresh-ceased"); err != nil {
		t.Fatalf("DeleteObject finalize failed: %v", err)
	}

	// Default retention is 30 days, so a non-force GC should keep the object.
	if err := mgr.GCObjects(ctx, false); err != nil {
		t.Fatalf("GCObjects(false) failed: %v", err)
	}
	_, err = mgr.GetObject(ctx, "fresh-ceased", true)
	if err != nil {
		t.Fatalf("expected fresh ceased object to remain without force, got %v", err)
	}

	// Explicit force GC should remove it regardless of retention window.
	if err := mgr.GCObjects(ctx, true); err != nil {
		t.Fatalf("GCObjects(true) failed: %v", err)
	}
	_, err = mgr.GetObject(ctx, "fresh-ceased", true)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound after forced GC, got %v", err)
	}
}

func TestListCreatingObjects(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	now := time.Now()
	objectPath := buildObjectPathForTest(t, now, nil, "creating")
	objectDir := filepath.Join(mgr.Root(), objectPath)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("mkdir object dir: %v", err)
	}

	meta := mgr.meta
	if err := meta.Create(ctx, &models.Object{
		ID:        "creating",
		Name:      "creating",
		Path:      objectPath,
		Status:    models.ObjectStatusCreating,
		CreatedAt: now,
		UpdatedAt: now,
		DataRef:   objectDir,
	}); err != nil {
		t.Fatalf("Create metadata failed: %v", err)
	}

	creating, err := mgr.ListCreatingObjects(ctx)
	if err != nil {
		t.Fatalf("ListCreatingObjects failed: %v", err)
	}
	if len(creating) != 1 || creating[0].Name != "creating" {
		t.Fatalf("expected 1 creating object, got %v", creating)
	}
}

func TestListDeletedObjects(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "obj"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}

	deleted, err := mgr.ListDeletedObjects(ctx)
	if err != nil {
		t.Fatalf("ListDeletedObjects failed: %v", err)
	}
	if len(deleted) != 1 {
		t.Fatalf("expected 1 deleted object, got %d", len(deleted))
	}
}

func TestRootAndClose(t *testing.T) {
	mgr := newTestManager(t)
	if mgr.Root() == "" {
		t.Fatal("expected non-empty root")
	}
	if err := mgr.Close(); err != nil {
		t.Fatalf("Close failed: %v", err)
	}
}

func TestCloseError(t *testing.T) {
	root := t.TempDir()
	cfg := &config.Config{
		Root:                root,
		MetadataAdapter:     "local",
		ActualDataAdapter:   "local",
		CeasedRetentionDays: 30,
		LogLevel:            "INFO",
		AdapterConfig:       map[string]string{},
	}
	mgr, err := New(cfg)
	if err != nil {
		t.Fatalf("new manager: %v", err)
	}

	// Replace adapters with error-returning mocks.
	mgr.meta = &errorCloseMetadataAdapter{}
	mgr.actual = &errorCloseActualDataAdapter{}

	err = mgr.Close()
	if err == nil {
		t.Fatal("expected error from Close")
	}
}

func TestObjectDir(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	dir, err := mgr.objectDir(ctx, "obj")
	if err != nil {
		t.Fatalf("objectDir failed: %v", err)
	}
	if !strings.HasSuffix(dir, string(filepath.Separator)+"obj") {
		t.Fatalf("expected objectDir to end with /obj, got %q", dir)
	}

	_, err = mgr.objectDir(ctx, "missing")
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

func TestRequireActive(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	if _, err := mgr.CreateObject(ctx, "obj", CreateObjectOptions{}); err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "obj"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}

	_, err := mgr.ReadActualFile(ctx, "obj", "obj.md")
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound for deleted object, got %v", err)
	}
}

func TestRegisterLocalFactoriesIdempotent(t *testing.T) {
	// registerLocalFactories is called by New; calling it again should be safe.
	registerLocalFactories()
	registerLocalFactories()

	ctx := context.Background()
	root := t.TempDir()
	meta, err := adapters.NewMetadataAdapter(ctx, "local", map[string]string{"root": root})
	if err != nil {
		t.Fatalf("NewMetadataAdapter failed: %v", err)
	}
	if meta == nil {
		t.Fatal("expected non-nil metadata adapter")
	}
}

func hasTag(tags []string, tag string) bool {
	for _, t := range tags {
		if t == tag {
			return true
		}
	}
	return false
}

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

func buildObjectPathForTest(t *testing.T, tm time.Time, classify []string, name string) string {
	t.Helper()
	path, err := local.BuildObjectPath(tm, classify, name)
	if err != nil {
		t.Fatalf("build object path: %v", err)
	}
	return path
}

// errorCloseMetadataAdapter is a minimal metadata adapter that returns an error on Close.
type errorCloseMetadataAdapter struct{}

func (e *errorCloseMetadataAdapter) Init(ctx context.Context) error                       { return nil }
func (e *errorCloseMetadataAdapter) Create(ctx context.Context, obj *models.Object) error { return nil }
func (e *errorCloseMetadataAdapter) Get(ctx context.Context, id models.ObjectID, includeDeleted bool) (*models.Object, error) {
	return nil, apperrors.ErrObjectNotFound
}
func (e *errorCloseMetadataAdapter) Update(ctx context.Context, obj *models.Object) error { return nil }
func (e *errorCloseMetadataAdapter) Delete(ctx context.Context, id models.ObjectID) error { return nil }
func (e *errorCloseMetadataAdapter) FinalizeDelete(ctx context.Context, id models.ObjectID) error {
	return nil
}
func (e *errorCloseMetadataAdapter) Purge(ctx context.Context, id models.ObjectID) error { return nil }
func (e *errorCloseMetadataAdapter) List(ctx context.Context, opts models.ListOptions) ([]*models.Object, error) {
	return nil, nil
}
func (e *errorCloseMetadataAdapter) Search(ctx context.Context, terms []string, opts models.ListOptions) ([]*models.Object, error) {
	return nil, nil
}
func (e *errorCloseMetadataAdapter) AddTag(ctx context.Context, id models.ObjectID, tag string) error {
	return nil
}
func (e *errorCloseMetadataAdapter) RemoveTag(ctx context.Context, id models.ObjectID, tag string) error {
	return nil
}
func (e *errorCloseMetadataAdapter) Recover(ctx context.Context) ([]*models.Object, error) {
	return nil, nil
}
func (e *errorCloseMetadataAdapter) Restore(ctx context.Context, id models.ObjectID) error {
	return nil
}
func (e *errorCloseMetadataAdapter) GC(ctx context.Context, retention time.Duration, force bool) ([]*models.Object, error) {
	return nil, nil
}
func (e *errorCloseMetadataAdapter) Close() error { return errors.New("metadata close error") }

var _ adapters.MetadataAdapter = (*errorCloseMetadataAdapter)(nil)

// errorCloseActualDataAdapter is a minimal actual-data adapter that returns an error on Close.
type errorCloseActualDataAdapter struct{}

func (e *errorCloseActualDataAdapter) Init(ctx context.Context) error { return nil }
func (e *errorCloseActualDataAdapter) WriteArchive(ctx context.Context, ref string, r io.Reader) (string, error) {
	return ref, nil
}
func (e *errorCloseActualDataAdapter) ReadArchive(ctx context.Context, ref string) (io.ReadCloser, error) {
	return io.NopCloser(strings.NewReader("")), nil
}
func (e *errorCloseActualDataAdapter) WriteFile(ctx context.Context, ref string, filename string, r io.Reader) (string, error) {
	return ref, nil
}
func (e *errorCloseActualDataAdapter) ReadFile(ctx context.Context, ref string, filename string) (io.ReadCloser, error) {
	return io.NopCloser(strings.NewReader("")), nil
}
func (e *errorCloseActualDataAdapter) Move(ctx context.Context, oldRef string, newRef string) (string, error) {
	return newRef, nil
}
func (e *errorCloseActualDataAdapter) Delete(ctx context.Context, ref string) error { return nil }
func (e *errorCloseActualDataAdapter) Exists(ctx context.Context, ref string) (bool, error) {
	return true, nil
}
func (e *errorCloseActualDataAdapter) Close() error { return errors.New("actual close error") }

var _ adapters.ActualDataAdapter = (*errorCloseActualDataAdapter)(nil)

func TestMoveObjectRemovesOldPathAndEmptyParents(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	obj, err := mgr.CreateObject(ctx, "moveme", CreateObjectOptions{Classify: []string{"old", "nested"}})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	oldObjectDir := filepath.Join(mgr.Root(), obj.Path)
	oldNestedDir := filepath.Dir(oldObjectDir)
	oldClassifyDir := filepath.Dir(oldNestedDir)

	if err := mgr.MoveObject(ctx, "moveme", []string{"new", "nested"}); err != nil {
		t.Fatalf("MoveObject failed: %v", err)
	}

	if _, err := os.Stat(oldObjectDir); !os.IsNotExist(err) {
		t.Fatalf("old object directory should be removed: %v", err)
	}
	if _, err := os.Stat(oldNestedDir); !os.IsNotExist(err) {
		t.Fatalf("old nested classify directory should be removed: %v", err)
	}
	if _, err := os.Stat(oldClassifyDir); !os.IsNotExist(err) {
		t.Fatalf("old classify directory should be removed: %v", err)
	}

	newObj, err := mgr.GetObject(ctx, "moveme", false)
	if err != nil {
		t.Fatalf("GetObject after move failed: %v", err)
	}
	if !strings.HasSuffix(newObj.Path, "new/nested/moveme") {
		t.Fatalf("expected path to end with new/nested/moveme, got %q", newObj.Path)
	}
}

func TestGCRemovesEmptyParents(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	obj, err := mgr.CreateObject(ctx, "gcme", CreateObjectOptions{Classify: []string{"demo"}})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "gcme"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}
	if err := mgr.DeleteObject(ctx, "gcme"); err != nil {
		t.Fatalf("DeleteObject finalize failed: %v", err)
	}

	// Backdate the ceased_at timestamp so the object is eligible for GC.
	metaPath := filepath.Join(mgr.Root(), obj.Path, "metadata.json")
	metaBytes, err := os.ReadFile(metaPath)
	if err != nil {
		t.Fatalf("read metadata.json failed: %v", err)
	}
	var raw map[string]any
	if err := json.Unmarshal(metaBytes, &raw); err != nil {
		t.Fatalf("unmarshal metadata.json failed: %v", err)
	}
	raw["CeasedAt"] = time.Now().Add(-31 * 24 * time.Hour).UTC().Format(time.RFC3339Nano)
	metaBytes, err = json.Marshal(raw)
	if err != nil {
		t.Fatalf("marshal metadata.json failed: %v", err)
	}
	if err := os.WriteFile(metaPath, metaBytes, 0o644); err != nil {
		t.Fatalf("write metadata.json failed: %v", err)
	}

	objectDir := filepath.Join(mgr.Root(), obj.Path)
	classifyDir := filepath.Dir(objectDir)

	if err := mgr.GC(ctx); err != nil {
		t.Fatalf("GC failed: %v", err)
	}

	if _, err := os.Stat(objectDir); !os.IsNotExist(err) {
		t.Fatalf("object directory should be removed by GC: %v", err)
	}
	if _, err := os.Stat(classifyDir); !os.IsNotExist(err) {
		t.Fatalf("empty classify directory should be removed by GC: %v", err)
	}
}

func TestGCCleanupRemovesEmptyParents(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	now := time.Now()
	objectPath := buildObjectPathForTest(t, now, []string{"demo"}, "orphan")
	objectDir := filepath.Join(mgr.Root(), objectPath)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("mkdir object dir: %v", err)
	}

	if err := mgr.meta.Create(ctx, &models.Object{
		ID:        "orphan",
		Name:      "orphan",
		Path:      objectPath,
		Status:    models.ObjectStatusCreating,
		CreatedAt: now,
		UpdatedAt: now,
		DataRef:   objectDir,
	}); err != nil {
		t.Fatalf("Create metadata failed: %v", err)
	}

	classifyDir := filepath.Dir(objectDir)

	if err := mgr.GCObjects(ctx, false); err != nil {
		t.Fatalf("GCObjects failed: %v", err)
	}

	if _, err := os.Stat(objectDir); !os.IsNotExist(err) {
		t.Fatalf("creating object directory should be removed: %v", err)
	}
	if _, err := os.Stat(classifyDir); !os.IsNotExist(err) {
		t.Fatalf("empty classify directory should be removed: %v", err)
	}
}

func TestDeleteObjectRetainsMetadataAndParents(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	obj, err := mgr.CreateObject(ctx, "keepme", CreateObjectOptions{Classify: []string{"demo"}})
	if err != nil {
		t.Fatalf("CreateObject failed: %v", err)
	}

	objectDir := filepath.Join(mgr.Root(), obj.Path)
	classifyDir := filepath.Dir(objectDir)

	if err := mgr.DeleteObject(ctx, "keepme"); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}

	// Deleted objects retain metadata, so the object directory and its parents
	// must remain even though actual data was removed.
	if _, err := os.Stat(objectDir); err != nil {
		t.Fatalf("deleted object directory should be retained: %v", err)
	}
	if _, err := os.Stat(filepath.Join(objectDir, "metadata.json")); err != nil {
		t.Fatalf("deleted object metadata should be retained: %v", err)
	}
	if _, err := os.Stat(classifyDir); err != nil {
		t.Fatalf("classify directory should be retained: %v", err)
	}
}

func TestCreateObjectWithMarkerTar(t *testing.T) {
	mgr := newTestManager(t)
	ctx := context.Background()

	markerContent := []byte("---\ndescription: tar desc\n---\n\nmarker body\n")
	archive := buildTarArchive(t, map[string][]byte{
		"markerobj.md": markerContent,
		"extra.txt":    []byte("extra data"),
	})

	obj, err := mgr.CreateObject(ctx, "markerobj", CreateObjectOptions{
		Data: bytes.NewReader(archive),
	})
	if err != nil {
		t.Fatalf("CreateObject with marker tar failed: %v", err)
	}
	if obj.Description != "tar desc" {
		t.Fatalf("expected description from marker frontmatter, got %q", obj.Description)
	}

	rc, err := mgr.ReadActualFile(ctx, "markerobj", "markerobj.md")
	if err != nil {
		t.Fatalf("ReadActualFile marker failed: %v", err)
	}
	defer rc.Close()
	got, err := io.ReadAll(rc)
	if err != nil {
		t.Fatalf("read marker failed: %v", err)
	}
	if !bytes.Equal(got, markerContent) {
		t.Fatalf("expected marker %q, got %q", markerContent, got)
	}

	rc2, err := mgr.ReadActualFile(ctx, "markerobj", "extra.txt")
	if err != nil {
		t.Fatalf("ReadActualFile extra failed: %v", err)
	}
	defer rc2.Close()
	got2, err := io.ReadAll(rc2)
	if err != nil {
		t.Fatalf("read extra failed: %v", err)
	}
	if string(got2) != "extra data" {
		t.Fatalf("expected extra data, got %q", got2)
	}
}
