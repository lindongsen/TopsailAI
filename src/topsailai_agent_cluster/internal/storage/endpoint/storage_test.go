package endpointstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func openTestStore(t *testing.T) (*Store, context.Context) {
	t.Helper()
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "endpoint.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store, ctx
}

func TestResourceMappingSurvivesRestart(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "endpoint.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	first, err := store.GetOrCreateResourceID(ctx, "adapter-a", "provider-key", 100)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	second, err := store.GetOrCreateResourceID(ctx, "adapter-a", "provider-key", 200)
	if err != nil {
		t.Fatal(err)
	}
	if first.ResourceID != second.ResourceID {
		t.Fatalf("resource ID changed: %q != %q", first.ResourceID, second.ResourceID)
	}
	if second.ResourceID == "provider-key" {
		t.Fatal("provider key leaked as resource ID")
	}
}

func TestJournalStagesAreDurableAndConflict(t *testing.T) {
	store, ctx := openTestStore(t)
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-1", EndpointID: "ep-1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "cap-1", PayloadSchemaVersion: "v1", Payload: []byte(`{"message":"hello"}`)}
	entry, inserted, err := store.AdmitJournal(ctx, intent, "hash-1", 100)
	if err != nil || !inserted || entry.Phase != protocol.PhaseAccepted {
		t.Fatalf("admit: %#v %v %v", entry, inserted, err)
	}
	if _, _, err := store.AdmitJournal(ctx, intent, "hash-2", 101); err == nil {
		t.Fatal("expected hash conflict")
	}
	if err := store.MarkInvocationStarted(ctx, intent.CommandID, 102); err != nil {
		t.Fatal(err)
	}
	if err := store.MarkEndpointAdmitted(ctx, intent.CommandID, 103); err != nil {
		t.Fatal(err)
	}
	admitted, err := store.GetJournal(ctx, intent.CommandID)
	if err != nil || admitted.Phase != protocol.PhaseEndpointAdmitted {
		t.Fatalf("admitted journal=%#v err=%v", admitted, err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: "hash-1", Phase: protocol.PhaseReceiptRecorded, DeliveryBoundary: protocol.DeliveryPipeWritten, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	if err := store.RecordReceipt(ctx, intent.CommandID, receipt, 104); err != nil {
		t.Fatal(err)
	}
	entry, err = store.GetJournal(ctx, intent.CommandID)
	if err != nil || entry.Phase != protocol.PhaseReceiptRecorded || entry.ReceiptJSON == "" {
		t.Fatalf("receipt: %#v %v", entry, err)
	}
}

func TestSourceCachePreservesLastSuccessOnFailure(t *testing.T) {
	store, ctx := openTestStore(t)
	success := SourceSnapshot{AdapterID: "adapter-a", ProviderType: "fixture", DisplayName: "A", Version: "1", Health: "healthy", Sessions: []protocol.Session{{SessionID: "s1", AdapterID: "adapter-a"}}, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 100, LastSuccessAtMS: ptr(100), DataKnown: true}
	if err := store.ApplySourceSnapshot(ctx, success, 100); err != nil {
		t.Fatal(err)
	}
	failure := success
	failure.Sessions = nil
	failure.ReportComplete = false
	failure.CollectionStatus = protocol.CollectionFailed
	failure.LastAttemptAtMS = 200
	failure.LastSuccessAtMS = nil
	failure.DataKnown = true
	failure.Stale = true
	failure.ErrorCode = "timeout"
	if err := store.ApplySourceSnapshot(ctx, failure, 200); err != nil {
		t.Fatal(err)
	}
	items, err := store.ListSourceSnapshots(ctx)
	if err != nil || len(items) != 1 {
		t.Fatalf("list: %v %#v", err, items)
	}
	item := items[0]
	if len(item.Sessions) != 1 || item.Sessions[0].SessionID != "s1" {
		t.Fatalf("old sessions lost: %#v", item.Sessions)
	}
	if item.LastSuccessAtMS == nil || *item.LastSuccessAtMS != 100 || !item.Stale || item.CollectionStatus != protocol.CollectionFailed {
		t.Fatalf("stale evidence lost: %#v", item)
	}
}

func ptr(value int64) *int64 { return &value }

func TestJournalListsAcceptedAndRecordedReceipts(t *testing.T) {
	store, ctx := openTestStore(t)
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-list", EndpointID: "ep", Operation: "send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{}`)}
	if _, inserted, err := store.AdmitJournal(ctx, intent, "hash-list", 1); err != nil || !inserted {
		t.Fatalf("admit: inserted=%v err=%v", inserted, err)
	}
	accepted, err := store.ListAcceptedCommands(ctx)
	if err != nil || len(accepted) != 1 || accepted[0].CommandID != intent.CommandID {
		t.Fatalf("accepted=%#v err=%v", accepted, err)
	}
	if err := store.MarkInvocationStarted(ctx, intent.CommandID, 2); err != nil {
		t.Fatal(err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: "hash-list", Phase: protocol.PhaseReceiptRecorded, Outcome: "accepted"}
	if err := store.RecordReceipt(ctx, intent.CommandID, receipt, 3); err != nil {
		t.Fatal(err)
	}
	recorded, err := store.ListRecordedReceipts(ctx)
	if err != nil || len(recorded) != 1 || recorded[0].CommandID != intent.CommandID {
		t.Fatalf("recorded=%#v err=%v", recorded, err)
	}
}

func TestResourceMappingLookupValidation(t *testing.T) {
	store, ctx := openTestStore(t)
	if _, err := store.LookupResourceID(ctx, ""); err == nil {
		t.Fatal("empty resource ID was accepted")
	}
	mapping, err := store.GetOrCreateResourceID(ctx, "a1", "provider-1", 1)
	if err != nil {
		t.Fatal(err)
	}
	got, err := store.LookupResourceID(ctx, mapping.ResourceID)
	if err != nil || got != mapping {
		t.Fatalf("mapping=%#v err=%v want=%#v", got, err, mapping)
	}
	if _, err := store.LookupResourceID(ctx, "res_missing"); err == nil {
		t.Fatal("missing resource mapping was accepted")
	}
}
