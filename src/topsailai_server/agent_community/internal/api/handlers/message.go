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
	"github.com/topsailai/agent-community/internal/nats"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/gorm"
)

// MessageHandler handles message-related HTTP requests.
type MessageHandler struct {
	db        *gorm.DB
	publisher *nats.Publisher
	evaluator *trigger.Evaluator
	log       *logger.Logger
}

// NewMessageHandler creates a new MessageHandler.
func NewMessageHandler(db *gorm.DB, publisher *nats.Publisher, evaluator *trigger.Evaluator, log *logger.Logger) *MessageHandler {
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
	SenderID           string `json:"sender_id" binding:"required"`
	SenderType         string `json:"sender_type" binding:"required"`
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

	// Validate sender type
	senderType := models.MemberType(req.SenderType)
	if senderType != models.MemberTypeUser &&
		senderType != models.MemberTypeManagerAgent &&
		senderType != models.MemberTypeWorkerAgent {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid sender_type"})
		return
	}

	// Verify sender is a member of the group
	var senderMember models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, req.SenderID).First(&senderMember).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusBadRequest, gin.H{"error": "sender is not a member of the group"})
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
		SenderID:           req.SenderID,
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
