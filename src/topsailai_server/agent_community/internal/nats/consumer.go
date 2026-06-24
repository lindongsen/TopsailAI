// Package nats provides NATS integration for the ACS service.
package nats

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/agent"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/message"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/internal/workpool"
	"github.com/topsailai/agent-community/pkg/logger"
)

const consumerModule = "consumer"

// EventPublisher publishes group and member events to NATS.
type EventPublisher interface {
	PublishPendingMessageWithAgentID(groupID string, msg *models.GroupMessage, trigger interface{}, agentID string) error
	PublishMessageCreate(msg *models.GroupMessage) error
	PublishMessageModify(msg *models.GroupMessage) error
	PublishMessageDelete(msg *models.GroupMessage) error
	PublishGroupCreate(group *models.Group) error
	PublishGroupModify(group *models.Group) error
	PublishGroupDelete(groupID string) error
	PublishGroupMemberCreate(member *models.GroupMember) error
	PublishGroupMemberModify(member *models.GroupMember) error
	PublishGroupMemberDelete(groupID, memberID string) error
	PublishAgentResponse(msg *models.GroupMessage) error
	PublishSystemError(msg *models.GroupMessage) error
	PublishAutoTriggerPendingMessage(groupID string, msg *models.GroupMessage, trigger interface{}) error
	PublishHeartbeat(nodeID string) error
}

// AgentExecutor executes agent commands (health, status, chat).
type AgentExecutor interface {
	CheckHealth(ctx context.Context, iface *agent.Interface, env map[string]string, traceID string) (*agent.ExecutionResult, error)
	CheckStatus(ctx context.Context, iface *agent.Interface, env map[string]string, traceID string) (*agent.ExecutionResult, error)
	Chat(ctx context.Context, iface *agent.Interface, env map[string]string, traceID string) (*agent.ExecutionResult, error)
}

// AccountService provides account login session operations for the consumer.
// A minimal interface is used here to avoid an import cycle with services.
type AccountService interface {
	EnsureLoginSession(ctx context.Context, accountID string) (string, int64, error)
}

// processAgentTargetFunc processes a single agent target for a pending message.
// The signature is extracted so the concurrent dispatch logic can be unit-tested
// with a stub implementation without invoking real agent/DB operations.
type processAgentTargetFunc func(
	ctx context.Context,
	group *models.Group,
	members []models.GroupMember,
	pendingMsg *models.GroupMessage,
	triggerInfo trigger.TriggerInfo,
	target trigger.AgentTarget,
	traceID string,
) error

// Consumer processes pending messages from NATS and dispatches them to agents.
type Consumer struct {
	db             *gorm.DB
	publisher      EventPublisher
	executor       AgentExecutor
	accountService AccountService
	pool           *workpool.Pool
	contextBuilder *message.ContextBuilder
	maxChainLength int
	cfg            *config.Config
}

// NewConsumer creates a new NATS consumer.
func NewConsumer(
	db *gorm.DB,
	publisher EventPublisher,
	executor AgentExecutor,
	accountService AccountService,
	pool *workpool.Pool,
	cfg *config.Config,
) *Consumer {
	return &Consumer{
		db:             db,
		publisher:      publisher,
		executor:       executor,
		accountService: accountService,
		pool:           pool,
		contextBuilder: message.NewContextBuilder(),
		maxChainLength: 5,
		cfg:            cfg,
	}
}

