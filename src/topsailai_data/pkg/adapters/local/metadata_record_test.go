package local

import (
	"encoding/json"
	"errors"
	"reflect"
	"testing"
	"time"

	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// TestMetadataRecordRoundTrip checks all disk fields without public tag suppression.
func TestMetadataRecordRoundTrip(t *testing.T) {
	now := time.Date(2026, 11, 11, 9, 0, 0, 0, time.UTC)
	obj := &models.Object{ID: "probe", Name: "probe", Path: "2026/1111/0900/work/probe", Description: "test", Tags: []string{"work"}, Status: models.ObjectStatusCeased, SchemaVersion: models.CurrentSchemaVersion, CreatedAt: now, UpdatedAt: now, DeletedAt: &now, CeasedAt: &now, DataRef: "2026/1111/0900/work/probe"}
	before := obj.Clone()
	data, err := encodeMetadataRecord(obj)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		t.Fatal(err)
	}
	if _, ok := fields["Tags"]; ok {
		t.Fatal("disk record persists tags")
	}
	if len(fields) != 11 {
		t.Fatalf("unexpected disk fields: %d", len(fields))
	}
	public, err := json.Marshal(obj)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(public, &fields); err != nil {
		t.Fatal(err)
	}
	if _, ok := fields["Tags"]; !ok {
		t.Fatal("public tags lost")
	}
	got, err := decodeMetadataRecord(data)
	if err != nil {
		t.Fatal(err)
	}
	want := obj.Clone()
	want.Tags = nil
	if !reflect.DeepEqual(*got, want) {
		t.Fatalf("round trip: %#v", got)
	}
	*got.DeletedAt = now.Add(time.Hour)
	*got.CeasedAt = now.Add(2 * time.Hour)
	if !reflect.DeepEqual(*obj, before) {
		t.Fatal("codec mutated original object")
	}
}

// TestMetadataRecordRejectsIncompatible checks strict parsing and schema handling.
func TestMetadataRecordRejectsIncompatible(t *testing.T) {
	for _, data := range []string{
		`{`, `null`, `{}`, `{"ID":"probe","Name":"probe","SchemaVersion":999}`,
		`{"ID":"probe","Name":"other","SchemaVersion":2}`,
		`{"ID":"../probe","Name":"../probe","SchemaVersion":2}`,
		`{"ID":"probe","Name":"probe","SchemaVersion":2,"Tags":["old"]}`,
		`{"ID":"probe","Name":"probe","SchemaVersion":2,"extra":1}`,
		`{"ID":"probe","Name":"probe","SchemaVersion":2} {}`,
		`{"ID":"probe","Name":"probe","SchemaVersion":2} trailing`,
	} {
		if _, err := decodeMetadataRecord([]byte(data)); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
			t.Fatalf("accepted %q: %v", data, err)
		}
	}
	if _, err := encodeMetadataRecord(nil); !errors.Is(err, apperrors.ErrInvalidArgument) {
		t.Fatal(err)
	}
	if _, err := encodeMetadataRecord(&models.Object{}); err == nil {
		t.Fatal("invalid object accepted")
	}
	obj := &models.Object{ID: "probe", Name: "probe", Path: "2026/1111/0900/probe", DataRef: "2026/1111/0900/probe", Status: models.ObjectStatusActive, SchemaVersion: models.CurrentSchemaVersion, CreatedAt: time.Date(10000, 1, 1, 0, 0, 0, 0, time.UTC)}
	if _, err := encodeMetadataRecord(obj); err == nil {
		t.Fatal("invalid timestamp accepted")
	}
}

// TestMetadataRecordLocationContract rejects unsafe or mismatched disk references.
func TestMetadataRecordLocationContract(t *testing.T) {
	base := models.Object{ID: "probe", Name: "probe", Path: "2026/1111/0900/probe", DataRef: "2026/1111/0900/probe", Status: models.ObjectStatusActive, SchemaVersion: models.CurrentSchemaVersion}
	for _, status := range []models.ObjectStatus{models.ObjectStatusCreating, models.ObjectStatusActive, models.ObjectStatusDeleted, models.ObjectStatusCeased} {
		obj := base.Clone()
		obj.Status = status
		data, err := encodeMetadataRecord(&obj)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := decodeMetadataRecord(data); err != nil {
			t.Fatalf("valid state %s: %v", status, err)
		}
	}
	for _, kind := range []string{"status", "missing", "absolute", "traversal", "prefix", "identity", "reference"} {
		t.Run(kind, func(t *testing.T) {
			obj := base.Clone()
			switch kind {
			case "status":
				obj.Status = "unknown"
			case "missing":
				obj.Path, obj.DataRef = "", ""
			case "absolute":
				obj.Path = "/2026/1111/0900/probe"
			case "traversal":
				obj.Path = "2026/1111/0900/../probe"
			case "prefix":
				obj.Path = "year/1111/0900/probe"
			case "identity":
				obj.Path, obj.DataRef = "2026/1111/0900/other", "2026/1111/0900/other"
			case "reference":
				obj.DataRef = "2026/1111/0900/other"
			}
			if _, err := encodeMetadataRecord(&obj); err == nil {
				t.Fatal("unsafe object encoded")
			}
			record := metadataRecord{ID: obj.ID, Name: obj.Name, Path: obj.Path, DataRef: obj.DataRef, Status: obj.Status, SchemaVersion: obj.SchemaVersion}
			data, err := json.Marshal(record)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := decodeMetadataRecord(data); !errors.Is(err, apperrors.ErrCorruptedMetadata) {
				t.Fatalf("unsafe disk record accepted: %v", err)
			}
		})
	}
}
