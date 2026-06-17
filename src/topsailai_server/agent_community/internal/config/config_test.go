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
