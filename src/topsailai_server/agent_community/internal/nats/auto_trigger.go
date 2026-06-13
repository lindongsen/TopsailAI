// Package nats provides NATS integration for the ACS service.
package nats

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/lock"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
)

const autoTriggerModule = "auto_trigger"

// AutoTrigger runs a periodic task to check for timeout-based auto-triggers.
type AutoTrigger struct {
	db             *gorm.DB
	js             nats.JetStreamContext
	publisher      *Publisher
	evaluator      *trigger.Evaluator
	lockManager    *lock.DistributedLock
	interval       time.Duration
	timeout        time.Duration
	stopCh         chan struct{}
	stopOnce       sync.Once
}

// NewAutoTrigger creates a new auto-trigger periodic task.
func NewAutoTrigger(
	db *gorm.DB,
	js nats.JetStreamContext,
	publisher *Publisher,
	evaluator *trigger.Evaluator,
	lockManager *lock.DistributedLock,
	interval time.Duration,
	timeout time.Duration,
) *AutoTrigger {
	if interval <= 0 {
		interval = 1 * time.Minute
	}
	if timeout <= 0 {
		timeout = 10 * time.Minute
	}

	return &AutoTrigger{
		db:          db,
		js:          js,
		publisher:   publisher,
		evaluator:   evaluator,
		lockManager: lockManager,
		interval:    interval,
		timeout:     timeout,
		stopCh:      make(chan struct{}),
	}
}

// Start starts the auto-trigger periodic task.
func (at *AutoTrigger) Start() {
	logger.InfoM(autoTriggerModule, "", "auto-trigger task started",
		"interval", at.interval.String(),
		"timeout", at.timeout.String(),
	)
	go at.run()
}

// Stop stops the auto-trigger periodic task.
func (at *AutoTrigger) Stop() {
	at.stopOnce.Do(func() {
		close(at.stopCh)
		logger.InfoM(autoTriggerModule, "", "auto-trigger task stopped")
	})
}

// run is the main loop of the auto-trigger task.
func (at *AutoTrigger) run() {
	ticker := time.NewTicker(at.interval)
	defer ticker.Stop()

	// Run immediately on start
	at.checkAllGroups()

	for {
		select {
		case <-at.stopCh:
			return
		case <-ticker.C:
			at.checkAllGroups()
		}
	}
}

// checkAllGroups checks all groups for timeout-based auto-triggers.
func (at *AutoTrigger) checkAllGroups() {
	ctx := context.Background()
	traceID := uuid.New().String()
	start := time.Now()

	// Fetch all active groups
	var groups []models.Group
	if err := at.db.Where("deleted_at IS NULL").Find(&groups).Error; err != nil {
		logger.ErrorM(autoTriggerModule, traceID, "failed to fetch groups for auto-trigger", "error", err)
		return
	}

	logger.InfoM(autoTriggerModule, traceID, "auto-trigger scan started",
		"group_count", len(groups),
	)

	triggered := 0
	skipped := 0
	lockHeld := 0

	for i := range groups {
		group := &groups[i]
		result, err := at.checkGroup(ctx, group, traceID)
		if err != nil {
			logger.ErrorM(autoTriggerModule, traceID, "failed to check group for auto-trigger",
				"group_id", group.GroupID,
				"error", err,
			)
		}
		switch result {
		case checkResultTriggered:
			triggered++
		case checkResultLockHeld:
			lockHeld++
		case checkResultSkipped:
			skipped++
		}
	}

	totalMs := time.Since(start).Milliseconds()
	logger.InfoM(autoTriggerModule, traceID, "auto-trigger scan completed",
		"group_count", len(groups),
		"triggered", triggered,
		"skipped", skipped,
		"lock_held", lockHeld,
		"total_duration_ms", totalMs,
	)
}

type checkResult int

const (
	checkResultSkipped checkResult = iota
	checkResultTriggered
	checkResultLockHeld
)

