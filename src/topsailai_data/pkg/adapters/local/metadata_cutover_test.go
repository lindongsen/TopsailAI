package local

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// TestMetadataCutoverAuthority checks separate tags and metadata-only lifecycle cleanup.
func TestMetadataCutoverAuthority(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatal(err)
	}
	layout, err := NewStoreLayout(root)
	if err != nil {
		t.Fatal(err)
	}
	gate, err := AcquireNamespaceLock(root)
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Release()
	lock, err := layout.AcquireMetadataLockUnderNamespace("probe", true)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Release()
	now := time.Now()
	obj := &models.Object{ID: "probe", Name: "probe", Path: "2026/1111/0900/work/probe", DataRef: "2026/1111/0900/work/probe", Status: models.ObjectStatusCreating, CreatedAt: now, UpdatedAt: now, Tags: []string{"one"}}
	if err := adapter.Create(ctx, obj); err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ObjectMetaPath(obj.ID)
	if err != nil {
		t.Fatal(err)
	}
	disk, err := os.ReadFile(filepath.Join(dir, "metadata.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(disk, &fields); err != nil {
		t.Fatal(err)
	}
	for name := range fields {
		if name == "Tags" || name == "tags" {
			t.Fatal("disk metadata contains tags")
		}
	}
	obj.Status = models.ObjectStatusActive
	obj.Tags = []string{"must-not-persist"}
	if err := adapter.Update(ctx, obj); err != nil {
		t.Fatal(err)
	}
	if err := adapter.AddTag(ctx, obj.ID, "two"); err != nil {
		t.Fatal(err)
	}
	if err := adapter.RemoveTag(ctx, obj.ID, "one"); err != nil {
		t.Fatal(err)
	}
	got, err := adapter.Get(ctx, obj.ID, false)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got.Tags, []string{"two"}) {
		t.Fatalf("tags: %v", got.Tags)
	}
	payload := filepath.Join(layout.ObjectRoot(), filepath.FromSlash(obj.Path))
	if err := os.MkdirAll(payload, 0755); err != nil {
		t.Fatal(err)
	}
	sentinel := filepath.Join(payload, "probe.md")
	if err := os.WriteFile(sentinel, []byte("payload"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := adapter.Delete(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if err := adapter.FinalizeDelete(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	got, err = adapter.Get(ctx, obj.ID, true)
	if err != nil || got.Status != models.ObjectStatusCeased || !reflect.DeepEqual(got.Tags, []string{"two"}) {
		t.Fatalf("ceased: %#v %v", got, err)
	}
	if err := adapter.Purge(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("metadata retained: %v", err)
	}
	if data, err := os.ReadFile(sentinel); err != nil || string(data) != "payload" {
		t.Fatalf("metadata purge touched payload: %q %v", data, err)
	}
}

// TestMetadataCutoverQueries checks payload-independent recovery and invisible creating records.
func TestMetadataCutoverQueries(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatal(err)
	}
	layout, err := NewStoreLayout(root)
	if err != nil {
		t.Fatal(err)
	}
	gate, err := AcquireNamespaceLock(root)
	if err != nil {
		t.Fatal(err)
	}
	defer gate.Release()
	lock, err := layout.AcquireMetadataLockUnderNamespace("probe", true)
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Release()
	obj := &models.Object{ID: "probe", Name: "probe", Path: "2026/1111/0900/probe", DataRef: "2026/1111/0900/probe", Status: models.ObjectStatusCreating, Tags: []string{"own"}}
	if err := adapter.Create(ctx, obj); err != nil {
		t.Fatal(err)
	}
	if _, err := adapter.Get(ctx, obj.ID, false); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("creating visible: %v", err)
	}
	list, err := adapter.List(ctx, models.ListOptions{IncludeDeleted: true})
	if err != nil || len(list) != 0 {
		t.Fatalf("creating list: %v %v", list, err)
	}
	creating, err := adapter.Recover(ctx)
	if err != nil || len(creating) != 1 {
		t.Fatalf("recover: %v %v", creating, err)
	}
	obj.Status = models.ObjectStatusActive
	if err := adapter.Update(ctx, obj); err != nil {
		t.Fatal(err)
	}
	list, err = adapter.Search(ctx, []string{"own"}, models.ListOptions{})
	if err != nil || len(list) != 1 {
		t.Fatalf("tag search without payload: %v %v", list, err)
	}
	if _, err := adapter.Get(ctx, "missing", true); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("missing: %v", err)
	}
	missing, err := layout.ObjectMetaPath("missing")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Fatalf("missing lookup grew store: %v", err)
	}
}
