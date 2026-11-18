package endpointstorage

import (
	"context"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// countJournalRows reports how many command_journal rows exist, so a test can
// assert that retention removed exactly one row rather than trusting the returned
// slice alone.
func countJournalRows(t *testing.T, store *Store) int {
	t.Helper()
	var count int
	if err := store.db.QueryRow(`SELECT COUNT(*) FROM command_journal`).Scan(&count); err != nil {
		t.Fatalf("count command journal rows: %v", err)
	}
	return count
}

// countSettlementRows reports how many receipt_settlement rows exist, so a test
// can prove the settlement was removed with its journal row.
func countSettlementRows(t *testing.T, store *Store) int {
	t.Helper()
	var count int
	if err := store.db.QueryRow(`SELECT COUNT(*) FROM receipt_settlement`).Scan(&count); err != nil {
		t.Fatalf("count receipt settlement rows: %v", err)
	}
	return count
}

// TestExpireCommandJournalDeletesASettledReceipt proves the one eligible case: a
// settled receipt past the cutoff is removed together with its settlement row.
func TestExpireCommandJournalDeletesASettledReceipt(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-old")
	if err := store.SettleReceipt(ctx, "cmd-old", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("settle cmd-old: %v", err)
	}

	expired, err := store.ExpireCommandJournal(ctx, 100)
	if err != nil {
		t.Fatalf("expire command journal: %v", err)
	}
	if len(expired) != 1 {
		t.Fatalf("expired entries = %d, want 1", len(expired))
	}
	if expired[0].CommandID != "cmd-old" {
		t.Fatalf("expired command id = %q, want cmd-old", expired[0].CommandID)
	}
	if expired[0].Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("expired phase = %q, want receipt_recorded", expired[0].Phase)
	}
	if expired[0].EffectCertainty != string(protocol.EffectAcknowledged) {
		t.Fatalf("expired effect certainty = %q, want %q", expired[0].EffectCertainty, protocol.EffectAcknowledged)
	}
	if got := countJournalRows(t, store); got != 0 {
		t.Fatalf("command journal rows = %d, want 0", got)
	}
	if got := countSettlementRows(t, store); got != 0 {
		t.Fatalf("receipt settlement rows = %d, want 0 because the settlement must go with its journal row", got)
	}
}

// TestExpireCommandJournalKeepsAnUnsettledReceipt proves retention never removes a
// receipt the Server has not answered. Deleting it would silently drop evidence
// that is still pending acknowledgement.
func TestExpireCommandJournalKeepsAnUnsettledReceipt(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-pending")

	expired, err := store.ExpireCommandJournal(ctx, 100)
	if err != nil {
		t.Fatalf("expire command journal: %v", err)
	}
	if len(expired) != 0 {
		t.Fatalf("expired entries = %d, want 0 because the receipt is unsettled", len(expired))
	}
	if got := countJournalRows(t, store); got != 1 {
		t.Fatalf("command journal rows = %d, want 1", got)
	}
}

// TestExpireCommandJournalKeepsUncertainPhases proves retention never removes the
// phases that record an operation whose effect is unknown. Each is the only
// evidence that an uncertain operation exists.
func TestExpireCommandJournalKeepsUncertainPhases(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	admit := func(commandID string) {
		intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: commandID, EndpointID: "endpoint-1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
		if _, _, err := store.AdmitJournal(ctx, intent, "hash-"+commandID, 1); err != nil {
			t.Fatalf("admit journal %s: %v", commandID, err)
		}
	}
	admit("cmd-accepted")
	admit("cmd-started")
	if err := store.MarkInvocationStarted(ctx, "cmd-started", 2); err != nil {
		t.Fatalf("mark invocation started: %v", err)
	}
	admit("cmd-admitted")
	if err := store.MarkInvocationStarted(ctx, "cmd-admitted", 2); err != nil {
		t.Fatalf("mark invocation started: %v", err)
	}
	if err := store.MarkEndpointAdmitted(ctx, "cmd-admitted", 3); err != nil {
		t.Fatalf("mark endpoint admitted: %v", err)
	}

	expired, err := store.ExpireCommandJournal(ctx, 100)
	if err != nil {
		t.Fatalf("expire command journal: %v", err)
	}
	if len(expired) != 0 {
		t.Fatalf("expired entries = %d, want 0 because accepted, invocation_started and endpoint_admitted are never eligible", len(expired))
	}
	if got := countJournalRows(t, store); got != 3 {
		t.Fatalf("command journal rows = %d, want 3", got)
	}
}

