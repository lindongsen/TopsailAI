package serverstorage

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestPanicInsideTransactionDoesNotPoisonThePooledConnection proves that a panic
// in a transaction callback cannot leave the connection inside an open
// transaction.
//
// withTransaction defers conn.Close(), and Conn.Close returns the connection to
// the pool. If the callback panics, the deferred Close runs while the transaction
// is still open, so the pool receives a connection that is inside a transaction.
// Every later statement on that connection then joins the abandoned transaction
// instead of starting its own. The statements report success, nothing commits, and
// a second connection keeps reading the old value. That is a silent data-loss
// shape: the caller is told the write succeeded.
//
// The test asserts on what a second connection observes, because that is the only
// evidence that separates "committed" from "reported success but never committed".
// Asserting on the returned error cannot distinguish them: the poisoned write
// returns nil.
func TestPanicInsideTransactionDoesNotPoisonThePooledConnection(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "original",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	func() {
		defer func() { _ = recover() }()
		_ = store.withTransaction(ctx, "panicking writer", func(txCtx context.Context, conn *sql.Conn) error {
			if _, err := conn.ExecContext(ctx, `UPDATE endpoints SET display_name = 'panicked'`); err != nil {
				return err
			}
			panic("callback panicked")
		})
	}()

	// A later write must commit on its own. If the pooled connection is still
	// inside the abandoned transaction, this statement joins it and never commits.
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "after",
		ConnectionState: "online", ObservedAtMS: 2000, CapabilityRevision: "v1",
	}, 2000); err != nil {
		t.Fatalf("the write after the panic failed: %v", err)
	}

	// A second connection is the only observer that can tell a commit from a
	// reported success, because it cannot see uncommitted state.
	other, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	var seen string
	if err := other.QueryRowContext(ctx, `SELECT display_name FROM endpoints WHERE endpoint_id = 'probe'`).Scan(&seen); err != nil {
		t.Fatal(err)
	}
	if seen != "after" {
		t.Fatalf("a second connection reads %q instead of %q, so the write reported success without committing; the pooled connection was returned to the pool while still inside the transaction the panic abandoned", seen, "after")
	}
}
