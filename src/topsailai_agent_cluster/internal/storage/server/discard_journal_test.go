package serverstorage

import (
	"context"
	"database/sql/driver"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestDiscardedWriteTransactionReleasesTheJournal reproduces the production
// descriptor pattern exactly.
//
// The production process held three descriptors: two on server.sqlite and one on
// server.sqlite-journal, while the pool was configured with SetMaxOpenConns(1).
// A measurement in TestStuckTransactionBlocksOrFailsDistinguishesTheRootCause
// established that one connection holding a write transaction holds exactly two
// descriptors, one on each file. Three descriptors therefore mean a second
// connection existed.
//
// This test checks whether discarding a connection that is inside a write
// transaction leaves its journal descriptor and its lock behind while the pool
// opens a replacement. If it does, the production pattern is explained: the
// abandoned connection keeps RESERVED, the replacement receives SQLITE_BUSY, and
// readers keep working because RESERVED does not block SHARED.
//
// The earlier handle-leak test missed this because its write matched no rows, so
// SQLite created no journal and the discarded connection held nothing.
func TestDiscardedWriteTransactionReleasesTheJournal(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.DB().ExecContext(ctx, `PRAGMA busy_timeout=100`); err != nil {
		t.Fatal(err)
	}

	// A real row is required: a write that matches no rows creates no journal, and
	// then the discarded connection holds no lock to leak.
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "probe",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	baseline := countOpenHandles(t, path)
	t.Logf("descriptors before the discarded transaction: %d", baseline)

	conn, err := store.DB().Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		_ = conn.Close()
		t.Fatalf("begin immediate: %v", err)
	}
	// This write modifies a row, so SQLite creates the rollback journal and the
	// connection holds RESERVED.
	if _, err := conn.ExecContext(ctx, `UPDATE endpoints SET display_name = 'held'`); err != nil {
		_ = conn.Close()
		t.Fatalf("write inside transaction: %v", err)
	}
	inTransaction := countOpenHandles(t, path)
	t.Logf("descriptors while the transaction is open: %d", inTransaction)

	// Discard the connection the way rollbackTransaction does when ROLLBACK fails.
	if err := conn.Raw(func(any) error { return driver.ErrBadConn }); !errors.Is(err, driver.ErrBadConn) {
		_ = conn.Close()
		t.Fatalf("discard connection error=%v, want driver.ErrBadConn", err)
	}
	_ = conn.Close()

	afterDiscard := countOpenHandles(t, path)
	t.Logf("descriptors after discarding the transaction holder: %d", afterDiscard)
	logDescriptors(t, path)

	// The decisive assertion: the write lock must be free. If the discarded
	// connection kept its journal and its RESERVED lock, this write fails with
	// SQLITE_BUSY while reads keep succeeding, which is the production symptom.
	start := time.Now()
	_, writeErr := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'after'`)
	elapsed := time.Since(start)
	if writeErr != nil {
		lower := strings.ToLower(writeErr.Error())
		if strings.Contains(lower, "locked") || strings.Contains(lower, "busy") {
			t.Fatalf("a discarded write transaction left the SQLite write lock held after %s, so the pool opens a replacement that can never write while readers keep succeeding; this is the production outage: %v", elapsed, writeErr)
		}
		t.Fatalf("write after discarding the transaction holder: %v", writeErr)
	}
	t.Logf("write after discard succeeded in %s", elapsed)
}

// logDescriptors prints every descriptor the process holds on the database and
// its journal, so a failure shows which file was left open.
func logDescriptors(t *testing.T, path string) {
	t.Helper()
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		return
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return
	}
	for _, entry := range entries {
		target, err := os.Readlink(filepath.Join("/proc/self/fd", entry.Name()))
		if err != nil {
			continue
		}
		if strings.HasPrefix(target, resolved) {
			t.Logf("  fd %s -> %s", entry.Name(), target)
		}
	}
}
