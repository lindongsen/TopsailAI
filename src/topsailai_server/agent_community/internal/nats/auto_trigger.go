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

	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
)

const autoTriggerModule = "auto_trigger"

// AutoTriggerPublisher is the subset of Publisher used by AutoTrigger.
type AutoTriggerPublisher interface {
	PublishAutoTriggerPendingMessage(groupID string, msg *models.GroupMessage, trigger interface{}) error
}

// AutoTriggerEvaluator is the subset of trigger.Evaluator used by AutoTrigger.
type AutoTriggerEvaluator interface {
	EvaluateAutoTriggerTimeout(ctx context.Context, lastMessage *models.GroupMessage, members []models.GroupMember) (*trigger.TriggerResult, error)
}

// AutoTriggerLock is the subset of lock.Lock used by AutoTrigger.
type AutoTriggerLock interface {
	Release() error
}

// AutoTriggerLockManager is the subset of lock.DistributedLock used by AutoTrigger.
type AutoTriggerLockManager interface {
	Acquire(ctx context.Context, lockType, resourceID string) (AutoTriggerLock, error)
}

// AutoTrigger runs a periodic task to check for timeout-based auto-triggers.
type AutoTrigger struct {
	db          *gorm.DB
	js          nats.JetStreamContext
	publisher   AutoTriggerPublisher
	evaluator   AutoTriggerEvaluator
	lockManager AutoTriggerLockManager
	interval    time.Duration
	timeout     time.Duration
	stopCh      chan struct{}
	stopOnce    sync.Once
	doneCh      chan struct{}
	started     bool
	mu          sync.Mutex
}

// NewAutoTrigger creates a new auto-trigger periodic task.
func NewAutoTrigger(
	db *gorm.DB,
	js nats.JetStreamContext,
	publisher AutoTriggerPublisher,
	evaluator AutoTriggerEvaluator,
	lockManager AutoTriggerLockManager,
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
		doneCh:      make(chan struct{}),
	}
}

// Start starts the auto-trigger periodic task.
func (at *AutoTrigger) Start() {
	at.mu.Lock()
	at.started = true
	at.mu.Unlock()
	logger.InfoM(autoTriggerModule, "", "auto-trigger task started",
		"interval", at.interval.String(),
		"timeout", at.timeout.String(),
	)
	go at.run()
}

// Stop stops the auto-trigger periodic task and waits for the background
// goroutine to finish. This prevents leaked goroutines from accessing closed
// test databases in subsequent tests.
func (at *AutoTrigger) Stop() {
	at.stopOnce.Do(func() {
		close(at.stopCh)
		logger.InfoM(autoTriggerModule, "", "auto-trigger task stopped")
	})
	at.mu.Lock()
	started := at.started
	at.mu.Unlock()
	if started {
		<-at.doneCh
	}
}

// run is the main loop of the auto-trigger task.
func (at *AutoTrigger) run() {
	defer close(at.doneCh)

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

// checkGroup evaluates a single group for timeout-based auto-trigger and
// publishes the original last message to NATS when appropriate.
//
// Important: the original user message is published directly as the pending
// message payload. No synthetic GroupMessage row is created. This keeps the
// agent response's processed_msg_id pointing to the real user message and
// avoids duplicate entries in the message history.
func (at *AutoTrigger) checkGroup(ctx context.Context, group *models.Group, traceID string) (checkResult, error) {
	if at.lockManager == nil {
		return checkResultSkipped, nil
	}

	lock, err := at.lockManager.Acquire(ctx, "auto-trigger", group.GroupID)
	if err != nil {
		return checkResultSkipped, fmt.Errorf("failed to acquire auto-trigger lock: %w", err)
	}
	if lock == nil {
		return checkResultLockHeld, nil
	}
	defer func() {
		if err := lock.Release(); err != nil {
			logger.WarnM(autoTriggerModule, traceID, "failed to release auto-trigger lock",
				"group_id", group.GroupID,
				"error", err,
			)
		}
	}()

	// Fetch the most recent non-deleted message in the group.
	var lastMessage models.GroupMessage
	if err := at.db.Where("group_id = ? AND is_deleted = ?", group.GroupID, false).
		Order("create_at_ms DESC").
		First(&lastMessage).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			return checkResultSkipped, nil
		}
		return checkResultSkipped, fmt.Errorf("failed to fetch last message: %w", err)
	}

	// Only user messages can trigger auto-triggers.
	if lastMessage.IsFromAgent() {
		return checkResultSkipped, nil
	}

	// Fetch group members.
	var members []models.GroupMember
	if err := at.db.Where("group_id = ?", group.GroupID).Find(&members).Error; err != nil {
		return checkResultSkipped, fmt.Errorf("failed to fetch group members: %w", err)
	}

	// Evaluate timeout-based auto-trigger.
	if at.evaluator == nil {
		return checkResultSkipped, nil
	}
	result, err := at.evaluator.EvaluateAutoTriggerTimeout(ctx, &lastMessage, members)
	if err != nil {
		return checkResultSkipped, fmt.Errorf("failed to evaluate auto-trigger: %w", err)
	}
	if result == nil || !result.ShouldTrigger || len(result.Targets) == 0 {
		return checkResultSkipped, nil
	}

	// Check if this message-agent pair has already been processed (any status)
	// to avoid duplicate auto-triggers. If the check itself fails, log the error
	// and continue; the unique constraint on (group_id, message_id, agent_id)
	// prevents duplicate inserts when the processing record is created below.
	var existingCount int64
	if err := at.db.Model(&models.AgentMessageProcessing{}).
		Where("group_id = ? AND message_id = ? AND agent_id = ?",
			group.GroupID, lastMessage.MessageID, result.Targets[0].AgentID).
		Count(&existingCount).Error; err != nil {
		logger.ErrorM(autoTriggerModule, traceID, "failed to check existing processing record; continuing",
			"group_id", group.GroupID,
			"message_id", lastMessage.MessageID,
			"agent_id", result.Targets[0].AgentID,
			"error", err,
		)
	} else if existingCount > 0 {
		logger.DebugM(autoTriggerModule, traceID, "auto-trigger already processed or in-flight for message",
			"group_id", group.GroupID,
			"message_id", lastMessage.MessageID,
			"agent_id", result.Targets[0].AgentID,
		)
		return checkResultSkipped, nil
	}

	// Build trigger info for NATS.
	triggerData := trigger.FormatTriggerForNATS(result.Trigger, result.Targets)

	// Publish the original message to NATS as a pending message. Using the
	// original message ID ensures the agent response's processed_msg_id points
	// back to the user's message instead of a synthetic pending message.
	if err := at.publisher.PublishAutoTriggerPendingMessage(group.GroupID, &lastMessage, triggerData); err != nil {
		return checkResultSkipped, fmt.Errorf("failed to publish auto-trigger pending message: %w", err)
	}

	// Record processing status as pending so subsequent scans do not re-trigger
	// the same message-agent pair while the consumer is working.
	processingRecord := &models.AgentMessageProcessing{
		GroupID:   group.GroupID,
		MessageID: lastMessage.MessageID,
		AgentID:   result.Targets[0].AgentID,
		Status:    models.ProcessingStatusPending,
	}
	if err := at.db.Create(processingRecord).Error; err != nil {
		logger.ErrorM(autoTriggerModule, traceID, "failed to create processing record", "error", err)
	}

	logger.InfoM(autoTriggerModule, traceID, "auto-trigger published pending message",
		"group_id", group.GroupID,
		"message_id", lastMessage.MessageID,
		"agent_id", result.Targets[0].AgentID,
	)

	return checkResultTriggered, nil
}