// Handler returns a NATS MsgHandler for processing pending messages.
func (c *Consumer) Handler() nats.MsgHandler {
	return func(msg *nats.Msg) {
		// Extract trace_id from NATS header or generate a new one
		traceID := msg.Header.Get("X-Trace-ID")
		if traceID == "" {
			traceID = uuid.New().String()
		}

		// Extract message_id from payload for logging
		var payload struct {
			MessageID string `json:"message_id"`
		}
		_ = json.Unmarshal(msg.Data, &payload)
		messageID := payload.MessageID
		if messageID == "" {
			messageID = "unknown"
		}

		// Reliable mode: ManualAck + InProgress heartbeat. The consumer always
		// uses explicit acknowledgement regardless of ACS_NATS_PENDING_MESSAGE_NO_ACK;
		// that variable only controls publisher-side publish-ack behaviour.
		// Start a goroutine to periodically send InProgress to reset AckWait timer.
		stopInProgress := make(chan struct{})
		logger.DebugM(consumerModule, traceID, "starting InProgress heartbeat for message", "message_id", messageID)

		go func() {
			ticker := time.NewTicker(20 * time.Second)
			defer ticker.Stop()
			for {
				select {
				case <-ticker.C:
					if err := msg.InProgress(); err != nil {
						logger.WarnM(consumerModule, traceID, "failed to send InProgress", "error", err)
					}
				case <-stopInProgress:
					return
				}
			}
		}()

		// Ensure heartbeat goroutine is always stopped to prevent goroutine leak.
		// This defer runs before the recover defer (LIFO), so stopInProgress is
		// closed even if a panic occurs and is recovered.
		defer func() {
			logger.DebugM(consumerModule, traceID, "stopping InProgress heartbeat for message", "message_id", messageID)
			close(stopInProgress)
		}()

		// Recover from panic to ensure graceful handling and heartbeat cleanup.
		defer func() {
			if r := recover(); r != nil {
				logger.ErrorM(consumerModule, traceID, "panic recovered in message handler", "panic", r)
			}
		}()

		if err := c.processMessage(msg, traceID); err != nil {
			logger.ErrorM(consumerModule, traceID, "failed to process pending message", "error", err)
			// Negative ack to trigger redelivery. For pool-limit backpressure,
			// this lets JetStream redeliver after AckWait rather than treating
			// saturation as a processing failure.
			msg.Nak()
			return
		}
		msg.Ack()
	}
}

// processMessage processes a single pending message from NATS.
// It parses the payload, validates the group, resolves agent targets, and
// dispatches each target concurrently. The function waits for all targets to
// complete before returning so that NATS acknowledgements (in reliable mode)
// accurately reflect end-to-end processing.
func (c *Consumer) processMessage(msg *nats.Msg, traceID string) error {
	ctx := context.Background()
	start := time.Now()

	// Parse pending message payload
	var payload PendingMessagePayload
	if err := json.Unmarshal(msg.Data, &payload); err != nil {
		return fmt.Errorf("failed to unmarshal pending message: %w", err)
	}

	groupID := payload.GroupID
	messageID := payload.MessageID

	logger.InfoM(consumerModule, traceID, "processing pending message",
		"group_id", groupID,
		"message_id", messageID,
	)

	// Fetch group
	var group models.Group
	if err := c.db.First(&group, "group_id = ?", groupID).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			logger.WarnM(consumerModule, traceID, "group not found, skipping message", "group_id", groupID)
			return nil // Ack to remove from queue
		}
		return fmt.Errorf("failed to fetch group: %w", err)
	}

	// Check if group is soft-deleted
	if group.DeletedAt.Valid {
		logger.WarnM(consumerModule, traceID, "group is deleted, skipping message", "group_id", groupID)
		return nil
	}

	// Fetch group members
	var members []models.GroupMember
	if err := c.db.Where("group_id = ?", groupID).Find(&members).Error; err != nil {
		return fmt.Errorf("failed to fetch group members: %w", err)
	}

	// Parse trigger info
	triggerMap, ok := payload.Trigger.(map[string]interface{})
	if !ok {
		return fmt.Errorf("invalid trigger format: expected map[string]interface{}")
	}
	triggerInfo, targets, err := trigger.ParseTriggerFromNATS(triggerMap)
	if err != nil {
		return fmt.Errorf("failed to parse trigger: %w", err)
	}

	if len(targets) == 0 {
		logger.WarnM(consumerModule, traceID, "no agent targets found, skipping message", "message_id", messageID)
		return nil
	}

	// Dispatch each target agent concurrently. Multiple worker-agent mentions
	// without a manager-agent must be invoked in parallel per the ACS spec.
	//
	// AgentWorkPool limit semantics: each goroutine calls processAgentTarget,
	// which acquires one slot from the per-node, per-user, and per-group
	// semaphores for that specific agent invocation. Therefore a single pending
	// message with N targets may consume up to N per-user slots and N per-group
	// slots while the targets are running. This keeps the documented concurrency
	// limits enforced per active agent call.
	//
	// Shared dependency safety:
	//   - c.contextBuilder: stateless, only reads inputs; safe for concurrent use.
	//   - c.publisher: interface implementations must be goroutine-safe; the
	//     production NATS publisher uses local message copies and is safe.
	//   - c.executor: interface implementations must be goroutine-safe; the
	//     production executor runs external commands and is safe to call from
	//     multiple goroutines.
	//   - c.db: *gorm.DB is documented as safe for concurrent use by multiple
	//     goroutines (connection pooling); each call is independent.
	//   - group, pendingMsg, triggerInfo, and the members slice header are only
	//     read by goroutines. Each goroutine owns a local copy of its target
	//     agent member, so no two goroutines write to the same memory.
	if err := c.dispatchTargets(ctx, &group, members, &payload.GroupMessage, triggerInfo, targets, traceID, c.processAgentTarget); err != nil {
		logger.ErrorM(consumerModule, traceID, "failed to dispatch agent targets", "error", err)
		if errors.Is(err, workpool.ErrPoolLimitReached) {
			return err
		}
	}

	totalMs := time.Since(start).Milliseconds()
	logger.InfoM(consumerModule, traceID, "pending message processed",
		"group_id", groupID,
		"message_id", messageID,
		"total_duration_ms", totalMs,
	)

	return nil
}

