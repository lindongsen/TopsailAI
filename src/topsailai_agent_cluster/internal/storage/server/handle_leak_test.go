package serverstorage

import (
	"context"
	"database/sql/driver"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// countOpenHandles returns how many file descriptors the current process holds on
// the given path.
//
// It reads /proc/self/fd rather than using a library because the question is
// specifically about operating-system handles, not about Go objects. A Go
// driverConn can be closed while the underlying SQLite connection keeps its file
// descriptor, and only the descriptor count reveals that difference.
func countOpenHandles(t *testing.T, path string) int {
	t.Helper()
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		t.Skipf("cannot inspect file descriptors: %v", err)
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		t.Fatalf("resolve %s: %v", path, err)
	}
	count := 0
	for _, entry := range entries {
		target, err := os.Readlink(filepath.Join("/proc/self/fd", entry.Name()))
		if err != nil {
			continue
		}
		if target == resolved || strings.HasPrefix(target, resolved+"-") {
			count++
		}
	}
	return count
}

// TestDiscardingConnectionsDoesNotLeakFileHandles verifies that repeatedly
// discarding a connection through driver.ErrBadConn does not accumulate open
// handles on the database file.
//
// This is the property the production outage depended on and no existing test
// checked. During the outage the Server process held three descriptors on
// server.sqlite while the pool was configured with SetMaxOpenConns(1), so at most
// one connection should have existed. Three descriptors mean the pool had already
// discarded connections whose underlying SQLite handles were still open.
//
// That difference explains the production symptom precisely. With a single pooled
// connection, a caller whose connection is stuck inside a transaction blocks
// waiting for the pool; it does not receive SQLITE_BUSY. The Server received
// SQLITE_BUSY 2512 times, so the lock was held by a connection the pool no longer
// knew about. A leaked handle is exactly such a connection: the pool opens a
// replacement, the replacement takes the write lock, and the abandoned handle
// keeps its own lock so every write fails.
func TestDiscardingConnectionsDoesNotLeakFileHandles(t *testing.T) {
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "server.db")
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()

	baseline := countOpenHandles(t, path)
	if baseline == 0 {
		t.Fatal("no descriptor on the database file after opening the store")
	}

	// Each cycle takes the pooled connection, starts a write transaction so it
	// holds the lock, and discards it the way rollbackTransaction does when
	// ROLLBACK fails.
	const cycles = 5
	for i := 0; i < cycles; i++ {
		conn, err := store.DB().Conn(ctx)
		if err != nil {
			t.Fatalf("cycle %d: acquire connection: %v", i, err)
		}
		if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
			_ = conn.Close()
			t.Fatalf("cycle %d: begin immediate: %v", i, err)
		}
		if err := conn.Raw(func(any) error { return driver.ErrBadConn }); !errors.Is(err, driver.ErrBadConn) {
			_ = conn.Close()
			t.Fatalf("cycle %d: discard connection error=%v, want driver.ErrBadConn", i, err)
		}
		_ = conn.Close()
	}

	after := countOpenHandles(t, path)
	if after > baseline {
		t.Fatalf("discarding %d connections left %d open handles on the database file (baseline %d), so each discarded connection keeps its SQLite file descriptor and its write lock while the pool opens a replacement; every later write then fails with SQLITE_BUSY until the process restarts", cycles, after, baseline)
	}
}
