// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/gorm"
)

// Publisher defines the interface for publishing messages to NATS.
type Publisher interface {
	PublishPendingMessageWithAgentID(groupID string, msg *models.GroupMessage, trigger interface{}, agentID string) error
	PublishMessageCreate(msg *models.GroupMessage) error
	PublishMessageModify(msg *models.GroupMessage) error
	PublishMessageDelete(msg *models.GroupMessage) error
}

// MessageHandler handles message-related HTTP requests.
type MessageHandler struct {
	db        *gorm.DB
	publisher Publisher
	evaluator *trigger.Evaluator
	log       *logger.Logger
}

// NewMessageHandler creates a new MessageHandler.
func NewMessageHandler(db *gorm.DB, publisher Publisher, evaluator *trigger.Evaluator, log *logger.Logger) *MessageHandler {
	return &MessageHandler{
		db:        db,
		publisher: publisher,
		evaluator: evaluator,
		log:       log,
	}
}

// CreateMessageRequest represents the request body for creating a message.
type CreateMessageRequest struct {
	MessageText        string `json:"message_text" binding:"required"`
	MessageAttachments string `json:"message_attachments"`
}

// UpdateMessageRequest represents the request body for updating a message.
type UpdateMessageRequest struct {
	MessageText        string `json:"message_text"`
	MessageAttachments string `json:"message_attachments"`
}

// MessageResponse represents a message in API responses.
type MessageResponse struct {
	GroupID            string      `json:"group_id"`
	MessageID          string      `json:"message_id"`
	MessageText        string      `json:"message_text"`
	MessageAttachments interface{} `json:"message_attachments"`
	SenderID           string      `json:"sender_id"`
	SenderType         string      `json:"sender_type"`
	ProcessedMsgID     string      `json:"processed_msg_id"`
	Mentions           interface{} `json:"mentions"`
	IsDeleted          bool        `json:"is_deleted"`
	DeleteAtMs         int64       `json:"delete_at_ms"`
	CreateAtMs         int64       `json:"create_at_ms"`
	UpdateAtMs         int64       `json:"update_at_ms"`
}

// ListMessagesResponse represents the response for listing messages.
type ListMessagesResponse struct {
	Items   []MessageResponse `json:"items"`
	Total   int64             `json:"total"`
	Offset  int               `json:"offset"`
	Limit   int               `json:"limit"`
	SortKey string            `json:"sort_key"`
	OrderBy string            `json:"order_by"`
}

