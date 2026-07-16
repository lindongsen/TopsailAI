package models

import (
	"testing"
	"time"
)

func TestObjectIDString(t *testing.T) {
	id := ObjectID("hello-world")
	if got := id.String(); got != "hello-world" {
		t.Fatalf("String() = %q, want %q", got, "hello-world")
	}
}

func TestObjectStatusIsFinal(t *testing.T) {
	cases := []struct {
		status ObjectStatus
		want   bool
	}{
		{ObjectStatusCreating, false},
		{ObjectStatusActive, false},
		{ObjectStatusDeleted, false},
		{ObjectStatusCeased, true},
		{ObjectStatus("unknown"), false},
	}

	for _, tc := range cases {
		t.Run(string(tc.status), func(t *testing.T) {
			if got := tc.status.IsFinal(); got != tc.want {
				t.Fatalf("IsFinal() = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestObjectClone(t *testing.T) {
	deletedAt := time.Now()
	ceasedAt := deletedAt.Add(time.Hour)
	original := Object{
		ID:            ObjectID("obj"),
		Name:          "obj",
		Path:          "2026/0714/2323/obj",
		Tags:          []string{"a", "b", "c"},
		Status:        ObjectStatusActive,
		SchemaVersion: 1,
		CreatedAt:     time.Now(),
		UpdatedAt:     time.Now(),
		DeletedAt:     &deletedAt,
		CeasedAt:      &ceasedAt,
		DataRef:       "ref",
	}

	cloned := original.Clone()

	if cloned.ID != original.ID {
		t.Fatalf("ID mismatch")
	}
	if cloned.Name != original.Name {
		t.Fatalf("Name mismatch")
	}
	if cloned.Path != original.Path {
		t.Fatalf("Path mismatch")
	}
	if cloned.DataRef != original.DataRef {
		t.Fatalf("DataRef mismatch")
	}

	// Mutate clone tags and verify original is unchanged.
	cloned.Tags[0] = "changed"
	if original.Tags[0] != "a" {
		t.Fatalf("original tags were mutated")
	}

	// Mutate clone timestamps and verify original is unchanged.
	*cloned.DeletedAt = time.Time{}
	if original.DeletedAt.IsZero() {
		t.Fatalf("original DeletedAt was mutated")
	}
	*cloned.CeasedAt = time.Time{}
	if original.CeasedAt.IsZero() {
		t.Fatalf("original CeasedAt was mutated")
	}
}

func TestObjectCloneNilSlicesAndPointers(t *testing.T) {
	original := Object{
		ID:     ObjectID("empty"),
		Name:   "empty",
		Status: ObjectStatusActive,
	}

	cloned := original.Clone()

	if cloned.Tags != nil {
		t.Fatalf("expected nil tags in clone, got %v", cloned.Tags)
	}
	if cloned.DeletedAt != nil {
		t.Fatalf("expected nil DeletedAt in clone")
	}
	if cloned.CeasedAt != nil {
		t.Fatalf("expected nil CeasedAt in clone")
	}
}

func TestListOptionsDefaults(t *testing.T) {
	opts := ListOptions{}
	if opts.Offset != 0 {
		t.Fatalf("expected default offset 0, got %d", opts.Offset)
	}
	if opts.Limit != 0 {
		t.Fatalf("expected default limit 0, got %d", opts.Limit)
	}
	if opts.IncludeDeleted {
		t.Fatal("expected default IncludeDeleted false")
	}
	if opts.Tags != nil {
		t.Fatalf("expected nil tags by default, got %v", opts.Tags)
	}
}

func TestAdapterConfig(t *testing.T) {
	cfg := AdapterConfig{"root": "/data", "bucket": "my-bucket"}
	if cfg["root"] != "/data" {
		t.Fatalf("expected root /data, got %q", cfg["root"])
	}
	if cfg["bucket"] != "my-bucket" {
		t.Fatalf("expected bucket my-bucket, got %q", cfg["bucket"])
	}
}
