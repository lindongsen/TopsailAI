// Package endpointstorage provides durable state owned by one Endpoint process.
package endpointstorage

import (
	"context"
	"database/sql"
	"embed"
	"fmt"

	_ "modernc.org/sqlite"
)

//go:embed internal/migrations/001_initial.sql
var migrationFS embed.FS

// Store owns the Endpoint-local SQLite database.
type Store struct {
	db *sql.DB
}

// Open opens an Endpoint database and applies embedded migrations.
func Open(ctx context.Context, path string) (*Store, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("open endpoint sqlite: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	store := &Store{db: db}
	for _, pragma := range []string{"PRAGMA journal_mode=DELETE", "PRAGMA synchronous=FULL", "PRAGMA busy_timeout=5000"} {
		if _, err := db.ExecContext(ctx, pragma); err != nil {
			_ = db.Close()
			return nil, fmt.Errorf("configure endpoint sqlite: %w", err)
		}
	}
	if err := store.migrate(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}
	return store, nil
}

// Close releases the Endpoint database connection.
func (s *Store) Close() error { return s.db.Close() }

func (s *Store) migrate(ctx context.Context) error {
	data, err := migrationFS.ReadFile("internal/migrations/001_initial.sql")
	if err != nil {
		return fmt.Errorf("read embedded endpoint migration: %w", err)
	}
	if _, err := s.db.ExecContext(ctx, string(data)); err != nil {
		return fmt.Errorf("apply endpoint migration: %w", err)
	}
	return nil
}
