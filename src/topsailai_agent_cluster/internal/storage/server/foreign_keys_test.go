package serverstorage

import (
	"context"
	"database/sql/driver"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// discardPooledConnection poisons and discards the Store's pooled connection the
// same way rollbackTransaction does after a failed rollback. The replacement
// connection taken from the pool afterwards is the one these tests inspect.
func discardPooledConnection(t *testing.T, store *Store) {
	t.Helper()
	conn, err := store.DB().Conn(context.Background())
	if err != nil {
		t.Fatalf("acquire connection: %v", err)
	}
	if err := conn.Raw(func(any) error { return driver.ErrBadConn }); err != nil {
		t.Logf("discard returned %v", err)
	}
	// The driver closes the connection while handling ErrBadConn, so Close
	// reports "already closed". Production code ignores this with a deferred
	// Close, and the discard has already happened either way.
	_ = conn.Close()
}

// TestForeignKeysSurviveConnectionDiscard verifies foreign key enforcement is a
// property of the DSN rather than of the single connection that ran the
// migration.
//
// The migration sets PRAGMA foreign_keys = ON, so the connection that applied it
// enforces foreign keys. That connection is not permanent: rollbackTransaction
// discards a poisoned connection with driver.ErrBadConn, and the replacement
// connection defaults to foreign_keys=0 unless the DSN carries the pragma. This
// test therefore asserts the value on a connection that did not run the
// migration, which is the only connection that can reveal the defect.
func TestForeignKeysSurviveConnectionDiscard(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	var before int
	if err := store.DB().QueryRowContext(ctx, "PRAGMA foreign_keys").Scan(&before); err != nil {
		t.Fatalf("read foreign_keys before discard: %v", err)
	}
	if before != 1 {
		t.Fatalf("foreign_keys before discard = %d, want 1", before)
	}

	discardPooledConnection(t, store)

	var after int
	if err := store.DB().QueryRowContext(ctx, "PRAGMA foreign_keys").Scan(&after); err != nil {
		t.Fatalf("read foreign_keys after discard: %v", err)
	}
	if after != 1 {
		t.Fatalf("foreign_keys after discard = %d, want 1; the DSN does not carry foreign_keys(ON), so the replacement connection stopped enforcing referential integrity", after)
	}
}

// TestForeignKeysBlockCommandForUnregisteredEndpointAfterDiscard verifies the
// referential integrity guarantee protects real data, not only a pragma value.
//
// A command row references its Endpoint. Admitting a command for an Endpoint
// that was never registered must fail, because the Server would otherwise store
// a command that can never be dispatched and can never be joined to a machine.
// The check is meaningful only after the migrated connection is discarded,
// because that is the state in which enforcement used to disappear.
func TestForeignKeysBlockCommandForUnregisteredEndpointAfterDiscard(t *testing.T) {
	ctx := context.Background()
	store, err := Open(ctx, filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	discardPooledConnection(t, store)

	intent := protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            "cmd-unregistered",
		EndpointID:           "never-registered",
		Operation:            "message.send",
		OperationVersion:     "v1",
		CapabilityRevision:   "c1",
		PayloadSchemaVersion: "v1",
		Payload:              []byte(`{"text":"x"}`),
		ExecuteBeforeAtMS:    9999999999999,
	}
	if err := store.AdmitCommand(ctx, intent, "hash-unregistered", 1000); err == nil {
		t.Fatal("command for an unregistered endpoint was admitted; foreign key enforcement is not active on the replacement connection")
	}

	var orphans int
	if err := store.DB().QueryRowContext(ctx, `SELECT count(*) FROM commands WHERE endpoint_id NOT IN (SELECT endpoint_id FROM endpoints)`).Scan(&orphans); err != nil {
		t.Fatalf("count orphan commands: %v", err)
	}
	if orphans != 0 {
		t.Fatalf("orphan command rows = %d, want 0", orphans)
	}
}
