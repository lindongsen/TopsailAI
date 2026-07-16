package local

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

func createObjectDir(t *testing.T, root string, obj *models.Object) string {
	t.Helper()
	objectDir := filepath.Join(root, obj.Path)
	if err := os.MkdirAll(objectDir, 0o755); err != nil {
		t.Fatalf("create object dir: %v", err)
	}
	data, err := json.MarshalIndent(obj, "", "  ")
	if err != nil {
		t.Fatalf("marshal metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644); err != nil {
		t.Fatalf("write metadata: %v", err)
	}
	if err := os.WriteFile(filepath.Join(objectDir, obj.Name+".md"), []byte("# "+obj.Name), 0o644); err != nil {
		t.Fatalf("write marker: %v", err)
	}
	return objectDir
}

func TestMetadataAdapterCreateAndGet(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	if err := adapter.Init(ctx); err != nil {
		t.Fatalf("init adapter: %v", err)
	}
	defer adapter.Close()

	name := "hello"
	id := models.ObjectID(name)
	now := time.Now().Truncate(time.Second)
	objectPath, err := BuildObjectPath(now, nil, name)
	if err != nil {
		t.Fatalf("build object path: %v", err)
	}

	obj := &models.Object{
		ID:        id,
		Name:      name,
		Path:      objectPath,
		Status:    models.ObjectStatusActive,
		CreatedAt: now,
		UpdatedAt: now,
		DataRef:   filepath.Join(root, objectPath),
	}
	if err := adapter.Create(ctx, obj); err != nil {
		t.Fatalf("Create failed: %v", err)
	}

	got, err := adapter.Get(ctx, id, false)
	if err != nil {
		t.Fatalf("Get failed: %v", err)
	}
	if got.ID != id {
		t.Fatalf("ID mismatch: got %q, want %q", got.ID, id)
	}
	if got.Name != name {
		t.Fatalf("Name mismatch: got %q, want %q", got.Name, name)
	}
	if got.Path != objectPath {
		t.Fatalf("Path mismatch: got %q, want %q", got.Path, objectPath)
	}
	if got.Status != models.ObjectStatusActive {
		t.Fatalf("Status mismatch: got %q", got.Status)
	}
	if got.SchemaVersion != 1 {
		t.Fatalf("SchemaVersion mismatch: got %d", got.SchemaVersion)
	}

	// Duplicate create should fail.
	if err := adapter.Create(ctx, obj); err == nil {
		t.Fatal("expected ErrObjectExists on duplicate create")
	} else if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("expected ErrObjectExists, got %v", err)
	}
}

func TestMetadataAdapterGetNotFound(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	_, err := adapter.Get(ctx, models.ObjectID("missing"), false)
	if err == nil {
		t.Fatal("expected error for missing object")
	}
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound, got %v", err)
	}
}

func TestMetadataAdapterGetCreatingHidden(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	name := "creating-obj"
	now := time.Now()
	objectPath, _ := BuildObjectPath(now, nil, name)
	obj := &models.Object{
		ID:        models.ObjectID(name),
		Name:      name,
		Path:      objectPath,
		Status:    models.ObjectStatusCreating,
		CreatedAt: now,
		UpdatedAt: now,
	}
	createObjectDir(t, root, obj)

	_, err := adapter.Get(ctx, obj.ID, false)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected ErrObjectNotFound for creating object, got %v", err)
	}

	got, err := adapter.Get(ctx, obj.ID, true)
	if err != nil {
		t.Fatalf("Get with includeDeleted failed: %v", err)
	}
	if got.Status != models.ObjectStatusCreating {
		t.Fatalf("expected creating status, got %q", got.Status)
	}
}

func TestMetadataAdapterUpdate(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	name := "update-me"
	now := time.Now().Truncate(time.Second)
	objectPath, _ := BuildObjectPath(now, nil, name)
	obj := &models.Object{
		ID:        models.ObjectID(name),
		Name:      name,
		Path:      objectPath,
		Status:    models.ObjectStatusActive,
		CreatedAt: now,
		UpdatedAt: now,
		Tags:      []string{"old"},
	}
	createObjectDir(t, root, obj)

	obj.Tags = []string{"new"}
	if err := adapter.Update(ctx, obj); err != nil {
		t.Fatalf("Update failed: %v", err)
	}

	got, err := adapter.Get(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("Get after update failed: %v", err)
	}
	if len(got.Tags) != 1 || got.Tags[0] != "new" {
		t.Fatalf("tags not updated: %v", got.Tags)
	}
	if !got.UpdatedAt.After(now) {
		t.Fatal("UpdatedAt was not advanced")
	}
}

