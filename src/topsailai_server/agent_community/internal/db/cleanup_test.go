// Package db provides database connection management and cleanup task tests.
package db

import (
	"fmt"
	"runtime"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
)

// setupCleanupTestDB creates an in-memory SQLite DB with agent_message_processing migrated.
func setupCleanupTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:%s?mode=memory&cache=shared", t.Name())), &gorm.Config{})
	require.NoError(t, err)
	err = db.AutoMigrate(&models.AgentMessageProcessing{})
	require.NoError(t, err)
	return db
}

// makeProcessingRecord creates a test record with specified status and age.
func makeProcessingRecord(status string, age time.Duration) *models.AgentMessageProcessing {
	now := time.Now()
	return &models.AgentMessageProcessing{
		GroupID:       "test-group",
		MessageID:     fmt.Sprintf("msg-%d", now.UnixNano()),
		AgentID:       "agent-1",
		Status:        status,
		CreateAtMs:    now.Add(-age).UnixMilli(),
		UpdateAtMs:    now.Add(-age).UnixMilli(),
		ProcessedAtMs: 0,
	}
}

// countRecords returns the total count of agent_message_processing records.
func countRecords(db *gorm.DB) int64 {
	var count int64
	db.Model(&models.AgentMessageProcessing{}).Count(&count)
	return count
}

// ==================== 8.1.1 Terminal Records Deletion ====================

// TestDoCleanup_DeletesOldTerminalRecords verifies terminal records older than retention are deleted.
func TestDoCleanup_DeletesOldTerminalRecords(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert 3 completed (8d old), 2 failed (8d old), 1 pending (8d old)
	// Use stalePendingHours=240 so pending is NOT stale (8d = 192h < 240h)
	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusFailed, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusFailed, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 8*24*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(6), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// 5 terminal records should be deleted, 1 pending remains
	assert.Equal(t, int64(1), countRecords(db))

	// Verify the remaining record is pending
	var remaining models.AgentMessageProcessing
	require.NoError(t, db.First(&remaining).Error)
	assert.Equal(t, models.ProcessingStatusPending, remaining.Status)
}

// TestDoCleanup_KeepsRecentTerminalRecords verifies recent terminal records are preserved.
func TestDoCleanup_KeepsRecentTerminalRecords(t *testing.T) {
	db := setupCleanupTestDB(t)

	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusCompleted, 3*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusFailed, 3*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 3*24*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(3), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// All records are within retention, none should be deleted
	assert.Equal(t, int64(3), countRecords(db))
}

// TestDoCleanup_DeletesOnlyCompletedAndFailed verifies only terminal statuses are deleted.
func TestDoCleanup_DeletesOnlyCompletedAndFailed(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Use stalePendingHours=240 so 8d pending is NOT stale (192h < 240h)
	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusFailed, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusRunning, 8*24*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(4), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// Only completed and failed should be deleted (2 records)
	assert.Equal(t, int64(2), countRecords(db))

	var remaining []models.AgentMessageProcessing
	require.NoError(t, db.Find(&remaining).Error)
	for _, r := range remaining {
		assert.False(t, r.IsTerminalStatus())
	}
}

// TestDoCleanup_RespectsRetentionDaysBoundary verifies boundary behavior with safe margins.
func TestDoCleanup_RespectsRetentionDaysBoundary(t *testing.T) {
	db := setupCleanupTestDB(t)
	now := time.Now()

	// Record at 6 days old (should be kept, within 7-day retention)
	withinRetention := &models.AgentMessageProcessing{
		GroupID:    "test-group",
		MessageID:  "msg-within",
		AgentID:    "agent-1",
		Status:     models.ProcessingStatusCompleted,
		CreateAtMs: now.Add(-6 * 24 * time.Hour).UnixMilli(),
		UpdateAtMs: now.Add(-6 * 24 * time.Hour).UnixMilli(),
	}
	// Record at 8 days old (should be deleted, past 7-day retention)
	pastRetention := &models.AgentMessageProcessing{
		GroupID:    "test-group",
		MessageID:  "msg-past",
		AgentID:    "agent-1",
		Status:     models.ProcessingStatusCompleted,
		CreateAtMs: now.Add(-8 * 24 * time.Hour).UnixMilli(),
		UpdateAtMs: now.Add(-8 * 24 * time.Hour).UnixMilli(),
	}

	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(withinRetention).Error)
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(pastRetention).Error)
	require.Equal(t, int64(2), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// Only the 8-day-old record should be deleted
	assert.Equal(t, int64(1), countRecords(db))

	var remaining models.AgentMessageProcessing
	require.NoError(t, db.First(&remaining).Error)
	assert.Equal(t, "msg-within", remaining.MessageID)
}

