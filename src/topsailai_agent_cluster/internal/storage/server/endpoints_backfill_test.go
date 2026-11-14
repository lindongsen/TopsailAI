package serverstorage

import (
	"context"
	"path/filepath"
	"testing"
)

// TestBackfillOfflineSinceRepairsLegacyRows verifies a row that is offline but
// carries no retention clock becomes eligible for expiry, while a connected row
// is never selected. The legacy row is the exact state the gd-dev Server held:
// offline, offline_since_at_ms = 0, and an old update_at_ms.
func TestBackfillOfflineSinceRepairsLegacyRows(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "legacy", "offline", 100)
	setOfflineSince(t, store, "legacy", 0)
	putEndpointInventory(t, store, "online", "online", 100)
	setOfflineSince(t, store, "online", 0)

	updated, err := store.BackfillOfflineSince(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if updated != 1 {
		t.Fatalf("backfilled rows = %d, want 1", updated)
	}
	if got := offlineSinceOf(t, store, "legacy"); got != 100 {
		t.Fatalf("legacy offline_since_at_ms = %d, want 100", got)
	}
	if got := offlineSinceOf(t, store, "online"); got != 0 {
		t.Fatalf("online offline_since_at_ms = %d, want 0", got)
	}

	// The repaired row must now be selectable by the real degrade predicate, and
	// the degraded row must then be selectable by the expiry predicate.
	degraded, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000)
	if err != nil {
		t.Fatal(err)
	}
	if len(degraded.DegradedEndpointIDs) != 1 || degraded.DegradedEndpointIDs[0] != "legacy" {
		t.Fatalf("degrade result = %+v, want legacy degraded", degraded)
	}
	result, err := store.ExpireDegradedEndpoints(ctx, 6000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DeletedEndpointIDs) != 1 || result.DeletedEndpointIDs[0] != "legacy" {
		t.Fatalf("expiry result = %+v, want legacy deleted", result)
	}
	assertRowCount(t, store, "endpoints", "legacy", 0)
	assertRowCount(t, store, "endpoints", "online", 1)
}

// TestBackfillOfflineSinceSkipsZeroUpdateTimestamp verifies a corrupt row is
// left unreachable rather than re-broken. Copying a zero update_at_ms into
// offline_since_at_ms would recreate the very state the backfill removes.
func TestBackfillOfflineSinceSkipsZeroUpdateTimestamp(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "corrupt", "offline", 100)
	setOfflineSince(t, store, "corrupt", 0)
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET update_at_ms = 0 WHERE endpoint_id = ?`, "corrupt"); err != nil {
		t.Fatal(err)
	}

	updated, err := store.BackfillOfflineSince(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if updated != 0 {
		t.Fatalf("backfilled rows = %d, want 0", updated)
	}
	if got := offlineSinceOf(t, store, "corrupt"); got != 0 {
		t.Fatalf("corrupt offline_since_at_ms = %d, want 0", got)
	}
}

// TestBackfillOfflineSincePreservesPositiveOfflineAge verifies an already
// correct row keeps its original clock. Re-deriving it from update_at_ms would
// grant a fresh retention window to a row that has been offline for a while.
func TestBackfillOfflineSincePreservesPositiveOfflineAge(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "aged", "offline", 900)
	setOfflineSince(t, store, "aged", 100)

	updated, err := store.BackfillOfflineSince(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if updated != 0 {
		t.Fatalf("backfilled rows = %d, want 0", updated)
	}
	if got := offlineSinceOf(t, store, "aged"); got != 100 {
		t.Fatalf("aged offline_since_at_ms = %d, want 100", got)
	}
}

// offlineSinceOf reads the retention clock for one Endpoint identity.
func offlineSinceOf(t *testing.T, store *Store, endpointID string) int64 {
	t.Helper()
	var value int64
	if err := store.DB().QueryRowContext(context.Background(), `SELECT offline_since_at_ms FROM endpoints WHERE endpoint_id = ?`, endpointID).Scan(&value); err != nil {
		t.Fatal(err)
	}
	return value
}
