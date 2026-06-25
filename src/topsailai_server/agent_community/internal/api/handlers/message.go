// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"context"
	"encoding/json"
	"errors"
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

// Evaluator defines the interface for trigger evaluation.
type Evaluator interface {
	Evaluate(ctx context.Context, msg *models.GroupMessage, members []models.GroupMember, contextMessages []models.GroupMessage) (*trigger.TriggerResult, error)
	ResolveAgents(ctx context.Context, msg *models.GroupMessage, members []models.GroupMember) (*trigger.TriggerResult, error)
}

// MessageHandler handles message-related HTTP requests.
type MessageHandler struct {
	db        *gorm.DB
	publisher Publisher
	evaluator Evaluator
	log       *logger.Logger
}

// NewMessageHandler creates a new MessageHandler.
func NewMessageHandler(db *gorm.DB, publisher Publisher, evaluator Evaluator, log *logger.Logger) *MessageHandler {
	return &MessageHandler{
		db:        db,
		publisher: publisher,
		evaluator: evaluator,
		log:       log,
	}
}

// CreateMessageRequest represents the request body for creating a message.
type CreateMessageRequest struct {
	MessageText        string          `json:"message_text" binding:"required"`
	MessageAttachments json.RawMessage `json:"message_attachments"`
	SenderID           string          `json:"sender_id"`
	SenderType         string          `json:"sender_type"`
	ProcessedMsgID     string          `json:"processed_msg_id"`
}

// UpdateMessageRequest represents the request body for updating a message.
type UpdateMessageRequest struct {
	MessageText        string          `json:"message_text"`
	MessageAttachments json.RawMessage `json:"message_attachments"`
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
}

// normalizeMessageAttachments accepts either a JSON array or a JSON string
// containing an array, validates it, and returns a compact JSON string for
// storage. It returns "[]" for nil/empty input and an error for invalid JSON
// or non-array values.
func normalizeMessageAttachments(raw json.RawMessage) (string, error) {
	if len(raw) == 0 {
		return "[]", nil
	}

	// Trim outer whitespace to simplify type detection.
	trimmed := strings.TrimSpace(string(raw))
	if trimmed == "" || trimmed == "null" {
		return "[]", nil
	}

	// If the value is a JSON string, unwrap it and validate the inner content.
	if len(trimmed) >= 2 && trimmed[0] == '"' && trimmed[len(trimmed)-1] == '"' {
		var inner string
		if err := json.Unmarshal([]byte(trimmed), &inner); err != nil {
			return "", errors.New("message_attachments is not valid JSON")
		}
		trimmed = strings.TrimSpace(inner)
	}

	if trimmed == "" || trimmed == "null" {
		return "[]", nil
	}

	if trimmed[0] != '[' {
		return "", errors.New("message_attachments must be a JSON array")
	}

	var arr []interface{}
	if err := json.Unmarshal([]byte(trimmed), &arr); err != nil {
		return "", errors.New("message_attachments is not valid JSON")
	}

	compact, err := json.Marshal(arr)
	if err != nil {
		return "", errors.New("message_attachments is not valid JSON")
	}
	return string(compact), nil
}

