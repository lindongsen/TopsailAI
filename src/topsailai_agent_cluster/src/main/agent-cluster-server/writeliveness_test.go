package main

import (
	"context"
	"database/sql"
	"errors"
	"io"
	"log/slog"
	"path/filepath"
	"strings"
	"testing"
	"time"

	_ "modernc.org/sqlite"

	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// discardLogger returns a logger that writes nowhere, so a test can assert on the
// returned error instead of on log text.
func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// openWatchdogStore opens a real SQLite store in a temporary directory.
//
// A real file is required rather than an in-memory database, because the lock
// behaviour under test is a property of the file and its journal. An in-memory
// database has no journal file and no second connection can observe the same lock,
// so a test using one would pass without exercising anything.
func openWatchdogStore(t *testing.T) *serverstorage.Store {
	t.Helper()
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "watchdog.sqlite"))
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return store
}

// holdSharedLock opens a second connection to the same file and keeps a read
// transaction open, which is the condition that blocks every writer's COMMIT under
// journal_mode(DELETE).
//
// The returned release function must be called to let the writer proceed. It is
// separate from the cleanup so a test can prove recovery after release rather than
// only proving the failure.
func holdSharedLock(t *testing.T, path string) func() {
	t.Helper()
	holder, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatalf("open holder: %v", err)
	}
	conn, err := holder.Conn(context.Background())
	if err != nil {
		t.Fatalf("holder conn: %v", err)
	}
	if _, err := conn.ExecContext(context.Background(), "BEGIN"); err != nil {
		t.Fatalf("holder begin: %v", err)
	}
	rows, err := conn.QueryContext(context.Background(), "SELECT count(*) FROM sqlite_master")
	if err != nil {
		t.Fatalf("holder read: %v", err)
	}
	// The cursor stays open on purpose. Closing it would release SHARED and the
	// writer would succeed, which is the opposite of the condition under test.
	_ = rows

	released := false
	release := func() {
		if released {
			return
		}
		released = true
		_ = rows.Close()
		_, _ = conn.ExecContext(context.Background(), "ROLLBACK")
		_ = conn.Close()
		_ = holder.Close()
	}
	t.Cleanup(release)
	return release
}

// TestWriteLivenessWatchdogStaysSilentOnAHealthyStore asserts the watchdog does not
// report a lost write when the database accepts writes.
//
// This is the false-positive guard. A watchdog that fires on a healthy database
// would restart a working Server, which is worse than the outage it prevents.
func TestWriteLivenessWatchdogStaysSilentOnAHealthyStore(t *testing.T) {
	store := openWatchdogStore(t)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	err := runWriteLiveness(ctx, discardLogger(), store, 50*time.Millisecond, 2*time.Second)
	if err != nil {
		t.Fatalf("watchdog reported a lost write on a healthy store: %v", err)
	}
}

// TestWriteLivenessWatchdogReportsALostWriteAfterTheBudget asserts the watchdog
// reports a lost write once the budget is exhausted while a second holder keeps
// SHARED.
//
// This is the detection test, and it is the reason the watchdog exists: the
// production Server ran for almost three hours in exactly this state while only
// logging each failure.
func TestWriteLivenessWatchdogReportsALostWriteAfterTheBudget(t *testing.T) {
	path := filepath.Join(t.TempDir(), "watchdog.sqlite")
	store, err := serverstorage.Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })

	release := holdSharedLock(t, path)
	defer release()

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	started := time.Now()
	err = runWriteLiveness(ctx, discardLogger(), store, 100*time.Millisecond, 500*time.Millisecond)
	elapsed := time.Since(started)

	if !errors.Is(err, errWriteLivenessLost) {
		t.Fatalf("watchdog returned %v after %s while a second holder kept SHARED; it must report errWriteLivenessLost, because a Server that cannot persist anything must not keep running", err, elapsed)
	}
	if elapsed < 500*time.Millisecond {
		t.Fatalf("watchdog reported a lost write after %s, before the 500ms budget elapsed; a budget that is not honoured would restart a Server during a transient lock", elapsed)
	}
}

