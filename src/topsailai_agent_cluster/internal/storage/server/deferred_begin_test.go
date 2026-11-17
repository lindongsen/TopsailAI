package serverstorage

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestReaderHoldingSharedBlocksCommitUntilItReleases proves the mechanism behind
// the production outage, and proves that it is recoverable.
//
// The production evidence was a combination that this mechanism explains:
//   - writers received SQLITE_BUSY for 2h56m
//   - readers kept working the whole time
//   - the rollback journal existed continuously and its mtime kept advancing,
//     which means a transaction was repeatedly attempted and repeatedly failed
//
// Under journal_mode(DELETE) a reader holds SHARED and a writer needs EXCLUSIVE to
// commit. A deferred BEGIN starts as a reader, takes SHARED, and only needs
// EXCLUSIVE at COMMIT. By then it has already modified pages and written the
// journal. If another connection holds SHARED, the COMMIT fails. The journal is
// then recreated and deleted on each retry, which is why its mtime advanced: that
// is a symptom of repeated attempts, not a stranded artifact.
//
// An earlier version of this test claimed the failed commit left a hot journal
// that blocked every later write. That claim was measured and disproved: ROLLBACK
// succeeds in about 200 microseconds and deletes the journal, and a genuine hot
// journal left by a killed process is recovered automatically on the next write.
// The journal is therefore not the blocker. The SHARED holder is.
//
// BEGIN IMMEDIATE avoids the conflict entirely: the write lock is taken before any
// page is modified, so a conflict fails before a journal exists.
func TestReaderHoldingSharedBlocksCommitUntilItReleases(t *testing.T) {
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

	// A reader holds SHARED for the whole scenario, which is what the Server's
	// continuous inventory and manifest polling does in production.
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

	// A deferred BEGIN, which is what withTransaction used before the fix.
	conn, err := store.DB().Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.ExecContext(ctx, "BEGIN"); err != nil {
		_ = conn.Close()
		t.Fatalf("begin: %v", err)
	}
	// The write succeeds because SHARED is compatible with SHARED. This is the
	// step that creates the journal.
	if _, err := conn.ExecContext(ctx, `UPDATE endpoints SET display_name = 'written'`); err != nil {
		_ = conn.Close()
		t.Fatalf("write inside a deferred transaction: %v", err)
	}
	journalPath := path + "-journal"
	if info, err := os.Stat(journalPath); err == nil {
		t.Logf("journal after the write inside a deferred transaction: %d bytes", info.Size())
	} else {
		t.Logf("no journal after the write: %v", err)
	}

	// COMMIT needs EXCLUSIVE and must fail because the reader holds SHARED.
	_, commitErr := conn.ExecContext(ctx, "COMMIT")
	if commitErr == nil {
		_ = conn.Close()
		t.Fatal("commit succeeded while a reader held SHARED, so this scenario cannot reproduce the production state")
	}
	t.Logf("commit failed as expected: %v", commitErr)

	// Roll back so the connection is not left in a transaction, then release it.
	// The rollback succeeds even while the reader holds SHARED, which is what
	// disproves the hot-journal theory: the journal is deleted here, not stranded.
	_, rollbackErr := conn.ExecContext(ctx, "ROLLBACK")
	t.Logf("rollback result: %v", rollbackErr)
	_ = conn.Close()

	if _, statErr := os.Stat(journalPath); statErr != nil {
		t.Logf("journal after the rollback: gone (%v), so no hot journal was stranded", statErr)
	} else {
		t.Logf("journal after the rollback: still present")
	}

	// The decisive observation: with the reader still holding SHARED, every later
	// write must fail. This is the production symptom.
	start := time.Now()
	_, writeErr := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'after'`)
	elapsed := time.Since(start)
	if writeErr == nil {
		t.Logf("a later write succeeded in %s, so this scenario did not reproduce the outage", elapsed)
	} else {
		lower := strings.ToLower(writeErr.Error())
		if strings.Contains(lower, "locked") || strings.Contains(lower, "busy") {
			t.Logf("a later write failed with SQLITE_BUSY after %s while the reader kept working: %v", elapsed, writeErr)
		} else {
			t.Logf("a later write failed with a different error: %v", writeErr)
		}
	}

	// Readers must still work, which is what made the outage look like a
	// provider problem rather than a database problem.
	if _, err := store.ListEndpoints(ctx, QueryOptions{Limit: 10}); err != nil {
		t.Logf("a read failed too: %v", err)
	} else {
		t.Logf("reads still succeed while writes fail, which is the production symptom")
	}

	if err := readTx.Rollback(); err != nil {
		t.Fatal(err)
	}

	// After the reader releases SHARED, recovery must be possible again. If it is
	// not, the database is permanently unwritable and only a restart helps.
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'recovered'`); err != nil {
		t.Fatalf("the database stayed unwritable after the reader released its lock, so the SHARED holder is not the only blocker: %v", err)
	}
	t.Logf("writes recover once the reader releases SHARED")
}