// CreateMessage handles POST /api/v1/groups/:group_id/messages.
func (h *MessageHandler) CreateMessage(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	authCtx, ok := getAuthContextOrAbort(c)
	if !ok {
		return
	}

	// Verify group exists
	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "group not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get group", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to create message", traceID)
		return
	}

	var req CreateMessageRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid create message request", "error", err.Error())
		writeErrorResponse(c, http.StatusBadRequest, err.Error(), traceID)
		return
	}

	// Validate processed_msg_id if provided.
	if req.ProcessedMsgID != "" {
		if err := h.validateProcessedMsgID(groupID, req.ProcessedMsgID, ""); err != nil {
			h.log.Warn("api", traceID, "invalid processed_msg_id", "error", err.Error())
			writeErrorResponse(c, http.StatusBadRequest, err.Error(), traceID)
			return
		}
	}

	// Resolve sender identity.
	senderID, senderType, status, err := h.resolveSenderIdentity(authCtx, groupID, req.SenderID, req.SenderType)
	if err != nil {
		h.log.Warn("api", traceID, "failed to resolve sender identity", "error", err.Error())
		writeErrorResponse(c, status, err.Error(), traceID)
		return
	}

	// Authorization: when sender is not overridden, admin can send to any group;
	// otherwise the caller must be a member (enforced by resolveSenderIdentity).
	if req.SenderID == "" && req.SenderType == "" && !isAdmin(authCtx) {
		var senderMember models.GroupMember
		if err := h.db.Where("group_id = ? AND member_id = ?", groupID, senderID).First(&senderMember).Error; err != nil {
			if err == gorm.ErrRecordNotFound {
				writeErrorResponse(c, http.StatusForbidden, "sender is not a member of the group", traceID)
				return
			}
			h.log.Error("api", traceID, "failed to verify sender membership", "error", err.Error())
			writeErrorResponse(c, http.StatusInternalServerError, "failed to create message", traceID)
			return
		}
	}

	// Get group members for mention extraction
	var members []models.GroupMember
	if err := h.db.Where("group_id = ?", groupID).Find(&members).Error; err != nil {
		h.log.Error("api", traceID, "failed to get members", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to create message", traceID)
		return
	}

	// Extract mentions from message text
	mentions := trigger.ExtractMentionsFromText(req.MessageText, members)
	mentionsJSON, _ := json.Marshal(mentions)

	// Normalize attachments
	attachments, err := normalizeMessageAttachments(req.MessageAttachments)
	if err != nil {
		h.log.Warn("api", traceID, "invalid message attachments", "error", err.Error())
		writeErrorResponse(c, http.StatusBadRequest, err.Error(), traceID)
		return
	}

	message := models.GroupMessage{
		GroupID:            groupID,
		MessageID:          uuid.New().String(),
		MessageText:        req.MessageText,
		MessageAttachments: attachments,
		SenderID:           senderID,
		SenderType:         senderType,
		ProcessedMsgID:     req.ProcessedMsgID,
		Mentions:           string(mentionsJSON),
	}

	if err := h.db.Create(&message).Error; err != nil {
		h.log.Error("api", traceID, "failed to create message", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to create message", traceID)
		return
	}

	// Publish message create event
	if err := h.publisher.PublishMessageCreate(&message); err != nil {
		h.log.Warn("api", traceID, "failed to publish message create event", "error", err.Error())
	}

	// Evaluate trigger
	h.evaluateAndTrigger(c, traceID, &message, members)

	h.log.Info("api", traceID, "message created", "group_id", groupID, "message_id", message.MessageID)
	writeDataResponse(c, http.StatusCreated, toMessageResponse(&message), traceID)
}

// validateProcessedMsgID validates that the referenced message exists in the same group
// and is not deleted. newMessageID is the ID of the message being created; pass empty
// when the new ID is not yet known.
func (h *MessageHandler) validateProcessedMsgID(groupID, processedMsgID, newMessageID string) error {
	if processedMsgID == "" {
		return nil
	}
	if newMessageID != "" && processedMsgID == newMessageID {
		return errors.New("processed_msg_id cannot reference the message itself")
	}
	var refMsg models.GroupMessage
	if err := h.db.Where("group_id = ? AND message_id = ?", groupID, processedMsgID).First(&refMsg).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			return errors.New("processed_msg_id references a non-existent message")
		}
		return errors.New("failed to validate processed_msg_id")
	}
	if refMsg.IsDeleted || refMsg.DeleteAtMs > 0 {
		return errors.New("processed_msg_id references a deleted message")
	}
	return nil
}

