package endpointstorage

import (
	"context"
	"database/sql"
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
	first, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "provider-key", 100)
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
	second, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "provider-key", 200)
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
	success := SourceSnapshot{AdapterID: "adapter-a", ProviderType: "fixture", DisplayName: "A", Version: "1", Health: "healthy", Sessions: []protocol.Session{{ClusterSessionID: "s1", AdapterID: "adapter-a"}}, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 100, LastSuccessAtMS: ptr(100), DataKnown: true}
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
	if len(item.Sessions) != 1 || item.Sessions[0].ClusterSessionID != "s1" {
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
	mapping, err := store.GetOrCreateResourceID(ctx, "a1", protocol.ResourceSession, "provider-1", 1)
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

func TestExpireSourceSnapshotsUsesLastSuccessAndPreservesDurableRecords(t *testing.T) {
	store, ctx := openTestStore(t)
	oldSuccess := int64(100)
	freshSuccess := int64(900)
	for _, snapshot := range []SourceSnapshot{
		{AdapterID: "old", ProviderType: "fixture", DisplayName: "old", Health: "healthy", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 800, LastSuccessAtMS: &oldSuccess, DataKnown: true, ReportComplete: true},
		{AdapterID: "fresh", ProviderType: "fixture", DisplayName: "fresh", Health: "healthy", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 900, LastSuccessAtMS: &freshSuccess, DataKnown: true, ReportComplete: true},
		{AdapterID: "never-succeeded", ProviderType: "fixture", DisplayName: "unknown", Health: "unknown", CollectionStatus: protocol.CollectionFailed, LastAttemptAtMS: 200},
	} {
		if err := store.ApplySourceSnapshot(ctx, snapshot, snapshot.LastAttemptAtMS); err != nil {
			t.Fatal(err)
		}
	}
	mapping, err := store.GetOrCreateResourceID(ctx, "old", protocol.ResourceSession, "provider-key", 100)
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-cache-expiry", EndpointID: "ep", Operation: "send", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{}`)}
	if _, inserted, err := store.AdmitJournal(ctx, intent, "hash-cache-expiry", 100); err != nil || !inserted {
		t.Fatalf("admit journal inserted=%v error=%v", inserted, err)
	}

	deleted, err := store.ExpireSourceSnapshots(ctx, 500)
	if err != nil {
		t.Fatal(err)
	}
	if len(deleted) != 2 || deleted[0] != "never-succeeded" || deleted[1] != "old" {
		t.Fatalf("deleted=%v, want [never-succeeded old]", deleted)
	}
	remaining, err := store.ListSourceSnapshots(ctx)
	if err != nil || len(remaining) != 1 || remaining[0].AdapterID != "fresh" {
		t.Fatalf("remaining=%#v error=%v", remaining, err)
	}
	if got, err := store.LookupResourceID(ctx, mapping.ResourceID); err != nil || got != mapping {
		t.Fatalf("resource mapping was deleted: got=%#v error=%v", got, err)
	}
	if entry, err := store.GetJournal(ctx, intent.CommandID); err != nil || entry.CommandID != intent.CommandID {
		t.Fatalf("command journal was deleted: entry=%#v error=%v", entry, err)
	}
}

func TestExpireSourceSnapshotsRejectsInvalidCutoff(t *testing.T) {
	store, ctx := openTestStore(t)
	if _, err := store.ExpireSourceSnapshots(ctx, 0); err == nil {
		t.Fatal("zero cutoff was accepted")
	}
}

func TestResourceMappingSeparatesResourceKinds(t *testing.T) {
	store, ctx := openTestStore(t)
	session, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "shared-key", 100)
	if err != nil {
		t.Fatal(err)
	}
	task, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceTask, "shared-key", 101)
	if err != nil {
		t.Fatal(err)
	}
	if session.ResourceID == task.ResourceID {
		t.Fatalf("session and task shared resource ID %q", session.ResourceID)
	}
	if session.ResourceKind != protocol.ResourceSession || task.ResourceKind != protocol.ResourceTask {
		t.Fatalf("resource kinds session=%q task=%q", session.ResourceKind, task.ResourceKind)
	}
	repeated, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "shared-key", 102)
	if err != nil {
		t.Fatal(err)
	}
	if repeated != session {
		t.Fatalf("repeated mapping=%#v want=%#v", repeated, session)
	}
}

func TestResourceMappingRejectsInvalidIdentity(t *testing.T) {
	store, ctx := openTestStore(t)
	for _, testCase := range []struct {
		name         string
		adapterID    string
		resourceKind string
		providerKey  string
		nowMS        int64
	}{
		{name: "empty adapter", resourceKind: protocol.ResourceSession, providerKey: "key", nowMS: 1},
		{name: "invalid kind", adapterID: "adapter-a", resourceKind: "workspace", providerKey: "key", nowMS: 1},
		{name: "empty provider key", adapterID: "adapter-a", resourceKind: protocol.ResourceSession, nowMS: 1},
		{name: "invalid timestamp", adapterID: "adapter-a", resourceKind: protocol.ResourceSession, providerKey: "key"},
	} {
		t.Run(testCase.name, func(t *testing.T) {
			if _, err := store.GetOrCreateResourceID(ctx, testCase.adapterID, testCase.resourceKind, testCase.providerKey, testCase.nowMS); err == nil {
				t.Fatal("invalid resource identity was accepted")
			}
		})
	}
}

