package serverstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// insertCommandRow writes one command row with an explicit status and age so a
// purge test can control both dimensions independently.
func insertCommandRow(t *testing.T, store *Store, commandID, endpointID string, status protocol.CommandStatus, updateAtMS int64) {
	t.Helper()
	_, err := store.DB().ExecContext(context.Background(), `INSERT INTO commands(command_id, request_hash, endpoint_id, operation, target_json, intent_json, status, phase, delivery_boundary, effect_certainty, deadline_at_ms, create_at_ms, update_at_ms) VALUES(?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)`,
		commandID, "hash-"+commandID, endpointID, "message.send", `{}`, status, protocol.PhaseAccepted, protocol.DeliveryNotStarted, protocol.EffectNotApplied, 1000, updateAtMS, updateAtMS)
	if err != nil {
		t.Fatal(err)
	}
}

// TestPurgeExpiredCommandsRemovesOnlyTerminalKnownEffect verifies the allowlist
// deletes exactly the terminal statuses whose effect is known, and retains every
// status that is still in flight or whose effect is unknown.
func TestPurgeExpiredCommandsRemovesOnlyTerminalKnownEffect(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	putEndpointInventory(t, store, "ep-1", "offline", 100)

	purgeable := []protocol.CommandStatus{protocol.StatusFinished, protocol.StatusRejected, protocol.StatusFailed, protocol.StatusExpired, protocol.StatusCancelled}
	retained := []protocol.CommandStatus{protocol.StatusUnconfirmed, protocol.StatusExecuting, protocol.StatusAdmitted, protocol.StatusDispatched, protocol.StatusEndpointAdmitted}
	for _, status := range purgeable {
		insertCommandRow(t, store, "cmd-"+string(status), "ep-1", status, 100)
	}
	for _, status := range retained {
		insertCommandRow(t, store, "cmd-"+string(status), "ep-1", status, 100)
	}

	purged, err := store.PurgeExpiredCommands(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if purged != int64(len(purgeable)) {
		t.Fatalf("purged = %d, want %d", purged, len(purgeable))
	}
	for _, status := range purgeable {
		assertCommandCount(t, store, "cmd-"+string(status), 0)
	}
	for _, status := range retained {
		assertCommandCount(t, store, "cmd-"+string(status), 1)
	}
}

// TestPurgeExpiredCommandsRespectsCutoff verifies a recent terminal command is
// retained, so the purge is bounded by age rather than by status alone.
func TestPurgeExpiredCommandsRespectsCutoff(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	putEndpointInventory(t, store, "ep-1", "offline", 100)
	insertCommandRow(t, store, "cmd-old", "ep-1", protocol.StatusFinished, 100)
	insertCommandRow(t, store, "cmd-new", "ep-1", protocol.StatusFinished, 300)

	purged, err := store.PurgeExpiredCommands(ctx, 200)
	if err != nil {
		t.Fatal(err)
	}
	if purged != 1 {
		t.Fatalf("purged = %d, want 1", purged)
	}
	assertCommandCount(t, store, "cmd-old", 0)
	assertCommandCount(t, store, "cmd-new", 1)
}

// TestPurgeExpiredCommandsRejectsNonPositiveCutoff verifies a zero cutoff is
// refused rather than deleting every command whose timestamp is not positive.
func TestPurgeExpiredCommandsRejectsNonPositiveCutoff(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.PurgeExpiredCommands(ctx, 0); err == nil {
		t.Fatal("zero cutoff was accepted")
	}
}

// TestPurgeDoesNotUnblockEndpointDeletion verifies the command purge is no
// longer the mechanism that releases an Endpoint metadata row.
//
// Before the degraded lifecycle existed, expiry deleted an offline row only when
// no command referenced it, so purging the blocking command was what let the row
// go. That coupling is gone: an offline row is now degraded first and deleted
// only when its own deadline passes, and the deletion removes the referencing
// commands explicitly. This test pins the new behaviour so the old coupling
// cannot silently return.
func TestPurgeDoesNotUnblockEndpointDeletion(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	putEndpointInventory(t, store, "blocked", "offline", 100)
	setOfflineSince(t, store, "blocked", 100)
	insertCommandRow(t, store, "cmd-blocking", "blocked", protocol.StatusFinished, 100)

	// Purging the only referencing command does not delete the endpoint row.
	if _, err := store.PurgeExpiredCommands(ctx, 200); err != nil {
		t.Fatal(err)
	}
	assertCommandCount(t, store, "cmd-blocking", 0)
	assertRowCount(t, store, "endpoints", "blocked", 1)

	// Degrading keeps the row and starts its own window.
	degraded, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000)
	if err != nil {
		t.Fatal(err)
	}
	if len(degraded.DegradedEndpointIDs) != 1 || degraded.DegradedEndpointIDs[0] != "blocked" {
		t.Fatalf("degrade result = %+v, want blocked degraded", degraded)
	}
	assertRowCount(t, store, "endpoints", "blocked", 1)

	// Only the degraded deadline releases it.
	result, err := store.ExpireDegradedEndpoints(ctx, 6000)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.DeletedEndpointIDs) != 1 || result.DeletedEndpointIDs[0] != "blocked" {
		t.Fatalf("expiry result = %+v, want blocked deleted", result)
	}
	assertRowCount(t, store, "endpoints", "blocked", 0)
}

// assertCommandCount checks one command identity in the commands table.
func assertCommandCount(t *testing.T, store *Store, commandID string, want int) {
	t.Helper()
	var got int
	if err := store.DB().QueryRowContext(context.Background(), `SELECT count(*) FROM commands WHERE command_id = ?`, commandID).Scan(&got); err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("command count for %s = %d, want %d", commandID, got, want)
	}
}
