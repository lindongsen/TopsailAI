package endpoint

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// newRejectionExecutor builds an executor whose registry has one configured
// fixture adapter, so a test can distinguish a missing mapping from a missing
// adapter configuration.
func newRejectionExecutor(t *testing.T) (*Executor, *endpointstorage.Store) {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return &countingExecuteAdapter{}, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	executor, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	return executor, store
}

// assertTerminalRejection proves the journal holds a durable terminal rejection
// with the expected bounded error code and a provably unapplied effect.
func assertTerminalRejection(t *testing.T, store *endpointstorage.Store, commandID, wantCode string) {
	t.Helper()
	entry, err := store.GetJournal(context.Background(), commandID)
	if err != nil {
		t.Fatalf("the rejection must be durable, otherwise the command never becomes terminal: %v", err)
	}
	if entry.Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("journal phase=%q, want %q", entry.Phase, protocol.PhaseReceiptRecorded)
	}
	var receipt protocol.ExecutionReceipt
	if err := json.Unmarshal([]byte(entry.ReceiptJSON), &receipt); err != nil {
		t.Fatalf("decode stored receipt: %v", err)
	}
	if receipt.CommandID != commandID {
		t.Fatalf("stored receipt command ID=%q, want %q", receipt.CommandID, commandID)
	}
	if receipt.ErrorCode != wantCode {
		t.Fatalf("stored error code=%q, want %q", receipt.ErrorCode, wantCode)
	}
	if receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("stored effect certainty=%q, want %q", receipt.EffectCertainty, protocol.EffectNotApplied)
	}
	if receipt.Outcome != "rejected" {
		t.Fatalf("stored outcome=%q, want rejected", receipt.Outcome)
	}
}

// TestExecuteRecordsTerminalRejectionForUnmappedResource proves a command whose
// target has no durable mapping is terminally rejected instead of returning a
// bare error. A bare error left no receipt, so the Server never learned the
// outcome and the operator waited the full wait budget while the command still
// displayed as dispatched.
func TestExecuteRecordsTerminalRejectionForUnmappedResource(t *testing.T) {
	executor, store := newRejectionExecutor(t)
	intent := protocol.ImmutableIntent{
		CommandID:         "unmapped-target",
		EndpointID:        "e1",
		Operation:         protocol.OperationMessageSend,
		OperationVersion:  "v1",
		Target:            &protocol.CommandTarget{Kind: "session", ResourceID: "res_absent", ProviderGeneration: "g1"},
		ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}
	receipt, err := executor.Execute(context.Background(), intent, "hash")
	if err != nil {
		t.Fatalf("an unmapped target is a decision, not an infrastructure failure: %v", err)
	}
	if receipt.ErrorCode != "target_not_found" {
		t.Fatalf("error code=%q, want target_not_found", receipt.ErrorCode)
	}
	assertTerminalRejection(t, store, intent.CommandID, "target_not_found")
}

// TestExecuteRecordsTerminalRejectionForUnconfiguredAdapter proves a mapping
// that points at an adapter this Endpoint no longer runs is terminally rejected
// rather than reported as an infrastructure failure.
func TestExecuteRecordsTerminalRejectionForUnconfiguredAdapter(t *testing.T) {
	executor, store := newRejectionExecutor(t)
	mapping, err := store.GetOrCreateResourceID(context.Background(), "a_removed", "provider", 1)
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{
		CommandID:         "unconfigured-adapter",
		EndpointID:        "e1",
		Operation:         protocol.OperationMessageSend,
		OperationVersion:  "v1",
		Target:            &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, ProviderGeneration: "g1"},
		ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}
	receipt, err := executor.Execute(context.Background(), intent, "hash")
	if err != nil {
		t.Fatalf("an unconfigured adapter is a decision, not an infrastructure failure: %v", err)
	}
	if receipt.ErrorCode != "adapter_not_configured" {
		t.Fatalf("error code=%q, want adapter_not_configured", receipt.ErrorCode)
	}
	assertTerminalRejection(t, store, intent.CommandID, "adapter_not_configured")
}

// TestServiceDoesNotPublishReceiptWithoutCommandID proves the transport never
// carries a receipt the Server cannot persist. The Server rejects a receipt
// whose command ID is empty, so publishing one would leave the command
// non-terminal forever while the Endpoint believed it had reported the result.
func TestServiceDoesNotPublishReceiptWithoutCommandID(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	transport := newServiceChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: coverageExecutor{}})
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            "cmd",
		EndpointID:           "e1",
		Operation:            protocol.OperationMessageSend,
		OperationVersion:     "v1",
		PayloadSchemaVersion: "v1",
		CapabilityRevision:   "c1",
		Payload:              []byte(`{}`),
		Target:               &protocol.CommandTarget{ResourceID: "r", ProviderGeneration: "g"},
	}
	service.executeFrame(context.Background(), channel.Frame{Type: channel.FrameCommand, FrameID: "cmd", RequestID: "req", Intent: &intent})
	if count := transport.count(channel.FrameReceipt); count != 0 {
		t.Fatalf("published %d receipt frames for an unusable receipt, want 0", count)
	}
	transport.mu.Lock()
	defer transport.mu.Unlock()
	for _, frame := range transport.frames {
		if frame.Type == channel.FrameReceipt && (frame.Receipt == nil || frame.Receipt.CommandID == "") {
			t.Fatalf("published a receipt without a command ID: %#v", frame.Receipt)
		}
	}
}
