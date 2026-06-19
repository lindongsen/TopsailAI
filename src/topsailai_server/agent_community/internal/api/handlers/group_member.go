// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/gorm"
)

// memberIDRegex validates that member_id contains only alphanumeric characters, hyphens, and underscores.
var memberIDRegex = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

// memberNameRegex validates that member_name contains only alphanumeric characters, hyphens, and underscores.
var memberNameRegex = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

// GroupMemberPublisher is the subset of the NATS publisher used by
// GroupMemberHandler. It is kept minimal to keep handler tests isolated.
type GroupMemberPublisher interface {
	PublishGroupMemberCreate(member *models.GroupMember) error
	PublishGroupMemberModify(member *models.GroupMember) error
	PublishGroupMemberDelete(groupID, memberID string) error
}

// GroupMemberHandler handles group member-related HTTP requests.
type GroupMemberHandler struct {
	db        *gorm.DB
	publisher GroupMemberPublisher
	log       *logger.Logger
}

// NewGroupMemberHandler creates a new GroupMemberHandler.
func NewGroupMemberHandler(db *gorm.DB, publisher GroupMemberPublisher, log *logger.Logger) *GroupMemberHandler {
	return &GroupMemberHandler{
		db:        db,
		publisher: publisher,
		log:       log,
	}
}

// MemberInterfaceField accepts either a JSON string or a JSON object and
// normalizes it to a compact JSON string for storage.
type MemberInterfaceField struct {
	value string
}

// UnmarshalJSON implements json.Unmarshaler. It accepts:
//   - a JSON string whose content is itself valid JSON (typically an object)
//   - a JSON object/array/value directly
// In both cases the stored representation is a compact JSON string.
func (m *MemberInterfaceField) UnmarshalJSON(data []byte) error {
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) == 0 || string(trimmed) == "null" {
		m.value = ""
		return nil
	}

	// Case 1: JSON string containing a JSON-encoded value.
	if trimmed[0] == '"' {
		var s string
		if err := json.Unmarshal(trimmed, &s); err != nil {
			return fmt.Errorf("member_interface is not a valid JSON string: %w", err)
		}
		if s == "" {
			m.value = ""
			return nil
		}
		if !json.Valid([]byte(s)) {
			return fmt.Errorf("member_interface string content is not valid JSON")
		}
		m.value = s
		return nil
	}

	// Case 2: JSON value (object, array, number, bool).
	if !json.Valid(trimmed) {
		return fmt.Errorf("member_interface is not valid JSON")
	}
	var v interface{}
	if err := json.Unmarshal(trimmed, &v); err != nil {
		return fmt.Errorf("member_interface could not be parsed: %w", err)
	}
	compact, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("member_interface could not be compacted: %w", err)
	}
	m.value = string(compact)
	return nil
}

// MarshalJSON implements json.Marshaler.
func (m MemberInterfaceField) MarshalJSON() ([]byte, error) {
	return json.Marshal(m.value)
}

// String returns the normalized JSON string representation.
func (m MemberInterfaceField) String() string {
	return m.value
}

// JoinGroupRequest represents the request body for joining a group.
type JoinGroupRequest struct {
	MemberID          string               `json:"member_id" binding:"required"`
	MemberName        string               `json:"member_name" binding:"required"`
	MemberDescription string               `json:"member_description"`
	MemberType        string               `json:"member_type" binding:"required"`
	MemberInterface   MemberInterfaceField `json:"member_interface"`
}

// UpdateMemberRequest represents the request body for updating a member.
type UpdateMemberRequest struct {
	MemberName        string               `json:"member_name"`
	MemberDescription string               `json:"member_description"`
	MemberStatus      string               `json:"member_status"`
	MemberInterface   MemberInterfaceField `json:"member_interface"`
	LastReadMessageID string               `json:"last_read_message_id"`
}

// GroupMemberResponse represents a group member in API responses.
type GroupMemberResponse struct {
	GroupID           string `json:"group_id"`
	MemberID          string `json:"member_id"`
	MemberName        string `json:"member_name"`
	MemberDescription string `json:"member_description"`
	MemberStatus      string `json:"member_status"`
	MemberType        string `json:"member_type"`
	MemberInterface   string `json:"member_interface"`
	LastReadMessageID string `json:"last_read_message_id"`
	CreateAtMs        int64  `json:"create_at_ms"`
	UpdateAtMs        int64  `json:"update_at_ms"`
}

// ListGroupMembersResponse represents the response for listing group members.
type ListGroupMembersResponse struct {
	Items   []GroupMemberResponse `json:"items"`
	Total   int64                 `json:"total"`
	Offset  int                   `json:"offset"`
	Limit   int                   `json:"limit"`
	SortKey string                `json:"sort_key"`
	OrderBy string                `json:"order_by"`
}

