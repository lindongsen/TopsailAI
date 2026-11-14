package endpointstorage

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// legacyInitialSQL is the 001_initial.sql shipped before resource mappings were
// namespaced by kind. It is reproduced here so the downgrade test can build a
// database the way an older binary would have built it.
const legacyInitialSQL = `CREATE TABLE IF NOT EXISTS command_journal (
    command_id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,
    intent_json TEXT NOT NULL,
    phase TEXT NOT NULL,
    receipt_json TEXT,
    created_at_ms BIGINT NOT NULL,
    updated_at_ms BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS resource_mapping (
    adapter_id TEXT NOT NULL,
    provider_key TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at_ms BIGINT NOT NULL,
    update_at_ms BIGINT NOT NULL,
    PRIMARY KEY (adapter_id, provider_key),
    UNIQUE (resource_id)
);
CREATE TABLE IF NOT EXISTS source_cache (
    adapter_id TEXT PRIMARY KEY,
    provider_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    version TEXT NOT NULL,
    health TEXT NOT NULL,
    sessions_json TEXT NOT NULL,
    report_complete INTEGER NOT NULL,
    collection_status TEXT NOT NULL,
    last_attempt_at_ms BIGINT NOT NULL,
    last_success_at_ms BIGINT,
    data_known INTEGER NOT NULL,
    stale INTEGER NOT NULL,
    error_code TEXT,
    error_message TEXT,
    update_at_ms BIGINT NOT NULL
);`

// openRawSQLite opens a database without running any Endpoint migration, so a
// test can install an exact schema shape.
func openRawSQLite(t *testing.T, path string) *sql.DB {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open raw sqlite: %v", err)
	}
	t.Cleanup(func() { _ = db.Close() })
	return db
}

// mappingColumnsOf reads the resource_mapping column set from an open database.
func mappingColumnsOf(t *testing.T, db *sql.DB) map[string]bool {
	t.Helper()
	rows, err := db.Query(`PRAGMA table_info(resource_mapping)`)
	if err != nil {
		t.Fatalf("inspect resource_mapping: %v", err)
	}
	defer func() { _ = rows.Close() }()
	columns := make(map[string]bool)
	for rows.Next() {
		var cid, notNull, primaryKey int
		var name, columnType string
		var defaultValue any
		if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			t.Fatalf("scan resource_mapping column: %v", err)
		}
		columns[name] = true
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("read resource_mapping columns: %v", err)
	}
	return columns
}

// TestNewerBinaryRejectsAnUnrecognisedMappingShape pins the refusal the newer
// binary performs. A database whose resource_mapping has neither the current
// columns nor the legacy provider_key must be rejected rather than migrated.
func TestNewerBinaryRejectsAnUnrecognisedMappingShape(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "unrecognised.db")

	db := openRawSQLite(t, path)
	if _, err := db.Exec(`CREATE TABLE resource_mapping (
		adapter_id TEXT NOT NULL,
		resource_id TEXT NOT NULL,
		created_at_ms BIGINT NOT NULL,
		update_at_ms BIGINT NOT NULL
	)`); err != nil {
		t.Fatalf("create unrecognised resource_mapping: %v", err)
	}
	if err := db.Close(); err != nil {
		t.Fatalf("close raw database: %v", err)
	}

	store, err := Open(ctx, path)
	if err == nil {
		_ = store.Close()
		t.Fatal("an unrecognised resource_mapping shape was accepted")
	}
	if !strings.Contains(err.Error(), "resource_mapping schema is unsupported") {
		t.Fatalf("refusal message = %q, want it to contain %q", err.Error(), "resource_mapping schema is unsupported")
	}
}

// TestOlderMigrationStepAcceptsANewerDatabase pins the downgrade hazard: the
// older migration step is a set of CREATE TABLE IF NOT EXISTS statements, so it
// succeeds against a database a newer binary already converted.
func TestOlderMigrationStepAcceptsANewerDatabase(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "newer.db")

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open newer database: %v", err)
	}
	if err := store.Close(); err != nil {
		t.Fatalf("close newer database: %v", err)
	}

	db := openRawSQLite(t, path)
	if _, err := db.Exec(legacyInitialSQL); err != nil {
		t.Fatalf("older migration step failed against a newer database: %v", err)
	}

	columns := mappingColumnsOf(t, db)
	if columns["provider_key"] {
		t.Fatal("the older migration step added provider_key to a newer database")
	}
	if !columns["provider_resource_key"] || !columns["resource_kind"] {
		t.Fatalf("the newer mapping columns were lost: %#v", columns)
	}
}

// TestOlderBinaryCannotReadTheNewerMapping pins the late failure: an older
// binary queries provider_key, which a newer database does not have.
func TestOlderBinaryCannotReadTheNewerMapping(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "newer.db")

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open newer database: %v", err)
	}
	if _, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "session-one", 1); err != nil {
		_ = store.Close()
		t.Fatalf("create a newer mapping: %v", err)
	}
	if err := store.Close(); err != nil {
		t.Fatalf("close newer database: %v", err)
	}

	db := openRawSQLite(t, path)
	var adapterID, providerKey, resourceID string
	err = db.QueryRow(`SELECT adapter_id, provider_key, resource_id FROM resource_mapping WHERE adapter_id=? AND provider_key=?`, "adapter-a", "session-one").Scan(&adapterID, &providerKey, &resourceID)
	if err == nil {
		t.Fatal("an older provider_key query succeeded against a newer database")
	}
	if !strings.Contains(err.Error(), "no such column: provider_key") {
		t.Fatalf("older query error = %q, want it to contain %q", err.Error(), "no such column: provider_key")
	}
}