// resolveSenderIdentity determines the sender_id and sender_type for a new message.
// If reqSenderID and reqSenderType are empty, it falls back to the authenticated account.
// If provided, the caller must be a member of the group and the requested sender must
// either match the caller's own member record or be a manager-agent member.
func (h *MessageHandler) resolveSenderIdentity(authCtx middleware.AuthContext, groupID, reqSenderID, reqSenderType string) (string, models.MemberType, int, error) {
	// Default: derive from authenticated account.
	if reqSenderID == "" && reqSenderType == "" {
		return authCtx.Account.AccountID, models.MemberTypeUser, 0, nil
	}

	// If one is provided, both must be provided.
	if reqSenderID == "" || reqSenderType == "" {
		return "", "", http.StatusBadRequest, errors.New("sender_id and sender_type must be provided together")
	}

	// Caller must be a member of the group to use sender override.
	var callerMember models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, authCtx.Account.AccountID).First(&callerMember).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			return "", "", http.StatusForbidden, errors.New("caller is not a member of the group")
		}
		return "", "", http.StatusInternalServerError, errors.New("failed to resolve sender identity")
	}

	// Look up the requested sender member.
	var senderMember models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, reqSenderID).First(&senderMember).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			return "", "", http.StatusBadRequest, errors.New("sender_id does not match a group member")
		}
		return "", "", http.StatusInternalServerError, errors.New("failed to resolve sender identity")
	}

	// sender_type must match the member's actual type.
	if string(senderMember.MemberType) != reqSenderType {
		return "", "", http.StatusBadRequest, errors.New("sender_type does not match the group member")
	}

	// Allowed if the requested sender matches the caller's own member record,
	// or if the requested sender is a manager-agent member.
	if senderMember.MemberID == callerMember.MemberID && senderMember.MemberType == callerMember.MemberType {
		return senderMember.MemberID, senderMember.MemberType, 0, nil
	}
	if senderMember.IsManagerAgent() {
		return senderMember.MemberID, senderMember.MemberType, 0, nil
	}

	return "", "", http.StatusForbidden, errors.New("caller is not authorized to send as the specified sender")
}

// evaluateAndTrigger evaluates if the message should trigger agents and publishes pending messages.
func (h *MessageHandler) evaluateAndTrigger(c *gin.Context, traceID string, msg *models.GroupMessage, members []models.GroupMember) {
	// Defense-in-depth: never trigger messages that already have a processed_msg_id.
	// The evaluator also checks this, but guarding here ensures a buggy evaluator or
	// future caller cannot accidentally publish a pending message for a processed message.
	if msg.ProcessedMsgID != "" {
		h.log.Debug("api", traceID, "skipping trigger for processed message", "message_id", msg.MessageID, "processed_msg_id", msg.ProcessedMsgID)
		return
	}

	// Get context messages for sliding window check. Exclude deleted messages
	// here as an optimization; the evaluator also filters them defensively.
	var contextMessages []models.GroupMessage
	if err := h.db.Where("group_id = ? AND is_deleted = ?", msg.GroupID, false).
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

	authCtx, ok := getAuthContextOrAbort(c)
	if !ok {
		return
	}

	// Verify group exists
	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "group not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get group", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to list messages", traceID)
		return
	}

	// Authorization: admin can list any group; user can list only member groups.
	allowed, err := canListGroupMembers(h.db, authCtx, groupID)
	if err != nil {
		h.log.Error("api", traceID, "failed to check list messages permission", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to list messages", traceID)
		return
	}
	if !allowed {
		writeErrorResponse(c, http.StatusForbidden, "forbidden", traceID)
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
		writeErrorResponse(c, http.StatusBadRequest, "invalid sort_key", traceID)
		return
	}

	// Determine whether the caller wants to include soft-deleted messages.
	// Only admin users may request this; non-admin callers are rejected when
	// they explicitly pass include_deleted=true.
	includeDeletedParam := strings.ToLower(c.Query("include_deleted"))
	includeDeleted := includeDeletedParam == "true" || includeDeletedParam == "1"
	if includeDeleted && !isAdmin(authCtx) {
		writeErrorResponse(c, http.StatusForbidden, "only admin can use include_deleted=true", traceID)
		return
	}

	// Build query. By default exclude soft-deleted messages; include them only
	// when an admin explicitly requests it.
	query := h.db.Model(&models.GroupMessage{}).Where("group_id = ?", groupID)
	if !includeDeleted {
		query = query.Where("is_deleted = ?", false)
	}

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
		writeErrorResponse(c, http.StatusInternalServerError, "failed to list messages", traceID)
		return
	}

	// Execute query
	var messages []models.GroupMessage
	orderClause := sortKey + " " + orderBy
	if err := query.Order(orderClause).Offset(offset).Limit(limit).Find(&messages).Error; err != nil {
		h.log.Error("api", traceID, "failed to list messages", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to list messages", traceID)
		return
	}

	items := make([]MessageResponse, 0, len(messages))
	for i := range messages {
		items = append(items, toMessageResponse(&messages[i]))
	}

	writeListResponse(c, http.StatusOK, items, total, offset, limit, traceID)
}
// GetMessage handles GET /api/v1/groups/:group_id/messages/:message_id.
func (h *MessageHandler) GetMessage(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	messageID := c.Param("message_id")

	authCtx, ok := getAuthContextOrAbort(c)
	if !ok {
		return
	}

	// Verify group exists
	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "group not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get group", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to get message", traceID)
		return
	}

	// Authorization: admin can get any group message; user can get only member groups.
	allowed, err := canListGroupMembers(h.db, authCtx, groupID)
	if err != nil {
		h.log.Error("api", traceID, "failed to check get message permission", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to get message", traceID)
		return
	}
	if !allowed {
		writeErrorResponse(c, http.StatusForbidden, "forbidden", traceID)
		return
	}

	// Fetch message, excluding soft-deleted records.
	var message models.GroupMessage
	if err := h.db.Where("group_id = ? AND message_id = ? AND is_deleted = ?", groupID, messageID, false).First(&message).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "message not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get message", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to get message", traceID)
		return
	}

	h.log.Info("api", traceID, "message retrieved", "group_id", groupID, "message_id", messageID)
	writeDataResponse(c, http.StatusOK, toMessageResponse(&message), traceID)
}


