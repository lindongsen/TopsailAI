package serverstorage

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

// TestConcurrentReadsDoNotFailWrites asserts that ordinary concurrent reads and
// writes all succeed, and it is a smoke test rather than a discriminating one.
//
// The pool is one connection, so a read and a write queue for the same connection
// and a reader can never hold SHARED while a writer commits. Under
// journal_mode(DELETE) that overlap is what makes a write fail with SQLITE_BUSY,
// so at this pool size the conflict is structurally impossible and this test can
// only catch a regression that reintroduces it, such as a second connection
// appearing without WAL.
//
// An earlier version of this comment described the opposite trade: that a larger
// pool buys read availability at the cost of letting a slow reader fail a write.
// That trade was measured and rejected. Raising the pool to eight let a reader
// holding SHARED longer than busy_timeout fail every write, which is the
// production outage's own symptom, so the pool was reverted to one. The comment
// is corrected here because a test whose stated purpose describes a configuration
// the project does not use cannot be trusted to describe what it measures.
func TestConcurrentReadsDoNotFailWrites(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	// Seed enough rows that a read is real work rather than a single-row lookup.
	for i := 0; i < 200; i++ {
		id := fmt.Sprintf("e%03d", i)
		if _, err := store.db.ExecContext(ctx, `INSERT INTO endpoints (endpoint_id, instance_id, display_name, hostname, connection_state, observed_at_ms, capability_revision, create_at_ms, update_at_ms) VALUES (?,?,?,?,?,?,?,?,?)`, id, id, id, "h", "online", 1, "r1", 1, 1); err != nil {
			t.Fatalf("seed %d: %v", i, err)
		}
	}

	// Readers run continuously while writes are attempted. Each read is short,
	// which is what the Server's own reads are: a bounded query over a small
	// result set.
	stop := make(chan struct{})
	var wg sync.WaitGroup
	var readErr error
	var readMu sync.Mutex
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
				}
				rows, err := store.db.QueryContext(ctx, `SELECT endpoint_id, display_name FROM endpoints ORDER BY endpoint_id LIMIT 50`)
				if err != nil {
					readMu.Lock()
					if readErr == nil {
						readErr = err
					}
					readMu.Unlock()
					return
				}
				for rows.Next() {
					var a, b string
					if err := rows.Scan(&a, &b); err != nil {
						rows.Close()
						readMu.Lock()
						if readErr == nil {
							readErr = err
						}
						readMu.Unlock()
						return
					}
				}
				rows.Close()
			}
		}()
	}

	// Writes must all succeed despite the concurrent reads.
	var writeErr error
	deadline := time.Now().Add(3 * time.Second)
	attempts := 0
	for time.Now().Before(deadline) {
		attempts++
		writeCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
		_, err := store.db.ExecContext(writeCtx, `UPDATE endpoints SET display_name = ? WHERE endpoint_id = 'e000'`, fmt.Sprintf("w%d", attempts))
		cancel()
		if err != nil {
			writeErr = err
			break
		}
	}
	close(stop)
	wg.Wait()

	if readErr != nil {
		t.Fatalf("a concurrent read failed: %v", readErr)
	}
	if writeErr != nil {
		t.Fatalf("a write failed while short concurrent reads were running, so the pool size lets a reader block a writer: %v", writeErr)
	}
	t.Logf("%d writes succeeded while four readers ran continuously", attempts)
}

// TestLongReaderMakesAWriteFail records what a long SHARED holder does to a write
// at the current pool size, so the behaviour is documented rather than assumed.
//
// At a pool of one the write does not fail with SQLITE_BUSY. It waits for the
// single connection, which the holder is occupying, and fails only when its own
// context deadline expires. That is a different failure from a lock conflict and
// it is the accepted cost of pool one: one connection held by a reader starves
// every writer until the reader finishes or the writer gives up.
//
// The lock conflict itself is recorded by
// TestTwoIndependentHandlesOnOneFileMakeWritesFail, which uses a second handle
// outside the pool to produce the SHARED holder that a pool of one cannot create.
// An earlier version of this comment claimed this test recorded the limit of a
// larger pool; the pool was reverted to one, so that claim no longer held.
func TestLongReaderMakesAWriteFail(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.db.ExecContext(ctx, `INSERT INTO endpoints (endpoint_id, instance_id, display_name, hostname, connection_state, observed_at_ms, capability_revision, create_at_ms, update_at_ms) VALUES ('e1','i1','e1','h','online',1,'r1',1,1)`); err != nil {
		t.Fatal(err)
	}

	// Hold SHARED on a dedicated connection for longer than busy_timeout.
	holder, err := store.db.Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer holder.Close()
	rows, err := holder.QueryContext(ctx, `SELECT endpoint_id FROM endpoints`)
	if err != nil {
		t.Fatal(err)
	}
	if !rows.Next() {
		t.Fatal("holder produced no row")
	}

	writeCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	start := time.Now()
	_, err = store.db.ExecContext(writeCtx, `UPDATE endpoints SET display_name='blocked' WHERE endpoint_id='e1'`)
	elapsed := time.Since(start)
	rows.Close()

	if err == nil {
		t.Fatalf("a write succeeded while a reader held SHARED for %v, so this test no longer records the limit of journal_mode(DELETE)", elapsed)
	}
	t.Logf("write failed after %v while a reader held SHARED: %v", elapsed, err)
	if elapsed < 4*time.Second {
		t.Fatalf("the write failed after only %v, so it did not wait for busy_timeout and the failure is not the SHARED conflict this test records", elapsed)
	}
}

var _ = sql.ErrNoRows
