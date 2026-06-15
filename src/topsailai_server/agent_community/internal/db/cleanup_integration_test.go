package db

import (
	"runtime"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
)

// ==================== 8.3 Integration-Style Tests ====================

// TestCleanup_Integration_RealDB verifies cleanup deletes old records and keeps fresh ones.
func TestCleanup_Integration_RealDB(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert 100 old terminal records
	for i := 0; i < 100; i++ {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(
			makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
		).Error)
	}
	// Insert 50 fresh records (within retention)
	for i := 0; i < 50; i++ {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(
			makeProcessingRecord(models.ProcessingStatusCompleted, 1*24*time.Hour),
		).Error)
	}
	require.Equal(t, int64(150), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})
	task.doCleanup()

	// 100 old terminal records should be deleted, 50 fresh remain
	assert.Equal(t, int64(50), countRecords(db))
}

// TestCleanup_Integration_Interval verifies cleanup runs on interval.
func TestCleanup_Integration_Interval(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert an old record
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
	defer task.Stop()

	// Wait for cleanup to execute (first immediate + ticker)
	assert.Eventually(t, func() bool {
		return countRecords(db) == 0
	}, 200*time.Millisecond, 20*time.Millisecond, "old record should be deleted by interval cleanup")
}

// TestCleanup_Integration_GracefulShutdown verifies no goroutine leak after stop.
func TestCleanup_Integration_GracefulShutdown(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Get baseline goroutine count
	baseline := runtime.NumGoroutine()

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          10 * time.Millisecond,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	task.Start()
	time.Sleep(50 * time.Millisecond)
	task.Stop()

	// Give goroutines time to exit
	time.Sleep(50 * time.Millisecond)

	// Allow some variance for runtime goroutines
	final := runtime.NumGoroutine()
	assert.LessOrEqual(t, final, baseline+2, "goroutine count should not leak significantly after Stop()")
}

// TestCleanup_Integration_LargeBatch verifies cleanup handles 1000+ records efficiently.
func TestCleanup_Integration_LargeBatch(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert 1000 old terminal records
	for i := 0; i < 1000; i++ {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(
			makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
		).Error)
	}
	require.Equal(t, int64(1000), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	start := time.Now()
	task.doCleanup()
	elapsed := time.Since(start)

	// All 1000 records should be deleted
	assert.Equal(t, int64(0), countRecords(db))
	// Should complete within 5 seconds even with 1000 records
	assert.Less(t, elapsed, 5*time.Second, "cleanup of 1000 records should complete within 5 seconds")
}

// TestCleanup_Integration_IndexUsage is a smoke test verifying DELETE performance with indexes.
func TestCleanup_Integration_IndexUsage(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert 500 old terminal records
	for i := 0; i < 500; i++ {
		require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(
			makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
		).Error)
	}
	require.Equal(t, int64(500), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           true,
		Interval:          time.Hour,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	// Use a timeout to ensure the query doesn't hang
	done := make(chan struct{})
	go func() {
		task.doCleanup()
		close(done)
	}()

	select {
	case <-done:
		// Success - query completed without timeout
		assert.Equal(t, int64(0), countRecords(db))
	case <-time.After(5 * time.Second):
		t.Fatal("cleanup query timed out - possible missing index")
	}
}

// TestCleanup_Integration_Disabled verifies no cleanup occurs when disabled.
func TestCleanup_Integration_Disabled(t *testing.T) {
	db := setupCleanupTestDB(t)

	// Insert an old record
	require.NoError(t, db.Session(&gorm.Session{SkipHooks: true}).Create(
		makeProcessingRecord(models.ProcessingStatusCompleted, 8*24*time.Hour),
	).Error)
	require.Equal(t, int64(1), countRecords(db))

	task := NewCleanupTask(db, config.CleanupConfig{
		Enabled:           false, // Disabled
		Interval:          50 * time.Millisecond,
		RetentionDays:     7,
		StalePendingHours: 240,
		BatchSize:         1000,
	})

	task.Start()
	time.Sleep(100 * time.Millisecond)
	task.Stop()

	// Record should still exist because cleanup is disabled
	assert.Equal(t, int64(1), countRecords(db))
}
