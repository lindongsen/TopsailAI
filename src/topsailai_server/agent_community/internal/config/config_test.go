// Package config provides centralized configuration management tests.
package config

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// TestCleanupConfig_Defaults verifies default cleanup configuration values.
func TestCleanupConfig_Defaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.True(t, cfg.Cleanup.Enabled)
	assert.Equal(t, time.Hour, cfg.Cleanup.Interval)
	assert.Equal(t, 7, cfg.Cleanup.RetentionDays)
	assert.Equal(t, 24, cfg.Cleanup.StalePendingHours)
	assert.Equal(t, 1000, cfg.Cleanup.BatchSize)
}

// TestCleanupConfig_EnabledOverride verifies ACS_CLEANUP_ENABLED env var override.
func TestCleanupConfig_EnabledOverride(t *testing.T) {
	t.Setenv("ACS_CLEANUP_ENABLED", "false")
	cfg, err := Load()
	require.NoError(t, err)
	assert.False(t, cfg.Cleanup.Enabled)
}

// TestCleanupConfig_IntervalOverride verifies ACS_CLEANUP_INTERVAL env var override.
func TestCleanupConfig_IntervalOverride(t *testing.T) {
	t.Setenv("ACS_CLEANUP_INTERVAL", "30m")
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 30*time.Minute, cfg.Cleanup.Interval)
}

// TestCleanupConfig_RetentionDaysOverride verifies ACS_CLEANUP_RETENTION_DAYS env var override.
func TestCleanupConfig_RetentionDaysOverride(t *testing.T) {
	t.Setenv("ACS_CLEANUP_RETENTION_DAYS", "14")
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 14, cfg.Cleanup.RetentionDays)
}

// TestCleanupConfig_StalePendingHoursOverride verifies ACS_CLEANUP_STALE_PENDING_HOURS env var override.
func TestCleanupConfig_StalePendingHoursOverride(t *testing.T) {
	t.Setenv("ACS_CLEANUP_STALE_PENDING_HOURS", "48")
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 48, cfg.Cleanup.StalePendingHours)
}

// TestCleanupConfig_BatchSizeOverride verifies ACS_CLEANUP_BATCH_SIZE env var override.
func TestCleanupConfig_BatchSizeOverride(t *testing.T) {
	t.Setenv("ACS_CLEANUP_BATCH_SIZE", "500")
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 500, cfg.Cleanup.BatchSize)
}

// TestCleanupConfig_ZeroRetention verifies zero retention days is accepted.
func TestCleanupConfig_ZeroRetention(t *testing.T) {
	t.Setenv("ACS_CLEANUP_RETENTION_DAYS", "0")
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 0, cfg.Cleanup.RetentionDays)
}

// TestCleanupConfig_NegativeRetention verifies negative retention days is accepted (parsed as int).
func TestCleanupConfig_NegativeRetention(t *testing.T) {
	t.Setenv("ACS_CLEANUP_RETENTION_DAYS", "-1")
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, -1, cfg.Cleanup.RetentionDays)
}

// TestManagerAgentConfig_Defaults verifies default manager-agent auto-join values.
func TestManagerAgentConfig_Defaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "manager-agent", cfg.Agent.ManagerAgent.MemberID)
	assert.Equal(t, "manager-agent", cfg.Agent.ManagerAgent.MemberName)
	assert.Equal(t, "Default group manager agent", cfg.Agent.ManagerAgent.MemberDescription)
	assert.Equal(t, "topsailai_agent", cfg.Agent.ManagerAgent.Adaptor)
	assert.Equal(t, "", cfg.Agent.ManagerAgent.CmdChat)
	assert.Equal(t, "", cfg.Agent.ManagerAgent.CmdCheckHealth)
	assert.Equal(t, "", cfg.Agent.ManagerAgent.CmdCheckStatus)
	assert.Equal(t, "", cfg.Agent.ManagerAgent.APIBase)
	assert.Equal(t, "", cfg.Agent.ManagerAgent.APIKey)
	assert.Equal(t, "bearer", cfg.Agent.ManagerAgent.APIAuth)
	assert.Equal(t, 600*time.Second, cfg.Agent.ManagerAgent.TimeoutChat)
	assert.Equal(t, 5*time.Second, cfg.Agent.ManagerAgent.TimeoutCheckHealth)
	assert.Equal(t, 5*time.Second, cfg.Agent.ManagerAgent.TimeoutCheckStatus)
}

