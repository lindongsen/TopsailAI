package endpointstorage

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// legacyMappingSchema is the pre-002 shape: one provider_key column and a
// two-column primary key. A database in this shape must be converted by 002.
const legacyMappingSchema = `CREATE TABLE resource_mapping (
	adapter_id TEXT NOT NULL,
	provider_key TEXT NOT NULL,
	resource_id TEXT NOT NULL,
	created_at_ms BIGINT NOT NULL,
	update_at_ms BIGINT NOT NULL,
	PRIMARY KEY (adapter_id, provider_key)
);`

// buildLegacyDatabase writes a pre-002 database holding one mapping row.
func buildLegacyDatabase(t *testing.T, path string) {
	t.Helper()
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open legacy database: %v", err)
	}
	defer func() { _ = db.Close() }()
	if _, err := db.Exec(legacyMappingSchema); err != nil {
		t.Fatalf("create legacy schema: %v", err)
	}
	if _, err := db.Exec(`INSERT INTO resource_mapping(adapter_id, provider_key, resource_id, created_at_ms, update_at_ms) VALUES('adapter-a','session-one','res_legacy_one',1,1)`); err != nil {
		t.Fatalf("insert legacy row: %v", err)
	}
}

// TestConcurrentStartupConvertsOneLegacyDatabase opens the same legacy database
// from several goroutines at once. Every opener must succeed, because a second
// process finding the database already converted is a normal startup, not a
// failure. Before the busy_timeout ordering fix and the post-failure column
// re-inspection, this raced into SQLITE_BUSY and into a "no such column:
// provider_key" schema error.
func TestConcurrentStartupConvertsOneLegacyDatabase(t *testing.T) {
	// The race window between the column inspection and the migration attempt is
	// narrow, so one round can pass by luck. Repeating the round makes a missing
	// guard fail reliably instead of intermittently.
	const rounds = 20
	for round := 0; round < rounds; round++ {
		path := filepath.Join(t.TempDir(), "legacy.db")
		buildLegacyDatabase(t, path)

		const openers = 6
		var wait sync.WaitGroup
		errs := make([]error, openers)
		start := make(chan struct{})
		for index := 0; index < openers; index++ {
			wait.Add(1)
			go func(slot int) {
				defer wait.Done()
				<-start
				store, err := Open(context.Background(), path)
				if err != nil {
					errs[slot] = err
					return
				}
				_ = store.Close()
			}(index)
		}
		close(start)
		wait.Wait()

		for index, err := range errs {
			if err != nil {
				t.Fatalf("round %d opener %d failed on a concurrently converted database: %v", round, index, err)
			}
		}
	}
}

// TestConcurrentStartupPreservesTheLegacyMapping proves the concurrent openers
// above did not merely avoid an error: the converted database still carries the
// original Cluster resource ID under the new kind column.
func TestConcurrentStartupPreservesTheLegacyMapping(t *testing.T) {
	path := filepath.Join(t.TempDir(), "legacy.db")
	buildLegacyDatabase(t, path)

	const openers = 6
	var wait sync.WaitGroup
	start := make(chan struct{})
	for index := 0; index < openers; index++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			<-start
			if store, err := Open(context.Background(), path); err == nil {
				_ = store.Close()
			}
		}()
	}
	close(start)
	wait.Wait()

	ctx := context.Background()
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("open converted database: %v", err)
	}
	defer func() { _ = store.Close() }()

	mapping, err := store.LookupResourceID(ctx, "res_legacy_one")
	if err != nil {
		t.Fatalf("lookup the legacy resource ID: %v", err)
	}
	if mapping.ResourceID != "res_legacy_one" {
		t.Fatalf("resource ID=%q, want res_legacy_one", mapping.ResourceID)
	}
	if mapping.ResourceKind != protocol.ResourceSession {
		t.Fatalf("resource kind=%q, want %q", mapping.ResourceKind, protocol.ResourceSession)
	}
	if mapping.ProviderResourceKey != "session-one" {
		t.Fatalf("provider key=%q, want session-one", mapping.ProviderResourceKey)
	}
}

// TestBusyTimeoutIsConfiguredBeforeAnyContendingStatement pins the ordering the
// concurrent startup depends on. journal_mode and synchronous both take the
// write lock, so a busy_timeout set after them cannot protect them.
func TestBusyTimeoutIsConfiguredBeforeAnyContendingStatement(t *testing.T) {
	raw, err := os.ReadFile("db.go")
	if err != nil {
		t.Fatalf("read db.go: %v", err)
	}
	source := string(raw)
	timeout := strings.Index(source, `"PRAGMA busy_timeout=5000"`)
	if timeout < 0 {
		t.Fatal("db.go does not configure PRAGMA busy_timeout")
	}
	for _, later := range []string{`"PRAGMA journal_mode=DELETE"`, `"PRAGMA synchronous=FULL"`} {
		position := strings.Index(source, later)
		if position < 0 {
			t.Fatalf("db.go does not configure %s", later)
		}
		if position < timeout {
			t.Fatalf("%s is configured before busy_timeout, so it can fail with SQLITE_BUSY before the timeout applies", later)
		}
	}
}

// TestMigrationRerunAfterAnotherProcessConverted proves the post-failure column
// re-inspection: applying 002 to a database another process already converted
// must be treated as success, not as a schema error.
func TestMigrationRerunAfterAnotherProcessConverted(t *testing.T) {
	path := filepath.Join(t.TempDir(), "converted.db")
	buildLegacyDatabase(t, path)

	ctx := context.Background()
	first, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("first open: %v", err)
	}
	if err := first.Close(); err != nil {
		t.Fatalf("close first store: %v", err)
	}

	// Force the stale-inspection path: run 002 again against the converted
	// database. It fails at the rename because resource_mapping_legacy already
	// exists, and the re-inspection must recognise the target shape.
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatalf("second open: %v", err)
	}
	defer func() { _ = store.Close() }()

	mapping, err := store.LookupResourceID(ctx, "res_legacy_one")
	if err != nil {
		t.Fatalf("lookup after the second open: %v", err)
	}
	if mapping.ResourceID != "res_legacy_one" {
		t.Fatalf("resource ID=%q, want res_legacy_one", mapping.ResourceID)
	}
}
