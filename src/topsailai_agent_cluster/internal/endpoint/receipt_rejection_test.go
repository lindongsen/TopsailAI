package endpoint

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// newSettlementService builds the minimum Service that can handle a receipt
// rejection: a real journal store and the pending map the handler mutates.
func newSettlementService(t *testing.T) (*Service, *endpointstorage.Store) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), filepath.Join(t.TempDir(), "endpoint.sqlite"))
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	service := &Service{storage: store, pendingReceipts: make(map[string]protocol.ExecutionReceipt)}
	return service, store
}

// seedPendingReceipt writes one journal row in the receipt_recorded phase and
// registers it as pending, which is the state a rejection arrives against.
func seedPendingReceipt(t *testing.T, service *Service, store *endpointstorage.Store, commandID string) {
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
	service.pendingReceipts[commandID] = receipt
}

// TestSettleRejectedReceiptSettlesAnUnknownCommand proves the re-home case: a
// Server that never admitted the command settles it durably, so the next
// reconnect does not re-send it.
func TestSettleRejectedReceiptSettlesAnUnknownCommand(t *testing.T) {
	ctx := context.Background()
	service, store := newSettlementService(t)
	seedPendingReceipt(t, service, store, "cmd-a")

	service.settleRejectedReceipt(ctx, channel.Frame{Type: channel.FrameReceiptRejected, FrameID: "cmd-a", ReceiptRejection: protocol.ReceiptRejectedUnknownCommand})

	if _, pending := service.pendingReceipts["cmd-a"]; pending {
		t.Fatal("an unknown-command rejection left the receipt pending in memory")
	}
	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 0 {
		t.Fatalf("recorded receipts = %d, want 0 after settlement", len(receipts))
	}
}

// TestSettleRejectedReceiptKeepsAConflictPending proves an integrity conflict is
// never settled. It is the only evidence that the two sides disagree about one
// command, so discarding it would hide a real defect behind a clean resend set.
func TestSettleRejectedReceiptKeepsAConflictPending(t *testing.T) {
	ctx := context.Background()
	service, store := newSettlementService(t)
	seedPendingReceipt(t, service, store, "cmd-a")

	service.settleRejectedReceipt(ctx, channel.Frame{Type: channel.FrameReceiptRejected, FrameID: "cmd-a", ReceiptRejection: protocol.ReceiptRejectedRevisionConflict})

	if _, pending := service.pendingReceipts["cmd-a"]; !pending {
		t.Fatal("a conflicting revision removed the receipt from the pending set")
	}
	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 1 || receipts[0].CommandID != "cmd-a" {
		t.Fatalf("recorded receipts = %#v, want cmd-a still present", receipts)
	}
}

// TestSettleRejectedReceiptKeepsAnUnrecognisedReasonPending proves a newer
// Server cannot make this Endpoint silently drop evidence it does not
// understand.
func TestSettleRejectedReceiptKeepsAnUnrecognisedReasonPending(t *testing.T) {
	ctx := context.Background()
	service, store := newSettlementService(t)
	seedPendingReceipt(t, service, store, "cmd-a")

	service.settleRejectedReceipt(ctx, channel.Frame{Type: channel.FrameReceiptRejected, FrameID: "cmd-a", ReceiptRejection: protocol.ReceiptRejection("some_future_reason")})

	if _, pending := service.pendingReceipts["cmd-a"]; !pending {
		t.Fatal("an unrecognised rejection reason removed the receipt from the pending set")
	}
	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 1 {
		t.Fatalf("recorded receipts = %d, want 1", len(receipts))
	}
}

// TestSettleRejectedReceiptFallsBackToRequestID proves the handler still finds
// the receipt when the frame carries only a request ID, because a rejection that
// silently does nothing would leave the resend loop running.
func TestSettleRejectedReceiptFallsBackToRequestID(t *testing.T) {
	ctx := context.Background()
	service, store := newSettlementService(t)
	seedPendingReceipt(t, service, store, "cmd-a")

	service.settleRejectedReceipt(ctx, channel.Frame{Type: channel.FrameReceiptRejected, RequestID: "cmd-a", ReceiptRejection: protocol.ReceiptRejectedUnknownCommand})

	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 0 {
		t.Fatalf("recorded receipts = %d, want 0 when the request id identifies the receipt", len(receipts))
	}
}

// TestSettleRejectedReceiptIgnoresAFrameWithoutAnIdentity proves a malformed
// rejection is refused rather than settling an empty command id.
func TestSettleRejectedReceiptIgnoresAFrameWithoutAnIdentity(t *testing.T) {
	ctx := context.Background()
	service, store := newSettlementService(t)
	seedPendingReceipt(t, service, store, "cmd-a")

	service.settleRejectedReceipt(ctx, channel.Frame{Type: channel.FrameReceiptRejected, ReceiptRejection: protocol.ReceiptRejectedUnknownCommand})

	if _, pending := service.pendingReceipts["cmd-a"]; !pending {
		t.Fatal("a rejection without an identity cleared an unrelated receipt")
	}
	receipts, err := store.ListRecordedReceipts(ctx)
	if err != nil {
		t.Fatalf("list recorded receipts: %v", err)
	}
	if len(receipts) != 1 {
		t.Fatalf("recorded receipts = %d, want 1", len(receipts))
	}
}
