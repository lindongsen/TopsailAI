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

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/config"
	"github.com/topsailai/topsailai_data/pkg/models"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

func newTestManager(t *testing.T) (*Manager, string) {
	t.Helper()
	root := t.TempDir()

	mgr, err := New(&config.Config{
		Root:              root,
		MetadataAdapter:   "local",
		ActualDataAdapter: "local",
	})
	if err != nil {
		t.Fatalf("create manager: %v", err)
	}
	return mgr, root
}

// tarBytes wraps a single payload in a minimal tar archive stream.
func tarBytes(t *testing.T, filename string, payload []byte) io.Reader {
	t.Helper()
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	hdr := &tar.Header{
		Name:     filename,
		Mode:     0o644,
		Size:     int64(len(payload)),
		ModTime:  time.Now(),
		Typeflag: tar.TypeReg,
	}
	if err := tw.WriteHeader(hdr); err != nil {
		t.Fatalf("write tar header: %v", err)
	}
	if _, err := tw.Write(payload); err != nil {
		t.Fatalf("write tar body: %v", err)
	}
	if err := tw.Close(); err != nil {
		t.Fatalf("close tar writer: %v", err)
	}
	return bytes.NewReader(buf.Bytes())
}

// readActualArchive reads the first regular file from a tar archive stream.
func readActualArchive(t *testing.T, r io.Reader) []byte {
	t.Helper()
	tr := tar.NewReader(r)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			t.Fatal("no file in archive")
		}
		if err != nil {
			t.Fatalf("read tar header: %v", err)
		}
		if hdr.Typeflag == tar.TypeReg {
			data, err := io.ReadAll(tr)
			if err != nil {
				t.Fatalf("read tar file: %v", err)
			}
			return data
		}
	}
}

func hasAllTags(tags, want []string) bool {
	set := make(map[string]bool, len(tags))
	for _, t := range tags {
		set[t] = true
	}
	for _, w := range want {
		if !set[w] {
			return false
		}
	}
	return true
}

func TestCreateOverCeasedObject(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "reusable-object"

	// First creation.
	obj, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("first payload")),
	})
	if err != nil {
		t.Fatalf("first create failed: %v", err)
	}
	if obj.Status != models.ObjectStatusActive {
		t.Fatalf("expected active, got %s", obj.Status)
	}

	// Soft delete to move through deleted -> ceased.
	if err := mgr.DeleteObject(ctx, models.ObjectID(name)); err != nil {
		t.Fatalf("delete failed: %v", err)
	}

	// Verify the object is ceased before recreating.
	ceasedObj, err := mgr.GetObject(ctx, models.ObjectID(name), true)
	if err != nil {
		t.Fatalf("get ceased object failed: %v", err)
	}
	if ceasedObj.Status != models.ObjectStatusCeased {
		t.Fatalf("expected ceased before recreate, got %s", ceasedObj.Status)
	}

	// Recreate over the ceased object.
	obj2, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("second payload")),
	})
	if err != nil {
		t.Fatalf("create over ceased object failed: %v", err)
	}
	if obj2.Status != models.ObjectStatusActive {
		t.Fatalf("expected active after recreate, got %s", obj2.Status)
	}
	if obj2.ID != obj.ID {
		t.Fatalf("object ID changed: %s -> %s", obj.ID, obj2.ID)
	}

	// Verify new payload is readable.
	archiveReader, err := mgr.ReadActualArchive(ctx, models.ObjectID(name))
	if err != nil {
		t.Fatalf("read actual archive failed: %v", err)
	}
	defer archiveReader.Close()
	data := readActualArchive(t, archiveReader)
	if string(data) != "second payload" {
		t.Fatalf("unexpected payload: %q", string(data))
	}
}

func TestCreateOverActiveObjectReturnsExists(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "active-object"
	if _, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("payload")),
	}); err != nil {
		t.Fatalf("create failed: %v", err)
	}

	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("new payload")),
	})
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("expected ErrObjectExists, got: %v", err)
	}
}

func TestCreateOverDeletedObjectReturnsExists(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "deleted-object"
	id := models.ObjectID(name)

	// Manually create a metadata record in the "deleted" state.
	now := time.Now()
	objectPath, err := local.BuildObjectPath(now, nil, name)
	if err != nil {
		t.Fatalf("build object path: %v", err)
	}
	objectDir := filepath.Join(root, objectPath)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("create object dir: %v", err)
	}
	deletedAt := now.Add(-time.Minute)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusDeleted,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     deletedAt,
		DeletedAt:     &deletedAt,
		DataRef:       objectDir,
	}
	data, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		t.Fatalf("marshal metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, name+".md"), []byte{}, 0o644); err != nil {
		t.Fatalf("write marker: %v", err)
	}

	_, err = mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("new payload")),
	})
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("expected ErrObjectExists for deleted object, got: %v", err)
	}
}