// tableColumnsOf returns the column names of one table in a schema script.
func tableColumnsOf(t *testing.T, script, table string) []string {
	t.Helper()
	start := strings.Index(script, "CREATE TABLE IF NOT EXISTS "+table+" (")
	if start < 0 {
		t.Fatalf("schema script does not create %s", table)
	}
	body := script[start:]
	end := strings.Index(body, ");")
	if end < 0 {
		t.Fatalf("schema script does not close %s", table)
	}
	body = body[:end]
	var columns []string
	for _, line := range strings.Split(body, "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "CREATE TABLE") {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 2 {
			continue
		}
		switch fields[0] {
		case "PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT":
			continue
		}
		columns = append(columns, fields[0])
	}
	return columns
}

// TestSharedTablesAreIdenticalAcrossVersions pins the premise the downgrade
// hazard rests on: command_journal and source_cache kept the same columns, so an
// older binary can still write them into a newer database. If either table ever
// diverges, the downgrade story changes and this test must be revisited.
func TestSharedTablesAreIdenticalAcrossVersions(t *testing.T) {
	current, err := os.ReadFile(filepath.Join("internal", "migrations", "001_initial.sql"))
	if err != nil {
		t.Fatalf("read the current initial migration: %v", err)
	}
	for _, table := range []string{"command_journal", "source_cache"} {
		currentColumns := tableColumnsOf(t, string(current), table)
		legacyColumns := tableColumnsOf(t, legacyInitialSQL, table)
		if len(currentColumns) == 0 || len(legacyColumns) == 0 {
			t.Fatalf("%s column list is empty: current %#v legacy %#v", table, currentColumns, legacyColumns)
		}
		if strings.Join(currentColumns, ",") != strings.Join(legacyColumns, ",") {
			t.Fatalf("%s columns diverged: current %#v legacy %#v", table, currentColumns, legacyColumns)
		}
	}
}

// TestOlderBinaryStillWritesTheSharedTables pins the dangerous half: the older
// binary keeps writing command_journal and source_cache rows into a database
// whose resource_mapping it cannot read.
func TestOlderBinaryStillWritesTheSharedTables(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "newer.db")

	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open newer database: %v", err)
	}
	if err := store.Close(); err != nil {
		t.Fatalf("close newer database: %v", err)
	}

	db := openRawSQLite(t, path)
	if _, err := db.Exec(legacyInitialSQL); err != nil {
		t.Fatalf("older migration step failed: %v", err)
	}
	// The older migration step is a set of CREATE TABLE IF NOT EXISTS statements,
	// so it is a no-op against the tables the newer binary already created. Assert
	// the resulting shape explicitly, otherwise a fixture that never applied would
	// look identical to one that did.
	journalColumns := tableColumnsOf(t, legacyInitialSQL, "command_journal")
	if len(journalColumns) == 0 {
		t.Fatal("the legacy command_journal fixture declares no columns")
	}
	liveColumns := mappingColumnsOf(t, db)
	if !liveColumns["provider_resource_key"] {
		t.Fatalf("the newer resource_mapping shape was lost: %#v", liveColumns)
	}
	if _, err := db.Exec(`INSERT INTO command_journal(command_id, request_hash, intent_json, phase, created_at_ms, updated_at_ms) VALUES('cmd-old','hash','{}','accepted',1,1)`); err != nil {
		t.Fatalf("older binary could not write command_journal: %v", err)
	}
	if _, err := db.Exec(`INSERT INTO source_cache(adapter_id, provider_type, display_name, version, health, sessions_json, report_complete, collection_status, last_attempt_at_ms, data_known, stale, update_at_ms) VALUES('adapter-a','topsailai','display','1.0','healthy','[]',1,'ok',1,1,0,1)`); err != nil {
		t.Fatalf("older binary could not write source_cache: %v", err)
	}

	var journalCount, cacheCount int
	if err := db.QueryRow(`SELECT COUNT(*) FROM command_journal`).Scan(&journalCount); err != nil {
		t.Fatalf("count command_journal: %v", err)
	}
	if err := db.QueryRow(`SELECT COUNT(*) FROM source_cache`).Scan(&cacheCount); err != nil {
		t.Fatalf("count source_cache: %v", err)
	}
	if journalCount != 1 || cacheCount != 1 {
		t.Fatalf("older binary writes = journal %d cache %d, want 1 and 1", journalCount, cacheCount)
	}
}

// TestDowngradeBoundaryIsDocumented keeps the document and the behaviour
// together: the document must state that downgrade is not detected at startup
// and that the shared tables keep accepting older writes.
func TestDowngradeBoundaryIsDocumented(t *testing.T) {
	path := filepath.Join("..", "..", "..", "docs", "agent-cluster-endpoint-database.md")
	content, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read the downgrade boundary document: %v", err)
	}
	text := string(content)

	for _, required := range []string{
		"Downgrade is not detected at startup",
		"no such column: provider_key",
		"command_journal` and `source_cache` keep the same columns",
	} {
		if !strings.Contains(text, required) {
			t.Fatalf("the downgrade boundary document no longer states %q", required)
		}
	}
	if strings.Contains(text, "the process exits without writing anything") {
		t.Fatal("the downgrade boundary document still claims the older binary exits at startup")
	}
}
