package endpointstorage

import (
	"context"
	"path/filepath"
	"testing"
)

// openIdentityStore opens a fresh Endpoint store for identity tests.
func openIdentityStore(t *testing.T) *Store {
	t.Helper()
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "endpoint.sqlite"))
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store
}

// TestObserveServerIdentityReportsOnlyARealChange proves the storage rule that
// decides whether recorded receipts may be discarded.
//
// The empty-identity case is proven here rather than through the Service,
// because the Service returns before calling this method when the identity is
// empty. The guard is therefore unreachable from that path and would otherwise
// be certified by a test that never executes it.
func TestObserveServerIdentityReportsOnlyARealChange(t *testing.T) {
	ctx := context.Background()
	store := openIdentityStore(t)

	changed, err := store.ObserveServerIdentity(ctx, "server-a", 1)
	if err != nil {
		t.Fatalf("first observation: %v", err)
	}
	if changed {
		t.Fatal("the first observation reported a change, but there is no previous Server to differ from")
	}

	changed, err = store.ObserveServerIdentity(ctx, "server-a", 2)
	if err != nil {
		t.Fatalf("repeat observation: %v", err)
	}
	if changed {
		t.Fatal("a repeated identity reported a change, so a restarted Server would lose receipts it can still apply")
	}

	changed, err = store.ObserveServerIdentity(ctx, "server-b", 3)
	if err != nil {
		t.Fatalf("changed observation: %v", err)
	}
	if !changed {
		t.Fatal("a different identity reported no change, so a re-home would never discard inapplicable receipts")
	}

	changed, err = store.ObserveServerIdentity(ctx, "", 4)
	if err != nil {
		t.Fatalf("empty observation: %v", err)
	}
	if changed {
		t.Fatal("an absent identity reported a change, so an older Server would be mistaken for a new one")
	}

	// The empty observation must not overwrite the recorded identity either,
	// because the next real observation would then look like a change.
	changed, err = store.ObserveServerIdentity(ctx, "server-b", 5)
	if err != nil {
		t.Fatalf("observation after empty: %v", err)
	}
	if changed {
		t.Fatal("an empty observation overwrote the stored identity, so the same Server looked like a new one")
	}
}
