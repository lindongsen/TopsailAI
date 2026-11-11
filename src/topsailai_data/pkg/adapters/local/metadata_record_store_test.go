package local

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"testing"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// recordStoreFixture prepares a valid local record in a locked metadata directory.
func recordStoreFixture(t *testing.T) (StoreLayout, *models.Object, string) {
	t.Helper()
	layout := metadataLockLayout(t)
	lock, err := layout.AcquireMetadataLock("probe", true)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := lock.Release(); err != nil {
			t.Error(err)
		}
	})
	obj := &models.Object{ID: "probe", Name: "probe", Path: "2026/1111/0900/probe", DataRef: "2026/1111/0900/probe", Status: models.ObjectStatusActive, SchemaVersion: models.CurrentSchemaVersion, Tags: []string{"private"}}
	return layout, obj, filepath.Dir(lock.Path())
}

// TestHashMetadataRecordStore checks round trip, absent records and safe replacement.
func TestHashMetadataRecordStore(t *testing.T) {
	layout, obj, dir := recordStoreFixture(t)
	if _, err := layout.readMetadataRecord(obj.ID); !errors.Is(err, apperrors.ErrObjectNotFound) {
		t.Fatalf("missing record: %v", err)
	}
	if err := layout.writeMetadataRecord(obj); err != nil {
		t.Fatal(err)
	}
	got, err := layout.readMetadataRecord(obj.ID)
	if err != nil || got.ID != obj.ID || len(got.Tags) != 0 {
		t.Fatalf("round trip: %#v %v", got, err)
	}
	path := filepath.Join(dir, "metadata.json")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	obj.DataRef = "../unsafe"
	if err := layout.writeMetadataRecord(obj); err == nil {
		t.Fatal("unsafe write accepted")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatalf("failed write changed record: %v", err)
	}
}

// TestHashMetadataRecordRejectsMisplaced checks valid records cannot impersonate IDs.
func TestHashMetadataRecordRejectsMisplaced(t *testing.T) {
	layout, obj, dir := recordStoreFixture(t)
	obj.ID, obj.Name = "other", "other"
	obj.Path, obj.DataRef = "2026/1111/0900/other", "2026/1111/0900/other"
	data, err := encodeMetadataRecord(obj)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "metadata.json")
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := layout.readMetadataRecord("probe"); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("misplaced record accepted: %v", err)
	}
	if err := os.WriteFile(path, []byte("{"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := layout.readMetadataRecord("probe"); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("corrupt record accepted: %v", err)
	}
}

// TestHashMetadataRecordRejectsAliases checks leaf validation for reads and writes.
func TestHashMetadataRecordRejectsAliases(t *testing.T) {
	layout, obj, dir := recordStoreFixture(t)
	path := filepath.Join(dir, "metadata.json")
	target := filepath.Join(t.TempDir(), "target")
	if err := os.WriteFile(target, []byte("sentinel"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, path); err != nil {
		t.Fatal(err)
	}
	if _, err := layout.readMetadataRecord(obj.ID); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("alias read accepted: %v", err)
	}
	if err := layout.writeMetadataRecord(obj); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("alias write accepted: %v", err)
	}
	data, err := os.ReadFile(target)
	if err != nil || string(data) != "sentinel" {
		t.Fatalf("alias target modified: %q %v", data, err)
	}
}

// TestHashMetadataRecordPublishFailure verifies rename failure leaves no temporary files.
func TestHashMetadataRecordPublishFailure(t *testing.T) {
	layout, obj, dir := recordStoreFixture(t)
	path := filepath.Join(dir, "metadata.json")
	if err := os.Mkdir(path, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := layout.readMetadataRecord(obj.ID); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("directory read accepted: %v", err)
	}
	if err := layout.writeMetadataRecord(obj); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
		t.Fatalf("directory write accepted: %v", err)
	}
	if err := publishMetadataRecord(path, []byte("record")); err == nil {
		t.Fatal("rename to directory accepted")
	}
	matches, err := filepath.Glob(filepath.Join(dir, ".metadata-*.tmp"))
	if err != nil || len(matches) != 0 {
		t.Fatalf("temporary files leaked: %v %v", matches, err)
	}
	if err := publishMetadataRecord(filepath.Join(dir, "missing", "metadata.json"), nil); err == nil {
		t.Fatal("missing parent accepted")
	}
}

// TestHashMetadataRecordInvalidLocations checks resolution and missing-directory failures.
func TestHashMetadataRecordInvalidLocations(t *testing.T) {
	layout, obj, _ := recordStoreFixture(t)
	if _, err := layout.readMetadataRecord("../probe"); !errors.Is(err, apperrors.ErrInvalidName) {
		t.Fatalf("invalid ID accepted: %v", err)
	}
	obj.ID, obj.Name = "missing", "missing"
	obj.Path, obj.DataRef = "2026/1111/0900/missing", "2026/1111/0900/missing"
	if err := layout.writeMetadataRecord(obj); err == nil {
		t.Fatal("write created missing directory")
	}
	other, err := NewStoreLayout(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(t.TempDir(), other.MetaRoot()); err != nil {
		t.Fatal(err)
	}
	if _, err := other.readMetadataRecord(obj.ID); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("alias directory read accepted: %v", err)
	}
	if err := other.writeMetadataRecord(obj); !errors.Is(err, apperrors.ErrInvalidPath) {
		t.Fatalf("alias directory write accepted: %v", err)
	}
}
