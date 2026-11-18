package endpoint

import (
	"context"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// seedSettledReceipt writes one settled receipt_recorded row so a collection cycle
// has something eligible for retention.
func seedSettledReceipt(t *testing.T, store *endpointstorage.Store, commandID string, createdAtMS int64) {
	t.Helper()
	ctx := context.Background()
	intent := protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            commandID,
		EndpointID:           "endpoint-1",
		Operation:            "message.send",
		OperationVersion:     "v1",
		CapabilityRevision:   "v1",
		PayloadSchemaVersion: "v1",
		Payload:              []byte(`{"text":"x"}`),
		ExecuteBeforeAtMS:    100,
	}
	if _, _, err := store.AdmitJournal(ctx, intent, "hash-"+commandID, createdAtMS); err != nil {
		t.Fatalf("admit journal %s: %v", commandID, err)
	}
	receipt := protocol.ExecutionReceipt{
		CommandID:       commandID,
		RequestHash:     "hash-" + commandID,
		CommandRevision: 1,
		Phase:           protocol.PhaseReceiptRecorded,
		EffectCertainty: protocol.EffectAcknowledged,
		Outcome:         "accepted",
	}
	if err := store.RecordReceipt(ctx, commandID, receipt, createdAtMS+1); err != nil {
		t.Fatalf("record receipt %s: %v", commandID, err)
	}
	if err := store.SettleReceipt(ctx, commandID, protocol.SettlementOriginRejection, protocol.ReceiptRejectedUnknownCommand, createdAtMS+2); err != nil {
		t.Fatalf("settle %s: %v", commandID, err)
	}
}

// journalRowExists reports whether the durable row survived, using the public
// storage API rather than raw SQL so the assertion cannot depend on an unexported
// field.
func journalRowExists(t *testing.T, store *endpointstorage.Store, commandID string) bool {
	t.Helper()
	_, err := store.GetJournal(context.Background(), commandID)
	if err == nil {
		return true
	}
	if strings.Contains(err.Error(), "not found") {
		return false
	}
	t.Fatalf("read journal %s: %v", commandID, err)
	return false
}

// newRetentionCollector builds a collector with one healthy binding so a
// collection cycle runs to completion.
func newRetentionCollector(t *testing.T, store *endpointstorage.Store, options CollectorOptions) *Collector {
	t.Helper()
	bindings := []Binding{{
		AdapterID:    "current",
		ProviderType: "fixture",
		Adapter:      fakeAdapter{result: adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded}},
	}}
	collector, err := NewCollectorWithOptions(context.Background(), bindings, time.Second, store, options)
	if err != nil {
		t.Fatalf("create collector: %v", err)
	}
	return collector
}