// TestManagerAgentConfig_Override verifies manager-agent env var overrides.
func TestManagerAgentConfig_Override(t *testing.T) {
	t.Setenv("ACS_GROUP_MANAGER_AGENT_CMD_CHAT", "my_cmd_chat")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH", "my_cmd_check_health")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_CMD_CHECK_STATUS", "my_cmd_check_status")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_API_BASE", "http://manager.example.com")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_API_KEY", "manager-key")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_API_AUTH", "token")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHAT", "120s")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_HEALTH", "10s")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_STATUS", "15s")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_MEMBER_ID", "custom-manager")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_MEMBER_NAME", "Custom Manager")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_MEMBER_DESCRIPTION", "Custom description")
	t.Setenv("ACS_GROUP_MANAGER_AGENT_ADAPTOR", "custom_adaptor")

	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "my_cmd_chat", cfg.Agent.ManagerAgent.CmdChat)
	assert.Equal(t, "my_cmd_check_health", cfg.Agent.ManagerAgent.CmdCheckHealth)
	assert.Equal(t, "my_cmd_check_status", cfg.Agent.ManagerAgent.CmdCheckStatus)
	assert.Equal(t, "http://manager.example.com", cfg.Agent.ManagerAgent.APIBase)
	assert.Equal(t, "manager-key", cfg.Agent.ManagerAgent.APIKey)
	assert.Equal(t, "token", cfg.Agent.ManagerAgent.APIAuth)
	assert.Equal(t, 120*time.Second, cfg.Agent.ManagerAgent.TimeoutChat)
	assert.Equal(t, 10*time.Second, cfg.Agent.ManagerAgent.TimeoutCheckHealth)
	assert.Equal(t, 15*time.Second, cfg.Agent.ManagerAgent.TimeoutCheckStatus)
	assert.Equal(t, "custom-manager", cfg.Agent.ManagerAgent.MemberID)
	assert.Equal(t, "Custom Manager", cfg.Agent.ManagerAgent.MemberName)
	assert.Equal(t, "Custom description", cfg.Agent.ManagerAgent.MemberDescription)
	assert.Equal(t, "custom_adaptor", cfg.Agent.ManagerAgent.Adaptor)
}

// TestLoad_ServerDefaults verifies default server configuration values.
func TestLoad_ServerDefaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "", cfg.Server.Host)
	assert.Equal(t, 7370, cfg.Server.Port)
	assert.Equal(t, 30*time.Second, cfg.Server.ReadTimeout)
	assert.Equal(t, 30*time.Second, cfg.Server.WriteTimeout)
}

// TestLoad_ServerEnvOverrides verifies server env var overrides.
func TestLoad_ServerEnvOverrides(t *testing.T) {
	t.Setenv("ACS_HTTP_PORT", "8080")
	t.Setenv("ACS_HTTP_HOST", "127.0.0.1")
	t.Setenv("ACS_SERVER_READ_TIMEOUT", "45s")
	t.Setenv("ACS_SERVER_WRITE_TIMEOUT", "60s")

	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "127.0.0.1", cfg.Server.Host)
	assert.Equal(t, 8080, cfg.Server.Port)
	assert.Equal(t, 45*time.Second, cfg.Server.ReadTimeout)
	assert.Equal(t, 60*time.Second, cfg.Server.WriteTimeout)
}

