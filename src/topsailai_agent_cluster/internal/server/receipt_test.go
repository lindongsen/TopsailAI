package server

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

func TestPersistReceiptAndAckPersistsBeforeAck(t *testing.T) {
	ctx := context.Background()
	store, err := serverstorage.Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "instance-1", DisplayName: "endpoint-1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "v1"}, 1); err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitCommand(ctx, testIntent("ack-order"), "hash", 1); err != nil {
		t.Fatal(err)
	}
	acked := false
	receipt := protocol.ExecutionReceipt{CommandID: "ack-order", RequestHash: "hash", CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	ack := func(context.Context, string) error {
		acked = true
		if _, err := store.GetCommand(ctx, receipt.CommandID); err != nil {
			return err
		}
		return nil
	}
	if err := PersistReceiptAndAck(ctx, store, receipt, channel.Peer{EndpointID: "endpoint-1"}, time.UnixMilli(2), ack, nil); err != nil {
		t.Fatal(err)
	}
	if !acked {
		t.Fatal("receipt was not acknowledged")
	}
}

func TestPersistReceiptAndAckDoesNotAckAfterPersistenceFailure(t *testing.T) {
	ctx := context.Background()
	store, err := serverstorage.Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	called := false
	receipt := protocol.ExecutionReceipt{CommandID: "missing", RequestHash: "hash", CommandRevision: 1}
	err = PersistReceiptAndAck(ctx, store, receipt, channel.Peer{EndpointID: "endpoint-1"}, time.UnixMilli(2), func(context.Context, string) error {
		called = true
		return nil
	}, nil)
	if err == nil {
		t.Fatal("persistence failure was accepted")
	}
	if called {
		t.Fatal("ack was sent after persistence failure")
	}
}

func testIntent(id string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{HashVersion: "v1", CommandID: id, EndpointID: "endpoint-1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
}

func TestPersistReceiptAndAckValidatesDependenciesAndOrdersWork(t *testing.T) {
	if err := PersistReceiptAndAck(context.Background(), nil, protocol.ExecutionReceipt{}, channel.Peer{}, time.Now(), func(context.Context, string) error { return nil }, nil); err == nil {
		t.Fatal("nil store accepted")
	}
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "v1"}, 1); err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitCommand(context.Background(), testIntent("c1"), "h1", 1); err != nil {
		t.Fatal(err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: "c1", RequestHash: "h1", Outcome: "finished", Phase: protocol.PhaseReceiptRecorded}
	called := false
	err = PersistReceiptAndAck(context.Background(), store, receipt, channel.Peer{EndpointID: "endpoint-1"}, time.UnixMilli(10), func(_ context.Context, endpoint string) error { called = endpoint == "endpoint-1"; return nil }, nil)
	if err != nil || !called {
		t.Fatalf("persist/ack err=%v called=%v", err, called)
	}
}

// TestPersistReceiptAndAckRejectsAnUnknownCommand proves the re-home case is
// reported to the Endpoint instead of only logged. Without the rejection frame
// the Endpoint keeps the receipt pending and re-sends it on every reconnect,
// because it reloads the pending set from its journal.
func TestPersistReceiptAndAckRejectsAnUnknownCommand(t *testing.T) {
	ctx := context.Background()
	store, err := serverstorage.Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	acked := false
	var gotReason protocol.ReceiptRejection
	receipt := protocol.ExecutionReceipt{CommandID: "from-the-previous-server", RequestHash: "hash", CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	err = PersistReceiptAndAck(ctx, store, receipt, channel.Peer{EndpointID: "endpoint-1"}, time.UnixMilli(2), func(context.Context, string) error {
		acked = true
		return nil
	}, func(_ context.Context, endpointID string, reason protocol.ReceiptRejection) error {
		if endpointID != "endpoint-1" {
			t.Fatalf("rejection addressed %q, want endpoint-1", endpointID)
		}
		gotReason = reason
		return nil
	})
	if err == nil {
		t.Fatal("an unknown command was accepted")
	}
	if acked {
		t.Fatal("an unknown command was acknowledged")
	}
	if gotReason != protocol.ReceiptRejectedUnknownCommand {
		t.Fatalf("rejection reason = %q, want %q", gotReason, protocol.ReceiptRejectedUnknownCommand)
	}
	if !gotReason.Settles() {
		t.Fatal("an unknown command must authorise settlement")
	}
}

// TestPersistReceiptAndAckRejectsAConflictingRevision proves an integrity
// disagreement is reported with a reason that does not authorise settlement.
// Settling it would erase the only evidence that two sides disagree.
func TestPersistReceiptAndAckRejectsAConflictingRevision(t *testing.T) {
	ctx := context.Background()
	store, err := serverstorage.Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "instance-1", DisplayName: "endpoint-1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "v1"}, 1); err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitCommand(ctx, testIntent("conflict"), "hash", 1); err != nil {
		t.Fatal(err)
	}
	stored := protocol.ExecutionReceipt{CommandID: "conflict", RequestHash: "hash", CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	if err := store.ApplyReceipt(ctx, stored, 2); err != nil {
		t.Fatal(err)
	}
	conflicting := stored
	conflicting.Outcome = "rejected"
	var gotReason protocol.ReceiptRejection
	err = PersistReceiptAndAck(ctx, store, conflicting, channel.Peer{EndpointID: "endpoint-1"}, time.UnixMilli(3), func(context.Context, string) error {
		t.Fatal("a conflicting receipt was acknowledged")
		return nil
	}, func(_ context.Context, _ string, reason protocol.ReceiptRejection) error {
		gotReason = reason
		return nil
	})
	if err == nil {
		t.Fatal("a conflicting receipt was accepted")
	}
	if gotReason != protocol.ReceiptRejectedRevisionConflict {
		t.Fatalf("rejection reason = %q, want %q", gotReason, protocol.ReceiptRejectedRevisionConflict)
	}
	if gotReason.Settles() {
		t.Fatal("a conflicting revision must never authorise settlement")
	}
}

// TestPersistReceiptAndAckRejectsAStaleRevision proves an older revision is
// reported as stale, which does authorise settlement because the Server already
// represents a newer revision of the same receipt.
func TestPersistReceiptAndAckRejectsAStaleRevision(t *testing.T) {
	ctx := context.Background()
	store, err := serverstorage.Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "instance-1", DisplayName: "endpoint-1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "v1"}, 1); err != nil {
		t.Fatal(err)
	}
	if err := store.AdmitCommand(ctx, testIntent("stale"), "hash", 1); err != nil {
		t.Fatal(err)
	}
	newer := protocol.ExecutionReceipt{CommandID: "stale", RequestHash: "hash", CommandRevision: 2, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	if err := store.ApplyReceipt(ctx, newer, 2); err != nil {
		t.Fatal(err)
	}
	older := newer
	older.CommandRevision = 1
	var gotReason protocol.ReceiptRejection
	err = PersistReceiptAndAck(ctx, store, older, channel.Peer{EndpointID: "endpoint-1"}, time.UnixMilli(3), func(context.Context, string) error {
		t.Fatal("a stale receipt was acknowledged")
		return nil
	}, func(_ context.Context, _ string, reason protocol.ReceiptRejection) error {
		gotReason = reason
		return nil
	})
	if err == nil {
		t.Fatal("a stale receipt was accepted")
	}
	if gotReason != protocol.ReceiptRejectedRevisionStale {
		t.Fatalf("rejection reason = %q, want %q", gotReason, protocol.ReceiptRejectedRevisionStale)
	}
	if !gotReason.Settles() {
		t.Fatal("a stale revision must authorise settlement")
	}
}
