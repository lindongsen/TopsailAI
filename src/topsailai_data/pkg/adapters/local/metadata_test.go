package local

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/models"
)

func TestMetadataAdapterPurgeRemovesCeasedObject(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()

	adapter := NewMetadataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatalf("init adapter: %v", err)
	}
	defer adapter.Close()

	name := "purge-me"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, err := BuildObjectPath(now, nil, name)
	if err != nil {
		t.Fatalf("build object path: %v", err)
	}
	objectDir := filepath.Join(root, objectPath)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("create object dir: %v", err)
	}

	obj := models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusCeased,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}
	data, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		t.Fatalf("marshal metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, name+".md"), []byte("data"), 0o644); err != nil {
		t.Fatalf("write marker: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, name+".ceased"), []byte{}, 0o644); err != nil {
		t.Fatalf("write ceased marker: %v", err)
	}

	if err := adapter.Purge(ctx, id); err != nil {
		t.Fatalf("purge ceased object: %v", err)
	}

	if _, err := os.Stat(objectDir); !os.IsNotExist(err) {
		t.Fatalf("expected object directory to be removed, got err=%v", err)
	}
}

func TestMetadataAdapterPurgeRejectsNonCeased(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()

	adapter := NewMetadataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatalf("init adapter: %v", err)
	}
	defer adapter.Close()

	name := "active-object"
	id := models.ObjectID(name)
	now := time.Now()
	objectPath, err := BuildObjectPath(now, nil, name)
	if err != nil {
		t.Fatalf("build object path: %v", err)
	}
	objectDir := filepath.Join(root, objectPath)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("create object dir: %v", err)
	}

	obj := models.Object{
		ID:            id,
		Name:          name,
		Path:          objectPath,
		Status:        models.ObjectStatusActive,
		SchemaVersion: 1,
		CreatedAt:     now,
		UpdatedAt:     now,
		DataRef:       objectDir,
	}
	data, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		t.Fatalf("marshal metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}

	if err := adapter.Purge(ctx, id); err == nil {
		t.Fatal("expected error purging active object, got nil")
	}
}