// UpdateMessage handles PUT /api/v1/groups/:group_id/messages/:message_id.
func (h *MessageHandler) UpdateMessage(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	messageID := c.Param("message_id")

	authCtx, ok := getAuthContextOrAbort(c)
	if !ok {
		return
	}

	var req UpdateMessageRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid update message request", "error", err.Error())
		writeErrorResponse(c, http.StatusBadRequest, err.Error(), traceID)
		return
	}

	var message models.GroupMessage
	if err := h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&message).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "message not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get message", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to update message", traceID)
		return
	}

	// Authorization: admin can update any message; user can update only their own.
	if !isAdmin(authCtx) && message.SenderID != authCtx.Account.AccountID {
		writeErrorResponse(c, http.StatusForbidden, "forbidden", traceID)
		return
	}

	// Update fields
	updates := make(map[string]interface{})
	if req.MessageText != "" {
		updates["message_text"] = req.MessageText

		// Re-extract mentions from the updated text using current group members.
		var members []models.GroupMember
		if err := h.db.Where("group_id = ?", groupID).Find(&members).Error; err != nil {
			h.log.Error("api", traceID, "failed to get members for mention extraction", "error", err.Error())
			writeErrorResponse(c, http.StatusInternalServerError, "failed to update message", traceID)
			return
		}
		mentions := trigger.ExtractMentionsFromText(req.MessageText, members)
		mentionsJSON, _ := json.Marshal(mentions)
		updates["mentions"] = string(mentionsJSON)
	}
	if len(req.MessageAttachments) > 0 {
		attachments, err := normalizeMessageAttachments(req.MessageAttachments)
		if err != nil {
			h.log.Warn("api", traceID, "invalid message attachments", "error", err.Error())
			writeErrorResponse(c, http.StatusBadRequest, err.Error(), traceID)
			return
		}
		updates["message_attachments"] = attachments
	}
	updates["update_at_ms"] = time.Now().UnixMilli()

	if err := h.db.Model(&message).Updates(updates).Error; err != nil {
		h.log.Error("api", traceID, "failed to update message", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to update message", traceID)
		return
	}
	// Reload message
	h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&message)

	// Publish event
	if err := h.publisher.PublishMessageModify(&message); err != nil {
		h.log.Warn("api", traceID, "failed to publish message modify event", "error", err.Error())
	}

	h.log.Info("api", traceID, "message updated", "group_id", groupID, "message_id", messageID)
	writeDataResponse(c, http.StatusOK, toMessageResponse(&message), traceID)
}

