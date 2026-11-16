package serverstorage

import (
	"context"
	"path/filepath"
	"testing"
)

// TestServerIdentityIsDurableAcrossRestart proves the identity names the
// database rather than the process.
//
// A per-process value would change on every restart, so an Endpoint would
// abandon receipts that the restarted Server still holds and could still apply.
// Durability is what makes "same database" and "same identity" the same fact.
func TestServerIdentityIsDurableAcrossRestart(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.sqlite")

	first, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open server store: %v", err)
	}
	identity, err := first.ServerIdentity(ctx)
	if err != nil {
		t.Fatalf("read server identity: %v", err)
	}
	if identity == "" {
		t.Fatal("server identity is empty, so an Endpoint could never tell one Server from another")
	}
	if err := first.Close(); err != nil {
		t.Fatalf("close server store: %v", err)
	}

	second, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("reopen server store: %v", err)
	}
	t.Cleanup(func() { _ = second.Close() })
	reopened, err := second.ServerIdentity(ctx)
	if err != nil {
		t.Fatalf("read reopened server identity: %v", err)
	}
	if reopened != identity {
		t.Fatalf("identity after restart = %q, want %q", reopened, identity)
	}
}

// TestServerIdentityDiffersBetweenDatabases proves two Servers cannot share an
// identity by accident, because a shared identity would make a re-home
// undetectable and leave inapplicable receipts in the resend set forever.
func TestServerIdentityDiffersBetweenDatabases(t *testing.T) {
	ctx := context.Background()
	first, err := Open(ctx, filepath.Join(t.TempDir(), "a.sqlite"))
	if err != nil {
		t.Fatalf("open first store: %v", err)
	}
	t.Cleanup(func() { _ = first.Close() })
	second, err := Open(ctx, filepath.Join(t.TempDir(), "b.sqlite"))
	if err != nil {
		t.Fatalf("open second store: %v", err)
	}
	t.Cleanup(func() { _ = second.Close() })

	a, err := first.ServerIdentity(ctx)
	if err != nil {
		t.Fatalf("read first identity: %v", err)
	}
	b, err := second.ServerIdentity(ctx)
	if err != nil {
		t.Fatalf("read second identity: %v", err)
	}
	if a == b {
		t.Fatalf("two databases share identity %q, so a re-home would be undetectable", a)
	}
}
