// Package db provides database connection management and auto-migration for the ACS service.
package db

import (
	"database/sql"
	"fmt"
	"time"

	_ "github.com/lib/pq"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/schema"
)

// DB wraps a GORM database connection with application-specific helpers.
type DB struct {
	Conn *gorm.DB
}

// New initializes the database connection, auto-creates the database if needed,
// and auto-migrates all table structures.
func New(cfg *config.Config) (*DB, error) {
	// Attempt to create database if it does not exist.
	if err := ensureDatabaseExists(cfg.Database); err != nil {
		logger.Warn("failed to ensure database exists, continuing anyway", "error", err.Error())
	}

	// Open connection to the target database.
	conn, err := openConnection(cfg.Database)
	if err != nil {
		return nil, fmt.Errorf("failed to open database connection: %w", err)
	}

	sqlDB, err := conn.DB()
	if err != nil {
		return nil, fmt.Errorf("failed to get underlying sql.DB: %w", err)
	}

	// Configure connection pool.
	sqlDB.SetMaxOpenConns(25)
	sqlDB.SetMaxIdleConns(5)
	sqlDB.SetConnMaxLifetime(5 * time.Minute)

	// Auto-migrate all models.
	if err := autoMigrate(conn); err != nil {
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

// openConnection opens a GORM connection to the target database.
func openConnection(cfg config.DatabaseConfig) (*gorm.DB, error) {
	return gorm.Open(postgres.Open(cfg.DSN()), &gorm.Config{
		NamingStrategy: schema.NamingStrategy{
			SingularTable: true,
		},
	})
}

// openRawDB opens a raw *sql.DB connection for use with golang-migrate.
func openRawDB(cfg config.DatabaseConfig) (*sql.DB, error) {
	dsn := cfg.DSN()
	return sql.Open("postgres", dsn)
}

// autoMigrate runs GORM AutoMigrate for all application models.
func autoMigrate(conn *gorm.DB) error {
	return conn.AutoMigrate(
		&models.Group{},
		&models.GroupMember{},
		&models.GroupMessage{},
		&models.AgentMessageProcessing{},
	)
}

// Close gracefully closes the database connection.
func (d *DB) Close() error {
	sqlDB, err := d.Conn.DB()
	if err != nil {
		return err
	}
	return sqlDB.Close()
}
