package endpointstorage

import (
	"context"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// openStoreAt opens a store at an explicit path so a test can close and reopen it.
func openStoreAt(t *testing.T, ctx context.Context, path string) *Store {
	t.Helper()
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open store at %q: %v", path, err)
	}
	return store
}

// sourceSnapshot builds a complete successful snapshot for one adapter.
func sourceSnapshot(adapterID string, sessionIDs []string, attemptMS int64, successMS *int64) SourceSnapshot {
	sessions := make([]protocol.Session, 0, len(sessionIDs))
	for _, sessionID := range sessionIDs {
		sessions = append(sessions, protocol.Session{
			ClusterSessionID:  sessionID,
			ProviderSessionID: "provider-" + sessionID,
			AdapterID:         adapterID,
			State:             "running",
			ObservedAtMS:      attemptMS,
		})
	}
	return SourceSnapshot{
		AdapterID:        adapterID,
		ProviderType:     "fixture",
		DisplayName:      adapterID,
		Version:          "1",
		Health:           "healthy",
		Sessions:         sessions,
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		LastAttemptAtMS:  attemptMS,
		LastSuccessAtMS:  successMS,
		DataKnown:        true,
	}
}

// TestSourceCacheSurvivesRestart pins that a persisted source row, including the
// Session adapter association inside sessions_json, is still readable after the
// process closes and reopens the database.
func TestSourceCacheSurvivesRestart(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "endpoint.db")
	store := openStoreAt(t, ctx, path)
	success := int64(100)
	if err := store.ApplySourceSnapshot(ctx, sourceSnapshot("adapter-a", []string{"res_session_one"}, 100, &success), 100); err != nil {
		t.Fatalf("apply source snapshot: %v", err)
	}
	if err := store.Close(); err != nil {
		t.Fatalf("close store: %v", err)
	}
	store = openStoreAt(t, ctx, path)
	defer store.Close()
	items, err := store.ListSourceSnapshots(ctx)
	if err != nil {
		t.Fatalf("list source snapshots after restart: %v", err)
	}
	if len(items) != 1 {
		t.Fatalf("source cache rows after restart=%d, want 1", len(items))
	}
	item := items[0]
	if len(item.Sessions) != 1 || item.Sessions[0].ClusterSessionID != "res_session_one" {
		t.Fatalf("sessions after restart=%#v, want the one persisted session", item.Sessions)
	}
	if item.Sessions[0].AdapterID != "adapter-a" {
		t.Fatalf("session adapter association after restart=%q, want adapter-a", item.Sessions[0].AdapterID)
	}
	if item.LastSuccessAtMS == nil || *item.LastSuccessAtMS != 100 {
		t.Fatalf("last success after restart=%v, want 100", item.LastSuccessAtMS)
	}
}

// TestJournalSurvivesRestart pins that the durable command record, its phase and
// its receipt are still readable after the process closes and reopens the database.
func TestJournalSurvivesRestart(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "endpoint.db")
	store := openStoreAt(t, ctx, path)
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-restart", EndpointID: "ep", Operation: "send", OperationVersion: "v1", CapabilityRevision: "cap", PayloadSchemaVersion: "v1", Payload: []byte(`{}`)}
	if _, inserted, err := store.AdmitJournal(ctx, intent, "hash-restart", 100); err != nil || !inserted {
		t.Fatalf("admit journal: inserted=%v error=%v", inserted, err)
	}
	if err := store.MarkInvocationStarted(ctx, intent.CommandID, 101); err != nil {
		t.Fatalf("mark invocation started: %v", err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: "hash-restart", Phase: protocol.PhaseReceiptRecorded, DeliveryBoundary: protocol.DeliveryPipeWritten, EffectCertainty: protocol.EffectAcknowledged, Outcome: "accepted"}
	if err := store.RecordReceipt(ctx, intent.CommandID, receipt, 102); err != nil {
		t.Fatalf("record receipt: %v", err)
	}
	if err := store.Close(); err != nil {
		t.Fatalf("close store: %v", err)
	}
	store = openStoreAt(t, ctx, path)
	defer store.Close()
	entry, err := store.GetJournal(ctx, intent.CommandID)
	if err != nil {
		t.Fatalf("get journal after restart: %v", err)
	}
	if entry.Phase != protocol.PhaseReceiptRecorded {
		t.Fatalf("journal phase after restart=%q, want %q", entry.Phase, protocol.PhaseReceiptRecorded)
	}
	if entry.ReceiptJSON == "" {
		t.Fatal("journal receipt after restart is empty, so the recorded evidence was lost")
	}
	if entry.RequestHash != "hash-restart" {
		t.Fatalf("journal request hash after restart=%q, want hash-restart", entry.RequestHash)
	}
}

