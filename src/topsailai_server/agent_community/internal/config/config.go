// Package config provides centralized configuration management for the ACS service.
// All environment variables are prefixed with ACS_ and loaded via Viper.
package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/spf13/viper"
)

// Config holds all application configuration.
type Config struct {
	Server        ServerConfig        `mapstructure:"server"`
	Database      DatabaseConfig      `mapstructure:"database"`
	NATS          NATSConfig          `mapstructure:"nats"`
	Agent         AgentConfig         `mapstructure:"agent"`
	AgentWorkPool AgentWorkPoolConfig `mapstructure:"agent_work_pool"`
	Log           LogConfig           `mapstructure:"log"`
	Cleanup       CleanupConfig       `mapstructure:"cleanup"`
	Discovery     DiscoveryConfig     `mapstructure:"discovery"`
	Account       AccountConfig       `mapstructure:"account"`
}

// ServerConfig holds HTTP server settings.
type ServerConfig struct {
	Port         int           `mapstructure:"port"`
	ReadTimeout  time.Duration `mapstructure:"read_timeout"`
	WriteTimeout time.Duration `mapstructure:"write_timeout"`
}

// DatabaseConfig holds database connection settings.
type DatabaseConfig struct {
	Driver   string `mapstructure:"driver"`
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
	PendingMessageNoAck              bool   `mapstructure:"pending_message_no_ack"`
	AckWaitSeconds                   int    `mapstructure:"ack_wait_seconds"`
	MaxAckPending                    int    `mapstructure:"max_ack_pending"`
}

// AgentConfig holds manager-agent and trigger settings.
type AgentConfig struct {
	AutoTriggerTimeout time.Duration      `mapstructure:"auto_trigger_timeout"`
	AgentPrompt        string             `mapstructure:"agent_prompt"`
	ManagerAgent       ManagerAgentConfig `mapstructure:"manager_agent"`
}

// ManagerAgentConfig holds default settings used when auto-joining a manager-agent to a new group.
type ManagerAgentConfig struct {
	MemberID           string        `mapstructure:"member_id"`
	MemberName         string        `mapstructure:"member_name"`
	MemberDescription  string        `mapstructure:"member_description"`
	Adaptor            string        `mapstructure:"adaptor"`
	CmdChat            string        `mapstructure:"cmd_chat"`
	CmdCheckHealth     string        `mapstructure:"cmd_check_health"`
	CmdCheckStatus     string        `mapstructure:"cmd_check_status"`
	APIBase            string        `mapstructure:"api_base"`
	APIKey             string        `mapstructure:"api_key"`
	APIAuth            string        `mapstructure:"api_auth"`
	TimeoutChat        time.Duration `mapstructure:"timeout_chat"`
	TimeoutCheckHealth time.Duration `mapstructure:"timeout_check_health"`
	TimeoutCheckStatus time.Duration `mapstructure:"timeout_check_status"`
}

