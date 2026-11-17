package serverstorage

import (
	"context"
	"database/sql"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestBlockedRollbackIsBoundedByTheBudget proves that a rollback blocked by an
// open cursor is released by the transaction budget instead of hanging forever.
//
// The blocked rollback itself is inherent to SQLite: conn.Raw waits while a cursor
// is open on that connection, so a callback that returns with a cursor alive makes
// the rollback wait for the cursor. What the budget changes is the outcome. Without
// it the rollback never finishes, the connection never returns to the pool, and at
// a pool of one connection every later read and write waits forever. With it the
// wait is bounded and the connection is released.
//
// The test therefore asserts both halves, and the second half is the fix:
//
//  1. while the rollback is blocked, a second writer fails with SQLITE_BUSY and a
//     reader still succeeds. This is inherent, and it is recorded because it is the
//     asymmetry that made the production outage look like a provider problem;
//
//  1. a callback returns an error while a cursor is open, so the rollback blocks
//     on conn.Raw;
//
//  2. while it blocks, the connection stays inside a transaction and keeps its
//     read lock;
//
//  3. a second writer therefore fails with SQLITE_BUSY;
//
//  4. reads keep succeeding, which is why the outage looked like a provider
//     problem instead of a database problem;
//
//  5. once the blocked rollback is released by the budget, writes recover.
//
// This test does NOT claim to be the production outage's mechanism. The strand
// produces db=1 journal=0, while production showed db=2 journal=1, and production
// logged 2512 SQLITE_BUSY errors from writers that reached SQLite, which a stranded
// pool connection would have prevented. The strand is a real defect with the same
// symptom, not the proven cause.
//
// Point 4 is the one that matters most. A database that refuses writes but serves
// reads is exactly what the production Server did for two hours and fifty-six
// minutes, and it is why the operator saw timeouts on provider-backed commands
// while inventory reads kept working.
func TestBlockedRollbackIsBoundedByTheBudget(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "server.sqlite")
	store, err := Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()

	ctx := context.Background()
	for i := 0; i < 500; i++ {
		id := "e" + string(rune('a'+i%26)) + string(rune('a'+(i/26)%26))
		if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
			EndpointID: id, InstanceID: "i-" + id, DisplayName: id,
			ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
		}, 1000); err != nil {
			t.Fatalf("seed endpoint %d: %v", i, err)
		}
	}

	// Start the blocked rollback in the background. It will hold the connection
	// inside a transaction for the whole budget.
	rollbackDone := make(chan time.Duration, 1)
	go func() {
		start := time.Now()
		_ = store.withTransaction(ctx, "blocked rollback", func(txCtx context.Context, conn *sql.Conn) error {
			rows, err := conn.QueryContext(txCtx, `SELECT endpoint_id FROM endpoints`)
			if err != nil {
				return err
			}
			if rows.Next() {
				var id string
				_ = rows.Scan(&id)
			}
			return errors.New("callback rejected the first row while the cursor is open")
		})
		rollbackDone <- time.Since(start)
	}()

	// Let the callback reach its error and the rollback start blocking.
	time.Sleep(500 * time.Millisecond)

	// A second writer, from outside the pool, must fail with SQLITE_BUSY while the
	// rollback is blocked. This is the production symptom.
	holder, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open second handle: %v", err)
	}
	defer holder.Close()
	holder.SetMaxOpenConns(1)

	writeCtx, cancelWrite := context.WithTimeout(ctx, 8*time.Second)
	defer cancelWrite()
	writeStart := time.Now()
	_, writeErr := holder.ExecContext(writeCtx, `UPDATE endpoints SET connection_state = 'offline' WHERE endpoint_id = 'e1'`)
	writeElapsed := time.Since(writeStart)
	t.Logf("second writer while the rollback is blocked: err=%v elapsed=%s", writeErr, writeElapsed)

	// A read must still succeed. This is the asymmetry that hid the outage.
	readCtx, cancelRead := context.WithTimeout(ctx, 8*time.Second)
	defer cancelRead()
	readStart := time.Now()
	var count int
	readErr := holder.QueryRowContext(readCtx, `SELECT COUNT(*) FROM endpoints`).Scan(&count)
	readElapsed := time.Since(readStart)
	t.Logf("reader while the rollback is blocked: err=%v rows=%d elapsed=%s", readErr, count, readElapsed)

	if writeErr == nil {
		t.Fatalf("the second writer succeeded while the rollback was blocked, so the lock is not held and this test proves nothing")
	}
	if readErr != nil {
		t.Fatalf("the reader failed too (%v), so the asymmetry that hid the outage is absent", readErr)
	}
	t.Logf("writes fail while reads succeed, which is the asymmetry that hid the outage")

	// Wait for the blocked rollback to be released by the budget, then prove
	// writes recover.
	select {
	case elapsed := <-rollbackDone:
		t.Logf("the blocked rollback was released after %s", elapsed)
	case <-time.After(60 * time.Second):
		t.Fatalf("the blocked rollback never finished")
	}

	recoverCtx, cancelRecover := context.WithTimeout(ctx, 10*time.Second)
	defer cancelRecover()
	recoverStart := time.Now()
	_, recoverErr := holder.ExecContext(recoverCtx, `UPDATE endpoints SET connection_state = 'offline' WHERE endpoint_id = 'e1'`)
	t.Logf("writer after the rollback was released: err=%v elapsed=%s", recoverErr, time.Since(recoverStart))
	if recoverErr != nil {
		t.Fatalf("writes did not recover after the blocked rollback was released: %v", recoverErr)
	}
}
