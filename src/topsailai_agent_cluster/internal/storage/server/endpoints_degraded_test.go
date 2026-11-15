package serverstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestDegradeOfflineEndpointsMovesOnlyStaleOfflineRows verifies degradation
// selects exactly the rows that have been offline past the offline window, and
// that it degrades rather than deletes them.
//
// The metadata row must survive because the degraded window is the only period
// in which an operator can still see that the machine existed, when it was last
// seen and when its record will be removed. Deleting at this point would make
// the degraded retention setting meaningless.
func TestDegradeOfflineEndpointsMovesOnlyStaleOfflineRows(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	for _, item := range []struct {
		id      string
		state   string
		offline int64
	}{
		{id: "stale", state: "offline", offline: 100},
		{id: "recent", state: "offline", offline: 300},
		{id: "online", state: "online", offline: 0},
	} {
		putEndpointInventory(t, store, item.id, item.state, 100)
		setOfflineSince(t, store, item.id, item.offline)
	}

	result, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DegradedEndpointIDs) != 1 || result.DegradedEndpointIDs[0] != "stale" {
		t.Fatalf("degrade result = %+v, want only stale degraded", result)
	}
	if len(result.InventoryEndpointIDs) != 1 || result.InventoryEndpointIDs[0] != "stale" {
		t.Fatalf("degrade inventory = %+v, want only stale inventory removed", result.InventoryEndpointIDs)
	}

	// The metadata row survives with a materialized deadline.
	assertRowCount(t, store, "endpoints", "stale", 1)
	assertRowCount(t, store, "endpoint_session_state", "stale", 0)
	state, degradedSince, expiresAt := endpointLifecycleOf(t, store, "stale")
	if state != "degraded" || degradedSince != 1000 || expiresAt != 6000 {
		t.Fatalf("stale state=%q degraded_since=%d expires_at=%d, want degraded/1000/6000", state, degradedSince, expiresAt)
	}

	// A recent offline row keeps its inventory and stays offline.
	assertRowCount(t, store, "endpoints", "recent", 1)
	assertRowCount(t, store, "endpoint_session_state", "recent", 1)
	if state, _, _ := endpointLifecycleOf(t, store, "recent"); state != "offline" {
		t.Fatalf("recent state = %q, want offline", state)
	}

	// A connected row is untouched.
	assertRowCount(t, store, "endpoints", "online", 1)
	assertRowCount(t, store, "endpoint_session_state", "online", 1)
	if state, _, _ := endpointLifecycleOf(t, store, "online"); state != "online" {
		t.Fatalf("online state = %q, want online", state)
	}
}

// TestDegradeOfflineEndpointsNeverSelectsOnlineRows verifies the connection-state
// guard is load-bearing rather than redundant.
//
// The production write paths cannot produce an online row with a positive
// offline_since_at_ms: UpsertEndpoint forces the clock to zero for an online
// state, and MarkPersistedEndpointsOffline converts every online row to offline
// before a sweep runs. The guard therefore protects against a corrupt or
// hand-edited row, which is exactly the state this test writes directly. Without
// the guard, a positive clock alone would make a live Endpoint eligible and its
// inventory would be deleted while the machine is still connected.
func TestDegradeOfflineEndpointsNeverSelectsOnlineRows(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "corrupt-online", "online", 100)
	setOfflineSince(t, store, "corrupt-online", 100)

	result, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DegradedEndpointIDs) != 0 || len(result.InventoryEndpointIDs) != 0 {
		t.Fatalf("degrade selected an online row: %+v", result)
	}
	assertRowCount(t, store, "endpoints", "corrupt-online", 1)
	assertRowCount(t, store, "endpoint_session_state", "corrupt-online", 1)
}

// TestDegradeOfflineEndpointsSkipsZeroOfflineClock verifies a row with no
// retention clock is not degraded. Such a row has no evidence of when it went
// offline, so degrading it would invent a deadline from nothing.
func TestDegradeOfflineEndpointsSkipsZeroOfflineClock(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "no-clock", "offline", 100)
	setOfflineSince(t, store, "no-clock", 0)

	result, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DegradedEndpointIDs) != 0 {
		t.Fatalf("degrade selected a row without an offline clock: %+v", result)
	}
	if state, _, _ := endpointLifecycleOf(t, store, "no-clock"); state != "offline" {
		t.Fatalf("state = %q, want offline", state)
	}
}

