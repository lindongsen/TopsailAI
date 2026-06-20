// Package db provides database migration utility tests.
package db

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/config"
)

// sqliteFileConfig returns a Config that uses a temporary SQLite file database.
// golang-migrate requires a persistent database file because each migration step
// may open a new connection; :memory: databases are connection-scoped.
func sqliteFileConfig(t *testing.T) *config.Config {
	t.Helper()
	dir := t.TempDir()
	return &config.Config{
		Database: config.DatabaseConfig{
			Driver: "sqlite",
			Name:   filepath.Join(dir, "migrate_test.db"),
		},
	}
}

// ==================== A. MigrateUp ====================

// TestMigrateUp_SQLite_CreatesTables verifies MigrateUp creates all expected
// tables using the SQLite-compatible migration files.
func TestMigrateUp_SQLite_CreatesTables(t *testing.T) {
	cfg := sqliteFileConfig(t)

	require.NoError(t, MigrateUp(cfg))

	db, err := openSQLiteConnection(cfg.Database)
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, _ := db.DB()
		if sqlDB != nil {
			_ = sqlDB.Close()
		}
	})

	for _, table := range []string{
		"groups",
		"group_member",
		"group_messages",
		"agent_message_processing",
		"accounts",
		"api_keys",
		"audit_logs",
		"schema_migrations",
	} {
		assert.True(t, db.Migrator().HasTable(table), "table %s should exist", table)
	}
}

// TestMigrateUp_SQLite_Idempotent verifies running MigrateUp twice succeeds.
func TestMigrateUp_SQLite_Idempotent(t *testing.T) {
	cfg := sqliteFileConfig(t)

	require.NoError(t, MigrateUp(cfg))
	assert.NoError(t, MigrateUp(cfg))
}

// TestMigrateUp_UnsupportedDriver verifies MigrateUp returns an error for an
// unsupported database driver.
func TestMigrateUp_UnsupportedDriver(t *testing.T) {
	cfg := &config.Config{
		Database: config.DatabaseConfig{
			Driver:   "mysql",
			Name:     "test",
			Host:     "localhost",
			Port:     3306,
			User:     "acs",
			Password: "acs",
			SSLMode:  "disable",
		},
	}

	err := MigrateUp(cfg)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unsupported database driver")
}

// ==================== B. MigrateDown ====================

// TestMigrateDown_SQLite_RemovesTables verifies MigrateDown removes the tables
// created by MigrateUp.
func TestMigrateDown_SQLite_RemovesTables(t *testing.T) {
	cfg := sqliteFileConfig(t)

	require.NoError(t, MigrateUp(cfg))
	require.NoError(t, MigrateDown(cfg))

	db, err := openSQLiteConnection(cfg.Database)
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, _ := db.DB()
		if sqlDB != nil {
			_ = sqlDB.Close()
		}
	})

	for _, table := range []string{
		"agent_message_processing",
		"group_messages",
		"group_member",
		"groups",
		"audit_logs",
		"api_keys",
		"accounts",
	} {
		assert.False(t, db.Migrator().HasTable(table), "table %s should not exist", table)
	}
}

// TestMigrateDown_SQLite_Idempotent verifies running MigrateDown twice succeeds.
func TestMigrateDown_SQLite_Idempotent(t *testing.T) {
	cfg := sqliteFileConfig(t)

	require.NoError(t, MigrateUp(cfg))
	require.NoError(t, MigrateDown(cfg))
	assert.NoError(t, MigrateDown(cfg))
}

// ==================== C. MigrateVersion ====================

// TestMigrateVersion_SQLite_AfterUp verifies the version after MigrateUp.
func TestMigrateVersion_SQLite_AfterUp(t *testing.T) {
	cfg := sqliteFileConfig(t)

	require.NoError(t, MigrateUp(cfg))

	version, dirty, err := MigrateVersion(cfg)
	require.NoError(t, err)
	assert.False(t, dirty, "migration should not be dirty")
	assert.Equal(t, uint(2), version, "expected latest migration version")
}

// TestMigrateVersion_SQLite_BeforeAnyMigration verifies the version before any
// migration has been applied.
func TestMigrateVersion_SQLite_BeforeAnyMigration(t *testing.T) {
	cfg := sqliteFileConfig(t)

	version, dirty, err := MigrateVersion(cfg)
	require.NoError(t, err)
	assert.False(t, dirty)
	assert.Equal(t, uint(0), version)
}

// TestMigrateVersion_UnsupportedDriver verifies MigrateVersion returns an error
// for an unsupported database driver.
func TestMigrateVersion_UnsupportedDriver(t *testing.T) {
	cfg := &config.Config{
		Database: config.DatabaseConfig{
			Driver:   "cassandra",
			Name:     "test",
			Host:     "localhost",
			Port:     9042,
			User:     "acs",
			Password: "acs",
			SSLMode:  "disable",
		},
	}

	version, dirty, err := MigrateVersion(cfg)
	require.Error(t, err)
	assert.Equal(t, uint(0), version)
	assert.False(t, dirty)
	assert.Contains(t, err.Error(), "unsupported database driver")
}

