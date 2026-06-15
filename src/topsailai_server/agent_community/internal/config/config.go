// Package config provides centralized configuration management for the ACS service.
// All environment variables are prefixed with ACS_ and loaded via Viper.
package config

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/viper"
)

// Config holds all application configuration.
type Config struct {
	Server   ServerConfig   `mapstructure:"server"`
	Database DatabaseConfig `mapstructure:"database"`
	NATS     NATSConfig     `mapstructure:"nats"`
	Agent    AgentConfig    `mapstructure:"agent"`
	Pool     PoolConfig     `mapstructure:"pool"`
	Log      LogConfig      `mapstructure:"log"`
	Cleanup  CleanupConfig  `mapstructure:"cleanup"`
}

// ServerConfig holds HTTP server settings.
type ServerConfig struct {
	Port         int           `mapstructure:"port"`
	ReadTimeout  time.Duration `mapstructure:"read_timeout"`
	WriteTimeout time.Duration `mapstructure:"write_timeout"`
}

// DatabaseConfig holds PostgreSQL connection settings.
type DatabaseConfig struct {
	Host     string `mapstructure:"host"`
	Port     int    `mapstructure:"port"`
	User     string `mapstructure:"user"`
	Password string `mapstructure:"password"`
	Name     string `mapstructure:"name"`
	SSLMode  string `mapstructure:"sslmode"`
}

// NATSConfig holds NATS connection and subject settings.
type NATSConfig struct {
	Servers                          string `mapstructure:"servers"`
	StreamGroup                      string `mapstructure:"stream_group"`
	SubjectGroupPendingMessagePrefix string `mapstructure:"subject_group_pending_message_prefix"`
	SubjectGroupMessagePrefix        string `mapstructure:"subject_group_message_prefix"`
}

// AgentConfig holds manager-agent and trigger settings.
type AgentConfig struct {
	ManagerAPIBase     string        `mapstructure:"manager_api_base"`
	ManagerAPIKey      string        `mapstructure:"manager_api_key"`
	ManagerAPIAuth     string        `mapstructure:"manager_api_auth"`
	AutoTriggerTimeout time.Duration `mapstructure:"auto_trigger_timeout"`
	AgentPrompt        string        `mapstructure:"agent_prompt"`
}

// PoolConfig holds AgentWorkPool concurrency limits.
type PoolConfig struct {
	Global           int           `mapstructure:"global"`
	PerUser          int           `mapstructure:"per_user"`
	PerGroup         int           `mapstructure:"per_group"`
	StatsLogInterval time.Duration `mapstructure:"stats_log_interval"`
}

// LogConfig holds logging settings.
type LogConfig struct {
	Output     string `mapstructure:"output"`
	Level      string `mapstructure:"level"`
	FilePath   string `mapstructure:"file_path"`
	MaxSize    int    `mapstructure:"max_size_mb"`
	MaxAge     int    `mapstructure:"max_age_days"`
	MaxBackups int    `mapstructure:"max_backups"`
}

// CleanupConfig holds settings for the agent_message_processing cleanup job.
type CleanupConfig struct {
	Enabled           bool          `mapstructure:"enabled"`
	Interval          time.Duration `mapstructure:"interval"`
	RetentionDays     int           `mapstructure:"retention_days"`
	StalePendingHours int           `mapstructure:"stale_pending_hours"`
	BatchSize         int           `mapstructure:"batch_size"`
}

// Load reads configuration from environment variables with ACS_ prefix.
func Load() (*Config, error) {
	v := viper.New()
	v.SetEnvPrefix("ACS")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	// Server defaults
	v.SetDefault("server.port", 7370)
	v.SetDefault("server.read_timeout", "30s")
	v.SetDefault("server.write_timeout", "30s")

	// Database defaults
	v.SetDefault("database.host", "localhost")
	v.SetDefault("database.port", 5432)
	v.SetDefault("database.user", "acs")
	v.SetDefault("database.password", "acs")
	v.SetDefault("database.name", "acs")
	v.SetDefault("database.sslmode", "disable")

	// NATS defaults
	v.SetDefault("nats.servers", "nats://localhost:4222")
	v.SetDefault("nats.stream_group", "acs_group")
	v.SetDefault("nats.subject_group_pending_message_prefix", "acs.group.pending-message")
	v.SetDefault("nats.subject_group_message_prefix", "acs.group.message")

	// Agent defaults
	v.SetDefault("agent.manager_api_base", "")
	v.SetDefault("agent.manager_api_key", "")
	v.SetDefault("agent.manager_api_auth", "BearerToken")
	v.SetDefault("agent.auto_trigger_timeout", "10m")
	v.SetDefault("agent.agent_prompt", "")

	// Pool defaults
	v.SetDefault("pool.global", 10)
	v.SetDefault("pool.per_user", 5)
	v.SetDefault("pool.per_group", 5)
	v.SetDefault("pool.stats_log_interval", "30s")

	// Log defaults
	v.SetDefault("log.output", "stdout")
	v.SetDefault("log.level", "info")
	v.SetDefault("log.file_path", "/var/log/acs/acs.log")
	v.SetDefault("log.max_size_mb", 100)
	v.SetDefault("log.max_age_days", 30)
	v.SetDefault("log.max_backups", 10)

	// Cleanup defaults
	v.SetDefault("cleanup.enabled", true)
	v.SetDefault("cleanup.interval", "1h")
	v.SetDefault("cleanup.retention_days", 7)
	v.SetDefault("cleanup.stale_pending_hours", 24)
	v.SetDefault("cleanup.batch_size", 1000)

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	return &cfg, nil
}

// DSN returns the PostgreSQL connection string.
func (d *DatabaseConfig) DSN() string {
	return fmt.Sprintf(
		"host=%s port=%d user=%s password=%s dbname=%s sslmode=%s",
		d.Host, d.Port, d.User, d.Password, d.Name, d.SSLMode,
	)
}
