// Package db provides database connection management and auto-migration for the ACS service.
package db

import (
	"sync"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
)

const cleanupModule = "cleanup"

// CleanupTask runs a periodic task to clean up old agent_message_processing records.
type CleanupTask struct {
	db       *gorm.DB
	cfg      config.CleanupConfig
	stopCh   chan struct{}
	stopOnce sync.Once
}

// NewCleanupTask creates a new cleanup task.
func NewCleanupTask(db *gorm.DB, cfg config.CleanupConfig) *CleanupTask {
	return &CleanupTask{
		db:     db,
		cfg:    cfg,
		stopCh: make(chan struct{}),
	}
}

// Start starts the cleanup periodic task.
func (c *CleanupTask) Start() {
	if !c.cfg.Enabled {
		logger.InfoM(cleanupModule, "", "cleanup task is disabled, skipping start")
		return
	}
	logger.InfoM(cleanupModule, "", "cleanup task started",
		"interval", c.cfg.Interval.String(),
		"retention_days", c.cfg.RetentionDays,
		"stale_pending_hours", c.cfg.StalePendingHours,
	)
	go c.run()
}

// Stop stops the cleanup periodic task.
func (c *CleanupTask) Stop() {
	c.stopOnce.Do(func() {
		close(c.stopCh)
		logger.InfoM(cleanupModule, "", "cleanup task stopped")
	})
}

// run is the main loop of the cleanup task.
func (c *CleanupTask) run() {
	ticker := time.NewTicker(c.cfg.Interval)
	defer ticker.Stop()

	// Run immediately on start
	c.doCleanup()

	for {
		select {
		case <-c.stopCh:
			return
		case <-ticker.C:
			c.doCleanup()
		}
	}
}

// doCleanup performs the actual cleanup of old agent_message_processing records.
func (c *CleanupTask) doCleanup() {
	traceID := uuid.New().String()
	start := time.Now()

	// 1. Delete terminal records (completed/failed) older than retention days.
	cutoffMs := time.Now().AddDate(0, 0, -c.cfg.RetentionDays).UnixMilli()
	result := c.db.Where("status IN ? AND create_at_ms < ?",
		[]string{models.ProcessingStatusCompleted, models.ProcessingStatusFailed},
		cutoffMs,
	).Delete(&models.AgentMessageProcessing{})
	if result.Error != nil {
		logger.ErrorM(cleanupModule, traceID, "failed to delete terminal processing records", "error", result.Error)
	} else {
		logger.InfoM(cleanupModule, traceID, "deleted terminal processing records",
			"retention_days", c.cfg.RetentionDays,
			"deleted_count", result.RowsAffected,
		)
	}

	// 2. Delete stale pending records older than stale_pending_hours.
	staleCutoffMs := time.Now().Add(-time.Duration(c.cfg.StalePendingHours) * time.Hour).UnixMilli()
	result = c.db.Where("status = ? AND create_at_ms < ?",
		models.ProcessingStatusPending,
		staleCutoffMs,
	).Delete(&models.AgentMessageProcessing{})
	if result.Error != nil {
		logger.ErrorM(cleanupModule, traceID, "failed to delete stale pending processing records", "error", result.Error)
	} else {
		logger.InfoM(cleanupModule, traceID, "deleted stale pending processing records",
			"stale_pending_hours", c.cfg.StalePendingHours,
			"deleted_count", result.RowsAffected,
		)
	}

	totalMs := time.Since(start).Milliseconds()
	logger.InfoM(cleanupModule, traceID, "cleanup run completed", "total_duration_ms", totalMs)
}