func TestCreateObjectWithoutData(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	obj, err := mgr.CreateObject(ctx, "empty-object", CreateObjectOptions{})
	if err != nil {
		t.Fatalf("create without data failed: %v", err)
	}
	if obj.Status != models.ObjectStatusActive {
		t.Fatalf("expected active, got %s", obj.Status)
	}

	markerPath := filepath.Join(obj.DataRef, "empty-object.md")
	if _, err := os.Stat(markerPath); err != nil {
		t.Fatalf("marker file missing: %v", err)
	}
}

func TestCreateObjectWithClassifyAndTags(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	obj, err := mgr.CreateObject(ctx, "classified", CreateObjectOptions{
		Classify: []string{"work", "2026"},
		Tags:     []string{"important", "work"},
	})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}
	if obj.Status != models.ObjectStatusActive {
		t.Fatalf("expected active, got %s", obj.Status)
	}
	if !strings.Contains(obj.Path, "work/2026/classified") {
		t.Fatalf("expected classify path in %q", obj.Path)
	}
	if !hasAllTags(obj.Tags, []string{"important", "work"}) {
		t.Fatalf("expected tags important and work, got %v", obj.Tags)
	}
}

func TestCreateObjectInvalidName(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	_, err := mgr.CreateObject(ctx, "", CreateObjectOptions{})
	if err == nil {
		t.Fatal("expected error for empty name")
	}
	if !errors.Is(err, apperrors.ErrInvalidName) {
		t.Fatalf("expected ErrInvalidName, got %v", err)
	}

	_, err = mgr.CreateObject(ctx, "a/b", CreateObjectOptions{})
	if !errors.Is(err, apperrors.ErrInvalidName) {
		t.Fatalf("expected ErrInvalidName, got %v", err)
	}
}

func TestGetObject(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "get-me"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("payload")),
	})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	obj, err := mgr.GetObject(ctx, id, false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}
	if obj.ID != id {
		t.Fatalf("ID mismatch: got %q, want %q", obj.ID, id)
	}

	_, err = mgr.GetObject(ctx, models.ObjectID("missing"), false)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

func TestListObjects(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	for _, name := range []string{"alpha", "beta", "gamma"} {
		_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
			Tags: []string{"shared", name + "-tag"},
		})
		if err != nil {
			t.Fatalf("create %s failed: %v", name, err)
		}
	}

	all, err := mgr.ListObjects(ctx, models.ListOptions{})
	if err != nil {
		t.Fatalf("ListObjects failed: %v", err)
	}
	if len(all) != 3 {
		t.Fatalf("expected 3 objects, got %d", len(all))
	}

	filtered, err := mgr.ListObjects(ctx, models.ListOptions{Tags: []string{"shared", "alpha-tag"}})
	if err != nil {
		t.Fatalf("ListObjects with tags failed: %v", err)
	}
	if len(filtered) != 1 || filtered[0].Name != "alpha" {
		t.Fatalf("expected only alpha, got %v", filtered)
	}

	page, err := mgr.ListObjects(ctx, models.ListOptions{Offset: 1, Limit: 1})
	if err != nil {
		t.Fatalf("ListObjects pagination failed: %v", err)
	}
	if len(page) != 1 {
		t.Fatalf("expected 1 object for offset=1 limit=1, got %d", len(page))
	}
}

func TestSearchObjects(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	_, err := mgr.CreateObject(ctx, "hello-world", CreateObjectOptions{
		Tags: []string{"greeting"},
	})
	if err != nil {
		t.Fatalf("create hello-world failed: %v", err)
	}
	_, err = mgr.CreateObject(ctx, "goodbye", CreateObjectOptions{
		Tags: []string{"world-news"},
	})
	if err != nil {
		t.Fatalf("create goodbye failed: %v", err)
	}

	results, err := mgr.SearchObjects(ctx, []string{"hello"}, models.ListOptions{})
	if err != nil {
		t.Fatalf("SearchObjects failed: %v", err)
	}
	if len(results) != 1 || results[0].Name != "hello-world" {
		t.Fatalf("expected hello-world, got %v", results)
	}

	results, err = mgr.SearchObjects(ctx, []string{"world"}, models.ListOptions{})
	if err != nil {
		t.Fatalf("SearchObjects failed: %v", err)
	}
	if len(results) != 2 {
		t.Fatalf("expected 2 results for world, got %d", len(results))
	}
}

