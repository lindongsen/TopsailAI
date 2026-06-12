// Package db provides database migration utilities using golang-migrate.
package db

import (
	"embed"
	"fmt"
	"io/fs"

	"github.com/golang-migrate/migrate/v4"
	"github.com/golang-migrate/migrate/v4/database/postgres"
	"github.com/golang-migrate/migrate/v4/source/iofs"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/pkg/logger"
)

//go:embed migrations/*.sql
var migrationsFS embed.FS

// MigrateUp runs all pending up migrations.
func MigrateUp(cfg *config.Config) error {
	m, err := newMigrateInstance(cfg)
	if err != nil {
		return err
	}

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

	version, dirty, err := m.Version()
	if err != nil && err != migrate.ErrNilVersion {
		return 0, false, fmt.Errorf("failed to get migration version: %w", err)
	}

	return version, dirty, nil
}

// newMigrateInstance creates a new migrate instance with embedded migrations.
func newMigrateInstance(cfg *config.Config) (*migrate.Migrate, error) {
	// Open the embedded migrations sub-directory to satisfy iofs driver requirements.
	migrationsSubFS, err := fs.Sub(migrationsFS, "migrations")
	if err != nil {
		return nil, fmt.Errorf("failed to open embedded migrations sub-directory: %w", err)
	}

	src, err := iofs.New(migrationsSubFS, ".")
	if err != nil {
		return nil, fmt.Errorf("failed to create iofs migration source: %w", err)
	}

	// Open a raw sql.DB connection for the migrate driver.
	db, err := openRawDB(cfg.Database)
	if err != nil {
		return nil, fmt.Errorf("failed to open raw database connection: %w", err)
	}
	defer db.Close()

	driver, err := postgres.WithInstance(db, &postgres.Config{
		DatabaseName: cfg.Database.Name,
	})
	if err != nil {
		return nil, fmt.Errorf("failed to create postgres migrate driver: %w", err)
	}

	m, err := migrate.NewWithInstance("iofs", src, cfg.Database.Name, driver)
	if err != nil {
		return nil, fmt.Errorf("failed to create migrate instance: %w", err)
	}

	return m, nil
}