// dispatchTargets runs each agent target in its own goroutine and waits for all
// to complete. The processFunc parameter allows tests to substitute a stub and
// prove that targets are dispatched concurrently without relying on real agent
// or database operations.
func (c *Consumer) dispatchTargets(
	ctx context.Context,
	group *models.Group,
	members []models.GroupMember,
	pendingMsg *models.GroupMessage,
	triggerInfo trigger.TriggerInfo,
	targets []trigger.AgentTarget,
	traceID string,
	processFunc processAgentTargetFunc,
) error {
	if len(targets) == 0 {
		return nil
	}

	var wg sync.WaitGroup
	var errMu sync.Mutex
	var errs []error
	for _, target := range targets {
		wg.Add(1)
		go func(t trigger.AgentTarget) {
			defer wg.Done()
			if err := processFunc(ctx, group, members, pendingMsg, triggerInfo, t, traceID); err != nil {
				logger.ErrorM(consumerModule, traceID, "failed to process agent target",
					"agent_id", t.AgentID,
					"message_id", pendingMsg.MessageID,
					"error", err,
				)
				errMu.Lock()
				errs = append(errs, err)
				errMu.Unlock()
				// Pool-limit errors are transient backpressure signals; rely on
				// NATS JetStream redelivery instead of recording a system error.
				if errors.Is(err, workpool.ErrPoolLimitReached) {
					return
				}
				// Try to send system error message for genuine processing failures.
				c.sendSystemError(ctx, group, members, pendingMsg, t.AgentID, err.Error(), traceID)
			}
		}(target)
	}
	wg.Wait()

	if len(errs) > 0 {
		return fmt.Errorf("%d agent target(s) failed: %v", len(errs), errs[0])
	}
	return nil
}

// isAgentAlreadyRunning checks if the specified agent is already processing the given message.
func (c *Consumer) isAgentAlreadyRunning(groupID, messageID, agentID, traceID string) (bool, error) {
	var existing models.AgentMessageProcessing
	err := c.db.Where("group_id = ? AND message_id = ? AND agent_id = ? AND status = ?",
		groupID, messageID, agentID, models.ProcessingStatusRunning).
		First(&existing).Error
	if err != nil {
		if err == gorm.ErrRecordNotFound {
			return false, nil
		}
		return false, err
	}
	return true, nil
}