// DeleteMessage handles DELETE /api/v1/groups/:group_id/messages/:message_id.
// Soft delete: clears message content but keeps the record (撤回消息).
func (h *MessageHandler) DeleteMessage(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	messageID := c.Param("message_id")

	authCtx, ok := getAuthContextOrAbort(c)
	if !ok {
		return
	}

	var message models.GroupMessage
	if err := h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&message).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "message not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get message for delete", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to delete message", traceID)
		return
	}

	// Authorization: admin can delete any message; user can delete only their own.
	if !isAdmin(authCtx) && message.SenderID != authCtx.Account.AccountID {
		writeErrorResponse(c, http.StatusForbidden, "forbidden", traceID)
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
		writeErrorResponse(c, http.StatusInternalServerError, "failed to delete message", traceID)
		return
	}

	// Reload message
	h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&message)
	// Publish event
	if err := h.publisher.PublishMessageDelete(&message); err != nil {
		h.log.Warn("api", traceID, "failed to publish message delete event", "error", err.Error())
	}

	h.log.Info("api", traceID, "message deleted", "group_id", groupID, "message_id", messageID)
	writeDataResponse(c, http.StatusOK, gin.H{"message": "message deleted"}, traceID)
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

	authCtx, ok := getAuthContextOrAbort(c)
	if !ok {
		return
	}

	// Parse optional body: { "agent_id": "optional-specific-agent" }
	var req struct {
		AgentID string `json:"agent_id"`
	}
	_ = c.ShouldBindJSON(&req) // optional, ignore error

	// 1. Verify group exists
	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "group not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get group for trigger", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to trigger message", traceID)
		return
	}

	// Authorization: admin can trigger any message; user can trigger only member groups.
	allowed, err := canListGroupMembers(h.db, authCtx, groupID)
	if err != nil {
		h.log.Error("api", traceID, "failed to check trigger permission", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to trigger message", traceID)
		return
	}
	if !allowed {
		writeErrorResponse(c, http.StatusForbidden, "forbidden", traceID)
		return
	}

	// 2. Verify message exists and belongs to the group
	var msg models.GroupMessage
	if err := h.db.Where("group_id = ? AND message_id = ?", groupID, messageID).First(&msg).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "message not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get message for trigger", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to trigger message", traceID)
		return
	}

	// 3. If agent_id specified, verify agent is a member of the group
	var targetAgentID string
	if req.AgentID != "" {
		var member models.GroupMember
		if err := h.db.Where("group_id = ? AND member_id = ?", groupID, req.AgentID).First(&member).Error; err != nil {
			if err == gorm.ErrRecordNotFound {
				writeErrorResponse(c, http.StatusNotFound, "agent not found", traceID)
				return
			}
			h.log.Error("api", traceID, "failed to get member for trigger", "error", err.Error())
			writeErrorResponse(c, http.StatusInternalServerError, "failed to trigger message", traceID)
			return
		}
		if !strings.HasSuffix(string(member.MemberType), "-agent") {
			writeErrorResponse(c, http.StatusBadRequest, "specified member is not an agent", traceID)
			return
		}
		targetAgentID = req.AgentID
	}

	// 4. Resolve target agents if no specific agent_id provided
	if targetAgentID == "" {
		var members []models.GroupMember
		if err := h.db.Where("group_id = ?", groupID).Find(&members).Error; err != nil {
			h.log.Error("api", traceID, "failed to get members for trigger", "error", err.Error())
			writeErrorResponse(c, http.StatusInternalServerError, "failed to trigger message", traceID)
			return
		}

		result, err := h.evaluator.ResolveAgents(c.Request.Context(), &msg, members)
		if err != nil {
			h.log.Warn("api", traceID, "trigger evaluation failed", "error", err.Error())
			writeErrorResponse(c, http.StatusInternalServerError, "failed to evaluate trigger", traceID)
			return
		}

		if !result.ShouldTrigger || len(result.Targets) == 0 {
			writeDataResponse(c, http.StatusAccepted, gin.H{
				"message_id": messageID,
				"group_id":   groupID,
				"trigger":    trigger.TriggerInfo{Type: trigger.TriggerTypeManual},
				"status":     "no_agents_to_trigger",
			}, traceID)
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

		writeDataResponse(c, http.StatusAccepted, gin.H{
			"message_id": messageID,
			"group_id":   groupID,
			"trigger":    trigger.TriggerInfo{Type: trigger.TriggerTypeManual, AgentID: result.Trigger.AgentID},
			"status":     "pending",
		}, traceID)
		return
	}

	// 5. Publish pending message directly for specific agent (bypass Evaluate NO_TRIGGER_CASES)
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeManual, AgentID: targetAgentID}
	triggerData := trigger.FormatTriggerForNATS(triggerInfo, []trigger.AgentTarget{{AgentID: targetAgentID}})
	if err := h.publisher.PublishPendingMessageWithAgentID(
		msg.GroupID, &msg, triggerData, targetAgentID,
	); err != nil {
		h.log.Error("api", traceID, "failed to publish trigger", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to publish trigger: "+err.Error(), traceID)
		return
	}

	writeDataResponse(c, http.StatusAccepted, gin.H{
		"message_id": messageID,
		"group_id":   groupID,
		"trigger":    triggerInfo,
		"status":     "pending",
	}, traceID)
}
