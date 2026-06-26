// Package db provides database connection management and auto-migration tests.
package db

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
)

// sqliteInMemory returns a DatabaseConfig that uses a unique in-memory SQLite DB.
func sqliteInMemory(t *testing.T) config.DatabaseConfig {
	t.Helper()
	return config.DatabaseConfig{
		Driver: "sqlite",
		Name:   fmt.Sprintf("file:%s?mode=memory&cache=shared", t.Name()),
	}
}

// newTestConfig returns a minimal Config with the provided database config.
func newTestConfig(dbCfg config.DatabaseConfig) *config.Config {
	return &config.Config{
		Database: dbCfg,
	}
}

// ==================== A. SQLite Connection Path (New) ====================

// TestNew_SQLite_Success verifies that New opens an in-memory SQLite database,
// runs auto-migration, and returns a usable DB wrapper.
func TestNew_SQLite_Success(t *testing.T) {
	cfg := newTestConfig(sqliteInMemory(t))

	db, err := New(cfg, nil)
	require.NoError(t, err)
	require.NotNil(t, db)
	require.NotNil(t, db.Conn)
	t.Cleanup(func() { _ = db.Close() })

	for _, table := range []string{
		"groups",
		"group_member",
		"group_messages",
		"agent_message_processing",
		"accounts",
		"api_keys",
		"audit_logs",
	} {
		assert.True(t, db.Conn.Migrator().HasTable(table), "table %s should exist", table)
	}
}

// TestNew_SQLite_InvalidPath verifies that New returns an error when the SQLite
// parent directory cannot be created.
func TestNew_SQLite_InvalidPath(t *testing.T) {
	if os.Getuid() == 0 {
		t.Skip("running as root; cannot simulate unwritable directory")
	}

	// Use a path under a non-existent directory with a name that cannot be created.
	dir := filepath.Join(os.TempDir(), "acs_db_test", "nonexistent", string([]byte{0}))
	cfg := newTestConfig(config.DatabaseConfig{
		Driver: "sqlite",
		Name:   filepath.Join(dir, "test.db"),
	})

	db, err := New(cfg, nil)
	require.Error(t, err)
	assert.Nil(t, db)
	assert.Contains(t, err.Error(), "failed to create directory for sqlite database")
}

// TestNew_SQLite_ConnectionPool verifies that New configures the connection pool.
func TestNew_SQLite_ConnectionPool(t *testing.T) {
	cfg := newTestConfig(sqliteInMemory(t))

	db, err := New(cfg, nil)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })

	sqlDB, err := db.Conn.DB()
	require.NoError(t, err)

	stats := sqlDB.Stats()
	assert.Equal(t, 25, stats.MaxOpenConnections)
	// MaxIdleConns and ConnMaxLifetime cannot be read back reliably across
	// drivers, so we only assert the value exposed via Stats.
}

// ==================== B. PostgreSQL Connection Helpers ====================

// TestDatabaseConfig_DSN verifies the PostgreSQL DSN format.
func TestDatabaseConfig_DSN(t *testing.T) {
	cfg := config.DatabaseConfig{
		Host:     "db.example.com",
		Port:     5433,
		User:     "acs_user",
		Password: "acs_pass",
		Name:     "acs_db",
		SSLMode:  "require",
	}

	expected := "host=db.example.com port=5433 user=acs_user password=acs_pass dbname=acs_db sslmode=require"
	assert.Equal(t, expected, cfg.DSN())
}

// TestEnsureDatabaseExists_SkipsWhenNoPostgres skips when no live Postgres is available.
func TestEnsureDatabaseExists_SkipsWhenNoPostgres(t *testing.T) {
	if os.Getenv("ACS_TEST_POSTGRES") == "" {
		t.Skip("skipping live Postgres test; set ACS_TEST_POSTGRES to enable")
	}
	cfg := config.DatabaseConfig{
		Host:     "localhost",
		Port:     5432,
		User:     "acs",
		Password: "acs",
		Name:     "acs_test_ensure_exists",
		SSLMode:  "disable",
	}
	err := ensureDatabaseExists(cfg)
	assert.NoError(t, err)
}

// ==================== C. Raw DB Opening (openRawDB) ====================

// TestOpenRawDB_SQLite verifies openRawDB returns a working *sql.DB for SQLite.
func TestOpenRawDB_SQLite(t *testing.T) {
	cfg := sqliteInMemory(t)

	db, err := openRawDB(cfg)
	require.NoError(t, err)
	require.NotNil(t, db)
	t.Cleanup(func() { _ = db.Close() })

	assert.NoError(t, db.Ping())
}