func TestResourceMappingMigrationPreservesLegacyIDs(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "legacy.db")
	createLegacyResourceMappings(t, path)

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	session, err := store.LookupResourceID(ctx, "res_session_existing")
	if err != nil {
		t.Fatal(err)
	}
	if session.AdapterID != "adapter-a" || session.ResourceKind != protocol.ResourceSession || session.ProviderResourceKey != "session-row:opaque" {
		t.Fatalf("migrated session=%#v", session)
	}
	model, err := store.LookupResourceID(ctx, "res_model_existing")
	if err != nil {
		t.Fatal(err)
	}
	if model.AdapterID != "adapter-a" || model.ResourceKind != protocol.ResourceModelProfile || model.ProviderResourceKey != "model:claude" {
		t.Fatalf("migrated model=%#v", model)
	}
	for _, resourceID := range []string{"res_session_existing", "res_model_existing"} {
		var createdAtMS, updateAtMS int64
		if err := store.db.QueryRowContext(ctx, `SELECT created_at_ms, update_at_ms FROM resource_mapping WHERE resource_id=?`, resourceID).Scan(&createdAtMS, &updateAtMS); err != nil {
			t.Fatal(err)
		}
		if createdAtMS != 100 || updateAtMS != 200 {
			t.Fatalf("resource %q timestamps=(%d,%d), want (100,200)", resourceID, createdAtMS, updateAtMS)
		}
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}

	store, err = Open(ctx, path)
	if err != nil {
		t.Fatalf("idempotent reopen: %v", err)
	}
	defer store.Close()
	repeated, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceModelProfile, "model:claude", 300)
	if err != nil {
		t.Fatal(err)
	}
	if repeated.ResourceID != "res_model_existing" {
		t.Fatalf("model resource ID changed to %q", repeated.ResourceID)
	}
	if _, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceTask, "session-row:opaque", 301); err != nil {
		t.Fatalf("new resource kind after migration: %v", err)
	}
}

// createLegacyResourceMappings creates the pre-resource-kind schema and representative rows.
func createLegacyResourceMappings(t *testing.T, path string) {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	const schema = `CREATE TABLE resource_mapping (
		adapter_id TEXT NOT NULL,
		provider_key TEXT NOT NULL,
		resource_id TEXT NOT NULL,
		created_at_ms BIGINT NOT NULL,
		update_at_ms BIGINT NOT NULL,
		PRIMARY KEY (adapter_id, provider_key),
		UNIQUE (resource_id)
	);`
	if _, err := db.Exec(schema); err != nil {
		t.Fatal(err)
	}
	for _, row := range []struct {
		providerKey string
		resourceID  string
	}{
		{providerKey: "session-row:opaque", resourceID: "res_session_existing"},
		{providerKey: "model:claude", resourceID: "res_model_existing"},
	} {
		if _, err := db.Exec(`INSERT INTO resource_mapping(adapter_id, provider_key, resource_id, created_at_ms, update_at_ms) VALUES(?, ?, ?, 100, 200)`, "adapter-a", row.providerKey, row.resourceID); err != nil {
			t.Fatal(err)
		}
	}
}

func TestResourceMappingMigrationRollsBackOnCopyFailure(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "invalid-legacy.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	const schema = `CREATE TABLE resource_mapping (
		adapter_id TEXT NOT NULL,
		provider_key TEXT NOT NULL,
		resource_id TEXT NOT NULL,
		created_at_ms BIGINT NOT NULL,
		update_at_ms BIGINT NOT NULL,
		PRIMARY KEY (adapter_id, provider_key)
	);`
	if _, err := db.Exec(schema); err != nil {
		t.Fatal(err)
	}
	for _, providerKey := range []string{"session-one", "session-two"} {
		if _, err := db.Exec(`INSERT INTO resource_mapping(adapter_id, provider_key, resource_id, created_at_ms, update_at_ms) VALUES('adapter-a', ?, 'res_duplicate', 1, 1)`, providerKey); err != nil {
			t.Fatal(err)
		}
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}

	if store, err := Open(ctx, path); err == nil {
		_ = store.Close()
		t.Fatal("migration with duplicate resource IDs succeeded")
	}
	db, err = sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	columns := make(map[string]bool)
	rows, err := db.Query(`PRAGMA table_info(resource_mapping)`)
	if err != nil {
		t.Fatal(err)
	}
	for rows.Next() {
		var cid, notNull, primaryKey int
		var name, columnType string
		var defaultValue any
		if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			rows.Close()
			t.Fatal(err)
		}
		columns[name] = true
	}
	if err := rows.Close(); err != nil {
		t.Fatal(err)
	}
	if !columns["provider_key"] || columns["provider_resource_key"] || columns["resource_kind"] {
		t.Fatalf("failed migration changed legacy columns: %#v", columns)
	}
	var count int
	if err := db.QueryRow(`SELECT COUNT(*) FROM resource_mapping`).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 2 {
		t.Fatalf("legacy row count = %d, want 2", count)
	}
}

func TestResourceMappingResourceIDIsUnique(t *testing.T) {
	store, ctx := openTestStore(t)
	first, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "session-one", 1)
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.db.ExecContext(ctx, `INSERT INTO resource_mapping(adapter_id, resource_kind, provider_resource_key, resource_id, created_at_ms, update_at_ms) VALUES('adapter-a', ?, 'session-two', ?, 2, 2)`, protocol.ResourceSession, first.ResourceID)
	if err == nil {
		t.Fatal("duplicate resource ID was accepted")
	}
}