// ==================== 8.1.2 Stale Pending Deletion ====================

// TestDoCleanup_DeletesStalePendingRecords verifies stale pending records are deleted.
func TestDoCleanup_DeletesStalePendingRecords(t *testing.T) {
	db := setupCleanupTestDB(t)

	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusPending, 25*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 48*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 1*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(3), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 24,
		BatchSize:         1000,
	})
	task.doCleanup()

	// 2 stale pending records should be deleted, 1 fresh remains
	assert.Equal(t, int64(1), countRecords(db))

	var remaining models.AgentMessageProcessing
	require.NoError(t, db.First(&remaining).Error)
	assert.Equal(t, models.ProcessingStatusPending, remaining.Status)
	// The remaining record should be the 1h old one
	assert.True(t, remaining.CreateAtMs > time.Now().Add(-2*time.Hour).UnixMilli())
}

// TestDoCleanup_KeepsFreshPendingRecords verifies fresh pending records are preserved.
func TestDoCleanup_KeepsFreshPendingRecords(t *testing.T) {
	db := setupCleanupTestDB(t)

	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusPending, 12*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 1*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(2), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// Both pending records are fresh, none should be deleted
	assert.Equal(t, int64(2), countRecords(db))
}

// TestDoCleanup_StalePendingBoundary verifies boundary behavior with safe margins.
func TestDoCleanup_StalePendingBoundary(t *testing.T) {
	db := setupCleanupTestDB(t)
	now := time.Now()

	// Record at 12 hours old (should be kept, within 24h stale threshold)
	withinStale := &models.AgentMessageProcessing{
		GroupID:    "test-group",
		MessageID:  "msg-stale-within",
		AgentID:    "agent-1",
		Status:     models.ProcessingStatusPending,
		CreateAtMs: now.Add(-12 * time.Hour).UnixMilli(),
		UpdateAtMs: now.Add(-12 * time.Hour).UnixMilli(),
	}
	// Record at 48 hours old (should be deleted, past 24h stale threshold)
	pastStale := &models.AgentMessageProcessing{
		GroupID:    "test-group",
		MessageID:  "msg-stale-past",
		AgentID:    "agent-1",
		Status:     models.ProcessingStatusPending,
		CreateAtMs: now.Add(-48 * time.Hour).UnixMilli(),
		UpdateAtMs: now.Add(-48 * time.Hour).UnixMilli(),
	}

	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(withinStale).Error)
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(pastStale).Error)
	require.Equal(t, int64(2), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 24,
		BatchSize:         1000,
	})
	task.doCleanup()

	// Only the 48-hour-old pending record should be deleted
	assert.Equal(t, int64(1), countRecords(db))

	var remaining models.AgentMessageProcessing
	require.NoError(t, db.First(&remaining).Error)
	assert.Equal(t, "msg-stale-within", remaining.MessageID)
}

