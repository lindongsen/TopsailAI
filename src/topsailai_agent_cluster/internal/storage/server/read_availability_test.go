package serverstorage

import (
	"context"
	"path/filepath"
	"testing"
	"time"
)

// TestOneStuckConnectionBlocksReadsAtPoolOne pins the cost of keeping the pool at
// one connection, so that cost is a recorded decision rather than a surprise.
//
// The pool is one because under journal_mode(DELETE) a second live connection lets
// a reader block a writer's COMMIT, which is the production outage's own symptom.
// The price of that choice is this test: a connection left inside a transaction
// starves every read and every write, because there is no other connection to
// serve them.
//
// The consequence is a rule for the transaction path, not a property of the pool:
// no code may leave a connection inside a transaction. That rule is enforced by
// three separate mechanisms, each with its own test:
//   - the deferred rollback on the panic path, so a panicking callback cannot
//     return a connection to the pool mid-transaction
//     (TestPanicInsideTransactionDoesNotPoisonThePooledConnection)
//   - BEGIN IMMEDIATE, so a write conflict is reported before any page is modified
//     (TestWithTransactionSerializesWritersBeforeTheyModifyPages)
//   - the transaction budget, so a callback that blocks cannot hold the connection
//     forever (TestTransactionBudgetReleasesTheWriteLock)
//
// An earlier version of this test asserted the opposite: that reads stay available
// while one pooled connection is stuck. That assertion only holds at a pool larger
// than one, and the pool was deliberately reverted to one, so the assertion was
// measuring a configuration the project does not use.
func TestOneStuckConnectionBlocksReadsAtPoolOne(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "server.db")
	store, err := Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer store.db.Close()

	ctx := context.Background()
	if _, err := store.db.ExecContext(ctx, `INSERT INTO endpoints (endpoint_id, instance_id, display_name, hostname, connection_state, observed_at_ms, capability_revision, create_at_ms, update_at_ms) VALUES ('e1','i1','e1','h1','online',1,'r1',1,1)`); err != nil {
		t.Fatalf("seed: %v", err)
	}

	// Take the only pooled connection and leave it inside a transaction.
	stuck, err := store.db.Conn(ctx)
	if err != nil {
		t.Fatalf("take pooled connection: %v", err)
	}
	defer stuck.Close()
	if _, err := stuck.ExecContext(ctx, "BEGIN"); err != nil {
		t.Fatalf("begin transaction: %v", err)
	}
	var held string
	if err := stuck.QueryRowContext(ctx, `SELECT display_name FROM endpoints WHERE endpoint_id='e1'`).Scan(&held); err != nil {
		t.Fatalf("read inside the stuck transaction: %v", err)
	}

	// A read must now block, because the pool has no second connection. The
	// bounded context keeps the test fast and makes the failure mode explicit.
	readCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	start := time.Now()
	var got string
	readErr := store.db.QueryRowContext(readCtx, `SELECT display_name FROM endpoints WHERE endpoint_id='e1'`).Scan(&got)
	elapsed := time.Since(start)
	if readErr == nil {
		t.Fatalf("a read completed in %v while the only pooled connection was inside a transaction, so the pool is not one connection and this test no longer describes the configured behaviour", elapsed)
	}
	t.Logf("a read was blocked for %v while the only pooled connection was inside a transaction, which is the accepted cost of pool size one", elapsed)

	// Releasing the connection must restore service. This is the property that
	// makes the rule enforceable: the outage is recoverable as soon as the holder
	// lets go, which is why a restart fixed the production service.
	if _, err := stuck.ExecContext(ctx, "ROLLBACK"); err != nil {
		t.Fatalf("rollback: %v", err)
	}
	_ = stuck.Close()

	recoverCtx, recoverCancel := context.WithTimeout(ctx, 5*time.Second)
	defer recoverCancel()
	start = time.Now()
	if err := store.db.QueryRowContext(recoverCtx, `SELECT display_name FROM endpoints WHERE endpoint_id='e1'`).Scan(&got); err != nil {
		t.Fatalf("reads did not recover after the connection was released: %v", err)
	}
	t.Logf("reads recovered in %v once the connection was released", time.Since(start))
}
