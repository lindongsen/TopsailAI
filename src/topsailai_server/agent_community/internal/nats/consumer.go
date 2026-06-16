// Package nats provides NATS integration for the ACS service.
package nats

import (
	"context"
	"encoding/json"
	"fmt"
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

// Consumer processes pending messages from NATS and dispatches them to agents.
type Consumer struct {
	db             *gorm.DB
	publisher      *Publisher
	executor       *agent.Executor
	pool           *workpool.Pool
	contextBuilder *message.ContextBuilder
	maxChainLength int
	cfg            *config.Config
}

// NewConsumer creates a new NATS consumer.
func NewConsumer(
	db *gorm.DB,
	publisher *Publisher,
	executor *agent.Executor,
	pool *workpool.Pool,
	cfg *config.Config,
) *Consumer {
	return &Consumer{
		db:             db,
		publisher:      publisher,
		executor:       executor,
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

		if err := c.processMessage(msg, traceID); err != nil {
			logger.ErrorM(consumerModule, traceID, "failed to process pending message", "error", err)
			// Negative ack to trigger redelivery
			msg.Nak()
			return
		}
		msg.Ack()
	}
}

// processMessage processes a single pending message from NATS.
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

	// Acquire semaphore for concurrency control
	userID := payload.SenderID
	if err := c.pool.AcquireWithTimeout(30*time.Second, userID, groupID, traceID); err != nil {
		return fmt.Errorf("failed to acquire work pool slot: %w", err)
	}
	defer c.pool.Release(userID, groupID, traceID)

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

	// Process each target agent
	for _, target := range targets {
		if err := c.processAgentTarget(ctx, &group, members, &payload.GroupMessage, triggerInfo, target, traceID); err != nil {
			logger.ErrorM(consumerModule, traceID, "failed to process agent target",
				"agent_id", target.AgentID,
				"message_id", messageID,
				"error", err,
			)
			// Try to send system error message
			c.sendSystemError(ctx, &group, members, &payload.GroupMessage, target.AgentID, err.Error(), traceID)
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

// processAgentTarget processes a single agent target.
func (c *Consumer) processAgentTarget(
	ctx context.Context,
	group *models.Group,
	members []models.GroupMember,
	pendingMsg *models.GroupMessage,
	triggerInfo trigger.TriggerInfo,
	target trigger.AgentTarget,
	traceID string,
) error {
	// Find target agent member
	var agentMember *models.GroupMember
	for i := range members {
		if members[i].MemberID == target.AgentID {
			agentMember = &members[i]
			break
		}
	}

	if agentMember == nil {
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

	// Set member_status to processing before invoking agent
	if err := c.updateMemberStatus(agentMember.GroupID, agentMember.MemberID, models.MemberStatusProcessing, traceID); err != nil {
		logger.WarnM(consumerModule, traceID, "failed to set agent status to processing",
			"agent_id", agentMember.MemberID,
			"error", err,
		)
	}

	// Ensure status is always reset to idle when processing ends
	defer func() {
		if err := c.updateMemberStatus(agentMember.GroupID, agentMember.MemberID, models.MemberStatusIdle, traceID); err != nil {
			logger.WarnM(consumerModule, traceID, "failed to set agent status to idle",
				"agent_id", agentMember.MemberID,
				"error", err,
			)
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
		group, members, agentMember, allMessages,
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
		agentMember,
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
	if err := c.db.Save(agentMember).Error; err != nil {
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
	if err := c.db.Create(errorMsg).Error; err != nil {
		logger.ErrorM(consumerModule, traceID, "failed to save system error message", "error", err)
		return
	}

	// Publish error message to NATS
	if err := c.publisher.PublishSystemError(errorMsg); err != nil {
		logger.ErrorM(consumerModule, traceID, "failed to publish system error message", "error", err)
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

// recordProcessingStatus records the agent message processing status.
func (c *Consumer) recordProcessingStatus(groupID, messageID, agentID string, success bool, errorMsg string, traceID string) {
	status := models.ProcessingStatusCompleted
	if !success {
		status = models.ProcessingStatusFailed
	}

	record := &models.AgentMessageProcessing{
		GroupID:   groupID,
		MessageID: messageID,
		AgentID:   agentID,
		Status:    status,
	}

	if !success {
		record.ErrorMessage = errorMsg
	}

	record.ProcessedAtMs = time.Now().UnixMilli()

	if err := c.db.Create(record).Error; err != nil {
		logger.ErrorM(consumerModule, traceID, "failed to record processing status", "error", err)
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
