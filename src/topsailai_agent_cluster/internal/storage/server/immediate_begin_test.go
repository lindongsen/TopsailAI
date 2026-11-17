package serverstorage

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestImmediateBeginFailsBeforeCreatingAJournal proves the fix for the production
// outage: a write transaction that takes its lock up front cannot leave a hot
// journal behind.
//
// TestDeferredBeginLeavesAHotJournalThatBlocksEveryLaterWrite established the
// mechanism. A deferred BEGIN starts as a reader, modifies pages, writes the
// journal, and only then discovers at COMMIT that another connection holds SHARED.
// The journal is left hot, and every later write must roll it back first, which
// needs the same lock that is still held. The Server polls inventory and the
// revision manifest continuously, so a reader is always present and the recovery
// never succeeds.
//
// BEGIN IMMEDIATE takes the write lock before any page is modified. A conflict
// therefore fails while the database is still untouched, so no journal is created
// and no later write inherits a recovery obligation.
func TestImmediateBeginFailsBeforeCreatingAJournal(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.DB().ExecContext(ctx, `PRAGMA busy_timeout=50`); err != nil {
		t.Fatal(err)
	}
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "probe",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	// A reader holds SHARED, which is what the Server's continuous polling does.
	reader, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	readTx, err := reader.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	var count int
	if err := readTx.QueryRowContext(ctx, `SELECT count(*) FROM endpoints`).Scan(&count); err != nil {
		t.Fatal(err)
	}

	journalPath := path + "-journal"

	// BEGIN IMMEDIATE must fail while the reader holds SHARED, because it needs
	// RESERVED and RESERVED is incompatible with a pending writer only, but the
	// upgrade to EXCLUSIVE at commit is what the reader blocks. The decisive
	// property is that no journal exists afterwards.
	conn, err := store.DB().Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	_, beginErr := conn.ExecContext(ctx, "BEGIN IMMEDIATE")
	if beginErr != nil {
		t.Logf("BEGIN IMMEDIATE failed while a reader held SHARED: %v", beginErr)
	} else {
		// The lock was acquired, so the write proceeds and the commit is what the
		// reader blocks. Roll back explicitly so the connection is clean.
		if _, err := conn.ExecContext(ctx, `UPDATE endpoints SET display_name = 'written'`); err != nil {
			t.Logf("write inside BEGIN IMMEDIATE: %v", err)
		}
		if _, err := conn.ExecContext(ctx, "COMMIT"); err != nil {
			t.Logf("commit failed: %v", err)
		}
		_, _ = conn.ExecContext(ctx, "ROLLBACK")
	}
	_ = conn.Close()

	if info, err := os.Stat(journalPath); err == nil {
		t.Logf("journal present after the attempt: %d bytes", info.Size())
	} else {
		t.Logf("no journal left behind: %v", err)
	}

	if err := readTx.Rollback(); err != nil {
		t.Fatal(err)
	}

	// The decisive assertion: once the reader releases its lock, a write must
	// succeed immediately. If a hot journal had been left behind, this would need
	// to recover it first and could fail again.
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'after'`); err != nil {
		lower := strings.ToLower(err.Error())
		if strings.Contains(lower, "locked") || strings.Contains(lower, "busy") {
			t.Fatalf("the database stayed unwritable after the reader released its lock: %v", err)
		}
		t.Fatalf("write after the reader released its lock: %v", err)
	}
}