// JoinGroup handles POST /api/v1/groups/:group_id/members.
func (h *GroupMemberHandler) JoinGroup(c *gin.Context) {
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
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to join group"})
		return
	}

	var req JoinGroupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid join group request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	// Validate member_id
	if !memberIDRegex.MatchString(req.MemberID) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid member_id: must contain only alphanumeric characters, hyphens, and underscores"})
		return
	}

	// Validate member_name
	if !memberNameRegex.MatchString(req.MemberName) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid member_name: must contain only alphanumeric characters, hyphens, and underscores"})
		return
	}

	// Validate member type
	memberType := models.MemberType(req.MemberType)
	if memberType != models.MemberTypeUser &&
		memberType != models.MemberTypeManagerAgent &&
		memberType != models.MemberTypeWorkerAgent {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid member_type"})
		return
	}
	member := models.GroupMember{
		GroupID:           groupID,
		MemberID:          req.MemberID,
		MemberName:        req.MemberName,
		MemberDescription: req.MemberDescription,
		MemberType:        memberType,
		MemberStatus:      models.MemberStatusOnline,
		MemberInterface:   req.MemberInterface.String(),
	}
	// Check for duplicate member
	var existingMember models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, req.MemberID).First(&existingMember).Error; err == nil {
		c.JSON(http.StatusConflict, gin.H{"error": "member already exists in group"})
		return
	}

	if err := h.db.Create(&member).Error; err != nil {
		h.log.Error("api", traceID, "failed to join group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to join group"})
		return
	}

	// Publish event
	if h.publisher != nil {
		if err := h.publisher.PublishGroupMemberCreate(&member); err != nil {
			h.log.Warn("api", traceID, "failed to publish member join event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "member joined group", "group_id", groupID, "member_id", req.MemberID)
	c.JSON(http.StatusCreated, toGroupMemberResponse(&member))
}

// ListGroupMembers handles GET /api/v1/groups/:group_id/members.
func (h *GroupMemberHandler) ListGroupMembers(c *gin.Context) {
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
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list members"})
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
	allowedSortKeys := map[string]bool{"create_at_ms": true, "update_at_ms": true, "member_id": true, "member_name": true, "member_type": true, "member_status": true}
	if !allowedSortKeys[sortKey] {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid sort_key"})
		return
	}

	// Build query
	query := h.db.Model(&models.GroupMember{}).Where("group_id = ?", groupID)

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
		h.log.Error("api", traceID, "failed to count members", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list members"})
		return
	}

	// Execute query
	var members []models.GroupMember
	orderClause := sortKey + " " + orderBy
	if err := query.Order(orderClause).Offset(offset).Limit(limit).Find(&members).Error; err != nil {
		h.log.Error("api", traceID, "failed to list members", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list members"})
		return
	}

	items := make([]GroupMemberResponse, 0, len(members))
	for i := range members {
		items = append(items, toGroupMemberResponse(&members[i]))
	}

	c.JSON(http.StatusOK, ListGroupMembersResponse{
		Items:   items,
		Total:   total,
		Offset:  offset,
		Limit:   limit,
		SortKey: sortKey,
		OrderBy: orderBy,
	})
}

// UpdateMember handles PUT /api/v1/groups/:group_id/members/:member_id.
func (h *GroupMemberHandler) UpdateMember(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	memberID := c.Param("member_id")

	var req UpdateMemberRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid update member request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	var member models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, memberID).First(&member).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "member not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get member", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update member"})
		return
	}

	// Validate member_name if provided
	if req.MemberName != "" && !memberNameRegex.MatchString(req.MemberName) {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid member_name: must contain only alphanumeric characters, hyphens, and underscores"})
		return
	}

	// Update fields
	updates := make(map[string]interface{})
	if req.MemberName != "" {
		updates["member_name"] = req.MemberName
	}
	if req.MemberDescription != "" {
		updates["member_description"] = req.MemberDescription
	}
	if req.MemberStatus != "" {
		updates["member_status"] = req.MemberStatus
	}
	if req.MemberInterface.String() != "" {
		updates["member_interface"] = req.MemberInterface.String()
	}
	if req.LastReadMessageID != "" {
		updates["last_read_message_id"] = req.LastReadMessageID
	}
	updates["update_at_ms"] = time.Now().UnixMilli()

	if err := h.db.Model(&member).Updates(updates).Error; err != nil {
		h.log.Error("api", traceID, "failed to update member", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update member"})
		return
	}

	// Reload member
	h.db.Where("group_id = ? AND member_id = ?", groupID, memberID).First(&member)

	// Publish modify event when member_status changes so subscribers can observe transitions
	if h.publisher != nil && req.MemberStatus != "" {
		if err := h.publisher.PublishGroupMemberModify(&member); err != nil {
			h.log.Warn("api", traceID, "failed to publish member modify event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "member updated", "group_id", groupID, "member_id", memberID)
	c.JSON(http.StatusOK, toGroupMemberResponse(&member))
}

// LeaveGroup handles DELETE /api/v1/groups/:group_id/members/:member_id.
func (h *GroupMemberHandler) LeaveGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	memberID := c.Param("member_id")

	var member models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, memberID).First(&member).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "member not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get member for leave", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to leave group"})
		return
	}

	if err := h.db.Delete(&member).Error; err != nil {
		h.log.Error("api", traceID, "failed to leave group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to leave group"})
		return
	}

	// Publish event
	if h.publisher != nil {
		if err := h.publisher.PublishGroupMemberDelete(groupID, memberID); err != nil {
			h.log.Warn("api", traceID, "failed to publish member leave event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "member left group", "group_id", groupID, "member_id", memberID)
	c.String(http.StatusNoContent, "")
}
func toGroupMemberResponse(m *models.GroupMember) GroupMemberResponse {
	return GroupMemberResponse{
		GroupID:           m.GroupID,
		MemberID:          m.MemberID,
		MemberName:        m.MemberName,
		MemberDescription: m.MemberDescription,
		MemberStatus:      string(m.MemberStatus),
		MemberType:        string(m.MemberType),
		MemberInterface:   m.MemberInterface,
		LastReadMessageID: m.LastReadMessageID,
		CreateAtMs:        m.CreateAtMs,
		UpdateAtMs:        m.UpdateAtMs,
	}
}
