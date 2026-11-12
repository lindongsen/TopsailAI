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
	}{
		{id: "expired", state: "offline", updated: 100},
		{id: "recent", state: "offline", updated: 300},
		{id: "online", state: "online", updated: 100},
	} {
		putEndpointInventory(t, store, item.id, item.state, item.updated)
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

	updated, err := store.MarkPersistedEndpointsOffline(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if updated != 1 {
		t.Fatalf("offline updates = %d, want 1", updated)
	}
	result, err := store.ExpireOfflineEndpoints(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.InventoryEndpointIDs) != 1 || result.InventoryEndpointIDs[0] != "stale-online" {
		t.Fatalf("expiry result = %+v", result)
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