func TestUpdateActualData(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "update-data"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "old.txt", []byte("old content")),
	})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	if err := mgr.UpdateActualData(ctx, id, tarBytes(t, "new.txt", []byte("new content"))); err != nil {
		t.Fatalf("UpdateActualData failed: %v", err)
	}

	reader, err := mgr.ReadActualArchive(ctx, id)
	if err != nil {
		t.Fatalf("ReadActualArchive failed: %v", err)
	}
	defer reader.Close()
	data := readActualArchive(t, reader)
	if string(data) != "new content" {
		t.Fatalf("unexpected content: %q", string(data))
	}
}

func TestWriteAndReadActualFile(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "file-obj"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	payload := []byte{0x00, 0x01, 0x02, 0xff}
	if err := mgr.WriteActualFile(ctx, id, "binary.bin", bytes.NewReader(payload)); err != nil {
		t.Fatalf("WriteActualFile failed: %v", err)
	}

	reader, err := mgr.ReadActualFile(ctx, id, "binary.bin")
	if err != nil {
		t.Fatalf("ReadActualFile failed: %v", err)
	}
	defer reader.Close()
	got, err := io.ReadAll(reader)
	if err != nil {
		t.Fatalf("read file: %v", err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatalf("binary content mismatch")
	}
}

func TestReadActualFileNotFound(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "file-obj"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	_, err = mgr.ReadActualFile(ctx, id, "missing.txt")
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

func TestDeleteObject(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "delete-me"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("payload")),
	})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	if err := mgr.DeleteObject(ctx, id); err != nil {
		t.Fatalf("DeleteObject failed: %v", err)
	}

	_, err = mgr.GetObject(ctx, id, false)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound after delete, got %v", err)
	}

	ceased, err := mgr.GetObject(ctx, id, true)
	if err != nil {
		t.Fatalf("GetObject includeDeleted failed: %v", err)
	}
	if ceased.Status != models.ObjectStatusCeased {
		t.Fatalf("expected ceased, got %s", ceased.Status)
	}
}

func TestDeleteObjectNotFound(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	err := mgr.DeleteObject(ctx, models.ObjectID("missing"))
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

func TestDeleteObjectCreating(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "creating-obj"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCreating,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, name+".md"), []byte{}, 0o644)

	err := mgr.DeleteObject(ctx, id)
	if !errors.Is(err, apperrors.ErrObjectNotActive) {
		t.Fatalf("expected ErrObjectNotActive for creating object, got %v", err)
	}
}

func TestMoveObject(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "move-me"
	id := models.ObjectID(name)
	obj, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("payload")),
	})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}
	oldPath := obj.Path

	if err := mgr.MoveObject(ctx, id, []string{"archive", "2026"}); err != nil {
		t.Fatalf("MoveObject failed: %v", err)
	}

	moved, err := mgr.GetObject(ctx, id, false)
	if err != nil {
		t.Fatalf("GetObject after move failed: %v", err)
	}
	if moved.Path == oldPath {
		t.Fatal("object path did not change after move")
	}
	if !strings.Contains(moved.Path, "archive/2026/"+name) {
		t.Fatalf("expected archive/2026 in path, got %q", moved.Path)
	}

	oldDir := filepath.Join(root, oldPath)
	if _, err := os.Stat(oldDir); !os.IsNotExist(err) {
		t.Fatalf("old directory should be removed: %v", err)
	}

	reader, err := mgr.ReadActualArchive(ctx, id)
	if err != nil {
		t.Fatalf("ReadActualArchive after move failed: %v", err)
	}
	defer reader.Close()
	data := readActualArchive(t, reader)
	if string(data) != "payload" {
		t.Fatalf("unexpected content after move: %q", string(data))
	}
}

func TestMoveObjectSamePathIsNoOp(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "move-me"
	id := models.ObjectID(name)
	obj, err := mgr.CreateObject(ctx, name, CreateObjectOptions{})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}
	oldPath := obj.Path

	if err := mgr.MoveObject(ctx, id, nil); err != nil {
		t.Fatalf("MoveObject to same path failed: %v", err)
	}

	moved, err := mgr.GetObject(ctx, id, false)
	if err != nil {
		t.Fatalf("GetObject after no-op move failed: %v", err)
	}
	if moved.Path != oldPath {
		t.Fatalf("path changed on no-op move: %q -> %q", oldPath, moved.Path)
	}
}