// ==================== D. Migration Source Selection ====================

// TestNewMigrationSource_SQLite verifies the SQLite migration source can be
// created and contains the expected migration files.
func TestNewMigrationSource_SQLite(t *testing.T) {
	src, err := newMigrationSource("sqlite")
	require.NoError(t, err)
	require.NotNil(t, src)

	version, err := src.First()
	require.NoError(t, err)
	assert.Equal(t, uint(1), version)
}

// TestNewMigrationSource_Postgres verifies the PostgreSQL migration source can
// be created and contains the expected migration files.
func TestNewMigrationSource_Postgres(t *testing.T) {
	src, err := newMigrationSource("postgres")
	require.NoError(t, err)
	require.NotNil(t, src)

	version, err := src.First()
	require.NoError(t, err)
	assert.Equal(t, uint(1), version)
}

// TestNewMigrationSource_UnsupportedDriver verifies an unsupported driver
// returns an error.
func TestNewMigrationSource_UnsupportedDriver(t *testing.T) {
	src, err := newMigrationSource("oracle")
	require.Error(t, err)
	assert.Nil(t, src)
	assert.Contains(t, err.Error(), "unsupported database driver")
}

// ==================== E. Driver Selection ====================

// TestNewMigrateDriver_SQLite verifies a sqlite3 migrate driver can be created.
func TestNewMigrateDriver_SQLite(t *testing.T) {
	cfg := config.DatabaseConfig{
		Driver: "sqlite",
		Name:   filepath.Join(t.TempDir(), "driver_test.db"),
	}

	db, err := openRawDB(cfg)
	require.NoError(t, err)
	defer db.Close()

	driver, err := newMigrateDriver(cfg, db)
	require.NoError(t, err)
	require.NotNil(t, driver)
}

// TestNewMigrateDriver_UnsupportedDriver verifies an unsupported driver returns
// an error.
func TestNewMigrateDriver_UnsupportedDriver(t *testing.T) {
	cfg := config.DatabaseConfig{
		Driver:   "mongodb",
		Name:     "test",
		Host:     "localhost",
		Port:     27017,
		User:     "acs",
		Password: "acs",
		SSLMode:  "disable",
	}

	db, err := openRawDB(config.DatabaseConfig{Driver: "sqlite", Name: ":memory:"})
	require.NoError(t, err)
	defer db.Close()

	driver, err := newMigrateDriver(cfg, db)
	require.Error(t, err)
	assert.Nil(t, driver)
	assert.Contains(t, err.Error(), "unsupported database driver")
}

// ==================== F. End-to-End Up/Down/Up Cycle ====================

// TestMigrateUpDownUpCycle_SQLite verifies a full migration up, down, and up
// cycle succeeds and leaves the database in the expected state.
func TestMigrateUpDownUpCycle_SQLite(t *testing.T) {
	cfg := sqliteFileConfig(t)

	require.NoError(t, MigrateUp(cfg))

	version, dirty, err := MigrateVersion(cfg)
	require.NoError(t, err)
	assert.Equal(t, uint(2), version)
	assert.False(t, dirty)

	require.NoError(t, MigrateDown(cfg))

	version, dirty, err = MigrateVersion(cfg)
	require.NoError(t, err)
	assert.Equal(t, uint(0), version)
	assert.False(t, dirty)

	require.NoError(t, MigrateUp(cfg))

	version, dirty, err = MigrateVersion(cfg)
	require.NoError(t, err)
	assert.Equal(t, uint(2), version)
	assert.False(t, dirty)

	// Verify a table exists after the final up.
	db, err := openSQLiteConnection(cfg.Database)
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, _ := db.DB()
		if sqlDB != nil {
			_ = sqlDB.Close()
		}
	})
	assert.True(t, db.Migrator().HasTable("accounts"))
}

// ==================== G. File Cleanup ====================

// TestMigrateUp_SQLite_CreatesDatabaseFile verifies MigrateUp creates the
// SQLite database file if it does not exist.
func TestMigrateUp_SQLite_CreatesDatabaseFile(t *testing.T) {
	cfg := sqliteFileConfig(t)

	require.NoFileExists(t, cfg.Database.Name)
	require.NoError(t, MigrateUp(cfg))
	assert.FileExists(t, cfg.Database.Name)
}

// TestMigrateUp_SQLite_InvalidPath verifies MigrateUp returns an error when the
// SQLite parent directory cannot be created.
func TestMigrateUp_SQLite_InvalidPath(t *testing.T) {
	if os.Getuid() == 0 {
		t.Skip("running as root; cannot simulate unwritable directory")
	}

	dir := filepath.Join(os.TempDir(), "acs_migrate_test", string([]byte{0}))
	cfg := &config.Config{
		Database: config.DatabaseConfig{
			Driver: "sqlite",
			Name:   filepath.Join(dir, "test.db"),
		},
	}

	err := MigrateUp(cfg)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to open raw database connection")
}