// TestWriteLivenessWatchdogReturnsImmediatelyOnAnUnrecoverableError asserts a
// non-lock error is reported without waiting out the budget.
//
// Waiting cannot fix a corrupt or read-only database, and waiting is what let the
// production outage run for almost three hours. The distinction matters because a
// watchdog that waits on every error class would delay the exit for a condition
// that will never clear.
func TestWriteLivenessWatchdogReturnsImmediatelyOnAnUnrecoverableError(t *testing.T) {
	store := openWatchdogStore(t)
	// Closing the store makes every statement fail with a non-lock error, which is
	// the unrecoverable class.
	if err := store.Close(); err != nil {
		t.Fatalf("close store: %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	started := time.Now()
	err := runWriteLiveness(ctx, discardLogger(), store, 50*time.Millisecond, 30*time.Second)
	elapsed := time.Since(started)

	if err == nil {
		t.Fatal("watchdog returned nil for a closed store; a database that cannot be written must be reported")
	}
	if errors.Is(err, errWriteLivenessLost) {
		t.Fatalf("watchdog reported a lost write instead of the underlying error %v; the operator needs the real cause, not a generic verdict", err)
	}
	if elapsed > 5*time.Second {
		t.Fatalf("watchdog waited %s before reporting an unrecoverable error; waiting cannot fix this class and must not consume the budget", elapsed)
	}
}

// TestWriteLivenessWatchdogIsDisabledByAZeroBudget asserts the documented escape
// hatch works.
//
// An operator who prefers a blocked Server to a restarted one sets the budget to
// zero. If zero silently meant "use the default", that operator would get restarts
// they explicitly declined.
func TestWriteLivenessWatchdogIsDisabledByAZeroBudget(t *testing.T) {
	path := filepath.Join(t.TempDir(), "watchdog.sqlite")
	store, err := serverstorage.Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })

	release := holdSharedLock(t, path)
	defer release()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err = runWriteLiveness(ctx, discardLogger(), store, 50*time.Millisecond, 0)
	if err != nil {
		t.Fatalf("watchdog returned %v with a zero budget while the database was blocked; a zero budget must disable the watchdog, because that is the documented way to decline restarts", err)
	}
}

// TestWriteLivenessWatchdogLogsRecoveryAfterATransientLock asserts a transient lock
// is distinguishable from a lost write.
//
// Without the recovery log an operator sees a warning and never learns whether the
// condition cleared, so a near miss and a real outage look identical in the log.
func TestWriteLivenessWatchdogLogsRecoveryAfterATransientLock(t *testing.T) {
	path := filepath.Join(t.TempDir(), "watchdog.sqlite")
	store, err := serverstorage.Open(context.Background(), path)
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { _ = store.Close() })

	var logs strings.Builder
	logger := slog.New(slog.NewTextHandler(&logs, nil))

	release := holdSharedLock(t, path)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	done := make(chan error, 1)
	go func() {
		done <- runWriteLiveness(ctx, logger, store, 50*time.Millisecond, 30*time.Second)
	}()

	// The lock is held past the driver's busy_timeout of five seconds, because a
	// shorter hold is absorbed by the driver and the probe succeeds without ever
	// reporting an error. A test that released earlier would assert on a recovery
	// log that cannot exist, and would pass for the wrong reason if the log were
	// removed.
	time.Sleep(6 * time.Second)
	release()
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("watchdog returned %v after the lock was released; a transient lock must not be reported as a lost write", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("watchdog did not return after the lock was released")
	}

	if !strings.Contains(logs.String(), "database accepts writes again") {
		t.Fatalf("watchdog did not log recovery; log was %q. Without it a transient lock and a lost write look identical to an operator", logs.String())
	}
}

// TestIsLockContentionClassifiesErrorClasses asserts the classifier separates the
// transient class from the unrecoverable one.
//
// The watchdog's whole behaviour depends on this decision: a misclassification in
// either direction either waits on a condition that cannot clear or exits on one
// that would have.
func TestIsLockContentionClassifiesErrorClasses(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want bool
	}{
		{"nil", nil, false},
		{"busy", errors.New("database is locked (5) (SQLITE_BUSY)"), true},
		{"locked", errors.New("database is locked"), true},
		{"disk full", errors.New("database or disk is full (13)"), false},
		{"read only", errors.New("attempt to write a readonly database (8)"), false},
		{"corrupt", errors.New("database disk image is malformed (11)"), false},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := isLockContention(testCase.err); got != testCase.want {
				t.Fatalf("isLockContention(%v) = %v, want %v; a misclassification either waits on an unrecoverable error or exits on a transient one", testCase.err, got, testCase.want)
			}
		})
	}
}