func TestMoveObjectDepthExceeded(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "move-me"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	err = mgr.MoveObject(ctx, id, []string{"a", "b", "c", "d", "e", "f", "g", "h"})
	if !errors.Is(err, apperrors.ErrDepthExceeded) {
		t.Fatalf("expected ErrDepthExceeded, got %v", err)
	}
}

func TestRecoverObjectActivateExistingData(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "recover-me"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCreating,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, name+".md"), []byte("# "+name), 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, "data.txt"), []byte("data"), 0o644)

	if err := mgr.RecoverObject(ctx, id, false, nil); err != nil {
		t.Fatalf("RecoverObject failed: %v", err)
	}

	recovered, err := mgr.GetObject(ctx, id, false)
	if err != nil {
		t.Fatalf("GetObject after recover failed: %v", err)
	}
	if recovered.Status != models.ObjectStatusActive {
		t.Fatalf("expected active, got %s", recovered.Status)
	}
}

func TestRecoverObjectCleanupNoData(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "recover-cleanup"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCreating,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)

	if err := mgr.RecoverObject(ctx, id, false, nil); err != nil {
		t.Fatalf("RecoverObject cleanup failed: %v", err)
	}

	_, err := mgr.GetObject(ctx, id, true)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected object to be removed, got %v", err)
	}
}

func TestRecoverObjectResumeWithData(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "resume-me"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCreating,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)

	err := mgr.RecoverObject(ctx, id, true, tarBytes(t, "payload.txt", []byte("resumed")))
	if err != nil {
		t.Fatalf("RecoverObject resume failed: %v", err)
	}

	recovered, err := mgr.GetObject(ctx, id, false)
	if err != nil {
		t.Fatalf("GetObject after resume failed: %v", err)
	}
	if recovered.Status != models.ObjectStatusActive {
		t.Fatalf("expected active, got %s", recovered.Status)
	}
}

func TestRecoverObjectResumeWithoutData(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "resume-empty"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCreating,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)

	err := mgr.RecoverObject(ctx, id, true, nil)
	if err == nil {
		t.Fatal("expected error when resume requested without data")
	}
}

func TestRecoverObjectNotCreating(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "active-recover"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	err = mgr.RecoverObject(ctx, id, false, nil)
	if !errors.Is(err, apperrors.ErrObjectNotCreating) {
		t.Fatalf("expected ErrObjectNotCreating, got %v", err)
	}
}

func TestAddAndRemoveTag(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "tag-obj"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Classify: []string{"classify"},
		Tags:     []string{"own"},
	})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	// Add a tag.
	if err := mgr.AddTag(ctx, id, "new-tag"); err != nil {
		t.Fatalf("AddTag failed: %v", err)
	}
	obj, err := mgr.GetObject(ctx, id, false)
	if err != nil {
		t.Fatalf("GetObject after add failed: %v", err)
	}
	if !hasAllTags(obj.Tags, []string{"own", "new-tag"}) {
		t.Fatalf("expected own and new-tag, got %v", obj.Tags)
	}

	// Remove own tag.
	if err := mgr.RemoveTag(ctx, id, "own"); err != nil {
		t.Fatalf("RemoveTag failed: %v", err)
	}
	obj, err = mgr.GetObject(ctx, id, false)
	if err != nil {
		t.Fatalf("GetObject after remove failed: %v", err)
	}
	if hasAllTags(obj.Tags, []string{"own"}) {
		t.Fatalf("expected own tag removed, got %v", obj.Tags)
	}
}

func TestRemoveInheritedTagBlocked(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "tag-obj"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{
		Classify: []string{"classify"},
	})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	// Add an inherited tag via classify tag file.
	classifyDir := filepath.Join(root, filepath.Dir(mgr.objectDir(id)))
	if err := local.WriteTagsFile(filepath.Join(classifyDir, "classify.tags"), []string{"inherited"}); err != nil {
		t.Fatalf("write classify tags: %v", err)
	}

	obj, err := mgr.GetObject(ctx, id, false)
	if err != nil {
		t.Fatalf("GetObject failed: %v", err)
	}
	if !hasAllTags(obj.Tags, []string{"inherited"}) {
		t.Fatalf("expected inherited tag, got %v", obj.Tags)
	}

	// Removing inherited tag should fail.
	err = mgr.RemoveTag(ctx, id, "inherited")
	if !errors.Is(err, apperrors.ErrTagInherited) {
		t.Fatalf("expected ErrTagInherited, got %v", err)
	}
}

