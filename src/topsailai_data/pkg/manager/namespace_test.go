package manager

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/topsailai/topsailai_data/pkg/adapters/local"
	apperrors "github.com/topsailai/topsailai_data/pkg/errors"
)

// TestNamespaceCreateParentPreservesChild prevents replacement of a child tree.
func TestNamespaceCreateParentPreservesChild(t *testing.T) {
	m := newTestManager(t)
	ctx := context.Background()
	child, err := m.CreateObject(ctx, "child", CreateObjectOptions{
		Classify: []string{"parent"}, Data: newMarkdownData(t, "child", "child data"),
	})
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(payloadDirForTest(t, m, child.DataRef), "child.md")
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = m.CreateObject(ctx, "parent", CreateObjectOptions{Data: newMarkdownData(t, "parent", "parent data")})
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("parent create: %v", err)
	}
	after, err := os.ReadFile(path)
	if err != nil || string(after) != string(before) {
		t.Fatalf("child changed: %q, %v", after, err)
	}
}

// TestNamespaceRejectsNestedCreateAndMove preserves existing object boundaries.
func TestNamespaceRejectsNestedCreateAndMove(t *testing.T) {
	m := newTestManager(t)
	ctx := context.Background()
	parent := createTestObject(t, m, "parent")
	child := createTestObject(t, m, "child")
	_, err := m.CreateObject(ctx, "nested", CreateObjectOptions{
		Classify: []string{"parent"}, Data: newMarkdownData(t, "nested", "nested data"),
	})
	if !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("nested create: %v", err)
	}
	if err := m.MoveObject(ctx, child.ID, []string{"parent"}); !errors.Is(err, apperrors.ErrObjectExists) {
		t.Fatalf("nested move: %v", err)
	}
	for _, obj := range []string{parent.DataRef, child.DataRef} {
		if _, err := os.Stat(filepath.Join(payloadDirForTest(t, m, obj), filepath.Base(obj)+".md")); err != nil {
			t.Fatal(err)
		}
	}
}

// TestNamespaceManagerContention proves create and move honor the shared guard.
func TestNamespaceManagerContention(t *testing.T) {
	m := newTestManager(t)
	obj := createTestObject(t, m, "existing")
	lock, err := local.AcquireNamespaceLock(m.Root())
	if err != nil {
		t.Fatal(err)
	}
	defer lock.Release()
	_, err = m.CreateObject(context.Background(), "new", CreateObjectOptions{Data: newMarkdownData(t, "new", "new data")})
	if !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("create ignored namespace lock: %v", err)
	}
	if err := m.MoveObject(context.Background(), obj.ID, []string{"work"}); !errors.Is(err, apperrors.ErrObjectLocked) {
		t.Fatalf("move ignored namespace lock: %v", err)
	}
}