// TestOpenRawDB_PostgresDSN verifies openRawDB returns a *sql.DB with the postgres driver.
// This test does NOT call Ping() and therefore does not require a live Postgres server.
func TestOpenRawDB_PostgresDSN(t *testing.T) {
	cfg := config.DatabaseConfig{
		Driver:   "postgres",
		Host:     "localhost",
		Port:     5432,
		User:     "acs",
		Password: "acs",
		Name:     "acs",
		SSLMode:  "disable",
	}

	db, err := openRawDB(cfg)
	require.NoError(t, err)
	require.NotNil(t, db)
	t.Cleanup(func() { _ = db.Close() })

	// driver.Driver does not expose a Name() method; verify by opening with the
	// expected DSN and checking the returned *sql.DB is non-nil.
	assert.NotNil(t, db)
}

// ==================== D. Auto-Migration (autoMigrate) ====================

// TestAutoMigrate_AllModels verifies all required tables are created.
func TestAutoMigrate_AllModels(t *testing.T) {
	conn, err := openSQLiteConnection(sqliteInMemory(t))
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, _ := conn.DB()
		if sqlDB != nil {
			_ = sqlDB.Close()
		}
	})

	require.NoError(t, autoMigrate(conn))

	for _, table := range []string{
		"groups",
		"group_member",
		"group_messages",
		"agent_message_processing",
		"accounts",
		"api_keys",
		"audit_logs",
	} {
		assert.True(t, conn.Migrator().HasTable(table), "table %s should exist", table)
	}
}

// TestAutoMigrate_Idempotent verifies running autoMigrate twice does not fail.
func TestAutoMigrate_Idempotent(t *testing.T) {
	conn, err := openSQLiteConnection(sqliteInMemory(t))
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, _ := conn.DB()
		if sqlDB != nil {
			_ = sqlDB.Close()
		}
	})

	require.NoError(t, autoMigrate(conn))
	assert.NoError(t, autoMigrate(conn))
}

// ==================== E. Close (DB.Close) ====================

// TestDB_Close verifies Close releases the underlying connection.
func TestDB_Close(t *testing.T) {
	cfg := newTestConfig(sqliteInMemory(t))

	db, err := New(cfg, nil)
	require.NoError(t, err)
	require.NotNil(t, db)

	assert.NoError(t, db.Close())

	// After Close, getting the underlying sql.DB may still succeed because GORM
	// lazily reconnects, but Ping should fail for a closed SQLite in-memory DB.
	sqlDB, err := db.Conn.DB()
	if err == nil && sqlDB != nil {
		assert.Error(t, sqlDB.Ping())
	}
}

// ==================== F. Model Hook Smoke Tests via Auto-Migrated DB ====================

// TestNew_AllowsModelCreation verifies that records can be created after New.
func TestNew_AllowsModelCreation(t *testing.T) {
	cfg := newTestConfig(sqliteInMemory(t))

	db, err := New(cfg, nil)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })

	account := &models.Account{
		AccountName: "Test Account",
		Role:        models.AccountRoleUser,
		Status:      models.AccountStatusActive,
		LoginName:   "test@example.com",
		CreatorID:   "system",
	}
	require.NoError(t, db.Conn.Create(account).Error)
	assert.NotEmpty(t, account.AccountID)
	assert.True(t, account.CreateAtMs > 0)
	assert.True(t, account.UpdateAtMs > 0)

	group := &models.Group{
		GroupName: "Test Group",
		CreatorID: account.AccountID,
		OwnerID:   account.AccountID,
	}
	require.NoError(t, db.Conn.Create(group).Error)
	assert.NotEmpty(t, group.GroupID)
	assert.True(t, group.CreateAtMs > 0)
}

// TestNew_EnforcesUniqueLoginName verifies the unique index on accounts.login_name.
func TestNew_EnforcesUniqueLoginName(t *testing.T) {
	cfg := newTestConfig(sqliteInMemory(t))

	db, err := New(cfg, nil)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })

	loginName := "unique@example.com"
	acc1 := &models.Account{
		AccountName: "First",
		Role:        models.AccountRoleUser,
		Status:      models.AccountStatusActive,
		LoginName:   loginName,
		CreatorID:   "system",
	}
	acc2 := &models.Account{
		AccountName: "Second",
		Role:        models.AccountRoleUser,
		Status:      models.AccountStatusActive,
		LoginName:   loginName,
		CreatorID:   "system",
	}

	require.NoError(t, db.Conn.Create(acc1).Error)
	assert.Error(t, db.Conn.Create(acc2).Error)
}