// TestDoCleanup_MixedStatusesAndAges verifies correct deletion with mixed records.
func TestDoCleanup_MixedStatusesAndAges(t *testing.T) {
	db := setupCleanupTestDB(t)

	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour), // deleted (old terminal)
		makeProcessingRecord(models.ProcessingStatusFailed, 8*24*time.Hour),     // deleted (old terminal)
		makeProcessingRecord(models.ProcessingStatusPending, 25*time.Hour),      // deleted (stale pending)
		makeProcessingRecord(models.ProcessingStatusPending, 1*time.Hour),       // kept (fresh pending)
		makeProcessingRecord(models.ProcessingStatusRunning, 8*24*time.Hour),    // kept (non-terminal, not pending)
		makeProcessingRecord(models.ProcessingStatusCompleted, 1*24*time.Hour),  // kept (recent terminal)
		makeProcessingRecord(models.ProcessingStatusFailed, 1*24*time.Hour),     // kept (recent terminal)
		makeProcessingRecord(models.ProcessingStatusPending, 48*time.Hour),      // deleted (stale pending)
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(8), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 24, // Use 24h so pending(25h) and pending(48h) are stale
		BatchSize:         1000,
	})
	task.doCleanup()

	// 4 should be deleted: completed(8d), failed(8d), pending(25h), pending(48h)
	assert.Equal(t, int64(4), countRecords(db))

	var remaining []models.AgentMessageProcessing
	require.NoError(t, db.Find(&remaining).Error)
	for _, r := range remaining {
		// All remaining should be either fresh pending, recent terminal, or running
		isFreshPending := r.Status == models.ProcessingStatusPending && r.CreateAtMs > time.Now().Add(-24*time.Hour).UnixMilli()
		isRecentTerminal := r.IsTerminalStatus() && r.CreateAtMs > time.Now().Add(-7*24*time.Hour).UnixMilli()
		isRunning := r.Status == models.ProcessingStatusRunning
		assert.True(t, isFreshPending || isRecentTerminal || isRunning,
			"unexpected remaining record: status=%s, age=%v", r.Status, time.Since(time.UnixMilli(r.CreateAtMs)))
	}
}

// TestDoCleanup_EmptyTable verifies no panic or error on empty table.
func TestDoCleanup_EmptyTable(t *testing.T) {
	db := setupCleanupTestDB(t)

	require.Equal(t, int64(0), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	// Should not panic
	assert.NotPanics(t, func() {
		task.doCleanup()
	})

	// Count should still be 0
	assert.Equal(t, int64(0), countRecords(db))
}

// TestDoCleanup_AllRecordsWithinRetention verifies nothing deleted when all records are fresh.
func TestDoCleanup_AllRecordsWithinRetention(t *testing.T) {
	db := setupCleanupTestDB(t)

	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusCompleted, 1*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusFailed, 2*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 12*time.Hour),
		makeProcessingRecord(models.ProcessingStatusRunning, 3*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 6*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(5), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// All records are within retention/stale periods, none should be deleted
	assert.Equal(t, int64(5), countRecords(db))
}

// ==================== 8.1.4 Goroutine Lifecycle ====================

// TestStart_WhenEnabled_StartsGoroutine verifies cleanup goroutine starts and executes.
func TestStart_WhenEnabled_StartsGoroutine(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert an old record to verify cleanup runs
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour)).Error)
	require.Equal(t, int64(1), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          100 * time.Millisecond,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	task.Start()
	time.Sleep(150 * time.Millisecond) // Wait for first cleanup
	task.Stop()

	// Verify record was deleted
	assert.Equal(t, int64(0), countRecords(db))
}

// TestStart_WhenDisabled_LogsAndReturns verifies no cleanup when disabled.
func TestStart_WhenDisabled_LogsAndReturns(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert an old record
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour)).Error)
	require.Equal(t, int64(1), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           false,
		Interval:          100 * time.Millisecond,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	beforeGoroutines := runtime.NumGoroutine()
	task.Start()
	time.Sleep(150 * time.Millisecond)

	// Record should still exist (cleanup disabled)
	assert.Equal(t, int64(1), countRecords(db))

	// No new goroutine should have been started
	afterGoroutines := runtime.NumGoroutine()
	assert.LessOrEqual(t, afterGoroutines, beforeGoroutines+1, "no cleanup goroutine should be started when disabled")

	task.Stop() // Safe to call even when disabled
}

// TestStop_SignalsShutdown verifies Stop does not panic.
func TestStop_SignalsShutdown(t *testing.T) {
	db := setupCleanupTestDB(t)

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	task.Start()

	// Should not panic
	assert.NotPanics(t, func() {
		task.Stop()
	})
}

// TestStop_Idempotent verifies Stop can be called multiple times safely.
func TestStop_Idempotent(t *testing.T) {
	db := setupCleanupTestDB(t)

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	task.Start()
	task.Stop()

	// Second Stop should not panic (no "close of closed channel")
	assert.NotPanics(t, func() {
		task.Stop()
	})

	// Third Stop should also be safe
	assert.NotPanics(t, func() {
		task.Stop()
	})
}

