package serverstorage

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestCommitBusyDoesNotPoisonConnection verifies a failed SQLite commit cannot
// leave the Store's only pooled connection inside an active transaction.
func TestCommitBusyDoesNotPoisonConnection(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	putEndpointInventory(t, store, "expired", "offline", 100)
	setOfflineSince(t, store, "expired", 100)
	if _, err := store.DB().ExecContext(ctx, "PRAGMA busy_timeout=20"); err != nil {
		t.Fatal(err)
	}

	reader, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	readTx, err := reader.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	var rows int
	if err := readTx.QueryRowContext(ctx, `SELECT count(*) FROM endpoint_session_state`).Scan(&rows); err != nil {
		t.Fatal(err)
	}
	if rows != 1 {
		t.Fatalf("inventory rows=%d, want 1", rows)
	}

	if _, err := store.ExpireOfflineEndpoints(ctx, 200); err == nil {
		t.Fatal("expiry commit succeeded while an external read transaction held the database")
	} else if !strings.Contains(strings.ToLower(err.Error()), "locked") && !strings.Contains(strings.ToLower(err.Error()), "busy") {
		t.Fatalf("expiry error=%q, want SQLite busy/locked evidence", err)
	}
	if err := readTx.Rollback(); err != nil {
		t.Fatal(err)
	}

	report := protocol.InventoryReport{
		SchemaVersion:    "v1",
		SourceGeneration: "endpoint-local",
		SnapshotRevision: 2,
		ObservedAtMS:     300,
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
	}
	if err := store.ReplaceInventory(ctx, "expired", report, 300); err != nil {
		if strings.Contains(err.Error(), "cannot start a transaction within a transaction") {
			t.Fatalf("failed commit poisoned the pooled connection: %v", err)
		}
		t.Fatalf("inventory write after failed commit: %v", err)
	}
	committed, err := store.GetInventory(ctx, "expired")
	if err != nil {
		t.Fatal(err)
	}
	if committed.SnapshotRevision != 2 {
		t.Fatalf("committed revision=%d, want 2", committed.SnapshotRevision)
	}
}

// TestReplacementConnectionRetainsPragmas verifies discarding a bad connection
// cannot silently remove the Server's durability and lock-wait configuration.
func TestReplacementConnectionRetainsPragmas(t *testing.T) {
	store, err := Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	conn, err := store.DB().Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if err := conn.Raw(func(any) error { return driver.ErrBadConn }); !errors.Is(err, driver.ErrBadConn) {
		_ = conn.Close()
		t.Fatalf("discard connection error=%v, want driver.ErrBadConn", err)
	}
	_ = conn.Close()

	var busyTimeout int
	var synchronous int
	var journalMode string
	if err := store.DB().QueryRow(`PRAGMA busy_timeout`).Scan(&busyTimeout); err != nil {
		t.Fatal(err)
	}
	if err := store.DB().QueryRow(`PRAGMA synchronous`).Scan(&synchronous); err != nil {
		t.Fatal(err)
	}
	if err := store.DB().QueryRow(`PRAGMA journal_mode`).Scan(&journalMode); err != nil {
		t.Fatal(err)
	}
	if busyTimeout != 5000 || synchronous != 2 || strings.ToLower(journalMode) != "delete" {
		t.Fatalf("replacement pragmas busy_timeout=%d synchronous=%d journal_mode=%q", busyTimeout, synchronous, journalMode)
	}
}