// isDuplicateKeyError returns true if err indicates a duplicate-key/unique
// constraint violation. It checks GORM's generic error first, then falls back
// to driver-specific error text for SQLite and PostgreSQL.
func isDuplicateKeyError(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, gorm.ErrDuplicatedKey) {
		return true
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "unique constraint failed") || // SQLite
		strings.Contains(msg, "duplicate key value") || // PostgreSQL
		strings.Contains(msg, "duplicate entry") // MySQL
}

// checkAndCreateRunningRecord atomically claims a running record for the
// given message-agent pair. The auto-trigger task pre-inserts a pending
// reservation, so the consumer first tries to upgrade that pending record to
// running. If no pending record exists, it falls back to inserting a new
// running record. The unique index on (group_id, message_id, agent_id)
// guarantees that only one record can exist, so a plain INSERT is sufficient
// to detect duplicates across concurrent consumers.
//
// Returns (true, nil) if the record was claimed/created successfully.
// Returns (false, nil) if the agent is already processing this message.
// Returns (false, err) on database error.
func (c *Consumer) checkAndCreateRunningRecord(groupID, messageID, agentID, traceID string) (bool, error) {
	nowMs := time.Now().UnixMilli()

	// First, try to upgrade an existing pending reservation created by the
	// auto-trigger task. Only update if it is still pending so we do not
	// overwrite another running consumer.
	res := c.db.Model(&models.AgentMessageProcessing{}).
		Where("group_id = ? AND message_id = ? AND agent_id = ? AND status = ?",
			groupID, messageID, agentID, models.ProcessingStatusPending).
		Updates(map[string]interface{}{
			"status":       models.ProcessingStatusRunning,
			"update_at_ms": nowMs,
		})
	if res.Error != nil {
		return false, fmt.Errorf("failed to claim pending record: %w", res.Error)
	}
	if res.RowsAffected > 0 {
		logger.InfoM(consumerModule, traceID, "pending record claimed as running",
			"group_id", groupID,
			"message_id", messageID,
			"agent_id", agentID,
		)
		return true, nil
	}

	// No pending record to claim; insert a new running record.
	record := &models.AgentMessageProcessing{
		GroupID:    groupID,
		MessageID:  messageID,
		AgentID:    agentID,
		Status:     models.ProcessingStatusRunning,
		CreateAtMs: nowMs,
		UpdateAtMs: nowMs,
	}

	if err := c.db.Create(record).Error; err != nil {
		if isDuplicateKeyError(err) {
			logger.DebugM(consumerModule, traceID, "running record already exists, skipping duplicate",
				"group_id", groupID,
				"message_id", messageID,
				"agent_id", agentID,
			)
			return false, nil
		}
		return false, fmt.Errorf("failed to create running record: %w", err)
	}

	logger.InfoM(consumerModule, traceID, "running record created",
		"group_id", groupID,
		"message_id", messageID,
		"agent_id", agentID,
	)
	return true, nil
}