// TestLoad_DatabaseDefaults verifies default database configuration values.
func TestLoad_DatabaseDefaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "postgres", cfg.Database.Driver)
	assert.Equal(t, "localhost", cfg.Database.Host)
	assert.Equal(t, 5432, cfg.Database.Port)
	assert.Equal(t, "acs", cfg.Database.User)
	assert.Equal(t, "acs", cfg.Database.Password)
	assert.Equal(t, "acs", cfg.Database.Name)
	assert.Equal(t, "disable", cfg.Database.SSLMode)
}

// TestLoad_DatabaseNameExplicitlySet verifies ACS_DATABASE_NAME is honored when set.
func TestLoad_DatabaseNameExplicitlySet(t *testing.T) {
	t.Setenv("ACS_DATABASE_NAME", "custom_db")

	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "custom_db", cfg.Database.Name)
}

// TestLoad_NATSDefaults verifies default NATS configuration values.
func TestLoad_NATSDefaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "nats://localhost:4222", cfg.NATS.Servers)
	assert.Equal(t, "acs_group", cfg.NATS.StreamGroup)
	assert.Equal(t, "acs.group.pending-message", cfg.NATS.SubjectGroupPendingMessagePrefix)
	assert.Equal(t, "acs.group.message", cfg.NATS.SubjectGroupMessagePrefix)
	assert.False(t, cfg.NATS.PendingMessageNoAck)
	assert.Equal(t, 3600, cfg.NATS.AckWaitSeconds)
	assert.Equal(t, 10, cfg.NATS.MaxAckPending)
	assert.Equal(t, 0, cfg.NATS.MaxDeliver)
}

// TestLoad_NATSEnvOverrides verifies NATS env var overrides.
func TestLoad_NATSEnvOverrides(t *testing.T) {
	t.Setenv("ACS_NATS_SERVERS", "nats://n1.example.com:4222,nats://n2.example.com:4222")
	t.Setenv("ACS_NATS_STREAM_GROUP", "custom_group")
	t.Setenv("ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX", "custom.pending")
	t.Setenv("ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX", "custom.message")
	t.Setenv("ACS_NATS_PENDING_MESSAGE_NO_ACK", "true")
	t.Setenv("ACS_NATS_ACK_WAIT_SECONDS", "7200")
	t.Setenv("ACS_NATS_MAX_ACK_PENDING", "20")
	t.Setenv("ACS_NATS_MAX_DELIVER", "5")

	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "nats://n1.example.com:4222,nats://n2.example.com:4222", cfg.NATS.Servers)
	assert.Equal(t, "custom_group", cfg.NATS.StreamGroup)
	assert.Equal(t, "custom.pending", cfg.NATS.SubjectGroupPendingMessagePrefix)
	assert.Equal(t, "custom.message", cfg.NATS.SubjectGroupMessagePrefix)
	assert.True(t, cfg.NATS.PendingMessageNoAck)
	assert.Equal(t, 7200, cfg.NATS.AckWaitSeconds)
	assert.Equal(t, 20, cfg.NATS.MaxAckPending)
	assert.Equal(t, 5, cfg.NATS.MaxDeliver)
}

// TestLoad_AgentWorkPoolDefaults verifies default AgentWorkPool configuration values.
func TestLoad_AgentWorkPoolDefaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 10, cfg.AgentWorkPool.PerNode)
	assert.Equal(t, 5, cfg.AgentWorkPool.PerUser)
	assert.Equal(t, 5, cfg.AgentWorkPool.PerGroup)
	assert.Equal(t, 30*time.Second, cfg.AgentWorkPool.StatsLogInterval)
}

// TestLoad_AgentWorkPoolEnvOverrides verifies AgentWorkPool env var overrides.
func TestLoad_AgentWorkPoolEnvOverrides(t *testing.T) {
	t.Setenv("ACS_AGENT_WORK_POOL_PER_NODE", "20")
	t.Setenv("ACS_AGENT_WORK_POOL_PER_USER", "3")
	t.Setenv("ACS_AGENT_WORK_POOL_PER_GROUP", "1")
	t.Setenv("ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT", "45s")

	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 20, cfg.AgentWorkPool.PerNode)
	assert.Equal(t, 3, cfg.AgentWorkPool.PerUser)
	assert.Equal(t, 1, cfg.AgentWorkPool.PerGroup)
	assert.Equal(t, 45*time.Second, cfg.AgentWorkPool.AcquireTimeout)
}

