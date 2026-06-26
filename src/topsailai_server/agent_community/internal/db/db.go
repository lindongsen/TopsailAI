// Package db provides database connection management and auto-migration for the ACS service.
package db

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	_ "github.com/lib/pq"
	"github.com/nats-io/nats.go"
	"github.com/google/uuid"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"

	"gorm.io/driver/postgres"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/schema"
)
// migrationLockKey is the NATS KV key used to coordinate database auto-migration
// across ACS nodes. It uses the same dotted format as
// internal/lock/distributed_lock.go and must not contain ':'.
const migrationLockKey = "acs.lock.bootstrap.migration"

// migrationLockWaitTimeout is the maximum time a node will wait for another node
// to finish database migration before failing startup. It is aligned with the
// NATS KV bucket TTL (7200s) so that a crashed migrator does not cause other
// nodes to time out while the lock is still valid.
//
// This is a variable (not a constant) so that unit tests can override it with
// short values. Production code must not modify it.
var migrationLockWaitTimeout = 2 * time.Hour

// migrationLockPollInterval is the interval between checks while waiting for the
// migration lock to be released.
//
// This is a variable (not a constant) so that unit tests can override it with
// short values. Production code must not modify it.
var migrationLockPollInterval = 500 * time.Millisecond

// DB wraps a GORM database connection with application-specific helpers.
type DB struct {
	Conn *gorm.DB
}

// New initializes the database connection, auto-creates the database if needed,
// and auto-migrates all table structures.
//
// If kv is non-nil, database migration is protected by a NATS KV distributed
// lock so that only one ACS node performs AutoMigrate at a time. Other nodes
// wait for the lock to be released and then proceed. If kv is nil, migration
// runs without distributed coordination (suitable for single-node tests).
func New(cfg *config.Config, kv nats.KeyValue) (*DB, error) {
	var conn *gorm.DB
	var err error

	if cfg.Database.Driver == "sqlite" {
		// SQLite: open file directly, no need to create database.
		conn, err = openSQLiteConnection(cfg.Database)
		if err != nil {
			return nil, fmt.Errorf("failed to open sqlite database: %w", err)
		}
	} else {
		// PostgreSQL: attempt to create database if it does not exist.
		if err := ensureDatabaseExists(cfg.Database); err != nil {
			logger.Warn("failed to ensure database exists, continuing anyway", "error", err.Error())
		}

		conn, err = openConnection(cfg.Database)
		if err != nil {
			return nil, fmt.Errorf("failed to open database connection: %w", err)
		}
	}

	sqlDB, err := conn.DB()
	if err != nil {
		return nil, fmt.Errorf("failed to get underlying sql.DB: %w", err)
	}

	// Configure connection pool.
	sqlDB.SetMaxOpenConns(25)
	sqlDB.SetMaxIdleConns(5)
	sqlDB.SetConnMaxLifetime(5 * time.Minute)

	// Auto-migrate all models, protected by a distributed lock when available.
	if err := autoMigrateWithLock(conn, kv); err != nil {
		return nil, fmt.Errorf("failed to auto-migrate database: %w", err)
	}

	logger.Info("database initialized and migrated successfully")
	return &DB{Conn: conn}, nil
}

// ensureDatabaseExists connects to the default 'postgres' database and creates
// the target database if it does not exist. This is a tentative action;
// permission failures are returned but should not block startup.
func ensureDatabaseExists(cfg config.DatabaseConfig) error {
	// Connect to the default postgres database to manage the target DB.
	adminDSN := fmt.Sprintf(
		"host=%s port=%d user=%s password=%s dbname=postgres sslmode=%s",
		cfg.Host, cfg.Port, cfg.User, cfg.Password, cfg.SSLMode,
	)

	adminDB, err := gorm.Open(postgres.Open(adminDSN), &gorm.Config{
		NamingStrategy: schema.NamingStrategy{
			SingularTable: true,
		},
	})
	if err != nil {
		return fmt.Errorf("failed to connect to postgres admin db: %w", err)
	}

	sqlDB, err := adminDB.DB()
	if err != nil {
		return fmt.Errorf("failed to get underlying sql.DB: %w", err)
	}
	defer sqlDB.Close()

	// Check if database exists.
	var exists bool
	query := "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = $1)"
	if err := adminDB.Raw(query, cfg.Name).Scan(&exists).Error; err != nil {
		return fmt.Errorf("failed to check database existence: %w", err)
	}

	if exists {
		return nil
	}

	// Create database.
	createSQL := fmt.Sprintf("CREATE DATABASE %s", cfg.Name)
	if err := adminDB.Exec(createSQL).Error; err != nil {
		return fmt.Errorf("failed to create database (possible permission issue): %w", err)
	}

	return nil
}

// openConnection opens a GORM connection to the target PostgreSQL database.
func openConnection(cfg config.DatabaseConfig) (*gorm.DB, error) {
	return gorm.Open(postgres.Open(cfg.DSN()), &gorm.Config{
		NamingStrategy: schema.NamingStrategy{
			SingularTable: true,
		},
	})
}