// processAgentTarget processes a single agent target.
// It acquires one slot from each AgentWorkPool limit (per-node, per-user,
// per-group) for this specific agent invocation, executes the agent, and
// releases the slots when finished. This keeps the documented concurrency
// limits enforced per active agent call even when multiple targets run in
// parallel for the same pending message.
func (c *Consumer) processAgentTarget(
	ctx context.Context,
	group *models.Group,
	members []models.GroupMember,
	pendingMsg *models.GroupMessage,
	triggerInfo trigger.TriggerInfo,
	target trigger.AgentTarget,
	traceID string,
) error {
	if c.pool != nil {
		// Honor ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT. A positive timeout lets
		// the consumer wait briefly for a slot instead of rejecting the
		// message immediately, which is useful when a burst of agents is
		// triggered for the same pending message. A zero or negative timeout
		// preserves the original non-blocking behavior so JetStream can
		// redeliver the message once a slot is free.
		acquireTimeout := time.Duration(0)
		if c.cfg != nil {
			acquireTimeout = c.cfg.AgentWorkPool.AcquireTimeout
		}

		var err error
		if acquireTimeout > 0 {
			err = c.pool.AcquireWithTimeout(acquireTimeout, pendingMsg.SenderID, group.GroupID, traceID)
		} else {
			err = c.pool.TryAcquire(pendingMsg.SenderID, group.GroupID, traceID)
		}
		if err != nil {
			if errors.Is(err, workpool.ErrPoolLimitReached) {
				return err
			}
			return fmt.Errorf("failed to acquire work pool slot: %w", err)
		}
		defer c.pool.Release(pendingMsg.SenderID, group.GroupID, traceID)
	}
	// Find target agent member. Make a local value copy so each goroutine owns
	// its own member struct; this avoids data races on the shared members slice
	// backing array when multiple targets run concurrently.
	var agentMember models.GroupMember
	found := false
	for _, m := range members {
		if m.MemberID == target.AgentID {
			agentMember = m
			found = true
			break
		}
	}

	if !found {
		return fmt.Errorf("agent member not found: %s", target.AgentID)
	}

	// Check if agent is still in group
	if agentMember.DeletedAt.Valid {
		return fmt.Errorf("agent member is deleted: %s", target.AgentID)
	}

	// Parse agent interface
	iface, err := agent.ParseInterface(agentMember.MemberInterface)
	if err != nil {
		return fmt.Errorf("failed to parse agent interface: %w", err)
	}

	// Apply manager defaults if applicable
	if agentMember.MemberType == models.MemberTypeManagerAgent {
		iface.ApplyManagerDefaults(
			agent.GetEnvOrDefault("ACS_GROUP_MANAGER_AGENT_API_BASE", ""),
			agent.GetEnvOrDefault("ACS_GROUP_MANAGER_AGENT_API_KEY", ""),
			agent.GetEnvOrDefault("ACS_GROUP_MANAGER_AGENT_API_AUTH", "bearer"),
		)
	}

	// Check agent health before dispatching
	healthEnv := agent.MergeEnv(iface.Environments, map[string]string{
		"ACS_AGENT_ID":   agentMember.MemberID,
		"ACS_AGENT_NAME": agentMember.MemberName,
	})
	healthResult, err := c.executor.CheckHealth(ctx, iface, healthEnv, traceID)
	if err != nil || !healthResult.IsHealthy() {
		return fmt.Errorf("agent health check failed: %w, exit_code=%d", err, healthResult.ExitCode)
	}

	// Atomically check if this agent is already processing this message and create a running record.
	// This prevents race conditions between multiple nodes processing the same pending message.
	created, err := c.checkAndCreateRunningRecord(group.GroupID, pendingMsg.MessageID, agentMember.MemberID, traceID)
	if err != nil {
		return fmt.Errorf("failed to check and create running record: %w", err)
	}
	if !created {
		logger.WarnM(consumerModule, traceID, "agent already processing this message, skipping duplicate",
			"agent_id", agentMember.MemberID,
			"message_id", pendingMsg.MessageID,
		)
		return nil
	}

	// Set member_status to processing only after the agent is confirmed healthy and
	// no duplicate running record exists. This ensures the processing state is visible
	// for the actual duration of agent work rather than a transient pre-check window.
	statusSet := false
	if err := c.updateMemberStatus(agentMember.GroupID, agentMember.MemberID, models.MemberStatusProcessing, traceID); err != nil {
		logger.WarnM(consumerModule, traceID, "failed to set agent status to processing",
			"agent_id", agentMember.MemberID,
			"error", err,
		)
	} else {
		statusSet = true
		// Sync in-memory status so published events reflect the new DB state.
		agentMember.MemberStatus = models.MemberStatusProcessing
		if err := c.publisher.PublishGroupMemberModify(&agentMember); err != nil {
			logger.WarnM(consumerModule, traceID, "failed to publish member status processing event",
				"agent_id", agentMember.MemberID,
				"error", err,
			)
		}
	}

	// Ensure status is always reset to idle when processing ends, but only if we
	// successfully transitioned to processing to avoid unnecessary DB writes.
	defer func() {
		if !statusSet {
			return
		}
		if err := c.updateMemberStatus(agentMember.GroupID, agentMember.MemberID, models.MemberStatusIdle, traceID); err != nil {
			logger.WarnM(consumerModule, traceID, "failed to set agent status to idle",
				"agent_id", agentMember.MemberID,
				"error", err,
			)
		} else {
			// Sync in-memory status so published events reflect the new DB state.
			agentMember.MemberStatus = models.MemberStatusIdle
			if err := c.publisher.PublishGroupMemberModify(&agentMember); err != nil {
				logger.WarnM(consumerModule, traceID, "failed to publish member status idle event",
					"agent_id", agentMember.MemberID,
					"error", err,
				)
			}
		}
	}()

	// Check processing chain length to prevent infinite loops
	chainLength := c.getProcessingChainLength(pendingMsg)
	if chainLength >= c.maxChainLength {
		return fmt.Errorf("max processing chain length reached: %d", chainLength)
	}

	// Fetch all messages for context building
	var allMessages []models.GroupMessage
	if err := c.db.Where("group_id = ?", group.GroupID).
		Order("create_at_ms ASC").
		Find(&allMessages).Error; err != nil {
		return fmt.Errorf("failed to fetch messages: %w", err)
	}

	// Build context messages
	contextText, err := c.contextBuilder.BuildContext(
		group, members, &agentMember, allMessages,
		agentMember.LastReadMessageID, pendingMsg,
	)
	if err != nil {
		return fmt.Errorf("failed to build context: %w", err)
	}

	// Append target.MessageAppend if present (e.g., for multiple agents without manager)
	if target.MessageAppend != "" {
		contextText = contextText + "\n\n" + target.MessageAppend
	}

	// Determine group context: only pass when last_read_message_id is empty
	var groupContext string
	if agentMember.LastReadMessageID == "" {
		groupContext = group.GroupContext
	}

	// Determine login session key for manager-agent triggers.
	var loginSessionKey string
	if agentMember.MemberType == models.MemberTypeManagerAgent {
		if c.accountService != nil {
			sessionKey, _, err := c.accountService.EnsureLoginSession(ctx, pendingMsg.SenderID)
			if err != nil {
				logger.WarnM(consumerModule, traceID, "failed to ensure login session for manager-agent trigger",
					"sender_id", pendingMsg.SenderID,
					"agent_id", agentMember.MemberID,
					"error", err,
				)
			} else {
				loginSessionKey = sessionKey
			}
		} else {
			logger.WarnM(consumerModule, traceID, "account service not configured, cannot provide login session key",
				"sender_id", pendingMsg.SenderID,
				"agent_id", agentMember.MemberID,
			)
		}
	}

	// Build chat environment with all required variables
	chatEnv := iface.BuildChatEnv(
		agentMember.MemberID,
		agentMember.MemberName,
		string(agentMember.MemberType),
		group.GroupID,
		group.GroupName,
		pendingMsg.SenderID,
		pendingMsg.SenderID, // Use sender_id as name fallback
		pendingMsg.MessageID,
		contextText,
		target.Mode,
		c.cfg.Agent.AgentPrompt,
		groupContext,
		pendingMsg.Mentions,
		string(triggerInfo.Type),
		loginSessionKey,
	)

	// Execute agent chat
	chatResult, err := c.executor.Chat(ctx, iface, chatEnv, traceID)
	if err != nil {
		return fmt.Errorf("agent chat failed: %w", err)
	}

	// Create agent response message
	responseID := uuid.New().String()
	responseMsg := c.contextBuilder.BuildAgentResponseMessage(
		group.GroupID,
		&agentMember,
		chatResult.Stdout,
		pendingMsg.MessageID,
		responseID,
	)

	// Save response message to database
	if err := c.db.Create(responseMsg).Error; err != nil {
		return fmt.Errorf("failed to save agent response: %w", err)
	}

	// Update agent's last_read_message_id
	agentMember.LastReadMessageID = pendingMsg.MessageID
	agentMember.UpdateAtMs = time.Now().UnixMilli()
	if err := c.db.Save(&agentMember).Error; err != nil {
		logger.ErrorM(consumerModule, traceID, "failed to update last_read_message_id",
			"agent_id", agentMember.MemberID,
			"error", err,
		)
	}

	// Publish response to NATS
	if err := c.publisher.PublishAgentResponse(responseMsg); err != nil {
		logger.ErrorM(consumerModule, traceID, "failed to publish agent response",
			"message_id", responseID,
			"error", err,
		)
	}

	// Record processing status
	c.recordProcessingStatus(group.GroupID, pendingMsg.MessageID, agentMember.MemberID, true, "", traceID)

	logger.InfoM(consumerModule, traceID, "agent processed message successfully",
		"agent_id", agentMember.MemberID,
		"message_id", pendingMsg.MessageID,
		"response_id", responseID,
		"duration_ms", chatResult.Duration,
	)

	return nil
}