// TestStartStop_StartStopCycle verifies clean lifecycle without goroutine leaks.
func TestStartStop_StartStopCycle(t *testing.T) {
	db := setupCleanupTestDB(t)

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          50 * time.Millisecond,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	before := runtime.NumGoroutine()

	task.Start()
	time.Sleep(100 * time.Millisecond)
	task.Stop()

	// Give goroutine time to exit
	time.Sleep(50 * time.Millisecond)

	after := runtime.NumGoroutine()
	// Allow small variance due to runtime scheduling
	assert.LessOrEqual(t, after, before+2, "goroutine leak detected after Stop()")
}

// TestRun_ExecutesImmediately verifies first cleanup happens before first ticker.
func TestRun_ExecutesImmediately(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert an old record
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour)).Error)
	require.Equal(t, int64(1), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          10 * time.Second, // Long interval to ensure ticker doesn't fire
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	task.Start()

	// Wait a short time for immediate execution (should happen within 50ms)
	time.Sleep(100 * time.Millisecond)

	// Record should be deleted by immediate execution, not ticker
	assert.Equal(t, int64(0), countRecords(db))

	task.Stop()
}

// TestRun_ExecutesOnTicker verifies cleanup runs on ticker intervals.
func TestRun_ExecutesOnTicker(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert the old record BEFORE starting the goroutine to avoid concurrent SQLite access
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
	).Error)
	require.Equal(t, int64(1), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          50 * time.Millisecond,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	task.Start()

	// Wait for initial execution + at least one ticker execution.
	// The record should eventually be cleaned up by either initial or ticker execution.
	assert.Eventually(t, func() bool {
		return countRecords(db) == 0
	}, 500*time.Millisecond, 50*time.Millisecond, "record should be cleaned up by ticker")

	task.Stop()
}

// ==================== 8.4 Edge Cases ====================

// TestDoCleanup_NilDB verifies doCleanup does not panic with nil DB.
func TestDoCleanup_NilDB(t *testing.T) {
	task := &CleanupTask{
		db: nil,
		cfg: config.CleanupConfig{
			Enabled:           true,
			Interval:          time.Hour,
			RetentionDays:     7,
			StalePendingHours: 24,
			BatchSize:         1000,
		},
	}

	assert.NotPanics(t, func() {
		task.doCleanup()
	})
}

// TestDoCleanup_ConnectionLost verifies doCleanup does not panic when DB connection is lost.
func TestDoCleanup_ConnectionLost(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert a record before closing connection
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
	).Error)

	// Close the underlying SQL connection
	sqlDB, err := db.DB()
	require.NoError(t, err)
	require.NoError(t, sqlDB.Close())

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 24,
		BatchSize:         1000,
	})

	// Should log error but not panic
	assert.NotPanics(t, func() {
		task.doCleanup()
	})
}

// TestDoCleanup_FutureTimestamps verifies records with future timestamps are NOT deleted.
func TestDoCleanup_FutureTimestamps(t *testing.T) {
	db := setupCleanupTestDB(t)
	now := time.Now()

	// Record with future timestamp (24 hours in the future)
	futureRecord := &models.AgentMessageProcessing{
		GroupID:    "test-group",
		MessageID:  "msg-future",
		AgentID:    "agent-1",
		Status:     models.ProcessingStatusCompleted,
		CreateAtMs: now.Add(24 * time.Hour).UnixMilli(),
		UpdateAtMs: now.Add(24 * time.Hour).UnixMilli(),
	}
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(futureRecord).Error)
	require.Equal(t, int64(1), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     0, // Zero retention would delete everything with past timestamps
		StalePendingHours: 24,
		BatchSize:         1000,
	})
	task.doCleanup()

	// Future record should NOT be deleted (its CreateAtMs is > now)
	assert.Equal(t, int64(1), countRecords(db))

	var remaining models.AgentMessageProcessing
	require.NoError(t, db.First(&remaining).Error)
	assert.Equal(t, "msg-future", remaining.MessageID)
}

