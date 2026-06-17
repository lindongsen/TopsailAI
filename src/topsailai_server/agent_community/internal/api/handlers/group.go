// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"
)

// GroupPublisher defines the interface for publishing group-related events.
type GroupPublisher interface {
	PublishGroupCreate(group *models.Group) error
	PublishGroupModify(group *models.Group) error
	PublishGroupDelete(groupID string) error
	PublishGroupMemberCreate(member *models.GroupMember) error
}

// GroupHandler handles group-related HTTP requests.
type GroupHandler struct {
	db        *gorm.DB
	publisher GroupPublisher
	cfg       *config.Config
	log       *logger.Logger
}

// NewGroupHandler creates a new GroupHandler.
func NewGroupHandler(db *gorm.DB, publisher GroupPublisher, cfg *config.Config, log *logger.Logger) *GroupHandler {
	return &GroupHandler{
		db:        db,
		publisher: publisher,
		cfg:       cfg,
		log:       log,
	}
}

// CreateGroupRequest represents the request body for creating a group.
type CreateGroupRequest struct {
	GroupName    string `json:"group_name" binding:"required"`
	GroupContext string `json:"group_context"`
	GroupKey     string `json:"group_key"`
}

// UpdateGroupRequest represents the request body for updating a group.
type UpdateGroupRequest struct {
	GroupName    string `json:"group_name"`
	GroupContext string `json:"group_context"`
	GroupKey     string `json:"group_key"`
}

// GroupResponse represents a group in API responses.
type GroupResponse struct {
	GroupID      string `json:"group_id"`
	GroupName    string `json:"group_name"`
	GroupContext string `json:"group_context"`
	GroupKey     string `json:"group_key"`
	CreateAtMs   int64  `json:"create_at_ms"`
	UpdateAtMs   int64  `json:"update_at_ms"`
}

// ListGroupsResponse represents the response for listing groups.
type ListGroupsResponse struct {
	Items   []GroupResponse `json:"items"`
	Total   int64           `json:"total"`
	Offset  int             `json:"offset"`
	Limit   int             `json:"limit"`
	SortKey string          `json:"sort_key"`
	OrderBy string          `json:"order_by"`
}

// hashGroupKey hashes a group key using bcrypt.
func hashGroupKey(key string) (string, error) {
	if key == "" {
		return "", nil
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(key), bcrypt.DefaultCost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

// CreateGroup handles POST /api/v1/groups.
// When ACS_GROUP_MANAGER_AGENT_CMD_CHAT is configured, a default manager-agent
// member is automatically joined to the new group inside the same transaction.
func (h *GroupHandler) CreateGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)

	var req CreateGroupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid create group request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	hashedKey, err := hashGroupKey(req.GroupKey)
	if err != nil {
		h.log.Error("api", traceID, "failed to hash group key", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to process group key"})
		return
	}

	now := time.Now().UnixMilli()
	group := models.Group{
		GroupID:      uuid.New().String(),
		GroupName:    req.GroupName,
		GroupContext: req.GroupContext,
		GroupKey:     hashedKey,
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}

	var managerMember *models.GroupMember

	// Create group and optional default manager-agent atomically.
	if err := h.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&group).Error; err != nil {
			return err
		}

		if h.cfg != nil && h.cfg.Agent.ManagerAgent.CmdChat != "" {
			member, err := h.buildManagerAgentMember(group.GroupID)
			if err != nil {
				return err
			}
			if err := tx.Create(member).Error; err != nil {
				return err
			}
			managerMember = member
		}

		return nil
	}); err != nil {
		h.log.Error("api", traceID, "failed to create group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create group"})
		return
	}

	// Publish events after the transaction commits.
	if h.publisher != nil {
		if err := h.publisher.PublishGroupCreate(&group); err != nil {
			h.log.Warn("api", traceID, "failed to publish group create event", "error", err.Error())
		}

		if managerMember != nil {
			if err := h.publisher.PublishGroupMemberCreate(managerMember); err != nil {
				h.log.Warn("api", traceID, "failed to publish manager-agent member create event", "error", err.Error())
			}
		}
	}

	h.log.Info("api", traceID, "group created", "group_id", group.GroupID)
	c.JSON(http.StatusCreated, toGroupResponse(&group))
}