// sendSystemError sends a system error message using manager-agent identity.
// If no manager-agent exists, uses a system-level identity to avoid silent failures.
func (c *Consumer) sendSystemError(
	ctx context.Context,
	group *models.Group,
	members []models.GroupMember,
	pendingMsg *models.GroupMessage,
	failedAgentID string,
	errorText string,
	traceID string,
) {
	// Find a manager agent to use as sender
	var managerAgent *models.GroupMember
	for i := range members {
		if members[i].MemberType == models.MemberTypeManagerAgent && !members[i].DeletedAt.Valid {
			managerAgent = &members[i]
			break
		}
	}

	responseID := uuid.New().String()
	var errorMsg *models.GroupMessage

	if managerAgent != nil {
		errorMsg = c.contextBuilder.BuildSystemErrorMessage(
			group.GroupID,
			managerAgent,
			fmt.Sprintf("Agent %s failed: %s", failedAgentID, errorText),
			pendingMsg.MessageID,
			responseID,
		)
	} else {
		// No manager-agent: create system-level error message to avoid silent failure
		systemAgent := &models.GroupMember{
			MemberID:   "acs-system",
			MemberName: "System",
			MemberType: models.MemberTypeManagerAgent,
		}
		errorMsg = c.contextBuilder.BuildSystemErrorMessage(
			group.GroupID,
			systemAgent,
			fmt.Sprintf("Agent %s failed: %s", failedAgentID, errorText),
			pendingMsg.MessageID,
			responseID,
		)
	}
	// Save error message to database
	if c.db != nil {
		if err := c.db.Create(errorMsg).Error; err != nil {
			logger.ErrorM(consumerModule, traceID, "failed to save system error message", "error", err)
			return
		}
	}
	// Publish error message to NATS
	if c.publisher != nil {
		if err := c.publisher.PublishSystemError(errorMsg); err != nil {
			logger.ErrorM(consumerModule, traceID, "failed to publish system error message", "error", err)
		}
	}
	// Record processing status as failed
	c.recordProcessingStatus(group.GroupID, pendingMsg.MessageID, failedAgentID, false, errorText, traceID)

	if managerAgent != nil {
		logger.InfoM(consumerModule, traceID, "system error message sent",
			"manager_id", managerAgent.MemberID,
			"failed_agent", failedAgentID,
		)
	} else {
		logger.InfoM(consumerModule, traceID, "system error message sent with system identity", "failed_agent", failedAgentID)
	}
}