// TestExpireCommandJournalKeepsARowInsideTheWindow proves the cutoff is honoured,
// so retention cannot delete a receipt that is still recent.
func TestExpireCommandJournalKeepsARowInsideTheWindow(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-recent")
	if err := store.SettleReceipt(ctx, "cmd-recent", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("settle cmd-recent: %v", err)
	}

	expired, err := store.ExpireCommandJournal(ctx, 1)
	if err != nil {
		t.Fatalf("expire command journal: %v", err)
	}
	if len(expired) != 0 {
		t.Fatalf("expired entries = %d, want 0 because the row was created at ms 1 and the cutoff is 1", len(expired))
	}
	if got := countJournalRows(t, store); got != 1 {
		t.Fatalf("command journal rows = %d, want 1", got)
	}
}

// TestExpireCommandJournalRejectsANonPositiveCutoff proves a zero cutoff is
// refused rather than interpreted as "delete everything".
func TestExpireCommandJournalRejectsANonPositiveCutoff(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-a")
	if err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("settle cmd-a: %v", err)
	}

	if _, err := store.ExpireCommandJournal(ctx, 0); err == nil {
		t.Fatal("expire command journal accepted a zero cutoff, want an error")
	}
	if got := countJournalRows(t, store); got != 1 {
		t.Fatalf("command journal rows = %d, want 1 because a rejected cutoff must delete nothing", got)
	}
}

// TestExpireCommandJournalRemovesOnlyTheExpiredRow proves retention is selective:
// one settled row past the cutoff is removed while a settled row inside the window
// and an unsettled row both survive.
func TestExpireCommandJournalRemovesOnlyTheExpiredRow(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-old")
	if err := store.SettleReceipt(ctx, "cmd-old", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("settle cmd-old: %v", err)
	}
	recordReceipt(t, store, "cmd-pending")
	recordReceipt(t, store, "cmd-new")
	if err := store.SettleReceipt(ctx, "cmd-new", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("settle cmd-new: %v", err)
	}
	// Move cmd-new inside the window so only cmd-old is eligible.
	if _, err := store.db.ExecContext(ctx, `UPDATE command_journal SET created_at_ms = 500 WHERE command_id = ?`, "cmd-new"); err != nil {
		t.Fatalf("move cmd-new inside the window: %v", err)
	}

	expired, err := store.ExpireCommandJournal(ctx, 100)
	if err != nil {
		t.Fatalf("expire command journal: %v", err)
	}
	if len(expired) != 1 || expired[0].CommandID != "cmd-old" {
		t.Fatalf("expired entries = %+v, want exactly cmd-old", expired)
	}
	if got := countJournalRows(t, store); got != 2 {
		t.Fatalf("command journal rows = %d, want 2", got)
	}
	if got := countSettlementRows(t, store); got != 1 {
		t.Fatalf("receipt settlement rows = %d, want 1 because only cmd-old's settlement was removed", got)
	}
}

// TestExpireCommandJournalKeepsANonReceiptPhaseWithASettlement proves the phase
// filter is what protects an uncertain row, not the settlement filter.
//
// No production write can produce this state: SettleReceipt and
// SettleAllRecordedReceipts both select only receipt_recorded rows, so an
// accepted row never gains a settlement. The state is therefore seeded directly,
// because it is the only way to prove the phase filter is load-bearing. Without
// it, a corrupt or hand-edited row would be deleted even though it is the sole
// evidence that a command was admitted and never executed.
func TestExpireCommandJournalKeepsANonReceiptPhaseWithASettlement(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-accepted", EndpointID: "endpoint-1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	if _, _, err := store.AdmitJournal(ctx, intent, "hash-cmd-accepted", 1); err != nil {
		t.Fatalf("admit journal: %v", err)
	}
	// Seed the settlement directly: no production path can attach one to an
	// accepted row, which is exactly why the phase filter must be proven here.
	if _, err := store.db.ExecContext(ctx, `INSERT INTO receipt_settlement(command_id, reason, settled_at_ms) VALUES(?,?,?)`, "cmd-accepted", string(protocol.ReceiptRejectedUnknownCommand), 3); err != nil {
		t.Fatalf("seed settlement for an accepted row: %v", err)
	}

	expired, err := store.ExpireCommandJournal(ctx, 100)
	if err != nil {
		t.Fatalf("expire command journal: %v", err)
	}
	if len(expired) != 0 {
		t.Fatalf("expired entries = %+v, want none because an accepted row is never eligible even when a settlement exists", expired)
	}
	if got := countJournalRows(t, store); got != 1 {
		t.Fatalf("command journal rows = %d, want 1 because the accepted row is the only evidence the command was admitted and never executed", got)
	}
}