// buildManagerAgentMember constructs the default manager-agent group member from config.
func (h *GroupHandler) buildManagerAgentMember(groupID string) (*models.GroupMember, error) {
	mc := h.cfg.Agent.ManagerAgent

	// Validate configured manager-agent member_id and member_name.
	if !memberIDRegex.MatchString(mc.MemberID) {
		return nil, fmt.Errorf("invalid manager-agent member_id %q: must contain only alphanumeric characters, hyphens, and underscores", mc.MemberID)
	}
	if !memberNameRegex.MatchString(mc.MemberName) {
		return nil, fmt.Errorf("invalid manager-agent member_name %q: must contain only alphanumeric characters, hyphens, and underscores", mc.MemberName)
	}

	iface, err := buildManagerAgentMemberInterface(&mc)
	if err != nil {
		return nil, err
	}

	now := time.Now().UnixMilli()
	return &models.GroupMember{
		GroupID:           groupID,
		MemberID:          mc.MemberID,
		MemberName:        mc.MemberName,
		MemberDescription: mc.MemberDescription,
		MemberType:        models.MemberTypeManagerAgent,
		MemberStatus:      models.MemberStatusOnline,
		MemberInterface:   iface,
		CreateAtMs:        now,
		UpdateAtMs:        now,
	}, nil
}

// buildManagerAgentMemberInterface builds the member_interface JSON for the default manager-agent.
func buildManagerAgentMemberInterface(mc *config.ManagerAgentConfig) (string, error) {
	iface := map[string]interface{}{
		"adaptor":      mc.Adaptor,
		"cmd_chat":     mc.CmdChat,
		"timeout_chat": int64(mc.TimeoutChat.Seconds()),
	}

	if mc.CmdCheckHealth != "" {
		iface["cmd_check_health"] = mc.CmdCheckHealth
	}
	if mc.CmdCheckStatus != "" {
		iface["cmd_check_status"] = mc.CmdCheckStatus
	}
	if mc.TimeoutCheckHealth > 0 {
		iface["timeout_check_health"] = int64(mc.TimeoutCheckHealth.Seconds())
	}
	if mc.TimeoutCheckStatus > 0 {
		iface["timeout_check_status"] = int64(mc.TimeoutCheckStatus.Seconds())
	}

	envs := make(map[string]string)
	if mc.APIBase != "" {
		envs["ACS_AGENT_API_BASE"] = mc.APIBase
	}
	if mc.APIKey != "" {
		envs["ACS_AGENT_API_KEY"] = mc.APIKey
	}
	if mc.APIAuth != "" {
		envs["ACS_AGENT_API_AUTH"] = mc.APIAuth
	}
	iface["environments"] = envs

	data, err := json.Marshal(iface)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// GetGroup handles GET /api/v1/groups/:group_id.
func (h *GroupHandler) GetGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "group not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to get group"})
		return
	}

	c.JSON(http.StatusOK, toGroupResponse(&group))
}