func TestMetadataAdapterSoftDeleteLifecycle(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	name := "delete-me"
	now := time.Now()
	objectPath, _ := BuildObjectPath(now, nil, name)
	obj := &models.Object{
		ID:        models.ObjectID(name),
		Name:      name,
		Path:      objectPath,
		Status:    models.ObjectStatusActive,
		CreatedAt: now,
		UpdatedAt: now,
	}
	createObjectDir(t, root, obj)

	if err := adapter.Delete(ctx, obj.ID); err != nil {
		t.Fatalf("Delete failed: %v", err)
	}

	_, err := adapter.Get(ctx, obj.ID, false)
	if !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("expected hidden after delete, got %v", err)
	}

	got, err := adapter.Get(ctx, obj.ID, true)
	if err != nil {
		t.Fatalf("Get with includeDeleted failed: %v", err)
	}
	if got.Status != models.ObjectStatusDeleted {
		t.Fatalf("expected deleted status, got %q", got.Status)
	}
	if got.DeletedAt == nil {
		t.Fatal("DeletedAt not set")
	}

	// Finalize delete.
	if err := adapter.FinalizeDelete(ctx, obj.ID); err != nil {
		t.Fatalf("FinalizeDelete failed: %v", err)
	}
	got, err = adapter.Get(ctx, obj.ID, true)
	if err != nil {
		t.Fatalf("Get after finalize failed: %v", err)
	}
	if got.Status != models.ObjectStatusCeased {
		t.Fatalf("expected ceased status, got %q", got.Status)
	}
	if got.CeasedAt == nil {
		t.Fatal("CeasedAt not set")
	}

	// Delete on non-active should fail.
	if err := adapter.Delete(ctx, obj.ID); err == nil {
		t.Fatal("expected error deleting non-active object")
	}
}

func TestMetadataAdapterFinalizeDeleteRejectsNonDeleted(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	name := "active"
	now := time.Now()
	objectPath, _ := BuildObjectPath(now, nil, name)
	obj := &models.Object{
		ID:        models.ObjectID(name),
		Name:      name,
		Path:      objectPath,
		Status:    models.ObjectStatusActive,
		CreatedAt: now,
		UpdatedAt: now,
	}
	createObjectDir(t, root, obj)

	err := adapter.FinalizeDelete(ctx, obj.ID)
	if err == nil {
		t.Fatal("expected error finalizing active object")
	}
	if !errors.Is(err, apperrors.ErrObjectNotActive) {
		t.Fatalf("expected ErrObjectNotActive, got %v", err)
	}
}

func TestMetadataAdapterList(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	now := time.Now()
	create := func(name string, tags []string, status models.ObjectStatus) {
		objectPath, _ := BuildObjectPath(now, nil, name)
		obj := &models.Object{
			ID:        models.ObjectID(name),
			Name:      name,
			Path:      objectPath,
			Status:    status,
			CreatedAt: now,
			UpdatedAt: now,
			Tags:      tags,
		}
		createObjectDir(t, root, obj)
	}

	create("alpha", []string{"shared", "alpha-tag"}, models.ObjectStatusActive)
	create("beta", []string{"shared", "beta-tag"}, models.ObjectStatusActive)
	create("gamma", []string{"other"}, models.ObjectStatusActive)
	create("deleted", []string{"shared"}, models.ObjectStatusDeleted)

	// Default list returns active objects sorted by CreatedAt desc.
	all, err := adapter.List(ctx, models.ListOptions{})
	if err != nil {
		t.Fatalf("List failed: %v", err)
	}
	if len(all) != 3 {
		t.Fatalf("expected 3 active objects, got %d", len(all))
	}

	// Tag filter.
	filtered, err := adapter.List(ctx, models.ListOptions{Tags: []string{"shared"}})
	if err != nil {
		t.Fatalf("List with tags failed: %v", err)
	}
	if len(filtered) != 2 {
		t.Fatalf("expected 2 objects with shared tag, got %d", len(filtered))
	}

	filtered, err = adapter.List(ctx, models.ListOptions{Tags: []string{"shared", "alpha-tag"}})
	if err != nil {
		t.Fatalf("List with multiple tags failed: %v", err)
	}
	if len(filtered) != 1 || filtered[0].Name != "alpha" {
		t.Fatalf("expected only alpha, got %v", filtered)
	}

	// Pagination.
	page, err := adapter.List(ctx, models.ListOptions{Offset: 1, Limit: 1})
	if err != nil {
		t.Fatalf("List pagination failed: %v", err)
	}
	if len(page) != 1 {
		t.Fatalf("expected 1 object for offset=1 limit=1, got %d", len(page))
	}

	// Include deleted.
	withDeleted, err := adapter.List(ctx, models.ListOptions{IncludeDeleted: true})
	if err != nil {
		t.Fatalf("List includeDeleted failed: %v", err)
	}
	if len(withDeleted) != 4 {
		t.Fatalf("expected 4 objects including deleted, got %d", len(withDeleted))
	}
}

