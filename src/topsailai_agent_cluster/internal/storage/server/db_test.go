package serverstorage

import (
	"context"
	"database/sql"
	"encoding/json"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestStoreSchemaInventoryAndCancelCAS(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	endpoint := protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "test", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}
	if err := store.UpsertEndpoint(ctx, endpoint, 1); err != nil {
		t.Fatal(err)
	}
	report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "g1", SnapshotRevision: 1, ObservedAtMS: 1, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "a1", ProviderType: "test"}}, Sessions: []protocol.Session{{SessionID: "s1", AdapterID: "a1"}}}
	if err := store.ReplaceInventory(ctx, "e1", report, 2); err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd1", EndpointID: "e1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"hello"}`), ExecuteBeforeAtMS: 100}
	if err := store.AdmitCommand(ctx, intent, "hash1", 3); err != nil {
		t.Fatal(err)
	}
	cancelled, err := store.CancelCommand(ctx, "cmd1", 4)
	if err != nil || !cancelled {
		t.Fatalf("first cancel: cancelled=%v err=%v", cancelled, err)
	}
	cancelled, err = store.CancelCommand(ctx, "cmd1", 5)
	if err != nil || cancelled {
		t.Fatalf("second cancel: cancelled=%v err=%v", cancelled, err)
	}
	var tables int
	if err := store.DB().QueryRowContext(ctx, `SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('endpoints','endpoint_session_state','commands')`).Scan(&tables); err != nil {
		t.Fatal(err)
	}
	if tables != 3 {
		t.Fatalf("expected three business tables, got %d", tables)
	}
	if err := store.DB().QueryRowContext(ctx, `SELECT count(*) FROM endpoint_session_state`).Scan(&tables); err != nil && err != sql.ErrNoRows {
		t.Fatal(err)
	}
}

func TestCommandReceiptRevisionAndDispatchCAS(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	endpoint := protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "test", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}
	if err := store.UpsertEndpoint(ctx, endpoint, 1); err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-r", EndpointID: "e1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	if err := store.AdmitCommand(ctx, intent, "hash-r", 2); err != nil {
		t.Fatal(err)
	}
	claimed, err := store.DispatchCommand(ctx, intent.CommandID, 3)
	if err != nil || !claimed {
		t.Fatalf("dispatch: %v %v", claimed, err)
	}
	claimed, err = store.DispatchCommand(ctx, intent.CommandID, 4)
	if err != nil || claimed {
		t.Fatalf("second dispatch: %v %v", claimed, err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: "hash-r", CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, DeliveryBoundary: protocol.DeliverySubmitted, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	if err := store.ApplyReceipt(ctx, receipt, 5); err != nil {
		t.Fatal(err)
	}
	if err := store.ApplyReceipt(ctx, receipt, 6); err != nil {
		t.Fatal(err)
	}
	record, err := store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		t.Fatal(err)
	}
	if record.Status != protocol.StatusFinished || record.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("unexpected record: %#v", record)
	}
}

func TestCommandReceiptRejectsLowerRevision(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "e1", InstanceID: "instance-1", DisplayName: "e1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "v1"}, 1); err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-low", EndpointID: "e1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	if err := store.AdmitCommand(ctx, intent, "hash-low", 1); err != nil {
		t.Fatal(err)
	}
	high := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: "hash-low", CommandRevision: 2, Phase: protocol.PhaseReceiptRecorded, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	if err := store.ApplyReceipt(ctx, high, 2); err != nil {
		t.Fatal(err)
	}
	low := high
	low.CommandRevision = 1
	if err := store.ApplyReceipt(ctx, low, 3); err == nil {
		t.Fatal("lower receipt revision was accepted")
	}
}

func TestNotAppliedIsNotProjectedAsFinished(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "e1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-not-applied", EndpointID: "e1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	if err := store.AdmitCommand(ctx, intent, "hash-not-applied", 1); err != nil {
		t.Fatal(err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: "hash-not-applied", CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, DeliveryBoundary: protocol.DeliveryNotStarted, EffectCertainty: protocol.EffectNotApplied, Outcome: "rejected"}
	if err := store.ApplyReceipt(ctx, receipt, 2); err != nil {
		t.Fatal(err)
	}
	record, err := store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		t.Fatal(err)
	}
	if record.Status == protocol.StatusFinished || record.Status != protocol.StatusRejected {
		t.Fatalf("unexpected status: %q", record.Status)
	}
	if record.ErrorCode == "" {
		t.Fatal("expected error code")
	}
}

func TestSignalSentWithoutExitIsNotFinished(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "e1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-signal-sent", EndpointID: "e1", Operation: protocol.OperationAgentStop, OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"target":"session"}`), ExecuteBeforeAtMS: 100}
	if err := store.AdmitCommand(ctx, intent, "hash-signal-sent", 1); err != nil {
		t.Fatal(err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: "hash-signal-sent", CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, DeliveryBoundary: protocol.DeliverySignalSent, EffectCertainty: protocol.EffectAcknowledged, ExitConfirmed: false}
	if err := store.ApplyReceipt(ctx, receipt, 2); err != nil {
		t.Fatal(err)
	}
	record, err := store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		t.Fatal(err)
	}
	if record.Status == protocol.StatusFinished || record.Status != protocol.StatusExecuting {
		t.Fatalf("unexpected status: %q", record.Status)
	}
	if record.DeliveryBoundary != protocol.DeliverySignalSent || record.ExitConfirmed {
		t.Fatalf("receipt evidence was not preserved: %#v", record)
	}
}

