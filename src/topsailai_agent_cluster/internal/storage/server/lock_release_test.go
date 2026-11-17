package serverstorage

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"path/filepath"
	"strings"
	"testing"
)

// TestDiscardedConnectionReleasesTheWriteLock verifies that discarding a
// connection through driver.ErrBadConn actually releases the SQLite write lock
// it held.
//
// This is the property the production outage depended on and the existing
// recovery tests never checked. TestReplacementConnectionRetainsPragmas proves a
// replacement connection keeps its pragmas, and TestCommitBusyDoesNotPoisonConnection
// proves a failed commit does not leave the pooled connection inside a
// transaction. Neither proves the discarded connection stopped holding the lock.
//
// The distinction matters because the pool and the SQLite file are two different
// resources. If the Go-side driverConn is closed while the underlying SQLite
// connection stays open, the pool believes it has a healthy connection and opens
// a replacement, while the abandoned connection keeps the write lock. Every later
// write then fails with SQLITE_BUSY even though the pool is not poisoned, which is
// exactly the production symptom: callers received "database is locked" instead of
// blocking for the single pooled connection.
func TestDiscardedConnectionReleasesTheWriteLock(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	// Take the only pooled connection and start a write transaction on it, so it
	// holds the SQLite write lock.
	conn, err := store.DB().Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		_ = conn.Close()
		t.Fatalf("begin immediate: %v", err)
	}
	if _, err := conn.ExecContext(ctx, `UPDATE endpoints SET display_name = display_name WHERE 1 = 0`); err != nil {
		_ = conn.Close()
		t.Fatalf("write inside transaction: %v", err)
	}
	// Discard the connection the way rollbackTransaction does when ROLLBACK fails.
	// Raw reports driver.ErrBadConn to signal that the connection was discarded;
	// that return value is the success signal, not a failure.
	if err := conn.Raw(func(any) error { return driver.ErrBadConn }); !errors.Is(err, driver.ErrBadConn) {
		_ = conn.Close()
		t.Fatalf("discard connection error=%v, want driver.ErrBadConn", err)
	}
	_ = conn.Close()

	// A replacement connection must be able to write. If the discarded connection
	// still holds the lock, this fails with SQLITE_BUSY and the Server would stay
	// permanently unable to write until the process restarts.
	if _, err := store.DB().ExecContext(ctx, `PRAGMA busy_timeout=200`); err != nil {
		t.Fatalf("set busy timeout on replacement connection: %v", err)
	}
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = display_name`); err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "locked") || strings.Contains(strings.ToLower(err.Error()), "busy") {
			t.Fatalf("a discarded connection still holds the SQLite write lock, so every later write fails with SQLITE_BUSY until the process restarts: %v", err)
		}
		t.Fatalf("write after discarding the lock holder: %v", err)
	}
}

// TestFailedRollbackDoesNotLeaveTheWriteLockHeld verifies the full production
// path: a transaction whose COMMIT fails, whose ROLLBACK then also fails, and
// which is therefore discarded. The next write must succeed.
//
// The commit is forced to fail by holding a read transaction on a second
// connection, which is the same technique TestCommitBusyDoesNotPoisonConnection
// uses. The difference is the assertion: this test checks that the write lock is
// released, not merely that the pooled connection is reusable.
func TestFailedRollbackDoesNotLeaveTheWriteLockHeld(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if _, err := store.DB().ExecContext(ctx, `PRAGMA busy_timeout=20`); err != nil {
		t.Fatal(err)
	}

	reader, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	readTx, err := reader.BeginTx(ctx, &sql.TxOptions{ReadOnly: true})
	if err != nil {
		t.Fatal(err)
	}
	var rows int
	if err := readTx.QueryRowContext(ctx, `SELECT count(*) FROM endpoints`).Scan(&rows); err != nil {
		t.Fatal(err)
	}

	// This commit must fail because the reader holds SHARED and the writer cannot
	// reach EXCLUSIVE under journal_mode=DELETE.
	if _, err := store.DegradeOfflineEndpoints(ctx, 200, 1000, 5000); err == nil {
		t.Fatal("degrade commit succeeded while an external read transaction held the database")
	}

	if err := readTx.Rollback(); err != nil {
		t.Fatal(err)
	}

	// The write lock must be free now. A failure here means the failed transaction
	// left a connection holding the lock, which is the production outage.
	if _, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = display_name`); err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "locked") || strings.Contains(strings.ToLower(err.Error()), "busy") {
			t.Fatalf("the write lock is still held after a failed commit and rollback, so the Server cannot write until it restarts: %v", err)
		}
		t.Fatalf("write after failed commit: %v", err)
	}
}
