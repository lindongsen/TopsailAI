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
	if err := PersistReceiptAndAck(ctx, store, receipt, channel.Peer{EndpointID: "endpoint-1"}, time.UnixMilli(2), ack); err != nil {
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
	})
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
	if err := PersistReceiptAndAck(context.Background(), nil, protocol.ExecutionReceipt{}, channel.Peer{}, time.Now(), func(context.Context, string) error { return nil }); err == nil {
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
	err = PersistReceiptAndAck(context.Background(), store, receipt, channel.Peer{EndpointID: "endpoint-1"}, time.UnixMilli(10), func(_ context.Context, endpoint string) error { called = endpoint == "endpoint-1"; return nil })
	if err != nil || !called {
		t.Fatalf("persist/ack err=%v called=%v", err, called)
	}
}