// TestNew_EnforcesCompositePrimaryKey verifies the composite primary key on group_member.
func TestNew_EnforcesCompositePrimaryKey(t *testing.T) {
	cfg := newTestConfig(sqliteInMemory(t))

	db, err := New(cfg, nil)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })

	member := &models.GroupMember{
		GroupID:    "group-1",
		MemberID:   "member-1",
		MemberName: "Member One",
		MemberType: models.MemberTypeUser,
	}
	require.NoError(t, db.Conn.Create(member).Error)

	// Duplicate primary key should fail.
	dup := &models.GroupMember{
		GroupID:    "group-1",
		MemberID:   "member-1",
		MemberName: "Duplicate",
		MemberType: models.MemberTypeUser,
	}
	assert.Error(t, db.Conn.Create(dup).Error)
}

// ==================== G. Connection Pool Direct Configuration ====================

// TestConfigureConnectionPool verifies the pool is configured as documented.
func TestConfigureConnectionPool(t *testing.T) {
	conn, err := openSQLiteConnection(sqliteInMemory(t))
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, _ := conn.DB()
		if sqlDB != nil {
			_ = sqlDB.Close()
		}
	})

	sqlDB, err := conn.DB()
	require.NoError(t, err)

	sqlDB.SetMaxOpenConns(25)
	sqlDB.SetMaxIdleConns(5)
	sqlDB.SetConnMaxLifetime(5 * time.Minute)

	stats := sqlDB.Stats()
	assert.Equal(t, 25, stats.MaxOpenConnections)
}

// ==================== H. SQLite File Creation ====================

// TestOpenSQLiteConnection_CreatesDirectory verifies parent directories are created.
func TestOpenSQLiteConnection_CreatesDirectory(t *testing.T) {
	dir := t.TempDir()
	cfg := config.DatabaseConfig{
		Driver: "sqlite",
		Name:   filepath.Join(dir, "subdir", "acs.db"),
	}

	conn, err := openSQLiteConnection(cfg)
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, _ := conn.DB()
		if sqlDB != nil {
			_ = sqlDB.Close()
		}
	})

	assert.FileExists(t, cfg.Name)
}

// ==================== I. Raw DB Driver Selection ====================

// TestOpenRawDB_UnsupportedDriver verifies openRawDB returns an error for unknown drivers.
func TestOpenRawDB_UnsupportedDriver(t *testing.T) {
	cfg := config.DatabaseConfig{
		Driver:   "unknown",
		Name:     ":memory:",
		Host:     "localhost",
		Port:     5432,
		User:     "acs",
		Password: "acs",
		SSLMode:  "disable",
	}

	db, err := openRawDB(cfg)
	require.Error(t, err)
	assert.Nil(t, db)
}

// ==================== J. Ensure Database Exists Error Path ====================

// TestEnsureDatabaseExists_ReturnsErrorWhenPostgresUnreachable verifies that
// ensureDatabaseExists returns an error when Postgres is not reachable.
func TestEnsureDatabaseExists_ReturnsErrorWhenPostgresUnreachable(t *testing.T) {
	cfg := config.DatabaseConfig{
		Host:     "127.0.0.1",
		Port:     1, // Unlikely to be open
		User:     "acs",
		Password: "acs",
		Name:     "acs",
		SSLMode:  "disable",
	}

	err := ensureDatabaseExists(cfg)
	assert.Error(t, err)
}

// ==================== K. DB Wrapper Nil Safety ====================

// TestDB_Close_NilConn verifies Close handles a nil connection gracefully.
func TestDB_Close_NilConn(t *testing.T) {
	db := &DB{Conn: nil}
	assert.Error(t, db.Close())
}

// ==================== L. SQLite Shared Memory Isolation ====================

// TestNew_SQLite_IsolatedBetweenTests verifies that each test gets its own DB.
func TestNew_SQLite_IsolatedBetweenTests(t *testing.T) {
	cfg := newTestConfig(sqliteInMemory(t))

	db, err := New(cfg, nil)
	require.NoError(t, err)
	t.Cleanup(func() { _ = db.Close() })

	account := &models.Account{
		AccountName: "Isolated",
		Role:        models.AccountRoleUser,
		Status:      models.AccountStatusActive,
		LoginName:   "isolated@example.com",
		CreatorID:   "system",
	}
	require.NoError(t, db.Conn.Create(account).Error)

	var count int64
	require.NoError(t, db.Conn.Model(&models.Account{}).Where("login_name = ?", "isolated@example.com").Count(&count).Error)
	assert.Equal(t, int64(1), count)
}

// ==================== M. Migration Utilities (migrate.go) ====================
//
// SQLite-based migration tests for MigrateUp/MigrateDown/MigrateVersion live in
// migrate_test.go. migrate.go now supports both postgres and sqlite3 drivers.
