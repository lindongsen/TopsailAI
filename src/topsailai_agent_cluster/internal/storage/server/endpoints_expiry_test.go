package serverstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestExpireDegradedEndpointsRemovesOnlyExpiredDegradedRows verifies expiry
// selects exactly the degraded rows whose materialized deadline has passed.
//
// A degraded row whose deadline is still in the future must survive, because the
// degraded window is the period in which an operator can still see the record.
// An offline row must survive too: it has not been degraded yet, so it has no
// deadline and no basis for deletion.
func TestExpireDegradedEndpointsRemovesOnlyExpiredDegradedRows(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "expired", "offline", 100)
	setOfflineSince(t, store, "expired", 100)
	putEndpointInventory(t, store, "still-degraded", "offline", 300)
	setOfflineSince(t, store, "still-degraded", 300)
	putEndpointInventory(t, store, "offline-only", "offline", 500)
	setOfflineSince(t, store, "offline-only", 500)

	// Two degradation windows so the two degraded rows carry different
	// deadlines: "expired" is due at 6000 and "still-degraded" at 7000.
	if _, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000); err != nil {
		t.Fatal(err)
	}
	if _, err := store.DegradeOfflineEndpoints(ctx, 400, 2000, 5000); err != nil {
		t.Fatal(err)
	}

	result, err := store.ExpireDegradedEndpoints(ctx, 6000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DeletedEndpointIDs) != 1 || result.DeletedEndpointIDs[0] != "expired" {
		t.Fatalf("expiry result = %+v, want only expired deleted", result)
	}
	assertRowCount(t, store, "endpoints", "expired", 0)
	assertRowCount(t, store, "endpoints", "still-degraded", 1)
	assertRowCount(t, store, "endpoints", "offline-only", 1)
}

// TestExpireDegradedEndpointsDeletesCommandEvidence verifies the explicit
// cascade removes the commands that reference the endpoint.
//
// The schema declares commands.endpoint_id without ON DELETE CASCADE, so without
// this delete the endpoint row could never be removed once any command referenced
// it. unconfirmed is excluded from the purge allowlist because it is the only
// evidence of an unknown effect, so the purge alone can never unblock the row.
func TestExpireDegradedEndpointsDeletesCommandEvidence(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "gone", "offline", 100)
	setOfflineSince(t, store, "gone", 100)
	insertCommandRow(t, store, "cmd-unconfirmed", "gone", protocol.StatusUnconfirmed, 100)
	insertCommandRow(t, store, "cmd-finished", "gone", protocol.StatusFinished, 100)

	if _, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000); err != nil {
		t.Fatal(err)
	}
	result, err := store.ExpireDegradedEndpoints(ctx, 6000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DeletedEndpointIDs) != 1 || result.DeletedEndpointIDs[0] != "gone" {
		t.Fatalf("expiry result = %+v, want gone deleted", result)
	}
	if len(result.DeletedCommandIDs) != 2 {
		t.Fatalf("deleted command ids = %v, want both commands", result.DeletedCommandIDs)
	}
	assertCommandCount(t, store, "cmd-unconfirmed", 0)
	assertCommandCount(t, store, "cmd-finished", 0)
	assertRowCount(t, store, "endpoints", "gone", 0)
}

// TestExpireDegradedEndpointsPreservesOtherEndpointCommands verifies the cascade
// is scoped to the endpoint being deleted. A command belonging to a live endpoint
// must never be removed by another endpoint's expiry.
func TestExpireDegradedEndpointsPreservesOtherEndpointCommands(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "gone", "offline", 100)
	setOfflineSince(t, store, "gone", 100)
	putEndpointInventory(t, store, "alive", "online", 100)
	insertCommandRow(t, store, "cmd-gone", "gone", protocol.StatusUnconfirmed, 100)
	insertCommandRow(t, store, "cmd-alive", "alive", protocol.StatusUnconfirmed, 100)

	if _, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ExpireDegradedEndpoints(ctx, 6000); err != nil {
		t.Fatal(err)
	}
	assertCommandCount(t, store, "cmd-gone", 0)
	assertCommandCount(t, store, "cmd-alive", 1)
	assertRowCount(t, store, "endpoints", "alive", 1)
}

// TestExpireDegradedEndpointsSkipsZeroDeadline verifies a degraded row with no
// materialized deadline is never deleted. Zero means "no deletion date", so
// treating it as "expired long ago" would delete a row that was never scheduled.
func TestExpireDegradedEndpointsSkipsZeroDeadline(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	putEndpointInventory(t, store, "no-deadline", "offline", 100)
	setOfflineSince(t, store, "no-deadline", 100)
	if _, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000); err != nil {
		t.Fatal(err)
	}
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET expires_at_ms = 0 WHERE endpoint_id = ?`, "no-deadline"); err != nil {
		t.Fatal(err)
	}

	result, err := store.ExpireDegradedEndpoints(ctx, 6000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DeletedEndpointIDs) != 0 {
		t.Fatalf("expiry deleted a row without a deadline: %+v", result)
	}
	assertRowCount(t, store, "endpoints", "no-deadline", 1)
}

// TestExpireDegradedEndpointsRejectsInvalidCutoff verifies an invalid wall-clock
// cutoff cannot accidentally select every degraded Endpoint.
func TestExpireDegradedEndpointsRejectsInvalidCutoff(t *testing.T) {
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.ExpireDegradedEndpoints(context.Background(), 0); err == nil {
		t.Fatal("zero cutoff was accepted")
	}
}

// TestMarkPersistedEndpointsOfflinePreservesAge verifies startup recovery makes
// stale online projections eligible for degradation without granting a fresh TTL.
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
	result, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DegradedEndpointIDs) != 0 {
		t.Fatalf("startup recovery degraded a row whose clock is newer than the cutoff: %+v", result)
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
// liveness period and stale cleanup cannot degrade the online projection.
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
	result, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DegradedEndpointIDs) != 0 {
		t.Fatalf("reconnected endpoint degraded: %+v", result)
	}
}
