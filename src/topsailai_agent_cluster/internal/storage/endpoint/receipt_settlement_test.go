package endpointstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// recordReceipt writes one journal row in the receipt_recorded phase, which is
// the state ListRecordedReceipts selects.
func recordReceipt(t *testing.T, store *Store, commandID string) {
	t.Helper()
	ctx := context.Background()
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: commandID, EndpointID: "endpoint-1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	if _, _, err := store.AdmitJournal(ctx, intent, "hash-"+commandID, 1); err != nil {
		t.Fatalf("admit journal %s: %v", commandID, err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: commandID, RequestHash: "hash-" + commandID, CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	if err := store.RecordReceipt(ctx, commandID, receipt, 2); err != nil {
		t.Fatalf("record receipt %s: %v", commandID, err)
	}
}

func openJournalStore(t *testing.T) *Store {
	t.Helper()
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "endpoint.sqlite"))
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store
}

// TestSettleReceiptRemovesItFromTheResendSet proves settlement is durable. The
// pending set is reloaded from the journal on every reconnect, so an in-memory
// deletion alone would let the next reconnect re-send exactly what was settled.
func TestSettleReceiptRemovesItFromTheResendSet(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-a")
	recordReceipt(t, store, "cmd-b")

	before, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list before settlement: %v", err)
	}
	if len(before) != 2 {
		t.Fatalf("recorded receipts before settlement = %d, want 2", len(before))
	}

	if err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("settle cmd-a: %v", err)
	}

	after, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list after settlement: %v", err)
	}
	if len(after) != 1 || after[0].CommandID != "cmd-b" {
		t.Fatalf("recorded receipts after settlement = %#v, want only cmd-b", after)
	}
}

// TestSettleReceiptKeepsTheJournalEvidence proves settlement is a decision, not
// a deletion: the journal row and its receipt stay readable so the evidence that
// the receipt existed is preserved.
func TestSettleReceiptKeepsTheJournalEvidence(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-a")
	if err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("settle cmd-a: %v", err)
	}
	entry, err := store.GetJournal(ctx, "cmd-a")
	if err != nil {
		t.Fatalf("read the settled journal entry: %v", err)
	}
	if entry.CommandID != "cmd-a" {
		t.Fatalf("journal entry command id = %q, want cmd-a", entry.CommandID)
	}
	if entry.ReceiptJSON == "" {
		t.Fatal("settlement erased the stored receipt")
	}
	if entry.Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("journal phase = %q, want %q", entry.Phase, protocol.PhaseReceiptRecorded)
	}
}

// TestSettleReceiptIsIdempotent proves a repeated rejection for the same command
// does not fail, because the Server may report the same rejection on every
// reconnect until the Endpoint's own state converges.
func TestSettleReceiptIsIdempotent(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-a")
	if err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err != nil {
		t.Fatalf("first settlement: %v", err)
	}
	if err := store.SettleReceipt(ctx, "cmd-a", protocol.SettlementOriginRejection, protocol.ReceiptRejectedRevisionStale, 4); err != nil {
		t.Fatalf("second settlement: %v", err)
	}
	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 0 {
		t.Fatalf("recorded receipts = %d, want 0", len(receipts))
	}
}

// TestSettleReceiptRequiresACommandID proves an empty identifier is refused
// rather than writing a row that could never match a receipt.
func TestSettleReceiptRequiresACommandID(t *testing.T) {
	store := openJournalStore(t)
	if err := store.SettleReceipt(context.Background(), "", protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, 3); err == nil {
		t.Fatal("an empty command id was accepted")
	}
}

// TestSettleAllRecordedReceiptsSettlesEveryPendingReceipt proves the bulk path
// used on re-home settles the whole set in one step and reports how many rows it
// changed.
func TestSettleAllRecordedReceiptsSettlesEveryPendingReceipt(t *testing.T) {
	ctx := context.Background()
	store := openJournalStore(t)
	recordReceipt(t, store, "cmd-a")
	recordReceipt(t, store, "cmd-b")
	recordReceipt(t, store, "cmd-c")

	settled, err := store.SettleAllRecordedReceipts(ctx, protocol.ReceiptRejectedUnknownCommand, 5)
	if err != nil {
		t.Fatalf("settle all: %v", err)
	}
	if settled != 3 {
		t.Fatalf("settled rows = %d, want 3", settled)
	}
	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 0 {
		t.Fatalf("recorded receipts = %d, want 0", len(receipts))
	}

	again, err := store.SettleAllRecordedReceipts(ctx, protocol.ReceiptRejectedUnknownCommand, 6)
	if err != nil {
		t.Fatalf("second settle all: %v", err)
	}
	if again != 0 {
		t.Fatalf("second settle changed %d rows, want 0", again)
	}
}