func TestMetadataAdapterSearch(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	now := time.Now()
	create := func(name string, tags []string, status models.ObjectStatus) {
		objectPath, _ := BuildObjectPath(now, nil, name)
		obj := &models.Object{
			ID:        models.ObjectID(name),
			Name:      name,
			Path:      objectPath,
			Status:    status,
			CreatedAt: now,
			UpdatedAt: now,
			Tags:      tags,
		}
		createObjectDir(t, root, obj)
	}

	create("hello-world", []string{"greeting"}, models.ObjectStatusActive)
	create("goodbye", []string{"world-news"}, models.ObjectStatusActive)
	create("hidden", []string{"world"}, models.ObjectStatusDeleted)

	// Name match.
	results, err := adapter.Search(ctx, []string{"hello"}, models.ListOptions{})
	if err != nil {
		t.Fatalf("Search failed: %v", err)
	}
	if len(results) != 1 || results[0].Name != "hello-world" {
		t.Fatalf("expected hello-world, got %v", results)
	}

	// Tag match.
	results, err = adapter.Search(ctx, []string{"world-news"}, models.ListOptions{})
	if err != nil {
		t.Fatalf("Search tag failed: %v", err)
	}
	if len(results) != 1 || results[0].Name != "goodbye" {
		t.Fatalf("expected goodbye, got %v", results)
	}

	// OR terms.
	results, err = adapter.Search(ctx, []string{"hello", "goodbye"}, models.ListOptions{})
	if err != nil {
		t.Fatalf("Search OR failed: %v", err)
	}
	if len(results) != 2 {
		t.Fatalf("expected 2 results for OR, got %d", len(results))
	}

	// Case-insensitive.
	results, err = adapter.Search(ctx, []string{"HELLO"}, models.ListOptions{})
	if err != nil {
		t.Fatalf("Search case-insensitive failed: %v", err)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result for HELLO, got %d", len(results))
	}

	// Include deleted.
	results, err = adapter.Search(ctx, []string{"world"}, models.ListOptions{IncludeDeleted: true})
	if err != nil {
		t.Fatalf("Search includeDeleted failed: %v", err)
	}
	if len(results) != 3 {
		t.Fatalf("expected 3 results including deleted, got %d", len(results))
	}

	// Pagination.
	results, err = adapter.Search(ctx, []string{"world"}, models.ListOptions{IncludeDeleted: true, Offset: 1, Limit: 1})
	if err != nil {
		t.Fatalf("Search pagination failed: %v", err)
	}
	if len(results) != 1 {
		t.Fatalf("expected 1 result for offset=1 limit=1, got %d", len(results))
	}
}

func TestMetadataAdapterAddAndRemoveTag(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	name := "tagged"
	now := time.Now()
	objectPath, _ := BuildObjectPath(now, []string{"classify"}, name)
	obj := &models.Object{
		ID:        models.ObjectID(name),
		Name:      name,
		Path:      objectPath,
		Status:    models.ObjectStatusActive,
		CreatedAt: now,
		UpdatedAt: now,
		Tags:      []string{},
	}
	createObjectDir(t, root, obj)

	// Add inherited tag.
	classifyDir := filepath.Join(root, filepath.Dir(objectPath))
	_ = os.MkdirAll(classifyDir, 0o755)
	_ = WriteTagsFile(filepath.Join(classifyDir, "classify.tags"), []string{"inherited"})

	if err := adapter.AddTag(ctx, obj.ID, "own"); err != nil {
		t.Fatalf("AddTag failed: %v", err)
	}

	got, err := adapter.Get(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("Get after add failed: %v", err)
	}
	if !hasAllTags(got.Tags, []string{"inherited", "own"}) {
		t.Fatalf("expected inherited and own tags, got %v", got.Tags)
	}

	// Adding duplicate should be no-op.
	if err := adapter.AddTag(ctx, obj.ID, "own"); err != nil {
		t.Fatalf("AddTag duplicate failed: %v", err)
	}

	// Remove inherited tag should fail.
	if err := adapter.RemoveTag(ctx, obj.ID, "inherited"); err == nil {
		t.Fatal("expected error removing inherited tag")
	} else if !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatalf("expected ErrInvalidArgument, got %v", err)
	}

	// Remove own tag.
	if err := adapter.RemoveTag(ctx, obj.ID, "own"); err != nil {
		t.Fatalf("RemoveTag failed: %v", err)
	}
	got, err = adapter.Get(ctx, obj.ID, false)
	if err != nil {
		t.Fatalf("Get after remove failed: %v", err)
	}
	if hasAllTags(got.Tags, []string{"own"}) {
		t.Fatalf("own tag should be removed, got %v", got.Tags)
	}

	// Remove missing tag should fail.
	if err := adapter.RemoveTag(ctx, obj.ID, "missing"); err == nil {
		t.Fatal("expected error removing missing tag")
	} else if !errors.Is(err, apperrors.ErrTagNotFound) {
		t.Fatalf("expected ErrTagNotFound, got %v", err)
	}
}