// ListGroups handles GET /api/v1/groups.
func (h *GroupHandler) ListGroups(c *gin.Context) {
	traceID := middleware.GetTraceID(c)

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
	allowedSortKeys := map[string]bool{"create_at_ms": true, "update_at_ms": true, "group_id": true, "group_name": true}
	if !allowedSortKeys[sortKey] {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid sort_key"})
		return
	}

	// Build query
	query := h.db.Model(&models.Group{})

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
		h.log.Error("api", traceID, "failed to count groups", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list groups"})
		return
	}

	// Execute query with pagination and sorting
	var groups []models.Group
	orderClause := fmt.Sprintf("%s %s", sortKey, orderBy)
	if err := query.Order(orderClause).Offset(offset).Limit(limit).Find(&groups).Error; err != nil {
		h.log.Error("api", traceID, "failed to list groups", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list groups"})
		return
	}

	items := make([]GroupResponse, 0, len(groups))
	for i := range groups {
		items = append(items, toGroupResponse(&groups[i]))
	}

	c.JSON(http.StatusOK, ListGroupsResponse{
		Items:   items,
		Total:   total,
		Offset:  offset,
		Limit:   limit,
		SortKey: sortKey,
		OrderBy: orderBy,
	})
}

// UpdateGroup handles PUT /api/v1/groups/:group_id.
func (h *GroupHandler) UpdateGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	var req UpdateGroupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid update group request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	var group models.Group
	if err := h.db.Where("group_id = ?", groupID).First(&group).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "group not found"})
			return
		}
		h.log.Error("api", traceID, "failed to get group for update", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update group"})
		return
	}

	// Update fields
	updates := make(map[string]interface{})
	if req.GroupName != "" {
		updates["group_name"] = req.GroupName
	}
	if req.GroupContext != "" {
		updates["group_context"] = req.GroupContext
	}
	if req.GroupKey != "" {
		hashedKey, err := hashGroupKey(req.GroupKey)
		if err != nil {
			h.log.Error("api", traceID, "failed to hash group key", "error", err.Error())
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to process group key"})
			return
		}
		updates["group_key"] = hashedKey
	}
	updates["update_at_ms"] = time.Now().UnixMilli()

	if err := h.db.Model(&group).Updates(updates).Error; err != nil {
		h.log.Error("api", traceID, "failed to update group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update group"})
		return
	}

	// Reload group
	h.db.Where("group_id = ?", groupID).First(&group)

	// Publish event
	if h.publisher != nil {
		if err := h.publisher.PublishGroupModify(&group); err != nil {
			h.log.Warn("api", traceID, "failed to publish group modify event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "group updated", "group_id", groupID)
	c.JSON(http.StatusOK, toGroupResponse(&group))
}

// DeleteGroup handles DELETE /api/v1/groups/:group_id.
func (h *GroupHandler) DeleteGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	if err := h.db.Transaction(func(tx *gorm.DB) error {
		var group models.Group
		if err := tx.Where("group_id = ?", groupID).First(&group).Error; err != nil {
			return err
		}

		if err := tx.Where("group_id = ?", groupID).Delete(&models.GroupMessage{}).Error; err != nil {
			return err
		}
		if err := tx.Where("group_id = ?", groupID).Delete(&models.GroupMember{}).Error; err != nil {
			return err
		}
		if err := tx.Where("group_id = ?", groupID).Delete(&models.Group{}).Error; err != nil {
			return err
		}
		return nil
	}); err != nil {
		if err == gorm.ErrRecordNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "group not found"})
			return
		}
		h.log.Error("api", traceID, "failed to delete group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete group"})
		return
	}

	// Publish event
	if h.publisher != nil {
		if err := h.publisher.PublishGroupDelete(groupID); err != nil {
			h.log.Warn("api", traceID, "failed to publish group delete event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "group deleted", "group_id", groupID)
	c.Status(http.StatusNoContent)
}

// toGroupResponse converts a Group model to API response.
func toGroupResponse(g *models.Group) GroupResponse {
	return GroupResponse{
		GroupID:      g.GroupID,
		GroupName:    g.GroupName,
		GroupContext: g.GroupContext,
		GroupKey:     g.GroupKey,
		CreateAtMs:   g.CreateAtMs,
		UpdateAtMs:   g.UpdateAtMs,
	}
}

// parseTimeRange parses a time range string in format "startTime-endTime".
func parseTimeRange(rangeStr string) (int64, int64, error) {
	parts := strings.Split(rangeStr, "-")
	if len(parts) != 2 {
		return 0, 0, fmt.Errorf("invalid time range format")
	}
	start, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil {
		return 0, 0, err
	}
	end, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil {
		return 0, 0, err
	}
	if start < 0 || end < 0 {
		return 0, 0, fmt.Errorf("time values must be non-negative")
	}
	return start, end, nil
}