// TestLoad_LogDefaults verifies default log configuration values.
func TestLoad_LogDefaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "stdout", cfg.Log.Output)
	assert.Equal(t, "info", cfg.Log.Level)
	assert.Equal(t, "/var/log/acs/acs.log", cfg.Log.FilePath)
	assert.Equal(t, 100, cfg.Log.MaxSize)
	assert.Equal(t, 30, cfg.Log.MaxAge)
	assert.Equal(t, 10, cfg.Log.MaxBackups)
}

// TestLoad_DiscoveryDefaults verifies default service discovery configuration values.
func TestLoad_DiscoveryDefaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.True(t, cfg.Discovery.Enabled)
	assert.Equal(t, "acs", cfg.Discovery.ServiceName)
	assert.Equal(t, "acs_service_discovery", cfg.Discovery.BucketName)
	assert.Equal(t, 30*time.Second, cfg.Discovery.Heartbeat)
	assert.Equal(t, 120*time.Second, cfg.Discovery.TTL)
}

// TestLoad_AccountDefaults verifies default account configuration values.
func TestLoad_AccountDefaults(t *testing.T) {
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "", cfg.Account.AdminAPIKey)
	assert.Equal(t, "", cfg.Account.ManagerAPIKey)
	assert.Equal(t, 10, cfg.Account.APIKeyMaxPerAccount)
	assert.Equal(t, 86400, cfg.Account.LoginSessionExpirySeconds)
	assert.Equal(t, 10, cfg.Account.BcryptCost)
}

// TestLoad_AccountSanitization verifies invalid/zero account config values fall back to defaults.
func TestLoad_AccountSanitization(t *testing.T) {
	t.Setenv("ACS_API_KEY_MAX_PER_ACCOUNT", "0")
	t.Setenv("ACS_LOGIN_SESSION_EXPIRY_SECONDS", "-1")
	t.Setenv("ACS_BCRYPT_COST", "-5")

	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 10, cfg.Account.APIKeyMaxPerAccount)
	assert.Equal(t, 86400, cfg.Account.LoginSessionExpirySeconds)
	assert.Equal(t, 10, cfg.Account.BcryptCost)
}

// TestDatabaseConfig_DSN verifies the PostgreSQL DSN format.
func TestDatabaseConfig_DSN(t *testing.T) {
	d := DatabaseConfig{
		Host:     "db.example.com",
		Port:     5433,
		User:     "user",
		Password: "pass",
		Name:     "mydb",
		SSLMode:  "require",
	}
	expected := "host=db.example.com port=5433 user=user password=pass dbname=mydb sslmode=require"
	assert.Equal(t, expected, d.DSN())
}

// TestServerConfig_GetListenAddress verifies GetListenAddress behavior.
func TestServerConfig_GetListenAddress(t *testing.T) {
	assert.Equal(t, "0.0.0.0", (&ServerConfig{}).GetListenAddress())
	assert.Equal(t, "127.0.0.1", (&ServerConfig{Host: "127.0.0.1"}).GetListenAddress())
	assert.Equal(t, "0.0.0.0", (&ServerConfig{Host: ""}).GetListenAddress())
}

// TestServerConfig_HostOverride verifies ACS_HTTP_HOST env var override.
func TestServerConfig_HostOverride(t *testing.T) {
	t.Setenv("ACS_HTTP_HOST", "127.1.0.1")
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, "127.1.0.1", cfg.Server.Host)
	assert.Equal(t, "127.1.0.1", cfg.Server.GetListenAddress())
}

// TestServerConfig_PortOverride verifies ACS_HTTP_PORT env var override.
func TestServerConfig_PortOverride(t *testing.T) {
	t.Setenv("ACS_HTTP_PORT", "8080")
	cfg, err := Load()
	require.NoError(t, err)
	assert.Equal(t, 8080, cfg.Server.Port)
}