// getProcessingChainLength calculates the chain length of processed messages.
func (c *Consumer) getProcessingChainLength(msg *models.GroupMessage) int {
	if msg.ProcessedMsgID == "" {
		return 0
	}

	length := 0
	currentID := msg.ProcessedMsgID
	for length < c.maxChainLength+1 {
		var parentMsg models.GroupMessage
		if err := c.db.First(&parentMsg, "message_id = ?", currentID).Error; err != nil {
			break
		}
		length++
		if parentMsg.ProcessedMsgID == "" {
			break
		}
		currentID = parentMsg.ProcessedMsgID
	}

	return length
}

// createRunningRecord creates a running status record for the agent message processing.
func (c *Consumer) createRunningRecord(groupID, messageID, agentID, traceID string) error {
	record := &models.AgentMessageProcessing{
		GroupID:   groupID,
		MessageID: messageID,
		AgentID:   agentID,
		Status:    models.ProcessingStatusRunning,
	}

	if err := c.db.Create(record).Error; err != nil {
		return fmt.Errorf("failed to create running record: %w", err)
	}

	logger.InfoM(consumerModule, traceID, "running record created",
		"group_id", groupID,
		"message_id", messageID,
		"agent_id", agentID,
	)
	return nil
}

// recordProcessingStatus records the agent message processing status.
func (c *Consumer) recordProcessingStatus(groupID, messageID, agentID string, success bool, errorMsg string, traceID string) {
	if c.db == nil {
		return
	}

	status := models.ProcessingStatusCompleted
	if !success {
		status = models.ProcessingStatusFailed
	}

	now := time.Now().UnixMilli()

	// Try to update existing running record first
	result := c.db.Model(&models.AgentMessageProcessing{}).
		Where("group_id = ? AND message_id = ? AND agent_id = ? AND status = ?",
			groupID, messageID, agentID, models.ProcessingStatusRunning).
		Updates(map[string]interface{}{
			"status":          status,
			"error_message":   errorMsg,
			"processed_at_ms": now,
			"update_at_ms":    now,
		})

	if result.Error != nil {
		logger.ErrorM(consumerModule, traceID, "failed to update running record to final status", "error", result.Error)
		return
	}

	if result.RowsAffected == 0 {
		// No running record found, create a new one. This can happen when a
		// previous consumer crashed before recording the final status. The
		// unique index prevents duplicate records if another goroutine already
		// created a terminal record for this message-agent pair.
		record := &models.AgentMessageProcessing{
			GroupID:       groupID,
			MessageID:     messageID,
			AgentID:       agentID,
			Status:        status,
			ErrorMessage:  errorMsg,
			ProcessedAtMs: now,
		}
		if err := c.db.Create(record).Error; err != nil {
			if isDuplicateKeyError(err) {
				logger.DebugM(consumerModule, traceID, "terminal processing record already exists",
					"group_id", groupID,
					"message_id", messageID,
					"agent_id", agentID,
				)
				return
			}
			logger.ErrorM(consumerModule, traceID, "failed to record processing status", "error", err)
		}
	}
}

// updateMemberStatus updates the member_status of a group member in the database.
// It also updates the update_at_ms timestamp. Returns error if member not found.
func (c *Consumer) updateMemberStatus(groupID, memberID string, status models.MemberStatus, traceID string) error {
	result := c.db.Model(&models.GroupMember{}).
		Where("group_id = ? AND member_id = ?", groupID, memberID).
		Updates(map[string]interface{}{
			"member_status": status,
			"update_at_ms":  time.Now().UnixMilli(),
		})
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected == 0 {
		return fmt.Errorf("member not found: group_id=%s, member_id=%s", groupID, memberID)
	}

	logger.InfoM(consumerModule, traceID, "agent status updated",
		"agent_id", memberID,
		"group_id", groupID,
		"status", status,
	)
	return nil
}
