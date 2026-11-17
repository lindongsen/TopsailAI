package serverstorage

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"
	"time"
)

// TestTransactionBudgetReleasesTheWriteLock pins the property that made the
// production outage last almost three hours.
//
// SQLite has exactly one writer. A transaction that never finishes therefore
// stops every other write for as long as it exists, and busy_timeout does not
// help: it bounds how long a waiter waits, not how long the holder holds. The
// production Server passed a context with no deadline to every write, so nothing
// bounded the holder at all.
//
// The callback blocks on the context it is given, which is the budgeted one. That
// is the only way this test can distinguish a real budget from a decorative one:
// a budget that is applied to the statements withTransaction issues itself, but
// not to the callback, leaves the callback free to hold the lock forever. The
// first version of this test blocked on the caller's context and ran for five
// budgets, which proved the budget did not reach the callback at all.
func TestTransactionBudgetReleasesTheWriteLock(t *testing.T) {
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

	// The callback blocks until the budget expires. It must not be allowed to hold
	// the write lock for its whole duration.
	start := time.Now()
	err = store.withTransaction(ctx, "budget probe", func(txCtx context.Context, conn *sql.Conn) error {
		<-txCtx.Done()
		return txCtx.Err()
	})
	elapsed := time.Since(start)
	if err == nil {
		t.Fatalf("a transaction whose callback outlived the budget returned no error, so the budget did not bound it")
	}
	if elapsed > 2*transactionBudget {
		t.Fatalf("a transaction held the write lock for %v, so the budget did not bound the holder", elapsed)
	}
	t.Logf("transaction failed after %v: %v", elapsed, err)

	// The lock must be released, so an unrelated write succeeds promptly.
	writeCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	start = time.Now()
	if _, err := store.db.ExecContext(writeCtx, `UPDATE endpoints SET display_name='after' WHERE endpoint_id='e1'`); err != nil {
		t.Fatalf("a write failed after the over-budget transaction returned, so the lock was not released: %v", err)
	}
	t.Logf("write succeeded in %v after the over-budget transaction returned", time.Since(start))
}
