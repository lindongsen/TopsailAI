// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"encoding/json"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/internal/utils"
	"github.com/topsailai/agent-community/pkg/logger"
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
	auditSvc  *services.AuditLogService
}

// NewGroupHandler creates a new GroupHandler.
func NewGroupHandler(db *gorm.DB, publisher GroupPublisher, cfg *config.Config, log *logger.Logger, auditSvc *services.AuditLogService) *GroupHandler {
	return &GroupHandler{
		db:        db,
		publisher: publisher,
		cfg:       cfg,
		log:       log,
		auditSvc:  auditSvc,
	}
}

// CreateGroupRequest represents the request body for creating a group.
type CreateGroupRequest struct {
	GroupName    string `json:"group_name" binding:"required"`
	GroupContext string `json:"group_context"`
	GroupKey     string `json:"group_key"`
}

// audit writes an audit log record using the request context's client IP.
func (h *GroupHandler) audit(c *gin.Context, action, resourceType, resourceID, resourceName, detail string) {
	if h.auditSvc == nil {
		return
	}
	authCtx, ok := middleware.GetAuthContext(c)
	if !ok {
		authCtx = middleware.AuthContext{}
	}
	accountID := ""
	apiKeyID := ""
	if authCtx.Account != nil {
		accountID = authCtx.Account.AccountID
	}
	if authCtx.APIKey != nil {
		apiKeyID = authCtx.APIKey.APIKeyID
	}
	clientIP, _ := services.ClientIPFromContext(c.Request.Context())
	_, _ = h.auditSvc.Log(c.Request.Context(), &services.AuditLogRequest{
		AccountID:    accountID,
		APIKeyID:     apiKeyID,
		Action:       action,
		ResourceType: resourceType,
		ResourceID:   resourceID,
		ResourceName: resourceName,
		Detail:       detail,
		ClientIP:     clientIP,
	})
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
	CreatorID    string `json:"creator_id"`
	OwnerID      string `json:"owner_id"`
	CreateAtMs   int64  `json:"create_at_ms"`
	UpdateAtMs   int64  `json:"update_at_ms"`
}

// ListGroupsResponse represents the response for listing groups.
type ListGroupsResponse struct {
	Items  []GroupResponse `json:"items"`
	Total  int64           `json:"total"`
	Offset int             `json:"offset"`
	Limit  int             `json:"limit"`
}

// bcryptCost is the cost factor used by hashGroupKey. It is a variable so
// tests can inject an invalid cost to exercise the error path.
var bcryptCost = utils.BcryptDefaultCost

// hashGroupKey hashes a group key using bcrypt.
func hashGroupKey(key string) (string, error) {
	return utils.HashGroupKeyWithCost(key, bcryptCost)
}