// CreateMessage handles POST /api/v1/groups/:group_id/messages.
func (h *MessageHandler) CreateMessage(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	// Verify group exists
	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "group not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create message"})
		return
	}

	var req CreateMessageRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid create message request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Derive sender from authenticated account/session.
	authCtx, ok := middleware.GetAuthContext(c)
	if !ok || authCtx.Account == nil {
		h.log.Warn("api", traceID, "unauthenticated create message request")
		c.JSON(http.StatusUnauthorized, gin.H{"error": "unauthenticated"})
		return
	}
	senderID := authCtx.Account.AccountID
	senderType := models.MemberTypeUser

	// Verify sender is a member of the group
	var senderMember models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, senderID).First(&senderMember).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusForbidden, gin.H{"error": "sender is not a member of the group"})
			return
		}
		h.log.Error("api", traceID, "failed to verify sender membership", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create message"})
		return
	}

	// Get group members for mention extraction
	var members []models.GroupMember
	if err := h.db.Where("group_id = ?", groupID).Find(&members).Error; err != nil {
		h.log.Error("api", traceID, "failed to get members", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create message"})
		return
	}

	// Extract mentions from message text
	mentions := trigger.ExtractMentionsFromText(req.MessageText, members)
	mentionsJSON, _ := json.Marshal(mentions)

	// Parse attachments
	attachments := "[]"
	if req.MessageAttachments != "" {
		attachments = req.MessageAttachments
	}

	message := models.GroupMessage{
		GroupID:            groupID,
		MessageID:          uuid.New().String(),
		MessageText:        req.MessageText,
		MessageAttachments: attachments,
		SenderID:           senderID,
		SenderType:         senderType,
		Mentions:           string(mentionsJSON),
	}

	if err := h.db.Create(&message).Error; err != nil {
		h.log.Error("api", traceID, "failed to create message", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create message"})
		return
	}

	// Publish message create event
	if h.publisher != nil {
		if err := h.publisher.PublishMessageCreate(&message); err != nil {
			h.log.Warn("api", traceID, "failed to publish message create event", "error", err.Error())
		}
	}

	// Evaluate trigger
	h.evaluateAndTrigger(c, traceID, &message, members)

	h.log.Info("api", traceID, "message created", "group_id", groupID, "message_id", message.MessageID)
	c.JSON(http.StatusCreated, toMessageResponse(&message))
}

// evaluateAndTrigger evaluates if the message should trigger agents and publishes pending messages.
func (h *MessageHandler) evaluateAndTrigger(c *gin.Context, traceID string, msg *models.GroupMessage, members []models.GroupMember) {
	if h.evaluator == nil || h.publisher == nil {
		return
	}

	// Get context messages for sliding window check
	var contextMessages []models.GroupMessage
	if err := h.db.Where("group_id = ?", msg.GroupID).
		Order("create_at_ms ASC").
		Find(&contextMessages).Error; err != nil {
		h.log.Warn("api", traceID, "failed to get context messages for trigger evaluation", "error", err.Error())
		return
	}

	result, err := h.evaluator.Evaluate(c.Request.Context(), msg, members, contextMessages)
	if err != nil {
		h.log.Warn("api", traceID, "trigger evaluation failed", "error", err.Error())
		return
	}

	if !result.ShouldTrigger {
		return
	}

	// Publish pending message for each target
	triggerData := trigger.FormatTriggerForNATS(result.Trigger, result.Targets)
	for _, target := range result.Targets {
		if err := h.publisher.PublishPendingMessageWithAgentID(
			msg.GroupID, msg, triggerData, target.AgentID,
		); err != nil {
			h.log.Warn("api", traceID, "failed to publish pending message",
				"error", err.Error(),
				"agent_id", target.AgentID,
			)
		}
	}

	h.log.Info("api", traceID, "agent triggered",
		"message_id", msg.MessageID,
		"trigger_type", result.Trigger.Type,
		"targets_count", len(result.Targets),
	)
}

// ListMessages handles GET /api/v1/groups/:group_id/messages.
func (h *MessageHandler) ListMessages(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	// Verify group exists
	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "group not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list messages"})
		return
	}

	// Parse pagination
	offset, _ := strconv.Atoi(c.DefaultQuery("offset", "0"))
	if offset < 0 {
		offset = 0
	}
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "1000"))
	if limit <= 0 || limit > 1000 {
		limit = 1000
	}

	// Parse sorting
	sortKey := c.DefaultQuery("sort_key", "create_at_ms")
	orderBy := strings.ToLower(c.DefaultQuery("order_by", "desc"))
	if orderBy != "asc" && orderBy != "desc" {
		orderBy = "desc"
	}
	// Validate sort_key
	allowedSortKeys := map[string]bool{"create_at_ms": true, "update_at_ms": true, "message_id": true, "sender_id": true, "group_id": true}
	if !allowedSortKeys[sortKey] {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid sort_key"})
		return
	}

	// Build query
	query := h.db.Model(&models.GroupMessage{}).Where("group_id = ?", groupID)

	// Time range filtering
	if createRange := c.Query("create_at_ms"); createRange != "" {
		start, end, err := parseTimeRange(createRange)
		if err == nil {
			query = query.Where("create_at_ms BETWEEN ? AND ?", start, end)
		}
	}
	if updateRange := c.Query("update_at_ms"); updateRange != "" {
		start, end, err := parseTimeRange(updateRange)
		if err == nil {
			query = query.Where("update_at_ms BETWEEN ? AND ?", start, end)
		}
	}

	// Filter by processed_msg_id
	if processedMsgID := c.Query("processed_msg_id"); processedMsgID != "" {
		query = query.Where("processed_msg_id = ?", processedMsgID)
	}

	// Get total count
	var total int64
	if err := query.Count(&total).Error; err != nil {
		h.log.Error("api", traceID, "failed to count messages", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list messages"})
		return
	}

	// Execute query
	var messages []models.GroupMessage
	orderClause := sortKey + " " + orderBy
	if err := query.Order(orderClause).Offset(offset).Limit(limit).Find(&messages).Error; err != nil {
		h.log.Error("api", traceID, "failed to list messages", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list messages"})
		return
	}

	items := make([]MessageResponse, 0, len(messages))
	for i := range messages {
		items = append(items, toMessageResponse(&messages[i]))
	}

	c.JSON(http.StatusOK, ListMessagesResponse{
		Items:   items,
		Total:   total,
		Offset:  offset,
		Limit:   limit,
		SortKey: sortKey,
		OrderBy: orderBy,
	})
}

// UpdateMessage handles PUT /api/v1/groups/:group_id/messages/:message_id.
// Soft delete: clears message content but keeps the record.
func (h *MessageHandler) UpdateMessage(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	messageID := c.Param("message_id")

	var req UpdateMessageRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid update message request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	var message models.GroupMessage
	if err := h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&message).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "message not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get message", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update message"})
		return
	}

	// Update fields
	updates := make(map[string]interface{})
	if req.MessageText != "" {
		updates["message_text"] = req.MessageText
	}
	if req.MessageAttachments != "" {
		updates["message_attachments"] = req.MessageAttachments
	}
	updates["update_at_ms"] = time.Now().UnixMilli()

	if err := h.db.Model(&message).Updates(updates).Error; err != nil {
		h.log.Error("api", traceID, "failed to update message", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update message"})
		return
	}

	// Reload message
	h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&message)

	// Publish event
	if h.publisher != nil {
		if err := h.publisher.PublishMessageModify(&message); err != nil {
			h.log.Warn("api", traceID, "failed to publish message modify event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "message updated", "group_id", groupID, "message_id", messageID)
	c.JSON(http.StatusOK, toMessageResponse(&message))
}

// DeleteMessage handles DELETE /api/v1/groups/:group_id/messages/:message_id.
// Soft delete: clears message content but keeps the record (撤回消息).
func (h *MessageHandler) DeleteMessage(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	messageID := c.Param("message_id")

	var message models.GroupMessage
	if err := h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&message).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "message not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get message for delete", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete message"})
		return
	}

	// Soft delete: clear content but keep record
	updates := map[string]interface{}{
		"message_text":        "",
		"message_attachments": "[]",
		"is_deleted":          true,
		"delete_at_ms":        time.Now().UnixMilli(),
		"update_at_ms":        time.Now().UnixMilli(),
	}

	if err := h.db.Model(&message).Updates(updates).Error; err != nil {
		h.log.Error("api", traceID, "failed to delete message", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete message"})
		return
	}

	// Reload message
	h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&message)

	// Publish event
	if h.publisher != nil {
		if err := h.publisher.PublishMessageDelete(&message); err != nil {
			h.log.Warn("api", traceID, "failed to publish message delete event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "message deleted", "group_id", groupID, "message_id", messageID)
	c.Status(http.StatusNoContent)
}

// toMessageResponse converts a GroupMessage model to API response.
func toMessageResponse(m *models.GroupMessage) MessageResponse {
	var attachments interface{}
	json.Unmarshal([]byte(m.MessageAttachments), &attachments)

	var mentions interface{}
	json.Unmarshal([]byte(m.Mentions), &mentions)

	return MessageResponse{
		GroupID:            m.GroupID,
		MessageID:          m.MessageID,
		MessageText:        m.MessageText,
		MessageAttachments: attachments,
		SenderID:           m.SenderID,
		SenderType:         string(m.SenderType),
		ProcessedMsgID:     m.ProcessedMsgID,
		Mentions:           mentions,
		IsDeleted:          m.IsDeleted,
		DeleteAtMs:         m.DeleteAtMs,
		CreateAtMs:         m.CreateAtMs,
		UpdateAtMs:         m.UpdateAtMs,
	}
}


// TriggerMessage handles POST /api/v1/groups/:group_id/messages/:message_id/trigger.
// It manually triggers agent processing for a specific message, bypassing NO_TRIGGER_CASES.
func (h *MessageHandler) TriggerMessage(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	messageID := c.Param("message_id")

	// Parse optional body: { "agent_id": "optional-specific-agent" }
	var req struct {
		AgentID string `json:"agent_id"`
	}
	_ = c.ShouldBindJSON(&req) // optional, ignore error

	// 1. Verify group exists
	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "group not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get group for trigger", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to trigger message"})
		return
	}

	// 2. Verify message exists and belongs to the group
	var msg models.GroupMessage
	if err := h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&msg).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "message not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get message for trigger", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to trigger message"})
		return
	}

	// 3. If agent_id specified, verify agent is a member of the group
	var targetAgentID string
	if req.AgentID != "" {
		var member models.GroupMember
		if err := h.db.Where("group_id = ? AND member_id = ?", groupID, req.AgentID).First(&member).Error; err != nil {
			if err == gorm.ErrRecordNotFound {
				c.JSON(http.StatusNotFound, gin.H{"error": "agent not found"})
				return
			}
			h.log.Error("api", traceID, "failed to get member for trigger", "error", err.Error())
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to trigger message"})
			return
		}
		if !strings.HasSuffix(string(member.MemberType), "-agent") {
			c.JSON(http.StatusBadRequest, gin.H{"error": "specified member is not an agent"})
			return
		}
		targetAgentID = req.AgentID
	}

	// 4. Resolve target agents if no specific agent_id provided
	if targetAgentID == "" {
		var members []models.GroupMember
		if err := h.db.Where("group_id = ?", groupID).Find(&members).Error; err != nil {
			h.log.Error("api", traceID, "failed to get members for trigger", "error", err.Error())
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to trigger message"})
			return
		}

		result, err := h.evaluator.ResolveAgents(c.Request.Context(), &msg, members)
		if err != nil {
			h.log.Warn("api", traceID, "trigger evaluation failed", "error", err.Error())
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to evaluate trigger"})
			return
		}

		if !result.ShouldTrigger || len(result.Targets) == 0 {
			c.JSON(http.StatusAccepted, gin.H{
				"message_id": messageID,
				"group_id":   groupID,
				"trigger":    trigger.TriggerInfo{Type: trigger.TriggerTypeManual},
				"status":     "no_agents_to_trigger",
			})
			return
		}

		// Publish for each target
		triggerData := trigger.FormatTriggerForNATS(result.Trigger, result.Targets)
		for _, target := range result.Targets {
			if err := h.publisher.PublishPendingMessageWithAgentID(
				msg.GroupID, &msg, triggerData, target.AgentID,
			); err != nil {
				h.log.Warn("api", traceID, "failed to publish pending message",
					"error", err.Error(),
					"agent_id", target.AgentID,
				)
			}
		}

		c.JSON(http.StatusAccepted, gin.H{
			"message_id": messageID,
			"group_id":   groupID,
			"trigger":    trigger.TriggerInfo{Type: trigger.TriggerTypeManual, AgentID: result.Trigger.AgentID},
			"status":     "pending",
		})
		return
	}

	// 5. Publish pending message directly for specific agent (bypass Evaluate NO_TRIGGER_CASES)
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeManual, AgentID: targetAgentID}
	triggerData := trigger.FormatTriggerForNATS(triggerInfo, []trigger.AgentTarget{{AgentID: targetAgentID}})
	if err := h.publisher.PublishPendingMessageWithAgentID(
		msg.GroupID, &msg, triggerData, targetAgentID,
	); err != nil {
		h.log.Error("api", traceID, "failed to publish trigger", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to publish trigger: " + err.Error()})
		return
	}

	c.JSON(http.StatusAccepted, gin.H{
		"message_id": messageID,
		"group_id":   groupID,
		"trigger":    triggerInfo,
		"status":     "pending",
	})
}