// TestDegradeOfflineEndpointsIsIdempotent verifies a second sweep degrades
// nothing. Without the offline predicate the already-degraded row would be
// re-selected and its deadline pushed forward on every sweep, so the record
// would never expire.
func TestDegradeOfflineEndpointsIsIdempotent(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "stale", "offline", 100)
	setOfflineSince(t, store, "stale", 100)

	if _, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000); err != nil {
		t.Fatal(err)
	}
	_, firstDegradedSince, firstExpiresAt := endpointLifecycleOf(t, store, "stale")

	result, err := store.DegradeOfflineEndpoints(ctx, 200, 2000, 5000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DegradedEndpointIDs) != 0 {
		t.Fatalf("second sweep re-degraded a degraded row: %+v", result)
	}
	_, degradedSince, expiresAt := endpointLifecycleOf(t, store, "stale")
	if degradedSince != firstDegradedSince || expiresAt != firstExpiresAt {
		t.Fatalf("deadline moved on re-sweep: degraded_since %d->%d expires_at %d->%d", firstDegradedSince, degradedSince, firstExpiresAt, expiresAt)
	}
}

// TestDegradeOfflineEndpointsRejectsInvalidArguments verifies a zero cutoff,
// timestamp or retention is refused rather than selecting every row or writing a
// deadline in the past.
func TestDegradeOfflineEndpointsRejectsInvalidArguments(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	cases := []struct {
		name        string
		cutoffMS    int64
		nowMS       int64
		retentionMS int64
	}{
		{name: "zero cutoff", cutoffMS: 0, nowMS: 1000, retentionMS: 5000},
		{name: "zero now", cutoffMS: 200, nowMS: 0, retentionMS: 5000},
		{name: "zero retention", cutoffMS: 200, nowMS: 1000, retentionMS: 0},
	}
	for _, test := range cases {
		if _, err := store.DegradeOfflineEndpoints(ctx, test.cutoffMS, test.nowMS, test.retentionMS); err == nil {
			t.Fatalf("%s was accepted", test.name)
		}
	}
}

// putEndpointInventory stores one Endpoint and one latest inventory projection.
func putEndpointInventory(t *testing.T, store *Store, endpointID, state string, updatedAtMS int64) {
	t.Helper()
	ctx := context.Background()
	endpoint := protocol.Endpoint{EndpointID: endpointID, InstanceID: "instance-" + endpointID, DisplayName: endpointID, ConnectionState: state, ObservedAtMS: updatedAtMS, CapabilityRevision: "v1"}
	if err := store.UpsertEndpoint(ctx, endpoint, updatedAtMS); err != nil {
		t.Fatal(err)
	}
	report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 1, ObservedAtMS: updatedAtMS, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}
	if err := store.ReplaceInventory(ctx, endpointID, report, updatedAtMS); err != nil {
		t.Fatal(err)
	}
}

// setOfflineSince controls the retention clock independently from metadata age.
func setOfflineSince(t *testing.T, store *Store, endpointID string, offlineSinceMS int64) {
	t.Helper()
	if _, err := store.DB().ExecContext(context.Background(), `UPDATE endpoints SET offline_since_at_ms = ? WHERE endpoint_id = ?`, offlineSinceMS, endpointID); err != nil {
		t.Fatal(err)
	}
}

// endpointLifecycleOf reads the three lifecycle columns for one Endpoint.
func endpointLifecycleOf(t *testing.T, store *Store, endpointID string) (string, int64, int64) {
	t.Helper()
	var state string
	var degradedSinceMS, expiresAtMS int64
	if err := store.DB().QueryRowContext(context.Background(), `SELECT connection_state, degraded_since_at_ms, expires_at_ms FROM endpoints WHERE endpoint_id = ?`, endpointID).Scan(&state, &degradedSinceMS, &expiresAtMS); err != nil {
		t.Fatal(err)
	}
	return state, degradedSinceMS, expiresAtMS
}

