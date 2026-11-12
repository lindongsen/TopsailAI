// Package endpointstorage provides durable state owned by one Endpoint process.
package endpointstorage

import (
	"context"
	"database/sql"
	"embed"
	"fmt"

	_ "modernc.org/sqlite"
)

//go:embed internal/migrations/*.sql
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
	initial, err := migrationFS.ReadFile("internal/migrations/001_initial.sql")
	if err != nil {
		return fmt.Errorf("read embedded endpoint migration: %w", err)
	}
	if _, err := s.db.ExecContext(ctx, string(initial)); err != nil {
		return fmt.Errorf("apply endpoint migration: %w", err)
	}
	columns, err := s.resourceMappingColumns(ctx)
	if err != nil {
		return err
	}
	if columns["provider_resource_key"] && columns["resource_kind"] {
		return nil
	}
	if !columns["provider_key"] {
		return fmt.Errorf("resource_mapping schema is unsupported")
	}
	migration, err := migrationFS.ReadFile("internal/migrations/002_resource_mapping_kind.sql")
	if err != nil {
		return fmt.Errorf("read resource mapping migration: %w", err)
	}
	if _, err := s.db.ExecContext(ctx, string(migration)); err != nil {
		_, _ = s.db.ExecContext(context.WithoutCancel(ctx), "ROLLBACK")
		return fmt.Errorf("migrate resource mapping identity: %w", err)
	}
	return nil
}

func (s *Store) resourceMappingColumns(ctx context.Context) (map[string]bool, error) {
	rows, err := s.db.QueryContext(ctx, "PRAGMA table_info(resource_mapping)")
	if err != nil {
		return nil, fmt.Errorf("inspect resource mapping schema: %w", err)
	}
	defer rows.Close()
	columns := make(map[string]bool)
	for rows.Next() {
		var cid, notNull, primaryKey int
		var name, columnType string
		var defaultValue any
		if err := rows.Scan(&cid, &name, &columnType, &notNull, &defaultValue, &primaryKey); err != nil {
			return nil, fmt.Errorf("read resource mapping schema: %w", err)
		}
		columns[name] = true
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("read resource mapping schema: %w", err)
	}
	return columns, nil
}
