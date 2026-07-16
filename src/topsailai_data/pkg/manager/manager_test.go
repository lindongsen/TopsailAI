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

	// Manually create a metadata record in the "deleted" state. The manager's
	// DeleteObject finalizes to ceased immediately in the local adapter, so we
	// need to synthesize a deleted object to test the intermediate state.
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

	// Deleted objects must still reject create.
	_, err = mgr.CreateObject(ctx, name, CreateObjectOptions{
		Data: tarBytes(t, "payload.txt", []byte("new payload")),
	})
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("expected ErrObjectExists for deleted object, got: %v", err)
	}
}
