package manager

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/topsailai/topsailai_data/pkg/adapters"
	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	"github.com/topsailai/topsailai_data/pkg/models"
)

// cutoverFailUpdate injects metadata publication failure without replacing storage.
type cutoverFailUpdate struct {
	adapters.MetadataAdapter
	failure error
}

// Update preserves the original record while reporting injected failure.
func (a cutoverFailUpdate) Update(context.Context, *models.Object) error { return a.failure }

// TestCutoverMovePublication retains hash custody and tags across relative-ref moves.
func TestCutoverMovePublication(t *testing.T) {
	mgr := newTestManager(t)
	mgr.TrackStat = false
	ctx := context.Background()
	obj, err := mgr.CreateObject(ctx, "probe", CreateObjectOptions{Tags: []string{"own"}, Data: newMarkdownData(t, "probe", "body")})
	if err != nil {
		t.Fatal(err)
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
	oldPayload, err := layout.ResolveObjectRef(obj.DataRef)
	if err != nil {
		t.Fatal(err)
	}
	if err := mgr.MoveObject(ctx, obj.ID, []string{"work"}); err != nil {
		t.Fatal(err)
	}
	moved, err := mgr.GetObject(ctx, obj.ID, false)
	if err != nil {
		t.Fatal(err)
	}
	if moved.DataRef != moved.Path || filepath.IsAbs(moved.DataRef) || moved.Path == obj.Path || len(moved.Tags) != 1 || moved.Tags[0] != "own" {
		t.Fatalf("moved record: %+v", moved)
	}
	after, err := os.Stat(filepath.Join(meta, "lock"))
	if err != nil || !os.SameFile(before, after) {
		t.Fatalf("move replaced hash lock: %v", err)
	}
	if _, err := os.Lstat(oldPayload); !os.IsNotExist(err) {
		t.Fatalf("old payload survived successful move: %v", err)
	}
	target, err := layout.ResolveObjectRef(moved.DataRef)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(target, "probe.md")); err != nil {
		t.Fatal(err)
	}
}

// TestCutoverMoveFailureOwnership preserves both copies around metadata or cleanup failures.
func TestCutoverMoveFailureOwnership(t *testing.T) {
	for _, phase := range []string{"metadata", "source-cleanup"} {
		t.Run(phase, func(t *testing.T) {
			mgr := newTestManager(t)
			mgr.TrackStat = false
			ctx := context.Background()
			obj := createTestObject(t, mgr, "probe")
			layout, err := local.NewStoreLayout(mgr.Root())
			if err != nil {
				t.Fatal(err)
			}
			targetRef, err := local.BuildObjectPath(obj.CreatedAt, []string{"work"}, obj.Name)
			if err != nil {
				t.Fatal(err)
			}
			failure := errors.New("injected move failure")
			if phase == "metadata" {
				mgr.meta = cutoverFailUpdate{MetadataAdapter: mgr.meta, failure: failure}
			} else {
				mgr.actual = cutoverFailDelete{ActualDataAdapter: mgr.actual, failure: failure}
			}
			if err := mgr.MoveObject(ctx, obj.ID, []string{"work"}); !errors.Is(err, failure) {
				t.Fatalf("lost move failure: %v", err)
			}
			current, err := mgr.meta.Get(ctx, obj.ID, true)
			if err != nil {
				t.Fatal(err)
			}
			expected := obj.DataRef
			if phase == "source-cleanup" {
				expected = targetRef
			}
			if current.DataRef != expected {
				t.Fatalf("wrong authority: %q expected %q", current.DataRef, expected)
			}
			for _, ref := range []string{obj.DataRef, targetRef} {
				dir, err := layout.ResolveObjectRef(ref)
				if err != nil {
					t.Fatal(err)
				}
				if _, err := os.Stat(filepath.Join(dir, "probe.md")); err != nil {
					t.Fatalf("lost move copy: %v", err)
				}
			}
		})
	}
}