// assertRowCount checks one Endpoint identity in a named business table.
func assertRowCount(t *testing.T, store *Store, table, endpointID string, want int) {
	t.Helper()
	query := `SELECT count(*) FROM ` + table + ` WHERE endpoint_id = ?`
	var got int
	if err := store.DB().QueryRowContext(context.Background(), query, endpointID).Scan(&got); err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("%s count for %s = %d, want %d", table, endpointID, got, want)
	}
}

// TestUpsertEndpointClearsDegradedDeadlineOnReconnect verifies a recovered
// Endpoint stops advertising a deletion date.
//
// A degraded row carries a materialized deadline. If a reconnect left it in
// place, two things would go wrong: the endpoint list would show a deletion date
// for a machine that is currently connected, and a later sweep would delete a
// recovered row because the deadline had already passed. The deadline is
// therefore cleared on the same write that restores the online state.
func TestUpsertEndpointClearsDegradedDeadlineOnReconnect(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "recovered", "offline", 100)
	setOfflineSince(t, store, "recovered", 100)
	if _, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000); err != nil {
		t.Fatal(err)
	}
	state, degradedSince, expiresAt := endpointLifecycleOf(t, store, "recovered")
	if state != "degraded" || degradedSince != 1000 || expiresAt != 6000 {
		t.Fatalf("precondition state=%q degraded_since=%d expires_at=%d, want degraded/1000/6000", state, degradedSince, expiresAt)
	}

	// The Endpoint reconnects and reports itself online.
	reconnected := protocol.Endpoint{EndpointID: "recovered", InstanceID: "instance-recovered", DisplayName: "recovered", ConnectionState: "online", ObservedAtMS: 2000, CapabilityRevision: "v1"}
	if err := store.UpsertEndpoint(ctx, reconnected, 2000); err != nil {
		t.Fatal(err)
	}

	state, degradedSince, expiresAt = endpointLifecycleOf(t, store, "recovered")
	if state != "online" {
		t.Fatalf("state after reconnect = %q, want online", state)
	}
	if degradedSince != 0 || expiresAt != 0 {
		t.Fatalf("reconnect left degraded_since=%d expires_at=%d, want both cleared", degradedSince, expiresAt)
	}

	// The cleared deadline must also make the row ineligible for deletion.
	result, err := store.ExpireDegradedEndpoints(ctx, 999999)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DeletedEndpointIDs) != 0 {
		t.Fatalf("expiry deleted a recovered endpoint: %v", result.DeletedEndpointIDs)
	}
	assertRowCount(t, store, "endpoints", "recovered", 1)
}

// TestUpsertEndpointKeepsDegradedDeadlineWhileStillOffline verifies the clearing
// is conditional on the online state.
//
// An offline report from an already degraded Endpoint must not reset its
// deadline, otherwise a machine that keeps flapping would postpone its own
// deletion indefinitely and the degraded retention window would never elapse.
func TestUpsertEndpointKeepsDegradedDeadlineWhileStillOffline(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "flapping", "offline", 100)
	setOfflineSince(t, store, "flapping", 100)
	if _, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000); err != nil {
		t.Fatal(err)
	}

	stillOffline := protocol.Endpoint{EndpointID: "flapping", InstanceID: "instance-flapping", DisplayName: "flapping", ConnectionState: "offline", ObservedAtMS: 2000, CapabilityRevision: "v1"}
	if err := store.UpsertEndpoint(ctx, stillOffline, 2000); err != nil {
		t.Fatal(err)
	}

	state, degradedSince, expiresAt := endpointLifecycleOf(t, store, "flapping")
	if state != "degraded" || degradedSince != 1000 || expiresAt != 6000 {
		t.Fatalf("offline upsert changed the deadline: state=%q degraded_since=%d expires_at=%d, want degraded/1000/6000", state, degradedSince, expiresAt)
	}
}