func TestNotAppliedWithDeliveredBoundaryIsNotFinished(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "e1", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-delivered-not-applied", EndpointID: "e1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	if err := store.AdmitCommand(ctx, intent, "hash-delivered", 1); err != nil {
		t.Fatal(err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: "hash-delivered", CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, DeliveryBoundary: protocol.DeliverySubmitted, EffectCertainty: protocol.EffectNotApplied, Outcome: "failed", ErrorCode: "provider_rejected"}
	if err := store.ApplyReceipt(ctx, receipt, 2); err != nil {
		t.Fatal(err)
	}
	record, err := store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		t.Fatal(err)
	}
	if record.Status == protocol.StatusFinished {
		t.Fatal("not_applied receipt was projected as finished")
	}
}

func TestServerStorageQueriesAndExpiration(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	for _, endpoint := range []protocol.Endpoint{
		{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "v1"},
		{EndpointID: "e2", InstanceID: "i2", DisplayName: "two", ConnectionState: "offline", ObservedAtMS: 2, CapabilityRevision: "v2"},
	} {
		if err := store.UpsertEndpoint(ctx, endpoint, endpoint.ObservedAtMS); err != nil {
			t.Fatal(err)
		}
	}
	items, err := store.ListEndpoints(ctx, QueryOptions{Limit: 1, OrderBy: "desc", SortKey: "update_at_ms"})
	if err != nil || len(items) != 1 || items[0].EndpointID != "e2" {
		t.Fatalf("endpoint query=%#v err=%v", items, err)
	}
	report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "g1", SnapshotRevision: 1, ObservedAtMS: 1, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}
	if err := store.ReplaceInventory(ctx, "e1", report, 1); err != nil {
		t.Fatal(err)
	}
	got, err := store.GetInventory(ctx, "e1")
	if err != nil || got.SnapshotRevision != 1 {
		t.Fatalf("inventory=%#v err=%v", got, err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "expire", EndpointID: "e1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", ExecuteBeforeAtMS: 10, Payload: []byte(`{}`)}
	if err := store.AdmitCommand(ctx, intent, "hash-expire", 1); err != nil {
		t.Fatal(err)
	}
	expired, err := store.ExpireCommand(ctx, intent.CommandID, 11)
	if err != nil || !expired {
		t.Fatalf("expire=%v err=%v", expired, err)
	}
	expired, err = store.ExpireCommand(ctx, intent.CommandID, 12)
	if err != nil || expired {
		t.Fatalf("repeat expire=%v err=%v", expired, err)
	}
}

func TestCommandRecordMarshalJSONIncludesStableAndLegacyFields(t *testing.T) {
	record := CommandRecord{CommandID: "c1", EndpointID: "e1", Operation: "send", Status: protocol.StatusAdmitted, Phase: protocol.PhaseAccepted, DeadlineAtMS: 7}
	data, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]any
	if err := json.Unmarshal(data, &fields); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"command_id", "CommandID", "endpoint_id", "EndpointID", "status", "Status"} {
		if _, ok := fields[key]; !ok {
			t.Fatalf("missing JSON field %q in %s", key, data)
		}
	}
}

func TestCommandQueriesAndManifest(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "v1"}, 1); err != nil {
		t.Fatal(err)
	}
	for _, item := range []struct{ id, hash, resource string }{{"c1", "h1", "res_1"}, {"c2", "h2", "res_10"}} {
		target := &protocol.CommandTarget{ResourceID: item.resource, Generation: "g1"}
		intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: item.id, EndpointID: "e1", Operation: "send", Target: target, OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{"x":1}`), ExecuteBeforeAtMS: 100}
		if err := store.AdmitCommand(ctx, intent, item.hash, 1); err != nil {
			t.Fatal(err)
		}
	}
	items, err := store.ListCommands(ctx, "e1", "res_1", 20)
	if err != nil || len(items) != 1 || items[0].CommandID != "c1" {
		t.Fatalf("exact resource query=%#v err=%v", items, err)
	}
	items, err = store.ListCommands(ctx, "", "", 0)
	if err != nil || len(items) != 2 {
		t.Fatalf("bounded command query=%#v err=%v", items, err)
	}
	revisions, err := store.ListInventoryRevisions(ctx)
	if err != nil || len(revisions) != 0 {
		t.Fatalf("manifest revisions=%#v err=%v", revisions, err)
	}
}

func TestCommandAdmissionValidationAndCancellation(t *testing.T) {
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.AdmitCommand(context.Background(), protocol.ImmutableIntent{}, "", 1); err == nil {
		t.Fatal("invalid command accepted")
	}
	if ok, err := store.CancelCommand(context.Background(), "missing", 1); err != nil || ok {
		t.Fatalf("missing cancellation=%v err=%v", ok, err)
	}
}
