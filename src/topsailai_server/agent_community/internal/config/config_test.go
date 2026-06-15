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
