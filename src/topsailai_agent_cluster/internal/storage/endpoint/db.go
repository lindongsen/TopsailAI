// Package endpointstorage provides durable state owned by one Endpoint process.
package endpointstorage

import (
	"context"
	"database/sql"
	"embed"
	"fmt"
	"os"
	"path/filepath"
	"strings"

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
	if err := prepareDatabaseFile(path); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, fmt.Errorf("open endpoint sqlite: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	store := &Store{db: db}
	// busy_timeout must be set before any statement that can contend for the write
	// lock, because journal_mode and synchronous both take it. Setting it last
	// leaves the first two statements to fail immediately with SQLITE_BUSY when
	// another process opens the same database at the same moment.
	for _, pragma := range []string{"PRAGMA busy_timeout=5000", "PRAGMA journal_mode=DELETE", "PRAGMA synchronous=FULL"} {
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

// prepareDatabaseFile creates the database file and its directory with modes that
// keep Endpoint state unreadable to other local accounts.
//
// SQLite creates both with the process umask, which yields 0644 and 0755 on a
// default host. Ownership alone does not isolate the file: the Server container
// runs as a different uid but can still read a world-readable file, so the
// permission bits are the layer that actually enforces the boundary. The modes are
// applied to an existing file and directory as well, because every deployed
// Endpoint already holds a 0644 database inside a 0755 directory, and a fix that
// only affected new installs would leave the fleet exposed.
func prepareDatabaseFile(path string) error {
	if path == "" || path == ":memory:" || strings.HasPrefix(path, "file:") {
		return nil
	}
	if dir := filepath.Dir(path); dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0o750); err != nil {
			return fmt.Errorf("create endpoint database directory: %w", err)
		}
		// MkdirAll leaves an existing directory's mode untouched, so the
		// restrictive mode has to be applied explicitly for the upgrade path.
		if err := os.Chmod(dir, 0o750); err != nil {
			return fmt.Errorf("restrict endpoint database directory: %w", err)
		}
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return fmt.Errorf("create endpoint database file: %w", err)
	}
	if err := file.Close(); err != nil {
		return fmt.Errorf("close endpoint database file: %w", err)
	}
	// OpenFile applies its mode only when it creates the file, so an existing
	// 0644 database keeps its mode until it is corrected here.
	if err := os.Chmod(path, 0o600); err != nil {
		return fmt.Errorf("restrict endpoint database file: %w", err)
	}
	return nil
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
		// Another process may have applied the same migration between the column
		// inspection above and this attempt. The rollback restores whatever shape
		// the transaction started from, so re-inspecting distinguishes "another
		// process already converted this database" from "this migration cannot
		// run". Without this check a concurrent startup fails with a schema error
		// even though the database is already in the target shape.
		if raced, inspectErr := s.resourceMappingColumns(ctx); inspectErr == nil && raced["provider_resource_key"] && raced["resource_kind"] {
			return nil
		}
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
