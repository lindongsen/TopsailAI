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

// withTransaction runs one transaction on a pinned connection so a failed
// SQLite commit can be rolled back before that connection returns to the pool.
func (s *Store) withTransaction(ctx context.Context, operation string, run func(*sql.Conn) error) error {
	conn, err := s.db.Conn(ctx)
	if err != nil {
		return fmt.Errorf("acquire %s connection: %w", operation, err)
	}
	defer conn.Close()
	if _, err := conn.ExecContext(ctx, "BEGIN"); err != nil {
		return fmt.Errorf("begin %s: %w", operation, err)
	}
	if err := run(conn); err != nil {
		return rollbackTransaction(conn, operation, err)
	}
	if _, err := conn.ExecContext(ctx, "COMMIT"); err != nil {
		return rollbackTransaction(conn, operation, fmt.Errorf("commit %s: %w", operation, err))
	}
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
