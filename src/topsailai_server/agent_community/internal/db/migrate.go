// Package db provides database migration utilities using golang-migrate.
package db

import (
	"database/sql"
	"embed"
	"fmt"
	"io/fs"

	"github.com/golang-migrate/migrate/v4"
	"github.com/golang-migrate/migrate/v4/database"
	"github.com/golang-migrate/migrate/v4/database/postgres"
	"github.com/golang-migrate/migrate/v4/database/sqlite3"
	"github.com/golang-migrate/migrate/v4/source"
	"github.com/golang-migrate/migrate/v4/source/iofs"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/pkg/logger"
)

//go:embed migrations/*.sql
//go:embed migrations/sqlite/*.sql
var migrationsFS embed.FS

// MigrateUp runs all pending up migrations.
func MigrateUp(cfg *config.Config) error {
	m, err := newMigrateInstance(cfg)
	if err != nil {
		return err
	}
	defer m.Close()

	if err := m.Up(); err != nil && err != migrate.ErrNoChange {
		return fmt.Errorf("migration up failed: %w", err)
	}

	logger.Info("database migrations applied successfully")
	return nil
}

// MigrateDown runs all down migrations (rollback).
func MigrateDown(cfg *config.Config) error {
	m, err := newMigrateInstance(cfg)
	if err != nil {
		return err
	}
	defer m.Close()

	if err := m.Down(); err != nil && err != migrate.ErrNoChange {
		return fmt.Errorf("migration down failed: %w", err)
	}

	logger.Info("database migrations rolled back successfully")
	return nil
}

// MigrateVersion returns the current migration version.
func MigrateVersion(cfg *config.Config) (uint, bool, error) {
	m, err := newMigrateInstance(cfg)
	if err != nil {
		return 0, false, err
	}
	defer m.Close()

	version, dirty, err := m.Version()
	if err != nil && err != migrate.ErrNilVersion {
		return 0, false, fmt.Errorf("failed to get migration version: %w", err)
	}

	return version, dirty, nil
}

// newMigrateInstance creates a new migrate instance with embedded migrations.
// The caller is responsible for calling Close() on the returned migrate instance
// to release the underlying database connection.
func newMigrateInstance(cfg *config.Config) (*migrate.Migrate, error) {
	src, err := newMigrationSource(cfg.Database.Driver)
	if err != nil {
		return nil, err
	}

	// Open a raw sql.DB connection for the migrate driver. The connection is
	// owned by the returned migrate instance and is closed via m.Close().
	db, err := openRawDB(cfg.Database)
	if err != nil {
		return nil, fmt.Errorf("failed to open raw database connection: %w", err)
	}

	driver, err := newMigrateDriver(cfg.Database, db)
	if err != nil {
		_ = db.Close()
		return nil, err
	}

	m, err := migrate.NewWithInstance("iofs", src, cfg.Database.Name, driver)
	if err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("failed to create migrate instance: %w", err)
	}

	return m, nil
}

// newMigrationSource returns an iofs source driver containing the migrations
// appropriate for the requested database driver.
func newMigrationSource(driver string) (source.Driver, error) {
	var migrationsSubFS fs.FS
	var err error

	switch driver {
	case "sqlite":
		migrationsSubFS, err = fs.Sub(migrationsFS, "migrations/sqlite")
	case "postgres":
		migrationsSubFS, err = fs.Sub(migrationsFS, "migrations")
	default:
		return nil, fmt.Errorf("unsupported database driver for migrations: %s", driver)
	}
	if err != nil {
		return nil, fmt.Errorf("failed to open embedded migrations sub-directory: %w", err)
	}

	src, err := iofs.New(migrationsSubFS, ".")
	if err != nil {
		return nil, fmt.Errorf("failed to create iofs migration source: %w", err)
	}
	return src, nil
}

// newMigrateDriver creates the golang-migrate database driver for the given
// database configuration.
func newMigrateDriver(cfg config.DatabaseConfig, db *sql.DB) (database.Driver, error) {
	switch cfg.Driver {
	case "sqlite":
		return sqlite3.WithInstance(db, &sqlite3.Config{
			DatabaseName: cfg.Name,
		})
	case "postgres":
		return postgres.WithInstance(db, &postgres.Config{
			DatabaseName: cfg.Name,
		})
	default:
		return nil, fmt.Errorf("unsupported database driver for migrations: %s", cfg.Driver)
	}
}
