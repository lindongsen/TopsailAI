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

// TestCancelledTransactionReleasesTheWriteLock verifies that a write transaction
// whose context is cancelled after it has already written still releases the
// SQLite write lock.
//
// This is the shape the production outage had. A hot journal existed for almost
// three hours, which means a write transaction had modified pages and never
// finished. Writers received SQLITE_BUSY while readers kept working, which is
// exactly what a transaction holding RESERVED looks like under
// journal_mode=DELETE: other writers are blocked, readers are not.
//
// The Server passes request-scoped contexts with deadlines into these operations,
// so a cancellation arriving after the write but before the commit is a real
// path, not a contrived one.
func TestCancelledTransactionReleasesTheWriteLock(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.DB().ExecContext(ctx, `PRAGMA busy_timeout=200`); err != nil {
		t.Fatal(err)
	}

	// Seed one row so the write below actually modifies a page and therefore
	// creates a journal entry.
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "probe", InstanceID: "probe-1", DisplayName: "probe", ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1"}, 1000); err != nil {
		t.Fatal(err)
	}

	opCtx, cancel := context.WithCancel(ctx)
	err = store.withTransaction(opCtx, "probe cancelled write", func(txCtx context.Context, conn *sql.Conn) error {
		if _, err := conn.ExecContext(opCtx, `UPDATE endpoints SET display_name = 'changed'`); err != nil {
			return err
		}
		// Cancel after the write has landed but before the commit, which is the
		// production shape: the work is done, the commit never completes.
		cancel()
		return nil
	})
	if err == nil {
		t.Fatal("the transaction reported success even though its context was cancelled before the commit")
	}

	// The write lock must be free. A failure here means the cancelled transaction
	// left RESERVED held, so every later write fails with SQLITE_BUSY until the
	// process restarts, while readers keep working and hide the problem.
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'after'`); err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "locked") || strings.Contains(strings.ToLower(err.Error()), "busy") {
			t.Fatalf("a cancelled transaction left the write lock held, so the Server cannot write until it restarts while reads keep succeeding: %v", err)
		}
		t.Fatalf("write after cancelled transaction: %v", err)
	}
}

// TestCancelledDirectWriteReleasesTheWriteLock verifies the same property for a
// write that does not use withTransaction.
//
// Most Server writes are direct ExecContext calls, so they run as implicit
// transactions. If a cancellation can leave one of those holding the lock, the
// withTransaction protection never applies to the majority of the write surface.
func TestCancelledDirectWriteReleasesTheWriteLock(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.DB().ExecContext(ctx, `PRAGMA busy_timeout=200`); err != nil {
		t.Fatal(err)
	}
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "probe", InstanceID: "probe-1", DisplayName: "probe", ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1"}, 1000); err != nil {
		t.Fatal(err)
	}

	opCtx, cancel := context.WithCancel(ctx)
	cancel()
	if _, err := store.DB().ExecContext(opCtx, `UPDATE endpoints SET display_name = 'cancelled'`); err == nil {
		t.Fatal("a write with an already-cancelled context reported success")
	}

	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'after'`); err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "locked") || strings.Contains(strings.ToLower(err.Error()), "busy") {
			t.Fatalf("a cancelled direct write left the write lock held: %v", err)
		}
		t.Fatalf("write after cancelled direct write: %v", err)
	}
}

// TestOpenStoreHoldsOneDescriptorPerConnection records how many operating-system
// handles one pooled connection holds on the database file.
//
// The production process held three descriptors on server.sqlite while the pool
// was configured with SetMaxOpenConns(1). This test establishes the baseline so a
// later count can be interpreted: if one connection legitimately holds more than
// one descriptor, three descriptors do not prove a leak, and the leak hypothesis
// must be rejected rather than assumed.
func TestOpenStoreHoldsOneDescriptorPerConnection(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	baseline := countOpenHandles(t, path)
	t.Logf("descriptors on the database file with one pooled connection: %d", baseline)

	// Force a write so SQLite opens the rollback journal, then count again.
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{EndpointID: "probe", InstanceID: "probe-1", DisplayName: "probe", ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1"}, 1000); err != nil {
		t.Fatal(err)
	}
	afterWrite := countOpenHandles(t, path)
	t.Logf("descriptors after a committed write: %d", afterWrite)

	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		t.Skipf("cannot inspect file descriptors: %v", err)
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		target, err := os.Readlink(filepath.Join("/proc/self/fd", entry.Name()))
		if err != nil {
			continue
		}
		if strings.HasPrefix(target, resolved) {
			t.Logf("fd %s -> %s", entry.Name(), target)
		}
	}
}