// TestCollectExpiresSettledJournalReceipts proves the collection cycle is the
// place retention actually runs, and that each deletion is logged with the detail
// an operator needs to audit it.
func TestCollectExpiresSettledJournalReceipts(t *testing.T) {
	ctx := context.Background()
	store, err := endpointstorage.Open(ctx, t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	defer store.Close()
	seedSettledReceipt(t, store, "cmd-old", 100)

	var logged []endpointstorage.ExpiredJournalEntry
	collector := newRetentionCollector(t, store, CollectorOptions{
		CommandJournalExpiry: time.Hour,
		LogJournalDeletion: func(entry endpointstorage.ExpiredJournalEntry, retention time.Duration) {
			logged = append(logged, entry)
		},
	})
	// observedAtMS is one millisecond past the window, so the cutoff is strictly
	// greater than the row's creation time. The predicate is a strict comparison,
	// so a cutoff equal to the row time keeps the row.
	if _, err := collector.Collect(ctx, 100+time.Hour.Milliseconds()+1); err != nil {
		t.Fatalf("collect: %v", err)
	}
	if journalRowExists(t, store, "cmd-old") {
		t.Fatal("the settled receipt survived the collection cycle, want it deleted because it is past the retention window")
	}
	if len(logged) != 1 {
		t.Fatalf("deletion log entries = %d, want 1", len(logged))
	}
	if logged[0].CommandID != "cmd-old" {
		t.Fatalf("logged command id = %q, want cmd-old", logged[0].CommandID)
	}
	if logged[0].EffectCertainty != string(protocol.EffectAcknowledged) {
		t.Fatalf("logged effect certainty = %q, want %q so the audit log states whether the command applied", logged[0].EffectCertainty, protocol.EffectAcknowledged)
	}
}

// TestCollectKeepsJournalReceiptsInsideTheWindow proves a configured window is
// honoured, so enabling retention cannot delete recent evidence.
func TestCollectKeepsJournalReceiptsInsideTheWindow(t *testing.T) {
	ctx := context.Background()
	store, err := endpointstorage.Open(ctx, t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	defer store.Close()
	seedSettledReceipt(t, store, "cmd-recent", 100)

	var logged int
	collector := newRetentionCollector(t, store, CollectorOptions{
		CommandJournalExpiry: 720 * time.Hour,
		LogJournalDeletion: func(endpointstorage.ExpiredJournalEntry, time.Duration) {
			logged++
		},
	})
	if _, err := collector.Collect(ctx, 100+time.Minute.Milliseconds()); err != nil {
		t.Fatalf("collect: %v", err)
	}
	if !journalRowExists(t, store, "cmd-recent") {
		t.Fatal("the settled receipt was deleted although it is inside the retention window")
	}
	if logged != 0 {
		t.Fatalf("deletion log entries = %d, want 0", logged)
	}
}

// TestCollectSkipsJournalRetentionWhenDisabled proves a zero window disables
// retention, which is the behaviour tests and callers that have not opted into
// lifecycle management rely on.
func TestCollectSkipsJournalRetentionWhenDisabled(t *testing.T) {
	ctx := context.Background()
	store, err := endpointstorage.Open(ctx, t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	defer store.Close()
	seedSettledReceipt(t, store, "cmd-old", 100)

	collector := newRetentionCollector(t, store, CollectorOptions{})
	if _, err := collector.Collect(ctx, 100+time.Hour.Milliseconds()); err != nil {
		t.Fatalf("collect: %v", err)
	}
	if !journalRowExists(t, store, "cmd-old") {
		t.Fatal("the settled receipt was deleted although a zero window disables retention")
	}
}

// TestCollectFailsWhenJournalRetentionFails proves a retention failure is
// returned rather than logged and ignored. Continuing would leave a table that is
// supposed to be bounded growing while every cycle reports success.
func TestCollectFailsWhenJournalRetentionFails(t *testing.T) {
	ctx := context.Background()
	store, err := endpointstorage.Open(ctx, t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open endpoint store: %v", err)
	}
	seedSettledReceipt(t, store, "cmd-old", 100)
	// The collector is built while the store is open, because construction reads
	// the cache. Closing afterwards makes the retention query fail while the
	// collector still holds a non-nil store pointer.
	collector := newRetentionCollector(t, store, CollectorOptions{CommandJournalExpiry: time.Hour})
	if err := store.Close(); err != nil {
		t.Fatalf("close store: %v", err)
	}
	if _, err := collector.Collect(ctx, 100+time.Hour.Milliseconds()); err == nil {
		t.Fatal("collect succeeded although command journal retention failed, want an error")
	}
}

// TestNewCollectorRejectsNegativeJournalExpiry proves a negative window is refused
// at construction instead of being treated as a very short window.
func TestNewCollectorRejectsNegativeJournalExpiry(t *testing.T) {
	ctx := context.Background()
	if _, err := NewCollectorWithOptions(ctx, nil, time.Second, nil, CollectorOptions{CommandJournalExpiry: -time.Hour}); err == nil {
		t.Fatal("collector accepted a negative command journal expiry, want an error")
	}
}
