package serverstorage

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestStuckTransactionBlocksOrFailsDistinguishesTheRootCause answers the single
// question that separates the two candidate root causes of the production outage.
//
// The outage had a shape that looks self-contradictory. The pool was configured
// with SetMaxOpenConns(1), yet callers received SQLITE_BUSY 2512 times over almost
// three hours. Those two facts are only compatible under one of two explanations:
//
//  1. The single pooled connection was stuck inside a transaction. Then a caller
//     asking for a connection waits for the pool, and it blocks rather than
//     receiving SQLITE_BUSY. The observed BUSY would be impossible, so this
//     explanation is wrong.
//  2. A connection holding the write lock was not in the pool at all, so the pool
//     opened a replacement. The replacement then contends with the abandoned
//     connection's lock and receives SQLITE_BUSY. This matches the observation.
//
// This test measures which one actually happens, so the root cause is decided by
// evidence instead of by reasoning about database/sql internals.
func TestStuckTransactionBlocksOrFailsDistinguishesTheRootCause(t *testing.T) {
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

	// Seed a row so the write below modifies a page and therefore creates a
	// rollback journal. Without a real modification SQLite writes no journal and
	// the descriptor count would not reflect a write transaction.
	if err := store.UpsertEndpoint(ctx, protocol.Endpoint{
		EndpointID: "probe", InstanceID: "probe-1", DisplayName: "probe",
		ConnectionState: "online", ObservedAtMS: 1000, CapabilityRevision: "v1",
	}, 1000); err != nil {
		t.Fatal(err)
	}

	// Hold the only pooled connection inside a write transaction, which is the
	// state the production Server was in.
	holder, err := store.DB().Conn(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := holder.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		_ = holder.Close()
		t.Fatalf("begin immediate: %v", err)
	}
	if _, err := holder.ExecContext(ctx, `UPDATE endpoints SET display_name = 'held'`); err != nil {
		_ = holder.Close()
		t.Fatalf("write inside transaction: %v", err)
	}

	descriptors := countOpenHandles(t, path)
	t.Logf("descriptors with one connection holding a write transaction: %d", descriptors)
	entries, readErr := os.ReadDir("/proc/self/fd")
	if readErr == nil {
		resolved, _ := filepath.EvalSymlinks(path)
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

	// Now attempt a write from another goroutine and record whether it blocks or
	// fails. This is the decisive measurement.
	type outcome struct {
		blocked bool
		err     error
		elapsed time.Duration
	}
	done := make(chan outcome, 1)
	go func() {
		start := time.Now()
		_, err := store.DB().ExecContext(ctx, `UPDATE endpoints SET display_name = 'contender'`)
		done <- outcome{err: err, elapsed: time.Since(start)}
	}()

	var result outcome
	select {
	case result = <-done:
		result.blocked = false
	case <-time.After(3 * time.Second):
		result.blocked = true
	}

	if result.blocked {
		t.Logf("a second write BLOCKED waiting for the single pooled connection, so a stuck transaction cannot produce SQLITE_BUSY")
	} else if result.err != nil {
		lower := strings.ToLower(result.err.Error())
		if strings.Contains(lower, "locked") || strings.Contains(lower, "busy") {
			t.Logf("a second write FAILED with SQLITE_BUSY after %s while the pool had one connection, so the lock holder is not the pooled connection", result.elapsed)
		} else {
			t.Logf("a second write failed with a different error after %s: %v", result.elapsed, result.err)
		}
	} else {
		t.Logf("a second write SUCCEEDED after %s, so the pool opened a second connection despite SetMaxOpenConns(1)", result.elapsed)
	}

	if _, err := holder.ExecContext(ctx, "ROLLBACK"); err != nil {
		_ = holder.Close()
		t.Fatalf("rollback: %v", err)
	}
	_ = holder.Close()
}