// TestJournalKeepsTheFirstRecordOnReAdmit pins the DO NOTHING semantics: a repeated
// admit of the same command must return the original record and must not reset its
// phase, because resetting the phase would let a command be executed twice.
func TestJournalKeepsTheFirstRecordOnReAdmit(t *testing.T) {
	store, ctx := openTestStore(t)
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-keep", EndpointID: "ep", Operation: "send", OperationVersion: "v1", CapabilityRevision: "cap", PayloadSchemaVersion: "v1", Payload: []byte(`{}`)}
	if _, inserted, err := store.AdmitJournal(ctx, intent, "hash-keep", 100); err != nil || !inserted {
		t.Fatalf("admit journal: inserted=%v error=%v", inserted, err)
	}
	if err := store.MarkInvocationStarted(ctx, intent.CommandID, 101); err != nil {
		t.Fatalf("mark invocation started: %v", err)
	}
	entry, inserted, err := store.AdmitJournal(ctx, intent, "hash-keep", 200)
	if err != nil {
		t.Fatalf("re-admit journal: %v", err)
	}
	if inserted {
		t.Fatal("a repeated admit reported a new insert, so the first record was replaced")
	}
	if entry.Phase != protocol.PhaseInvocationStarted {
		t.Fatalf("phase after a repeated admit=%q, want %q: the first record was overwritten", entry.Phase, protocol.PhaseInvocationStarted)
	}
}

// TestSourceCacheReplacesSessionsOnCompleteSuccess pins the opposite direction of
// "not lost": a complete successful report must replace the previous session list,
// because a session the provider no longer reports is gone, not preserved.
func TestSourceCacheReplacesSessionsOnCompleteSuccess(t *testing.T) {
	store, ctx := openTestStore(t)
	first := int64(100)
	if err := store.ApplySourceSnapshot(ctx, sourceSnapshot("adapter-a", []string{"res_session_one"}, 100, &first), 100); err != nil {
		t.Fatalf("apply first snapshot: %v", err)
	}
	second := int64(200)
	if err := store.ApplySourceSnapshot(ctx, sourceSnapshot("adapter-a", []string{"res_session_two"}, 200, &second), 200); err != nil {
		t.Fatalf("apply second snapshot: %v", err)
	}
	item, found, err := store.SourceSnapshot(ctx, "adapter-a")
	if err != nil || !found {
		t.Fatalf("load source snapshot: found=%v error=%v", found, err)
	}
	if len(item.Sessions) != 1 || item.Sessions[0].ClusterSessionID != "res_session_two" {
		t.Fatalf("sessions after a complete success=%#v, want only res_session_two: a stale session survived a complete report", item.Sessions)
	}
}

// TestSourceCacheKeepsTheNewerLastSuccess pins the upgrade direction of the
// last_success_at_ms merge: a newer success must replace the older timestamp.
func TestSourceCacheKeepsTheNewerLastSuccess(t *testing.T) {
	store, ctx := openTestStore(t)
	first := int64(100)
	if err := store.ApplySourceSnapshot(ctx, sourceSnapshot("adapter-a", []string{"res_session_one"}, 100, &first), 100); err != nil {
		t.Fatalf("apply first snapshot: %v", err)
	}
	second := int64(900)
	if err := store.ApplySourceSnapshot(ctx, sourceSnapshot("adapter-a", []string{"res_session_one"}, 900, &second), 900); err != nil {
		t.Fatalf("apply second snapshot: %v", err)
	}
	item, found, err := store.SourceSnapshot(ctx, "adapter-a")
	if err != nil || !found {
		t.Fatalf("load source snapshot: found=%v error=%v", found, err)
	}
	if item.LastSuccessAtMS == nil || *item.LastSuccessAtMS != 900 {
		t.Fatalf("last success=%v, want 900: a newer success did not replace the older one", item.LastSuccessAtMS)
	}
}

// TestSourceCacheKeepsTheAdapterAssociationOnFailure pins that the Session
// adapter association inside sessions_json survives a failed collection, because
// a failure must not erase which adapter owned the retained sessions.
func TestSourceCacheKeepsTheAdapterAssociationOnFailure(t *testing.T) {
	store, ctx := openTestStore(t)
	success := int64(100)
	if err := store.ApplySourceSnapshot(ctx, sourceSnapshot("adapter-a", []string{"res_session_one"}, 100, &success), 100); err != nil {
		t.Fatalf("apply successful snapshot: %v", err)
	}
	failure := sourceSnapshot("adapter-a", nil, 200, nil)
	failure.ReportComplete = false
	failure.CollectionStatus = protocol.CollectionFailed
	failure.DataKnown = true
	failure.Stale = true
	failure.ErrorCode = "timeout"
	if err := store.ApplySourceSnapshot(ctx, failure, 200); err != nil {
		t.Fatalf("apply failed snapshot: %v", err)
	}
	item, found, err := store.SourceSnapshot(ctx, "adapter-a")
	if err != nil || !found {
		t.Fatalf("load source snapshot: found=%v error=%v", found, err)
	}
	if len(item.Sessions) != 1 {
		t.Fatalf("sessions after a failed collection=%#v, want the retained session", item.Sessions)
	}
	if item.Sessions[0].AdapterID != "adapter-a" {
		t.Fatalf("session adapter association after a failed collection=%q, want adapter-a", item.Sessions[0].AdapterID)
	}
	if item.LastSuccessAtMS == nil || *item.LastSuccessAtMS != 100 {
		t.Fatalf("last success after a failed collection=%v, want the retained 100", item.LastSuccessAtMS)
	}
}