func TestMetadataAdapterRecover(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	now := time.Now()
	create := func(name string, status models.ObjectStatus) {
		objectPath, _ := BuildObjectPath(now, nil, name)
		obj := &models.Object{
			ID:        models.ObjectID(name),
			Name:      name,
			Path:      objectPath,
			Status:    status,
			CreatedAt: now,
			UpdatedAt: now,
		}
		createObjectDir(t, root, obj)
	}

	create("creating-one", models.ObjectStatusCreating)
	create("active-one", models.ObjectStatusActive)
	create("ceased-one", models.ObjectStatusCeased)

	creating, err := adapter.Recover(ctx)
	if err != nil {
		t.Fatalf("Recover failed: %v", err)
	}
	if len(creating) != 1 || creating[0].Name != "creating-one" {
		t.Fatalf("expected only creating-one, got %v", creating)
	}
}

func TestMetadataAdapterGC(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	now := time.Now()
	create := func(name string, status models.ObjectStatus, ceasedAt *time.Time) {
		objectPath, _ := BuildObjectPath(now, nil, name)
		obj := &models.Object{
			ID:        models.ObjectID(name),
			Name:      name,
			Path:      objectPath,
			Status:    status,
			CreatedAt: now,
			UpdatedAt: now,
			CeasedAt:  ceasedAt,
		}
		createObjectDir(t, root, obj)
	}

	old := now.Add(-48 * time.Hour)
	recent := now.Add(-1 * time.Hour)
	create("expired", models.ObjectStatusCeased, &old)
	create("recent", models.ObjectStatusCeased, &recent)
	create("active", models.ObjectStatusActive, nil)

	candidates, err := adapter.GC(ctx, 24*time.Hour)
	if err != nil {
		t.Fatalf("GC failed: %v", err)
	}
	if len(candidates) != 1 || candidates[0].Name != "expired" {
		t.Fatalf("expected only expired, got %v", candidates)
	}
}

func TestMetadataAdapterScanObjectsBoundary(t *testing.T) {
	ctx := context.Background()
	root := t.TempDir()
	adapter := NewMetadataAdapter(root)
	_ = adapter.Init(ctx)
	defer adapter.Close()

	now := time.Now()
	objectPath, _ := BuildObjectPath(now, nil, "parent")
	objectDir := filepath.Join(root, objectPath)
	_ = os.MkdirAll(objectDir, 0o755)

	obj := &models.Object{
		ID:        models.ObjectID("parent"),
		Name:      "parent",
		Path:      objectPath,
		Status:    models.ObjectStatusActive,
		CreatedAt: now,
		UpdatedAt: now,
	}
	data, _ := json.MarshalIndent(obj, "", "  ")
	_ = os.WriteFile(filepath.Join(objectDir, "metadata.json"), data, 0o644)
	_ = os.WriteFile(filepath.Join(objectDir, "parent.md"), []byte("# parent"), 0o644)

	// Nested object.md inside parent should not create a second object.
	nested := filepath.Join(objectDir, "nested")
	_ = os.MkdirAll(nested, 0o755)
	_ = os.WriteFile(filepath.Join(nested, "nested.md"), []byte("# nested"), 0o644)

	objects, err := adapter.scanObjects(ctx, false)
	if err != nil {
		t.Fatalf("scanObjects failed: %v", err)
	}
	if len(objects) != 1 {
		t.Fatalf("expected 1 object, got %d", len(objects))
	}
	if objects[0].Name != "parent" {
		t.Fatalf("expected parent object, got %q", objects[0].Name)
	}
}

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