// CreateGroup handles POST /api/v1/groups.
// The authenticated creator is automatically joined as a user member, and when
// ACS_GROUP_MANAGER_AGENT_CMD_CHAT is configured, a default manager-agent
// member is automatically joined to the new group inside the same transaction.
func (h *GroupHandler) CreateGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)

	authCtx, ok := middleware.GetAuthContext(c)
	if !ok || !authCtx.IsAuthenticated || authCtx.Account == nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "authentication required"})
		return
	}

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
		GroupID:      models.GenerateGroupID(),
		GroupName:    req.GroupName,
		GroupContext: req.GroupContext,
		GroupKey:     hashedKey,
		CreatorID:    authCtx.Account.AccountID,
		OwnerID:      authCtx.Account.AccountID,
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}

	creatorMember := buildCreatorMember(&group, authCtx.Account)
	var managerMember *models.GroupMember

	// Create group, creator member, and optional default manager-agent atomically.
	if err := h.db.Transaction(func(tx *gorm.DB) error {
		if err := tx.Create(&group).Error; err != nil {
			return err
		}

		if err := tx.Create(creatorMember).Error; err != nil {
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
	if err := h.publisher.PublishGroupCreate(&group); err != nil {
		h.log.Warn("api", traceID, "failed to publish group create event", "error", err.Error())
	}

	if err := h.publisher.PublishGroupMemberCreate(creatorMember); err != nil {
		h.log.Warn("api", traceID, "failed to publish creator member create event", "error", err.Error())
	}

	if managerMember != nil {
		if err := h.publisher.PublishGroupMemberCreate(managerMember); err != nil {
			h.log.Warn("api", traceID, "failed to publish manager-agent member create event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "group created", "group_id", group.GroupID, "creator_id", creatorMember.MemberID)
	h.audit(c, "group.create", "group", group.GroupID, group.GroupName, "group created")
	writeDataResponse(c, http.StatusCreated, toGroupResponse(&group), traceID)
}

// buildCreatorMember constructs a user member record for the group creator.
func buildCreatorMember(group *models.Group, account *models.Account) *models.GroupMember {
	now := time.Now().UnixMilli()
	return &models.GroupMember{
		GroupID:           group.GroupID,
		MemberID:          account.AccountID,
		MemberName:        sanitizeMemberName(account.AccountName),
		MemberDescription: "Group creator",
		MemberStatus:      models.MemberStatusOnline,
		MemberType:        models.MemberTypeUser,
		MemberInterface:   "{}",
		CreateAtMs:        now,
		UpdateAtMs:        now,
	}
}

// sanitizeMemberName replaces characters that are not allowed in member_name
// (alphanumeric, hyphens, underscores) with underscores.
func sanitizeMemberName(name string) string {
	if name == "" {
		return "user"
	}
	sanitized := regexp.MustCompile(`[^a-zA-Z0-9_-]`).ReplaceAllString(name, "_")
	if sanitized == "" {
		return "user"
	}
	return sanitized
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
// Admin callers can access any group; non-admin callers must be a member.
func (h *GroupHandler) GetGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	authCtx, ok := middleware.GetAuthContext(c)
	if !ok || !authCtx.IsAuthenticated || authCtx.Account == nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "authentication required"})
		return
	}

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

	// Non-admin callers must be a member of the group.
	if authCtx.Account.Role != models.AccountRoleAdmin {
		var count int64
		if err := h.db.Model(&models.GroupMember{}).
			Where("group_id = ? AND member_id = ?", groupID, authCtx.Account.AccountID).
			Count(&count).Error; err != nil {
			h.log.Error("api", traceID, "failed to check group membership", "error", err.Error())
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to get group"})
			return
		}
		if count == 0 {
			c.JSON(http.StatusForbidden, gin.H{"error": "forbidden"})
			return
		}
	}

	writeDataResponse(c, http.StatusOK, toGroupResponse(&group), traceID)
}

// ListGroups handles GET /api/v1/groups.
// Non-admin callers only see groups they are members of.
func (h *GroupHandler) ListGroups(c *gin.Context) {
	traceID := middleware.GetTraceID(c)

	// Retrieve authenticated caller.
	authCtx, ok := middleware.GetAuthContext(c)
	if !ok || !authCtx.IsAuthenticated || authCtx.Account == nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "authentication required"})
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
	allowedSortKeys := map[string]bool{"create_at_ms": true, "update_at_ms": true, "group_id": true, "group_name": true}
	if !allowedSortKeys[sortKey] {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid sort_key"})
		return
	}

	// Build query
	query := h.db.Model(&models.Group{})

	// Non-admin callers can only list groups they have joined.
	if authCtx.Account.Role != models.AccountRoleAdmin {
		query = query.Joins("JOIN group_member ON group_member.group_id = groups.group_id").
			Where("group_member.member_id = ?", authCtx.Account.AccountID)
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

	// Get total count
	var total int64
	if err := query.Count(&total).Error; err != nil {
		h.log.Error("api", traceID, "failed to count groups", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list groups"})
		return
	}

	// Execute query with pagination and sorting
	var groups []models.Group
	orderClause := fmt.Sprintf("groups.%s %s", sortKey, orderBy)
	if err := query.Order(orderClause).Offset(offset).Limit(limit).Find(&groups).Error; err != nil {
		h.log.Error("api", traceID, "failed to list groups", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list groups"})
		return
	}

	items := make([]GroupResponse, 0, len(groups))
	for i := range groups {
		items = append(items, toGroupResponse(&groups[i]))
	}

	writeListResponse(c, http.StatusOK, items, total, offset, limit, traceID)
}

// UpdateGroup handles PUT /api/v1/groups/:group_id.
// Admin callers can update any group; non-admin callers can update only groups they own.
func (h *GroupHandler) UpdateGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	authCtx, ok := middleware.GetAuthContext(c)
	if !ok || !authCtx.IsAuthenticated || authCtx.Account == nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "authentication required"})
		return
	}

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

	// Non-admin callers must own the group.
	if authCtx.Account.Role != models.AccountRoleAdmin && group.OwnerID != authCtx.Account.AccountID {
		c.JSON(http.StatusForbidden, gin.H{"error": "forbidden"})
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
	if err := h.publisher.PublishGroupModify(&group); err != nil {
		h.log.Warn("api", traceID, "failed to publish group modify event", "error", err.Error())
	}

	h.log.Info("api", traceID, "group updated", "group_id", groupID)
	h.audit(c, "group.update", "group", group.GroupID, group.GroupName, "group updated")
	writeDataResponse(c, http.StatusOK, toGroupResponse(&group), traceID)
}

// DeleteGroup handles DELETE /api/v1/groups/:group_id.
// Admin callers can delete any group; non-admin callers can delete only groups they own.
func (h *GroupHandler) DeleteGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")

	authCtx, ok := middleware.GetAuthContext(c)
	if !ok || !authCtx.IsAuthenticated || authCtx.Account == nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "authentication required"})
		return
	}
	groupName := ""
	if err := h.db.Transaction(func(tx *gorm.DB) error {
		var group models.Group
		if err := tx.Where("group_id = ?", groupID).First(&group).Error; err != nil {
			return err
		}
		groupName = group.GroupName

		// Non-admin callers must own the group.
		if authCtx.Account.Role != models.AccountRoleAdmin && group.OwnerID != authCtx.Account.AccountID {
			return fmt.Errorf("forbidden")
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
		if err.Error() == "forbidden" {
			c.JSON(http.StatusForbidden, gin.H{"error": "forbidden"})
			return
		}
		h.log.Error("api", traceID, "failed to delete group", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete group"})
		return
	}

	// Publish event
	if err := h.publisher.PublishGroupDelete(groupID); err != nil {
		h.log.Warn("api", traceID, "failed to publish group delete event", "error", err.Error())
	}

	h.log.Info("api", traceID, "group deleted", "group_id", groupID)
	h.audit(c, "group.delete", "group", groupID, groupName, "group deleted")
	c.Status(http.StatusNoContent)
}

// toGroupResponse converts a Group model to API response.
// The group_key is never exposed in API responses.
func toGroupResponse(g *models.Group) GroupResponse {
	return GroupResponse{
		GroupID:      g.GroupID,
		GroupName:    g.GroupName,
		GroupContext: g.GroupContext,
		GroupKey:     "",
		CreatorID:    g.CreatorID,
		OwnerID:      g.OwnerID,
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
