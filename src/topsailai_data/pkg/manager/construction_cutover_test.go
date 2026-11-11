package manager

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/topsailai/topsailai_data/pkg/adapters"
	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/config"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// TestCutoverConstructionRoot resolves relative storage without changing input configuration.
func TestCutoverConstructionRoot(t *testing.T) {
	absolute := t.TempDir()
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	relative, err := filepath.Rel(cwd, absolute)
	if err != nil {
		t.Fatal(err)
	}
	cfg := &config.Config{
		Root:              relative,
		MetadataAdapter:   "local",
		ActualDataAdapter: "local",
		AdapterConfig:     map[string]string{},
	}
	mgr, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := mgr.Close(); err != nil {
			t.Error(err)
		}
	})
	if mgr.Root() != absolute {
		t.Fatalf("root = %q, want %q", mgr.Root(), absolute)
	}
	if cfg.Root != relative {
		t.Fatalf("input root changed to %q", cfg.Root)
	}
	if _, ok := cfg.AdapterConfig["root"]; ok {
		t.Fatal("input adapter configuration changed")
	}
	for _, name := range []string{"object", "meta"} {
		info, err := os.Stat(filepath.Join(absolute, name))
		if err != nil {
			t.Fatal(err)
		}
		if !info.IsDir() {
			t.Fatalf("%s is not a directory", name)
		}
	}
}

// TestCutoverCreationPublication verifies creation without recursively acquiring its gate.
func TestCutoverCreationPublication(t *testing.T) {
	cfg := &config.Config{Root: t.TempDir(), MetadataAdapter: "local", ActualDataAdapter: "local", ReadLock: true, TrackStat: false}
	mgr, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := mgr.Close(); err != nil {
			t.Error(err)
		}
	})
	obj, err := mgr.CreateObject(context.Background(), "probe", CreateObjectOptions{
		Tags: []string{"own"}, Data: newMarkdownData(t, "probe", "creation boundary"),
	})
	if err != nil {
		t.Fatal(err)
	}
	if obj.DataRef != obj.Path || filepath.IsAbs(obj.DataRef) {
		t.Fatalf("nonrelative reference: %q", obj.DataRef)
	}
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ObjectMetaPath(obj.ID)
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(dir, "metadata.json"))
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(data, []byte(`"tags"`)) {
		t.Fatal("disk record contains tags")
	}
	if _, err := os.Stat(filepath.Join(layout.ObjectRoot(), filepath.FromSlash(obj.Path), "probe.md")); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "tags")); err != nil {
		t.Fatal(err)
	}
	_, err = mgr.CreateObject(context.Background(), "probe", CreateObjectOptions{Data: newMarkdownData(t, "probe", "replacement")})
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("duplicate creation: %v", err)
	}
	after, err := mgr.meta.Get(context.Background(), obj.ID, false)
	if err != nil {
		t.Fatal(err)
	}
	if after.Description != obj.Description || len(after.Tags) != 1 || after.Tags[0] != "own" {
		t.Fatalf("duplicate changed record: %+v", after)
	}
}

// cutoverFailArchive injects a payload failure while retaining real adapter behavior elsewhere.
type cutoverFailArchive struct {
	adapters.ActualDataAdapter
	failure error
}

// WriteArchive fails before payload replacement to exercise creating-state retention.
func (a cutoverFailArchive) WriteArchive(context.Context, string, io.Reader) (string, error) {
	return "", a.failure
}

// TestCutoverCreationFailure keeps a discoverable record and nesting boundary.
func TestCutoverCreationFailure(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	original := mgr.actual
	failure := errors.New("injected archive failure")
	mgr.actual = cutoverFailArchive{ActualDataAdapter: original, failure: failure}
	ctx := context.Background()
	_, err := mgr.CreateObject(ctx, "probe", CreateObjectOptions{Tags: []string{"retained"}, Data: newMarkdownData(t, "probe", "failed creation")})
	if !errors.Is(err, failure) {
		t.Fatalf("failure lost: %v", err)
	}
	obj, err := mgr.meta.Get(ctx, "probe", true)
	if err != nil {
		t.Fatal(err)
	}
	if obj.Status != models.ObjectStatusCreating || len(obj.Tags) != 1 || obj.Tags[0] != "retained" {
		t.Fatalf("recovery state: %+v", obj)
	}
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	dir, err := layout.ResolveObjectRef(obj.DataRef)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "probe.md")); err != nil {
		t.Fatal(err)
	}
	mgr.actual = original
	_, err = mgr.CreateObject(ctx, "nested", CreateObjectOptions{Classify: []string{"probe"}, Data: newMarkdownData(t, "nested", "nested")})
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("creating boundary ignored: %v", err)
	}
	if _, err := mgr.meta.Get(ctx, "probe", false); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("creating visible: %v", err)
	}
}

