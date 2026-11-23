package serverstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestWarningsRoundTripThroughStorage proves a Provider warning survives
// persistence and both read paths.
//
// The warning is the only evidence that a hard interrupt dropped the operator's
// message, so losing it on reload would leave a command that ran with text
// silently discarded and nothing to explain it. Both read paths are asserted
// because `status` uses GetCommand while the list surface uses ListCommands, and
// a field copied in only one of them would be visible in one view and absent in
// the other.
func TestWarningsRoundTripThroughStorage(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)

	intent := protocol.ImmutableIntent{
		CommandID:         "cmd-warnings",
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationExecutionInterrupt,
		OperationVersion:  "v1",
		ExecuteBeforeAtMS: 5000,
		Target:            &protocol.CommandTarget{ResourceID: "res-1", ProviderGeneration: "g1"},
	}
	if err := store.AdmitCommand(ctx, intent, "hash-warnings", 1000); err != nil {
		t.Fatalf("admit command: %v", err)
	}
	warning := "hard_interrupt carries no message, so the supplied message was not delivered"
	receipt := protocol.ExecutionReceipt{
		CommandID:          intent.CommandID,
		RequestHash:        "hash-warnings",
		CommandRevision:    1,
		EndpointInstanceID: "instance-1",
		Phase:              protocol.PhaseReceiptRecorded,
		DeliveryBoundary:   protocol.DeliverySubmitted,
		EffectCertainty:    protocol.EffectAcknowledged,
		Outcome:            "not_reported",
		Warnings:           []string{warning},
	}
	if err := store.ApplyReceipt(ctx, receipt, 1100); err != nil {
		t.Fatalf("apply receipt: %v", err)
	}

	record, err := store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		t.Fatalf("get command: %v", err)
	}
	if len(record.Warnings) != 1 || record.Warnings[0] != warning {
		t.Fatalf("GetCommand warnings = %#v, want exactly %q", record.Warnings, warning)
	}

	records, err := store.ListCommands(ctx, "endpoint-1", "", 10)
	if err != nil {
		t.Fatalf("list commands: %v", err)
	}
	if len(records) != 1 {
		t.Fatalf("ListCommands returned %d records, want 1", len(records))
	}
	if len(records[0].Warnings) != 1 || records[0].Warnings[0] != warning {
		t.Fatalf("ListCommands warnings = %#v, want exactly %q", records[0].Warnings, warning)
	}
}

// TestNoWarningsStaysAbsentAfterReload proves a command without a warning does
// not acquire an empty one.
//
// An empty slice and an absent field render differently: the renderer prints a
// `warnings:` heading for a non-empty list only, so an empty-but-present slice
// would be harmless here, but a stored empty slice would still make every
// warning-free command carry a field it never had. Asserting absence keeps the
// stored document identical to what the Provider sent.
func TestNoWarningsStaysAbsentAfterReload(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	seedEndpoint(t, store)

	intent := protocol.ImmutableIntent{
		CommandID:         "cmd-no-warnings",
		EndpointID:        "endpoint-1",
		Operation:         protocol.OperationMessageSend,
		OperationVersion:  "v1",
		ExecuteBeforeAtMS: 5000,
		Target:            &protocol.CommandTarget{ResourceID: "res-1", ProviderGeneration: "g1"},
	}
	if err := store.AdmitCommand(ctx, intent, "hash-no-warnings", 1000); err != nil {
		t.Fatalf("admit command: %v", err)
	}
	receipt := protocol.ExecutionReceipt{
		CommandID:          intent.CommandID,
		RequestHash:        "hash-no-warnings",
		CommandRevision:    1,
		EndpointInstanceID: "instance-1",
		Phase:              protocol.PhaseReceiptRecorded,
		DeliveryBoundary:   protocol.DeliverySubmitted,
		EffectCertainty:    protocol.EffectAcknowledged,
		Outcome:            "not_reported",
	}
	if err := store.ApplyReceipt(ctx, receipt, 1100); err != nil {
		t.Fatalf("apply receipt: %v", err)
	}
	record, err := store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		t.Fatalf("get command: %v", err)
	}
	if len(record.Warnings) != 0 {
		t.Fatalf("a command without a warning reloaded with %#v", record.Warnings)
	}
}
