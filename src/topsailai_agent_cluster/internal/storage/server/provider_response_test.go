package serverstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestProviderResponseRoundTripsThroughStorage proves the provider's own return
// document survives persistence and both read paths, so the operator can still
// see it through `status` after the command finished. Server stores and returns
// the document verbatim without parsing any provider field.
func TestProviderResponseRoundTripsThroughStorage(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)

	intent := protocol.ImmutableIntent{
		CommandID:         "cmd-provider-response",
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationMessageSend,
		OperationVersion:  "v1",
		ExecuteBeforeAtMS: 5000,
		Target:            &protocol.CommandTarget{ResourceID: "res-1", ProviderGeneration: "g1"},
	}
	if err := store.AdmitCommand(ctx, intent, "hash-provider-response", 1000); err != nil {
		t.Fatalf("admit command: %v", err)
	}
	document := `{"ok":true,"delivery_state":"submitted","request_id":"req-1"}`
	receipt := protocol.ExecutionReceipt{
		CommandID:          intent.CommandID,
		RequestHash:        "hash-provider-response",
		CommandRevision:    1,
		EndpointInstanceID: "instance-1",
		Phase:              protocol.PhaseReceiptRecorded,
		DeliveryBoundary:   protocol.DeliverySubmitted,
		EffectCertainty:    protocol.EffectAcknowledged,
		Outcome:            "not_reported",
		ProviderResponse:   document,
	}
	if err := store.ApplyReceipt(ctx, receipt, 1100); err != nil {
		t.Fatalf("apply receipt: %v", err)
	}

	record, err := store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		t.Fatalf("get command: %v", err)
	}
	if record.ProviderResponse != document {
		t.Fatalf("GetCommand provider response = %q, want %q", record.ProviderResponse, document)
	}
	if record.ProviderResponseTruncated {
		t.Fatal("a complete document must not be marked truncated")
	}

	records, err := store.ListCommands(ctx, "endpoint-1", "", 10)
	if err != nil {
		t.Fatalf("list commands: %v", err)
	}
	if len(records) != 1 || records[0].ProviderResponse != document {
		t.Fatalf("ListCommands provider response = %#v", records)
	}
}

// TestProviderResponseTruncationFlagRoundTrips proves the truncation label is
// persisted, so a bounded document is never presented as complete after reload.
func TestProviderResponseTruncationFlagRoundTrips(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)

	intent := protocol.ImmutableIntent{
		CommandID:         "cmd-truncated",
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationMessageSend,
		OperationVersion:  "v1",
		ExecuteBeforeAtMS: 5000,
		Target:            &protocol.CommandTarget{ResourceID: "res-1", ProviderGeneration: "g1"},
	}
	if err := store.AdmitCommand(ctx, intent, "hash-truncated", 1000); err != nil {
		t.Fatalf("admit command: %v", err)
	}
	receipt := protocol.ExecutionReceipt{
		CommandID:                 intent.CommandID,
		RequestHash:               "hash-truncated",
		CommandRevision:           1,
		EndpointInstanceID:        "instance-1",
		Phase:                     protocol.PhaseReceiptRecorded,
		EffectCertainty:           protocol.EffectAcknowledged,
		Outcome:                   "not_reported",
		ProviderResponse:          `{"ok":true`,
		ProviderResponseTruncated: true,
	}
	if err := store.ApplyReceipt(ctx, receipt, 1100); err != nil {
		t.Fatalf("apply receipt: %v", err)
	}
	record, err := store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		t.Fatalf("get command: %v", err)
	}
	if !record.ProviderResponseTruncated {
		t.Fatal("truncation flag did not survive persistence")
	}
}
