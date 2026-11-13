package serverstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestExpireOfflineEndpointsRemovesOnlyStaleOfflineRecords verifies cleanup
// removes stale projections without treating online or recent data as expired.
func TestExpireOfflineEndpointsRemovesOnlyStaleOfflineRecords(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	for _, item := range []struct {
		id      string
		state   string
		updated int64
		offline int64
	}{
		{id: "expired", state: "offline", updated: 300, offline: 100},
		{id: "recent", state: "offline", updated: 100, offline: 300},
		{id: "online", state: "online", updated: 100, offline: 0},
	} {
		putEndpointInventory(t, store, item.id, item.state, item.updated)
		setOfflineSince(t, store, item.id, item.offline)
	}

	result, err := store.ExpireOfflineEndpoints(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.InventoryEndpointIDs) != 1 || result.InventoryEndpointIDs[0] != "expired" || len(result.DeletedEndpointIDs) != 1 || result.DeletedEndpointIDs[0] != "expired" {
		t.Fatalf("expiry result = %+v", result)
	}
	assertRowCount(t, store, "endpoints", "expired", 0)
	assertRowCount(t, store, "endpoint_session_state", "expired", 0)
	for _, id := range []string{"recent", "online"} {
		assertRowCount(t, store, "endpoints", id, 1)
		assertRowCount(t, store, "endpoint_session_state", id, 1)
	}
}

// TestExpireOfflineEndpointsPreservesCommandEvidence verifies a command keeps
// its Endpoint identity while the stale inventory that pollutes list is removed.
func TestExpireOfflineEndpointsPreservesCommandEvidence(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	putEndpointInventory(t, store, "referenced", "offline", 100)
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-1", EndpointID: "referenced", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"hello"}`), ExecuteBeforeAtMS: 1000}
	if err := store.AdmitCommand(ctx, intent, "hash", 110); err != nil {
		t.Fatal(err)
	}

	result, err := store.ExpireOfflineEndpoints(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.InventoryEndpointIDs) != 1 || result.InventoryEndpointIDs[0] != "referenced" || len(result.DeletedEndpointIDs) != 0 {
		t.Fatalf("expiry result = %+v", result)
	}
	assertRowCount(t, store, "endpoint_session_state", "referenced", 0)
	assertRowCount(t, store, "endpoints", "referenced", 1)
	var commands int
	if err := store.DB().QueryRowContext(ctx, `SELECT count(*) FROM commands WHERE command_id = 'cmd-1'`).Scan(&commands); err != nil {
		t.Fatal(err)
	}
	if commands != 1 {
		t.Fatalf("command count = %d, want 1", commands)
	}
}

// TestMarkPersistedEndpointsOfflinePreservesAge verifies startup recovery makes
// stale online projections eligible for expiry without granting a fresh TTL.
func TestMarkPersistedEndpointsOfflinePreservesAge(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	putEndpointInventory(t, store, "stale-online", "online", 100)

	updated, err := store.MarkPersistedEndpointsOffline(ctx, 300)
	if err != nil {
		t.Fatal(err)
	}
	if updated != 1 {
		t.Fatalf("offline updates = %d, want 1", updated)
	}
	var state string
	var offlineSinceMS int64
	if err := store.DB().QueryRowContext(ctx, `SELECT connection_state, offline_since_at_ms FROM endpoints WHERE endpoint_id = ?`, "stale-online").Scan(&state, &offlineSinceMS); err != nil {
		t.Fatal(err)
	}
	if state != "offline" || offlineSinceMS != 300 {
		t.Fatalf("recovered state=%q offline_since_at_ms=%d, want offline/300", state, offlineSinceMS)
	}
	result, err := store.ExpireOfflineEndpoints(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.InventoryEndpointIDs) != 0 {
		t.Fatalf("startup recovery expired inventory immediately: %+v", result)
	}
}

// TestMarkPersistedEndpointsOfflinePreservesExistingOfflineAge verifies restart
// recovery changes only persisted online rows.
func TestMarkPersistedEndpointsOfflinePreservesExistingOfflineAge(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	putEndpointInventory(t, store, "already-offline", "offline", 100)
	setOfflineSince(t, store, "already-offline", 50)
	if _, err := store.MarkPersistedEndpointsOffline(ctx, 300); err != nil {
		t.Fatal(err)
	}
	var got int64
	if err := store.DB().QueryRowContext(ctx, `SELECT offline_since_at_ms FROM endpoints WHERE endpoint_id = ?`, "already-offline").Scan(&got); err != nil {
		t.Fatal(err)
	}
	if got != 50 {
		t.Fatalf("offline_since_at_ms=%d, want 50", got)
	}
}

// TestUpsertEndpointOnlineClearsOfflineAge verifies reconnect starts a fresh
// liveness period and stale cleanup cannot remove the online projection.
func TestUpsertEndpointOnlineClearsOfflineAge(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	putEndpointInventory(t, store, "reconnected", "offline", 100)
	setOfflineSince(t, store, "reconnected", 50)
	endpoint := protocol.Endpoint{EndpointID: "reconnected", InstanceID: "instance-reconnected", DisplayName: "reconnected", ConnectionState: "online", ObservedAtMS: 300, CapabilityRevision: "v1"}
	if err := store.UpsertEndpoint(ctx, endpoint, 300); err != nil {
		t.Fatal(err)
	}
	var got int64
	if err := store.DB().QueryRowContext(ctx, `SELECT offline_since_at_ms FROM endpoints WHERE endpoint_id = ?`, "reconnected").Scan(&got); err != nil {
		t.Fatal(err)
	}
	if got != 0 {
		t.Fatalf("offline_since_at_ms=%d, want 0", got)
	}
	result, err := store.ExpireOfflineEndpoints(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.InventoryEndpointIDs) != 0 {
		t.Fatalf("reconnected endpoint expired: %+v", result)
	}
}

// TestExpireOfflineEndpointsRejectsInvalidCutoff verifies an invalid wall-clock
// cutoff cannot accidentally select every persisted Endpoint.
func TestExpireOfflineEndpointsRejectsInvalidCutoff(t *testing.T) {
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.ExpireOfflineEndpoints(context.Background(), 0); err == nil {
		t.Fatal("zero cutoff was accepted")
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

// TestExpireOfflineEndpointsNeverSelectsOnlineRows verifies the connection-state
// guard is load-bearing rather than redundant.
//
// The production write paths cannot produce an online row with a positive
// offline_since_at_ms: UpsertEndpoint forces the clock to zero for an online
// state, and MarkPersistedEndpointsOffline converts every online row to offline
// before a sweep runs. The guard therefore protects against a corrupt or
// hand-edited row, which is exactly the state this test writes directly. Without
// the guard, a positive clock alone would make an online Endpoint eligible and
// its live inventory would be deleted.
func TestExpireOfflineEndpointsNeverSelectsOnlineRows(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "corrupt-online", "online", 100)
	setOfflineSince(t, store, "corrupt-online", 100)

	result, err := store.ExpireOfflineEndpoints(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.InventoryEndpointIDs) != 0 || len(result.DeletedEndpointIDs) != 0 {
		t.Fatalf("expiry selected an online row: %+v", result)
	}
	assertRowCount(t, store, "endpoints", "corrupt-online", 1)
	assertRowCount(t, store, "endpoint_session_state", "corrupt-online", 1)
}