// checkGroup checks a single group for timeout-based auto-trigger.
func (at *AutoTrigger) checkGroup(ctx context.Context, group *models.Group, traceID string) (checkResult, error) {
	// Acquire distributed lock for this group
	lockKey, err := at.lockManager.Acquire(ctx, "auto_trigger", group.GroupID)
	if err != nil {
		return checkResultSkipped, fmt.Errorf("failed to acquire lock: %w", err)
	}
	if lockKey == nil {
		// Lock is held by another node, skip
		logger.DebugM(autoTriggerModule, traceID, "auto-trigger lock held by another node, skipping",
			"group_id", group.GroupID,
		)
		return checkResultLockHeld, nil
	}

	logger.DebugM(autoTriggerModule, traceID, "auto-trigger lock acquired",
		"group_id", group.GroupID,
	)

	defer func() {
		if err := lockKey.Release(); err != nil {
			logger.ErrorM(autoTriggerModule, traceID, "failed to release auto-trigger lock",
				"group_id", group.GroupID,
				"error", err,
			)
		}
	}()

	// Fetch group members
	var members []models.GroupMember
	if err := at.db.Where("group_id = ? AND deleted_at IS NULL", group.GroupID).Find(&members).Error; err != nil {
		return checkResultSkipped, fmt.Errorf("failed to fetch members: %w", err)
	}

	// Find the last message in the group
	var lastMessage models.GroupMessage
	if err := at.db.Where("group_id = ? AND deleted_at IS NULL AND is_deleted = ?", group.GroupID, false).
		Order("create_at_ms DESC").
		First(&lastMessage).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			// No messages in group, nothing to trigger
			return checkResultSkipped, nil
		}
		return checkResultSkipped, fmt.Errorf("failed to fetch last message: %w", err)
	}

	// Evaluate timeout-based auto-trigger
	result, err := at.evaluator.EvaluateAutoTriggerTimeout(ctx, &lastMessage, members)
	if err != nil {
		return checkResultSkipped, fmt.Errorf("failed to evaluate auto-trigger: %w", err)
	}

	if !result.ShouldTrigger {
		return checkResultSkipped, nil
	}

	// Check if there's already a pending auto-trigger for this message
	var existingCount int64
	if err := at.db.Model(&models.AgentMessageProcessing{}).
		Where("group_id = ? AND message_id = ? AND status = ?", group.GroupID, lastMessage.MessageID, models.ProcessingStatusPending).
		Count(&existingCount).Error; err != nil {
		logger.ErrorM(autoTriggerModule, traceID, "failed to check existing processing", "error", err)
	}
	if existingCount > 0 {
		logger.InfoM(autoTriggerModule, traceID, "auto-trigger already pending for message",
			"group_id", group.GroupID,
			"message_id", lastMessage.MessageID,
		)
		return checkResultSkipped, nil
	}

	// Create pending message record
	pendingID := uuid.New().String()
	pendingMsg := &models.GroupMessage{
		GroupID:        group.GroupID,
		MessageID:      pendingID,
		MessageText:    lastMessage.MessageText,
		SenderID:       lastMessage.SenderID,
		SenderType:     lastMessage.SenderType,
		ProcessedMsgID: lastMessage.MessageID,
		IsDeleted:      false,
	}

	// Save pending message to database
	if err := at.db.Create(pendingMsg).Error; err != nil {
		return checkResultSkipped, fmt.Errorf("failed to create pending message: %w", err)
	}

	// Record processing status as pending
	processingRecord := &models.AgentMessageProcessing{
		GroupID:   group.GroupID,
		MessageID: pendingID,
		AgentID:   result.Targets[0].AgentID,
		Status:    models.ProcessingStatusPending,
	}
	if err := at.db.Create(processingRecord).Error; err != nil {
		logger.ErrorM(autoTriggerModule, traceID, "failed to create processing record", "error", err)
	}

	// Build trigger info for NATS
	triggerData := trigger.FormatTriggerForNATS(result.Trigger, result.Targets)

	// Publish pending message to NATS
	if err := at.publisher.PublishAutoTriggerPendingMessage(group.GroupID, pendingMsg, triggerData); err != nil {
		return checkResultSkipped, fmt.Errorf("failed to publish auto-trigger pending message: %w", err)
	}

	logger.InfoM(autoTriggerModule, traceID, "auto-trigger published pending message",
		"group_id", group.GroupID,
		"message_id", lastMessage.MessageID,
		"pending_id", pendingID,
		"agent_id", result.Targets[0].AgentID,
	)

	return checkResultTriggered, nil
}