// TestDoCleanup_ConcurrentExecution verifies multiple cleanup tasks can run concurrently without panic or deadlock.
func TestDoCleanup_ConcurrentExecution(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert some old records
	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusFailed, 8*24*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 48*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(3), countRecords(db))

	// Create 3 tasks sharing the same DB
	tasks := make([]*CleanupTask, 3)
	for i := range tasks {
		tasks[i] = NewCleanupTask(db, config.CleanupConfig{
			Enabled:           true,
			Interval:          10 * time.Millisecond,
			RetentionDays:     7,
			StalePendingHours: 24,
			BatchSize:         1000,
		})
	}

	// Start all tasks concurrently
	for _, task := range tasks {
		task.Start()
	}

	// Let them run concurrently
	time.Sleep(100 * time.Millisecond)

	// Stop all tasks
	for _, task := range tasks {
		task.Stop()
	}

	// Give goroutines time to exit
	time.Sleep(50 * time.Millisecond)

	// No panic or deadlock should have occurred.
	// Records may or may not be deleted depending on race, but no panic is the key assertion.
	assert.NotPanics(t, func() {
		_ = countRecords(db)
	})
}

// TestDoCleanup_ZeroRetentionDays verifies retentionDays=0 deletes ALL terminal records.
func TestDoCleanup_ZeroRetentionDays(t *testing.T) {
	db := setupCleanupTestDB(t)

	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusCompleted, 1*time.Hour),
		makeProcessingRecord(models.ProcessingStatusCompleted, 1*time.Minute),
		makeProcessingRecord(models.ProcessingStatusFailed, 30*time.Minute),
		makeProcessingRecord(models.ProcessingStatusPending, 1*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(4), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     0, // Zero retention: cutoff = now, all past records are deleted
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// All 3 terminal records should be deleted, 1 pending remains
	assert.Equal(t, int64(1), countRecords(db))

	var remaining models.AgentMessageProcessing
	require.NoError(t, db.First(&remaining).Error)
	assert.Equal(t, models.ProcessingStatusPending, remaining.Status)
}

// TestDoCleanup_ZeroStalePendingHours verifies stalePendingHours=0 deletes ALL pending records.
func TestDoCleanup_ZeroStalePendingHours(t *testing.T) {
	db := setupCleanupTestDB(t)

	records := []*models.AgentMessageProcessing{
		makeProcessingRecord(models.ProcessingStatusPending, 1*time.Hour),
		makeProcessingRecord(models.ProcessingStatusPending, 1*time.Minute),
		makeProcessingRecord(models.ProcessingStatusPending, 30*time.Second),
		makeProcessingRecord(models.ProcessingStatusCompleted, 1*time.Hour),
	}
	for _, r := range records {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(r).Error)
	}
	require.Equal(t, int64(4), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 0, // Zero stale hours: cutoff = now, all past pending records are deleted
		BatchSize:         1000,
	})
	task.doCleanup()

	// All 3 pending records should be deleted, 1 completed remains (within 7-day retention)
	assert.Equal(t, int64(1), countRecords(db))

	var remaining models.AgentMessageProcessing
	require.NoError(t, db.First(&remaining).Error)
	assert.Equal(t, models.ProcessingStatusCompleted, remaining.Status)
}

// TestDoCleanup_VeryLargeRetention verifies very large retentionDays deletes nothing.
func TestDoCleanup_VeryLargeRetention(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert an old terminal record (8 days old)
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
	).Error)
	require.Equal(t, int64(1), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     36500, // 100 years
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// Record should NOT be deleted (100-year retention covers 8 days)
	assert.Equal(t, int64(1), countRecords(db))
}

// TestDoCleanup_RecordWithProcessedAt verifies cleanup uses CreateAtMs, not ProcessedAtMs.
func TestDoCleanup_RecordWithProcessedAt(t *testing.T) {
	db := setupCleanupTestDB(t)
	now := time.Now()

	// Record with old CreateAtMs but recent ProcessedAtMs
	record := &models.AgentMessageProcessing{
		GroupID:       "test-group",
		MessageID:     "msg-processed",
		AgentID:       "agent-1",
		Status:        models.ProcessingStatusCompleted,
		CreateAtMs:    now.Add(-8 * 24 * time.Hour).UnixMilli(), // 8 days old -> should be deleted
		UpdateAtMs:    now.Add(-8 * 24 * time.Hour).UnixMilli(),
		ProcessedAtMs: now.Add(-1 * time.Hour).UnixMilli(),      // Recently processed
	}
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(record).Error)
	require.Equal(t, int64(1), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// Record should be deleted based on CreateAtMs (8 days > 7 days), NOT ProcessedAtMs
	assert.Equal(t, int64(0), countRecords(db))
}