// AgentWorkPoolConfig holds AgentWorkPool concurrency limits.
type AgentWorkPoolConfig struct {
	PerNode          int           `mapstructure:"per_node"`
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

// DiscoveryConfig holds NATS service discovery settings.
type DiscoveryConfig struct {
	Enabled     bool          `mapstructure:"enabled"`
	ServiceName string        `mapstructure:"service_name"`
	BucketName  string        `mapstructure:"bucket_name"`
	Heartbeat   time.Duration `mapstructure:"heartbeat"`
	TTL         time.Duration `mapstructure:"ttl"`
}

// AccountConfig holds account, API key, and authentication settings.
type AccountConfig struct {
	AdminAPIKey               string `mapstructure:"admin_api_key"`
	ManagerAPIKey             string `mapstructure:"manager_api_key"`
	APIKeyMaxPerAccount       int    `mapstructure:"api_key_max_per_account"`
	LoginSessionExpirySeconds int    `mapstructure:"login_session_expiry_seconds"`
	BcryptCost                int    `mapstructure:"bcrypt_cost"`
}

// Load reads configuration from environment variables with ACS_ prefix.
func Load() (*Config, error) {
	v := viper.New()
	v.SetEnvPrefix("ACS")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	// Check if database.name was explicitly set before applying defaults.
	nameExplicitlySet := v.IsSet("database.name")

	// Server defaults
	v.SetDefault("server.port", 7370)
	v.SetDefault("server.read_timeout", "30s")
	v.SetDefault("server.write_timeout", "30s")
	// Database defaults
	v.SetDefault("database.driver", "postgres")
	v.SetDefault("database.host", "localhost")
	v.SetDefault("database.port", 5432)
	v.SetDefault("database.user", "acs")
	v.SetDefault("database.password", "acs")
	// Note: database.name default is handled after Unmarshal based on driver.
	v.SetDefault("database.sslmode", "disable")

	// NATS defaults
	v.SetDefault("nats.servers", "nats://localhost:4222")
	v.SetDefault("nats.stream_group", "acs_group")
	v.SetDefault("nats.subject_group_pending_message_prefix", "acs.group.pending-message")
	v.SetDefault("nats.subject_group_message_prefix", "acs.group.message")
	v.SetDefault("nats.pending_message_no_ack", false)
	v.SetDefault("nats.ack_wait_seconds", 3600)
	v.SetDefault("nats.max_ack_pending", 10)

	// Agent defaults
	v.SetDefault("agent.auto_trigger_timeout", "10m")
	v.SetDefault("agent.agent_prompt", "")
	// Manager-agent auto-join defaults.
	// These settings are used to automatically create a manager-agent member
	// when a group is created and ACS_GROUP_MANAGER_AGENT_CMD_CHAT is set.
	v.SetDefault("agent.manager_agent.member_id", "manager-agent")
	v.SetDefault("agent.manager_agent.member_name", "manager-agent")
	v.SetDefault("agent.manager_agent.member_description", "Default group manager agent")
	v.SetDefault("agent.manager_agent.adaptor", "topsailai_agent")
	v.SetDefault("agent.manager_agent.cmd_chat", "")
	v.SetDefault("agent.manager_agent.cmd_check_health", "")
	v.SetDefault("agent.manager_agent.cmd_check_status", "")
	v.SetDefault("agent.manager_agent.api_base", "")
	v.SetDefault("agent.manager_agent.api_key", "")
	v.SetDefault("agent.manager_agent.api_auth", "bearer")
	v.SetDefault("agent.manager_agent.timeout_chat", "600s")
	v.SetDefault("agent.manager_agent.timeout_check_health", "5s")
	v.SetDefault("agent.manager_agent.timeout_check_status", "5s")

	// Bind manager-agent settings to the documented ACS_GROUP_MANAGER_AGENT_* env vars.
	_ = v.BindEnv("agent.manager_agent.member_id", "ACS_GROUP_MANAGER_AGENT_MEMBER_ID")
	_ = v.BindEnv("agent.manager_agent.member_name", "ACS_GROUP_MANAGER_AGENT_MEMBER_NAME")
	_ = v.BindEnv("agent.manager_agent.member_description", "ACS_GROUP_MANAGER_AGENT_MEMBER_DESCRIPTION")
	_ = v.BindEnv("agent.manager_agent.adaptor", "ACS_GROUP_MANAGER_AGENT_ADAPTOR")
	_ = v.BindEnv("agent.manager_agent.cmd_chat", "ACS_GROUP_MANAGER_AGENT_CMD_CHAT")
	_ = v.BindEnv("agent.manager_agent.cmd_check_health", "ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH")
	_ = v.BindEnv("agent.manager_agent.cmd_check_status", "ACS_GROUP_MANAGER_AGENT_CMD_CHECK_STATUS")
	_ = v.BindEnv("agent.manager_agent.api_base", "ACS_GROUP_MANAGER_AGENT_API_BASE")
	_ = v.BindEnv("agent.manager_agent.api_key", "ACS_GROUP_MANAGER_AGENT_API_KEY")
	_ = v.BindEnv("agent.manager_agent.api_auth", "ACS_GROUP_MANAGER_AGENT_API_AUTH")
	_ = v.BindEnv("agent.manager_agent.timeout_chat", "ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHAT")
	_ = v.BindEnv("agent.manager_agent.timeout_check_health", "ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_HEALTH")
	_ = v.BindEnv("agent.manager_agent.timeout_check_status", "ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_STATUS")

	// AgentWorkPool defaults
	v.SetDefault("agent_work_pool.per_node", 10)
	v.SetDefault("agent_work_pool.per_user", 5)
	v.SetDefault("agent_work_pool.per_group", 5)
	v.SetDefault("agent_work_pool.stats_log_interval", "30s")

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

	// Discovery defaults
	v.SetDefault("discovery.enabled", true)
	v.SetDefault("discovery.service_name", "acs")
	v.SetDefault("discovery.bucket_name", "acs_service_discovery")
	v.SetDefault("discovery.heartbeat", "30s")
	v.SetDefault("discovery.ttl", "120s")

	// Account defaults
	v.SetDefault("account.api_key_max_per_account", 10)
	v.SetDefault("account.login_session_expiry_seconds", 86400)
	v.SetDefault("account.bcrypt_cost", 10)

	// Bind account settings to the documented ACS_* env vars.
	_ = v.BindEnv("account.admin_api_key", "ACS_ACCOUNT_ADMIN_API_KEY")
	_ = v.BindEnv("account.manager_api_key", "ACS_ACCOUNT_MANAGER_API_KEY")
	_ = v.BindEnv("account.api_key_max_per_account", "ACS_API_KEY_MAX_PER_ACCOUNT")
	_ = v.BindEnv("account.login_session_expiry_seconds", "ACS_LOGIN_SESSION_EXPIRY_SECONDS")
	_ = v.BindEnv("account.bcrypt_cost", "ACS_BCRYPT_COST")
	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	// Apply database.name default based on driver when not explicitly set.
	if !nameExplicitlySet || cfg.Database.Name == "" {
		if cfg.Database.Driver == "sqlite" {
			home := os.Getenv("ACS_HOME")
			if home == "" {
				home = os.Getenv("TOPSAILAI_HOME")
			}
			if home == "" {
				home = "/topsailai"
			}
			cfg.Database.Name = filepath.Join(home, "agent_community.db")
		} else {
			cfg.Database.Name = "acs"
		}
	}

	// Validate and sanitize account configuration.
	if cfg.Account.APIKeyMaxPerAccount <= 0 {
		cfg.Account.APIKeyMaxPerAccount = 10
	}
	if cfg.Account.LoginSessionExpirySeconds <= 0 {
		cfg.Account.LoginSessionExpirySeconds = 86400
	}
	if cfg.Account.BcryptCost <= 0 {
		cfg.Account.BcryptCost = 10
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

// GetListenAddress returns the listen address for the server.
func (s *ServerConfig) GetListenAddress() string {
	return "0.0.0.0"
}