func TestAddTagInvalid(t *testing.T) {
	ctx := context.Background()
	mgr, _ := newTestManager(t)
	defer mgr.Close()

	name := "tag-obj"
	id := models.ObjectID(name)
	_, err := mgr.CreateObject(ctx, name, CreateObjectOptions{})
	if err != nil {
		t.Fatalf("create failed: %v", err)
	}

	err = mgr.AddTag(ctx, id, "bad/tag")
	if !errors.Is(err, apperrors.ErrInvalidTag) {
		t.Fatalf("expected ErrInvalidTag, got %v", err)
	}
}

func TestGCRemovesExpiredCeased(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "expired-ceased"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	expired := now.Add(-time.Hour * 24 * 60)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCeased,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     expired,
		CeasedAt:      &expired,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, name+".ceased"), []byte{}, 0o644)

	if err := mgr.GC(ctx, models.GCOptions{Status: models.ObjectStatusCeased}); err != nil {
		t.Fatalf("GC failed: %v", err)
	}

	_, err := mgr.GetObject(ctx, id, true)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected expired ceased object removed, got %v", err)
	}
}

func TestGCKeepsRecentCeased(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "recent-ceased"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	recent := now.Add(-time.Hour)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCeased,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     recent,
		CeasedAt:      &recent,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, name+".ceased"), []byte{}, 0o644)

	if err := mgr.GC(ctx, models.GCOptions{Status: models.ObjectStatusCeased}); err != nil {
		t.Fatalf("GC failed: %v", err)
	}

	_, err := mgr.GetObject(ctx, id, true)
	if err != nil {
		t.Fatalf("expected recent ceased object kept, got %v", err)
	}
}

func TestGCFinalizesDeletedObjects(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "deleted-finalize"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	deletedAt := now.Add(-time.Minute)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusDeleted,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     deletedAt,
		DeletedAt:     &deletedAt,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, name+".md"), []byte("# "+name), 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, name+".deleted"), []byte{}, 0o644)

	if err := mgr.GC(ctx, models.GCOptions{Status: models.ObjectStatusDeleted}); err != nil {
		t.Fatalf("GC failed: %v", err)
	}

	finalized, err := mgr.GetObject(ctx, id, true)
	if err != nil {
		t.Fatalf("GetObject after GC failed: %v", err)
	}
	if finalized.Status != models.ObjectStatusCeased {
		t.Fatalf("expected ceased after GC finalize, got %s", finalized.Status)
	}
}

func TestGCCleansCreatingOrphans(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "creating-orphan"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCreating,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, name+".md"), []byte("# "+name), 0o644)

	if err := mgr.GC(ctx, models.GCOptions{Status: models.ObjectStatusCreating}); err != nil {
		t.Fatalf("GC failed: %v", err)
	}

	_, err := mgr.GetObject(ctx, id, true)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected creating orphan removed, got %v", err)
	}
}

func TestGCDryRun(t *testing.T) {
	ctx := context.Background()
	mgr, root := newTestManager(t)
	defer mgr.Close()

	name := "dryrun-ceased"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, _ := local.BuildObjectPath(now, nil, name)
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)
	expired := now.Add(-time.Hour * 24 * 60)
	obj := &models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCeased,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     expired,
		CeasedAt:      &expired,
		DataRef:       objectDir,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, name+".ceased"), []byte{}, 0o644)

	if err := mgr.GC(ctx, models.GCOptions{Status: models.ObjectStatusCeased, DryRun: true}); err != nil {
		t.Fatalf("GC dry-run failed: %v", err)
	}

	_, err := mgr.GetObject(ctx, id, true)
	if err != nil {
		t.Fatalf("expected dry-run to keep object, got %v", err)
	}
}

func TestRoot(t *testing.T) {
	mgr, root := newTestManager(t)
	defer mgr.Close()

	if mgr.Root() != root {
		t.Fatalf("Root mismatch: got %q, want %q", mgr.Root(), root)
	}
}

func TestClose(t *testing.T) {
	mgr, _ := newTestManager(t)
	if err := mgr.Close(); err != nil {
		t.Fatalf("Close failed: %v", err)
	}
}

func TestNewWithUnknownMetadataAdapter(t *testing.T) {
	_, err := New(&config.Config{
		Root:              t.TempDir(),
		MetadataAdapter:   "unknown",
		ActualDataAdapter: "local",
	})
	if err == nil {
		t.Fatal("expected error for unknown metadata adapter")
	}
}

func TestNewWithUnknownActualDataAdapter(t *testing.T) {
	_, err := New(&config.Config{
		Root:              t.TempDir(),
		MetadataAdapter:   "local",
		ActualDataAdapter: "unknown",
	})
	if err == nil {
		t.Fatal("expected error for unknown actual data adapter")
	}
}