// TestCutoverCreationReplacesCeased releases the removed leaf lock before replacement.
func TestCutoverCreationReplacesCeased(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	ctx := context.Background()
	obj := createTestObject(t, mgr, "probe", "old")
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	gate, err := local.AcquireNamespaceLock(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	lock, err := layout.AcquireMetadataLockUnderNamespace(obj.ID, true)
	if err != nil {
		_ = gate.Release()
		t.Fatal(err)
	}
	oldInfo, err := os.Stat(lock.Path())
	if err != nil {
		t.Fatal(err)
	}
	if err := mgr.meta.Delete(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if err := mgr.actual.Delete(ctx, obj.DataRef); err != nil {
		t.Fatal(err)
	}
	if err := mgr.meta.FinalizeDelete(ctx, obj.ID); err != nil {
		t.Fatal(err)
	}
	if err := lock.Release(); err != nil {
		t.Fatal(err)
	}
	if err := gate.Release(); err != nil {
		t.Fatal(err)
	}
	replacement, err := mgr.CreateObject(ctx, "probe", CreateObjectOptions{Tags: []string{"new"}, Data: newMarkdownData(t, "probe", "replacement")})
	if err != nil {
		t.Fatal(err)
	}
	if replacement.Status != models.ObjectStatusActive || len(replacement.Tags) != 1 || replacement.Tags[0] != "new" {
		t.Fatalf("replacement: %+v", replacement)
	}
	current, err := layout.AcquireExistingMetadataLock(obj.ID, true)
	if err != nil {
		t.Fatal(err)
	}
	defer current.Release()
	newInfo, err := os.Stat(current.Path())
	if err != nil {
		t.Fatal(err)
	}
	if os.SameFile(oldInfo, newInfo) {
		t.Log("filesystem reused the released lock inode; successful current lock acquisition is the custody evidence")
	}
}

// TestCutoverRejectedReplacementPreservesCeased checks preflight before retirement.
func TestCutoverRejectedReplacementPreservesCeased(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	ctx := context.Background()
	obj := createTestObject(t, mgr, "probe", "old")
	if err := mgr.AddTag(ctx, obj.ID, "retained"); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if err := mgr.DeleteObject(ctx, obj.ID); err != nil {
			t.Fatal(err)
		}
	}
	layout, err := local.NewStoreLayout(mgr.Root())
	if err != nil {
		t.Fatal(err)
	}
	meta, err := layout.ObjectMetaPath(obj.ID)
	if err != nil {
		t.Fatal(err)
	}
	before, err := os.Stat(filepath.Join(meta, "lock"))
	if err != nil {
		t.Fatal(err)
	}
	ref, err := local.BuildObjectPath(time.Now(), []string{"blocked"}, "probe")
	if err != nil {
		t.Fatal(err)
	}
	destination, err := layout.ResolveObjectRef(ref)
	if err != nil {
		t.Fatal(err)
	}
	obstruction := filepath.Dir(destination)
	if err := os.MkdirAll(filepath.Dir(obstruction), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(obstruction, []byte("unrelated"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, err = mgr.CreateObject(ctx, "probe", CreateObjectOptions{Classify: []string{"blocked"}, Data: newMarkdownData(t, "probe", "replacement")})
	if err == nil {
		t.Fatal("occupied ancestor accepted")
	}
	retained, err := mgr.meta.Get(ctx, obj.ID, true)
	if err != nil {
		t.Fatal(err)
	}
	if retained.Status != models.ObjectStatusCeased || len(retained.Tags) != 2 || retained.Tags[0] != "old" || retained.Tags[1] != "retained" {
		t.Fatalf("ceased record changed: %+v", retained)
	}
	after, err := os.Stat(filepath.Join(meta, "lock"))
	if err != nil {
		t.Fatal(err)
	}
	if !os.SameFile(before, after) {
		t.Fatal("rejected replacement changed lock identity")
	}
	data, err := os.ReadFile(obstruction)
	if err != nil || string(data) != "unrelated" {
		t.Fatalf("obstruction changed: %q, %v", data, err)
	}
}
