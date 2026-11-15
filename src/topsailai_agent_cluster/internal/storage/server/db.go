// Package serverstorage provides the durable Server SQLite store.
package serverstorage

import (
	"context"
	"database/sql"
	"embed"
	"fmt"
	"net/url"
	"strings"

	_ "modernc.org/sqlite"
)

//go:embed internal/migrations/001_initial.sql
var migrationFS embed.FS

// Store owns the Server database connection.
type Store struct {
	db *sql.DB
}

// Open opens a SQLite database and applies embedded migrations.
func Open(ctx context.Context, path string) (*Store, error) {
	dsn := path
	separator := "?"
	if strings.Contains(path, "?") {
		separator = "&"
	}
	pragmas := url.Values{}
	pragmas.Add("_pragma", "journal_mode(DELETE)")
	pragmas.Add("_pragma", "synchronous(FULL)")
	pragmas.Add("_pragma", "busy_timeout(5000)")
	db, err := sql.Open("sqlite", dsn+separator+pragmas.Encode())
	if err != nil {
		return nil, fmt.Errorf("open sqlite: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	store := &Store{db: db}
	if err := db.PingContext(ctx); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("configure server sqlite: %w", err)
	}
	if err := store.migrate(ctx); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

// Close releases the database connection.
func (s *Store) Close() error { return s.db.Close() }

// DB returns the underlying connection for transaction-scoped operations.
func (s *Store) DB() *sql.DB { return s.db }

func (s *Store) migrate(ctx context.Context) error {
	data, err := migrationFS.ReadFile("internal/migrations/001_initial.sql")
	if err != nil {
		return fmt.Errorf("read embedded migration: %w", err)
	}
	if _, err := s.db.ExecContext(ctx, string(data)); err != nil {
		return fmt.Errorf("apply migration: %w", err)
	}
	var hostnameColumn string
	err = s.db.QueryRowContext(ctx, `SELECT name FROM pragma_table_info('endpoints') WHERE name = 'hostname'`).Scan(&hostnameColumn)
	if err == sql.ErrNoRows {
		if _, err := s.db.ExecContext(ctx, `ALTER TABLE endpoints ADD COLUMN hostname TEXT NOT NULL DEFAULT ''`); err != nil {
			return fmt.Errorf("add endpoint hostname column: %w", err)
		}
	} else if err != nil {
		return fmt.Errorf("inspect endpoint schema: %w", err)
	}
	var offlineSinceColumn string
	err = s.db.QueryRowContext(ctx, `SELECT name FROM pragma_table_info('endpoints') WHERE name = 'offline_since_at_ms'`).Scan(&offlineSinceColumn)
	if err == sql.ErrNoRows {
		if _, err := s.db.ExecContext(ctx, `ALTER TABLE endpoints ADD COLUMN offline_since_at_ms BIGINT NOT NULL DEFAULT 0`); err != nil {
			return fmt.Errorf("add endpoint offline timestamp column: %w", err)
		}
	} else if err != nil {
		return fmt.Errorf("inspect endpoint offline timestamp schema: %w", err)
	}
	if _, err := s.db.ExecContext(ctx, `CREATE INDEX IF NOT EXISTS idx_endpoints_offline_since ON endpoints(offline_since_at_ms, endpoint_id)`); err != nil {
		return fmt.Errorf("index endpoint offline timestamp: %w", err)
	}
	// degraded_since_at_ms records when a row entered the degraded state, and
	// expires_at_ms records the immutable moment it will be deleted. Both default
	// to zero, which is correct for every existing row because no row can be
	// degraded before this column exists. This is the opposite of the
	// offline_since_at_ms migration, which added a column to rows that already
	// needed a value and therefore required a backfill.
	var degradedSinceColumn string
	err = s.db.QueryRowContext(ctx, `SELECT name FROM pragma_table_info('endpoints') WHERE name = 'degraded_since_at_ms'`).Scan(&degradedSinceColumn)
	if err == sql.ErrNoRows {
		if _, err := s.db.ExecContext(ctx, `ALTER TABLE endpoints ADD COLUMN degraded_since_at_ms BIGINT NOT NULL DEFAULT 0`); err != nil {
			return fmt.Errorf("add endpoint degraded timestamp column: %w", err)
		}
	} else if err != nil {
		return fmt.Errorf("inspect endpoint degraded timestamp schema: %w", err)
	}
	var expiresAtColumn string
	err = s.db.QueryRowContext(ctx, `SELECT name FROM pragma_table_info('endpoints') WHERE name = 'expires_at_ms'`).Scan(&expiresAtColumn)
	if err == sql.ErrNoRows {
		if _, err := s.db.ExecContext(ctx, `ALTER TABLE endpoints ADD COLUMN expires_at_ms BIGINT NOT NULL DEFAULT 0`); err != nil {
			return fmt.Errorf("add endpoint expiry deadline column: %w", err)
		}
	} else if err != nil {
		return fmt.Errorf("inspect endpoint expiry deadline schema: %w", err)
	}
	if _, err := s.db.ExecContext(ctx, `CREATE INDEX IF NOT EXISTS idx_endpoints_expires_at ON endpoints(expires_at_ms, endpoint_id)`); err != nil {
		return fmt.Errorf("index endpoint expiry deadline: %w", err)
	}
	return nil
}