// openSQLiteConnection opens a GORM connection to a SQLite database.
func openSQLiteConnection(cfg config.DatabaseConfig) (*gorm.DB, error) {
	// Ensure parent directory exists.
	dir := filepath.Dir(cfg.Name)
	if dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0755); err != nil {
			return nil, fmt.Errorf("failed to create directory for sqlite database: %w", err)
		}
	}
	return gorm.Open(sqlite.Open(cfg.Name), &gorm.Config{
		NamingStrategy: schema.NamingStrategy{
			SingularTable: true,
		},
	})
}

// openRawDB opens a raw *sql.DB connection for use with golang-migrate.
func openRawDB(cfg config.DatabaseConfig) (*sql.DB, error) {
	switch cfg.Driver {
	case "sqlite":
		return sql.Open("sqlite3", cfg.Name)
	case "postgres":
		dsn := cfg.DSN()
		return sql.Open("postgres", dsn)
	default:
		return nil, fmt.Errorf("unsupported database driver: %s", cfg.Driver)
	}
}

// autoMigrateWithLock runs auto-migrate under a distributed lock when kv is
// provided. If the lock is held by another node, this function waits for it to
// be released and then runs an idempotent auto-migrate to ensure the schema is
// present. If kv is nil, auto-migrate runs without coordination.
func autoMigrateWithLock(conn *gorm.DB, kv nats.KeyValue) error {
	return autoMigrateWithLockFn(conn, kv, autoMigrate)
}

// autoMigrateWithLockFn is the testable core of autoMigrateWithLock. It accepts
// a migrate function so that tests can inject failures or panics.
func autoMigrateWithLockFn(conn *gorm.DB, kv nats.KeyValue, migrateFn func(*gorm.DB) error) error {
	if kv == nil {
		return migrateFn(conn)
	}

	token := uuid.New().String()
	_, err := kv.Create(migrationLockKey, []byte(token))
	if err == nil {
		// We hold the lock; run migration and then release it. Use a dedicated
		// closure with recover so that a panic during migration still releases
		// the lock. The panic is re-raised so the server fails loudly.
		var migrateErr error
		func() {
			defer func() {
				if r := recover(); r != nil {
					if delErr := kv.Delete(migrationLockKey); delErr != nil {
						logger.Warn("failed to delete migration lock key after panic", "key", migrationLockKey, "error", delErr.Error())
					}
					panic(r)
				}
			}()
			migrateErr = migrateFn(conn)
		}()
		if delErr := kv.Delete(migrationLockKey); delErr != nil {
			logger.Warn("failed to delete migration lock key", "key", migrationLockKey, "error", delErr.Error())
		}
		return migrateErr
	}

	if errors.Is(err, nats.ErrKeyExists) {
		// Another node is migrating. Wait for the lock to be released.
		logger.Info("migration lock held by another node, waiting", "key", migrationLockKey)
		if waitErr := waitForMigrationLockRelease(kv); waitErr != nil {
			return fmt.Errorf("failed to wait for migration lock: %w", waitErr)
		}
		// Lock released. Run an idempotent auto-migrate to verify/complete the schema.
		logger.Info("migration lock released, continuing startup")
		return migrateFn(conn)
	}

	return fmt.Errorf("failed to acquire migration lock: %w", err)
}

// waitForMigrationLockRelease polls the NATS KV key until it disappears or the
// timeout is reached.
func waitForMigrationLockRelease(kv nats.KeyValue) error {
	ctx, cancel := context.WithTimeout(context.Background(), migrationLockWaitTimeout)
	defer cancel()

	ticker := time.NewTicker(migrationLockPollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return fmt.Errorf("timed out after %v waiting for migration lock %q to be released", migrationLockWaitTimeout, migrationLockKey)
		case <-ticker.C:
			_, err := kv.Get(migrationLockKey)
			if err == nats.ErrKeyNotFound {
				return nil
			}
			if err != nil {
				// A transient KV error should not cause immediate failure; retry on
				// the next tick so that brief NATS hiccups are tolerated.
				logger.Warn("failed to read migration lock key while waiting", "key", migrationLockKey, "error", err.Error())
			}
		}
	}
}

// autoMigrate runs GORM AutoMigrate for all application models.
func autoMigrate(conn *gorm.DB) error {
	return conn.AutoMigrate(
		&models.Group{},
		&models.GroupMember{},
		&models.GroupMessage{},
		&models.AgentMessageProcessing{},
		&models.Account{},
		&models.APIKey{},
		&models.AuditLog{},
	)
}

// Close gracefully closes the database connection.
func (d *DB) Close() error {
	if d == nil || d.Conn == nil {
		return fmt.Errorf("database connection is nil")
	}
	sqlDB, err := d.Conn.DB()
	if err != nil {
		return err
	}
	return sqlDB.Close()
}
