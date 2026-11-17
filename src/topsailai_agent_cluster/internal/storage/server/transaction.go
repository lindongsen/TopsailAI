package serverstorage

import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"fmt"
	"time"
)

const transactionCleanupTimeout = 5 * time.Second

// transactionBudget bounds how long one transaction may hold the write lock.
//
// SQLite has exactly one writer, so a transaction that never finishes stops every
// other write for as long as it exists. The production outage was exactly that: a
// write lock held for almost three hours while every other write failed with
// SQLITE_BUSY. busy_timeout bounds how long a *waiter* waits, but nothing bounded
// how long the *holder* held, because every Server write used a context with no
// deadline.
//
// The budget is generous relative to the work these transactions do, which is a
// handful of statements over a few thousand rows. It exists to convert "held
// forever" into "failed and released", not to make slow work fail.
const transactionBudget = 30 * time.Second

// withTransaction runs one transaction on a pinned connection so a failed
// SQLite commit can be rolled back before that connection returns to the pool.
//
// The transaction is closed by a deferred rollback rather than only on the error
// paths. A callback that panics unwinds past the explicit error handling, and the
// deferred conn.Close() would then return the connection to the pool while it is
// still inside the transaction. Every later statement on that connection joins
// the abandoned transaction instead of starting its own, so it reports success
// without committing and a second connection keeps reading the old value. That is
// silent data loss, and it is invisible to the caller because the poisoned write
// returns nil. The deferred rollback runs on the panic path too, so the connection
// is always outside a transaction before it is released.
//
// The callback receives the budgeted context rather than the caller's. Passing the
// caller's context would bound only the statements this function issues itself —
// Conn, BEGIN and COMMIT — while every statement inside the callback would keep
// running under a context with no deadline. The budget would then look present and
// bound nothing, which is exactly the shape of the production outage: a write lock
// held for almost three hours while the code believed it had a bound. A callback
// that blocks on its own must also observe the budget, so it is given the context
// that carries it.
func (s *Store) withTransaction(ctx context.Context, operation string, run func(context.Context, *sql.Conn) error) error {
	// The budget is applied here rather than at each call site so no caller can
	// forget it. A caller that already has a shorter deadline keeps it, because
	// WithTimeout never extends an existing deadline.
	ctx, cancel := context.WithTimeout(ctx, transactionBudget)
	defer cancel()
	conn, err := s.db.Conn(ctx)
	if err != nil {
		return fmt.Errorf("acquire %s connection: %w", operation, err)
	}
	defer conn.Close()
	// BEGIN IMMEDIATE takes the write lock before any page is modified, so a
	// conflict is reported here instead of at COMMIT. A deferred BEGIN starts as a
	// reader: the callback runs, pages are modified, the rollback journal is
	// created, and only COMMIT discovers that another connection holds SHARED. The
	// work is then discarded and the caller learns about the conflict after doing
	// it, which also means a callback with side effects has already run them.
	// Taking the lock up front makes the conflict cheap and keeps a writer from
	// modifying pages it cannot commit.
	//
	// This does not make a writer able to commit while a reader holds SHARED.
	// RESERVED is compatible with SHARED, so BEGIN IMMEDIATE succeeds and the
	// conflict still appears at COMMIT. What bounds that case is busy_timeout, and
	// what bounds how long the holder keeps the lock is transactionBudget below.
	// A larger pool was tried and reverted precisely because it does not help here:
	// see maxOpenConnections in db.go for the measurement.
	if _, err := conn.ExecContext(ctx, "BEGIN IMMEDIATE"); err != nil {
		return fmt.Errorf("begin %s: %w", operation, err)
	}
	// finished records that the transaction has already been closed, either by
	// COMMIT or by an explicit rollback on an error path. The deferred rollback
	// must not run a second time: a second ROLLBACK on a connection that is no
	// longer inside a transaction fails, and rollbackTransaction treats a failed
	// rollback as a reason to discard the connection, so a healthy connection
	// would be thrown away on every ordinary error.
	finished := false
	defer func() {
		if finished {
			return
		}
		// This path is reached only when the callback panicked, because every
		// ordinary exit sets finished before returning. There is no caller left to
		// report to, so the rollback is best effort; its purpose is to leave the
		// connection outside a transaction before conn.Close returns it to the pool.
		rollbackTransaction(conn, operation, nil)
	}()
	if err := run(ctx, conn); err != nil {
		finished = true
		return rollbackTransaction(conn, operation, err)
	}
	if _, err := conn.ExecContext(ctx, "COMMIT"); err != nil {
		finished = true
		return rollbackTransaction(conn, operation, fmt.Errorf("commit %s: %w", operation, err))
	}
	finished = true
	return nil
}

// rollbackTransaction uses an independent cleanup budget because the operation
// context may already be cancelled. A connection that cannot roll back is
// discarded instead of returning an active transaction to the pool.
func rollbackTransaction(conn *sql.Conn, operation string, cause error) error {
	cleanupCtx, cancel := context.WithTimeout(context.Background(), transactionCleanupTimeout)
	defer cancel()
	if _, err := conn.ExecContext(cleanupCtx, "ROLLBACK"); err != nil {
		discardErr := conn.Raw(func(any) error { return driver.ErrBadConn })
		if discardErr != nil && !errors.Is(discardErr, driver.ErrBadConn) {
			return fmt.Errorf("%w; rollback %s: %v; discard connection: %v", cause, operation, err, discardErr)
		}
		return fmt.Errorf("%w; rollback %s: %v; discarded connection", cause, operation, err)
	}
	return cause
}
