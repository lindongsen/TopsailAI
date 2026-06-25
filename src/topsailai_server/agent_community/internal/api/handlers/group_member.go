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
	"github.com/topsailai/agent-community/internal/utils"
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
	MemberID          string               `json:"member_id"`
	MemberName        string               `json:"member_name"`
	MemberDescription string               `json:"member_description"`
	MemberType        string               `json:"member_type"`
	MemberInterface   MemberInterfaceField `json:"member_interface"`
	GroupKey          string               `json:"group_key"`
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
}

// getAuthContextOrAbort extracts the authenticated account from the Gin context.
// It aborts the request with 401 if the caller is not authenticated or active.
func getAuthContextOrAbort(c *gin.Context) (middleware.AuthContext, bool) {
	traceID := middleware.GetTraceID(c)
	ac, ok := middleware.GetAuthContext(c)
	if !ok || !ac.IsAuthenticated || ac.Account == nil {
		writeErrorResponse(c, http.StatusUnauthorized, "authentication required", traceID)
		return ac, false
	}
	if !ac.Account.IsActive() {
		writeErrorResponse(c, http.StatusForbidden, "account is not active", traceID)
		return ac, false
	}
	return ac, true
}

// isAdmin returns true if the authenticated account has the admin role.
func isAdmin(ac middleware.AuthContext) bool {
	return ac.Account.Role == models.AccountRoleAdmin
}

// isGroupOwner returns true if the account owns the group.
func isGroupOwner(db *gorm.DB, groupID, accountID string) (bool, error) {
	var count int64
	if err := db.Model(&models.Group{}).
		Where("group_id = ? AND owner_id = ?", groupID, accountID).
		Count(&count).Error; err != nil {
		return false, err
	}
	return count > 0, nil
}

// isGroupMember returns true if the account is a member of the group.
func isGroupMember(db *gorm.DB, groupID, accountID string) (bool, error) {
	var count int64
	if err := db.Model(&models.GroupMember{}).
		Where("group_id = ? AND member_id = ?", groupID, accountID).
		Count(&count).Error; err != nil {
		return false, err
	}
	return count > 0, nil
}

// canJoinGroup checks whether the caller may add members to the group.
// Admin can add members to any group; user can add members only to groups they own.
func canJoinGroup(db *gorm.DB, ac middleware.AuthContext, groupID string) (bool, error) {
	if isAdmin(ac) {
		return true, nil
	}
	return isGroupOwner(db, groupID, ac.Account.AccountID)
}

// canListGroupMembers checks whether the caller may list members of the group.
// Admin can list any group; user can list only groups where they are a member.
func canListGroupMembers(db *gorm.DB, ac middleware.AuthContext, groupID string) (bool, error) {
	if isAdmin(ac) {
		return true, nil
	}
	return isGroupMember(db, groupID, ac.Account.AccountID)
}

// canUpdateMember checks whether the caller may update the member record.
// Admin can update any member; group owner can update any member in their own
// group; regular user can update only their own member record.
func canUpdateMember(db *gorm.DB, ac middleware.AuthContext, groupID, memberID string) (bool, error) {
	if isAdmin(ac) {
		return true, nil
	}

	// Group owner may update any member in their group.
	isOwner, err := isGroupOwner(db, groupID, ac.Account.AccountID)
	if err != nil {
		return false, err
	}
	if isOwner {
		return true, nil
	}

	// Regular user may update only their own member record.
	if memberID != ac.Account.AccountID {
		return false, nil
	}
	return isGroupMember(db, groupID, ac.Account.AccountID)
}

// canLeaveGroup checks whether the caller may remove the member record.
// Admin can remove any member; user can remove only their own member record.
func canLeaveGroup(db *gorm.DB, ac middleware.AuthContext, groupID, memberID string) (bool, error) {
	if isAdmin(ac) {
		return true, nil
	}
	if memberID != ac.Account.AccountID {
		return false, nil
	}
	return isGroupMember(db, groupID, ac.Account.AccountID)
}

// JoinGroup handles POST /api/v1/groups/:group_id/members.
//
// Authorization rules:
//   - Admin may add any member to any group.
//   - Group owner may add any member to their own group.
//   - Any authenticated, active account may self-join a public group.
//     Self-join requests must not supply member_id or member_type; doing so is
//     treated as an attempt to add a member and is forbidden.
//   - Any authenticated, active account may self-join a private group when the
//     correct group_key is provided in the request body.
//
// For self-joins the caller's member_id is always set to their account_id,
// member_type is forced to "user", and member_name defaults to the account name.
func (h *GroupMemberHandler) JoinGroup(c *gin.Context) {
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
		writeErrorResponse(c, http.StatusInternalServerError, "failed to join group", traceID)
		return
	}

	var req JoinGroupRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid join group request", "error", err.Error())
		writeErrorResponse(c, http.StatusBadRequest, err.Error(), traceID)
		return
	}

	// Determine authorization mode.
	ownerMode := false
	if isAdmin(authCtx) {
		ownerMode = true
	} else {
		isOwner, err := isGroupOwner(h.db, groupID, authCtx.Account.AccountID)
		if err != nil {
			h.log.Error("api", traceID, "failed to check group ownership", "error", err.Error())
			writeErrorResponse(c, http.StatusInternalServerError, "failed to join group", traceID)
			return
		}
		ownerMode = isOwner
	}

	var memberID, memberName, memberDescription string
	var memberType models.MemberType

	if ownerMode {
		// Owner/admin mode: request supplies member details.
		if req.MemberID == "" {
			writeErrorResponse(c, http.StatusBadRequest, "member_id is required", traceID)
			return
		}
		if req.MemberName == "" {
			writeErrorResponse(c, http.StatusBadRequest, "member_name is required", traceID)
			return
		}
		if req.MemberType == "" {
			writeErrorResponse(c, http.StatusBadRequest, "member_type is required", traceID)
			return
		}
		memberID = req.MemberID
		memberName = req.MemberName
		memberDescription = req.MemberDescription
		memberType = models.MemberType(req.MemberType)
	} else {
		// Self-join mode. Non-owners/admins may not supply member_id or
		// member_type; doing so is treated as an attempt to add a member.
		if req.MemberID != "" || req.MemberType != "" {
			writeErrorResponse(c, http.StatusForbidden, "only group owners and admins can add members", traceID)
			return
		}

		// Self-join mode.
		alreadyMember, err := isGroupMember(h.db, groupID, authCtx.Account.AccountID)
		if err != nil {
			h.log.Error("api", traceID, "failed to check group membership", "error", err.Error())
			writeErrorResponse(c, http.StatusInternalServerError, "failed to join group", traceID)
			return
		}
		if alreadyMember {
			writeErrorResponse(c, http.StatusForbidden, "already a member of this group", traceID)
			return
		}

		// Verify group_key for private groups.
		if !utils.VerifyGroupKey(req.GroupKey, group.GroupKey) {
			writeErrorResponse(c, http.StatusForbidden, "invalid group key", traceID)
			return
		}

		memberID = authCtx.Account.AccountID
		if req.MemberName != "" {
			memberName = req.MemberName
		} else {
			// Default self-join name to the sanitized account name so that
			// characters outside [A-Za-z0-9_-] are replaced with underscores.
			memberName = sanitizeMemberName(authCtx.Account.AccountName)
		}
		memberDescription = req.MemberDescription
		memberType = models.MemberTypeUser
	}

	// Validate member_id
	if !memberIDRegex.MatchString(memberID) {
		writeErrorResponse(c, http.StatusBadRequest, "invalid member_id: must contain only alphanumeric characters, hyphens, and underscores", traceID)
		return
	}

	// Validate member_name
	if !memberNameRegex.MatchString(memberName) {
		writeErrorResponse(c, http.StatusBadRequest, "invalid member_name: must contain only alphanumeric characters, hyphens, and underscores", traceID)
		return
	}

	// Validate member type
	if memberType != models.MemberTypeUser &&
		memberType != models.MemberTypeManagerAgent &&
		memberType != models.MemberTypeWorkerAgent {
		writeErrorResponse(c, http.StatusBadRequest, "invalid member_type", traceID)
		return
	}

	// Agent members require a member_interface.
	if (memberType == models.MemberTypeWorkerAgent || memberType == models.MemberTypeManagerAgent) &&
		req.MemberInterface.String() == "" {
		writeErrorResponse(c, http.StatusBadRequest, "member_interface is required for agent members", traceID)
		return
	}

	member := models.GroupMember{
		GroupID:           groupID,
		MemberID:          memberID,
		MemberName:        memberName,
		MemberDescription: memberDescription,
		MemberType:        memberType,
		MemberStatus:      models.MemberStatusOnline,
		MemberInterface:   req.MemberInterface.String(),
	}
	// Check for duplicate member
	var existingMember models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, memberID).First(&existingMember).Error; err == nil {
		writeErrorResponse(c, http.StatusConflict, "member already exists in group", traceID)
		return
	}

	if err := h.db.Create(&member).Error; err != nil {
		h.log.Error("api", traceID, "failed to join group", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to join group", traceID)
		return
	}
	// Publish event
	if err := h.publisher.PublishGroupMemberCreate(&member); err != nil {
		h.log.Warn("api", traceID, "failed to publish member join event", "error", err.Error())
	}

	h.log.Info("api", traceID, "member joined group", "group_id", groupID, "member_id", memberID)
	writeDataResponse(c, http.StatusCreated, toGroupMemberResponse(&member), traceID)
}

// ListGroupMembers handles GET /api/v1/groups/:group_id/members.
func (h *GroupMemberHandler) ListGroupMembers(c *gin.Context) {
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
		writeErrorResponse(c, http.StatusInternalServerError, "failed to list members", traceID)
		return
	}

	// Authorization: admin any group, user member group only.
	allowed, err := canListGroupMembers(h.db, authCtx, groupID)
	if err != nil {
		h.log.Error("api", traceID, "failed to check list members permission", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to list members", traceID)
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
	allowedSortKeys := map[string]bool{"create_at_ms": true, "update_at_ms": true, "member_id": true, "member_name": true, "member_type": true, "member_status": true}
	if !allowedSortKeys[sortKey] {
		writeErrorResponse(c, http.StatusBadRequest, "invalid sort_key", traceID)
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
		writeErrorResponse(c, http.StatusInternalServerError, "failed to list members", traceID)
		return
	}

	// Execute query
	var members []models.GroupMember
	orderClause := sortKey + " " + orderBy
	if err := query.Order(orderClause).Offset(offset).Limit(limit).Find(&members).Error; err != nil {
		h.log.Error("api", traceID, "failed to list members", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to list members", traceID)
		return
	}

	items := make([]GroupMemberResponse, 0, len(members))
	for i := range members {
		items = append(items, toGroupMemberResponse(&members[i]))
	}

	writeListResponse(c, http.StatusOK, items, total, offset, limit, traceID)
}

// UpdateMember handles PUT /api/v1/groups/:group_id/members/:member_id.
func (h *GroupMemberHandler) UpdateMember(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	memberID := c.Param("member_id")

	authCtx, ok := getAuthContextOrAbort(c)
	if !ok {
		return
	}

	var req UpdateMemberRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid update member request", "error", err.Error())
		writeErrorResponse(c, http.StatusBadRequest, err.Error(), traceID)
		return
	}
	var member models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, memberID).First(&member).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "member not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get member", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to update member", traceID)
		return
	}

	// Authorization: admin any member, group owner any member in their group,
	// user own member only.
	allowed, err := canUpdateMember(h.db, authCtx, groupID, memberID)
	if err != nil {
		h.log.Error("api", traceID, "failed to check update member permission", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to update member", traceID)
		return
	}
	if !allowed {
		writeErrorResponse(c, http.StatusForbidden, "forbidden", traceID)
		return
	}

	// Validate member_name if provided
	if req.MemberName != "" && !memberNameRegex.MatchString(req.MemberName) {
		writeErrorResponse(c, http.StatusBadRequest, "invalid member_name: must contain only alphanumeric characters, hyphens, and underscores", traceID)
		return
	}

	// Validate member_status if provided.
	if req.MemberStatus != "" {
		status := models.MemberStatus(req.MemberStatus)
		if status != models.MemberStatusOnline &&
			status != models.MemberStatusOffline &&
			status != models.MemberStatusIdle &&
			status != models.MemberStatusProcessing {
			writeErrorResponse(c, http.StatusBadRequest, "invalid member_status", traceID)
			return
		}
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
		writeErrorResponse(c, http.StatusInternalServerError, "failed to update member", traceID)
		return
	}

	// Reload member
	h.db.Where("group_id = ? AND member_id = ?", groupID, memberID).First(&member)

	// Publish modify event when member_status changes so subscribers can observe transitions
	if req.MemberStatus != "" {
		if err := h.publisher.PublishGroupMemberModify(&member); err != nil {
			h.log.Warn("api", traceID, "failed to publish member modify event", "error", err.Error())
		}
	}

	h.log.Info("api", traceID, "member updated", "group_id", groupID, "member_id", memberID)
	writeDataResponse(c, http.StatusOK, toGroupMemberResponse(&member), traceID)
}

// LeaveGroup handles DELETE /api/v1/groups/:group_id/members/:member_id.
func (h *GroupMemberHandler) LeaveGroup(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	groupID := c.Param("group_id")
	memberID := c.Param("member_id")

	authCtx, ok := getAuthContextOrAbort(c)
	if !ok {
		return
	}

	var member models.GroupMember
	if err := h.db.Where("group_id = ? AND member_id = ?", groupID, memberID).First(&member).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			writeErrorResponse(c, http.StatusNotFound, "member not found", traceID)
			return
		}
		h.log.Error("api", traceID, "failed to get member for leave", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to leave group", traceID)
		return
	}

	// Authorization: admin any member, user own member only.
	allowed, err := canLeaveGroup(h.db, authCtx, groupID, memberID)
	if err != nil {
		h.log.Error("api", traceID, "failed to check leave permission", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to leave group", traceID)
		return
	}
	if !allowed {
		writeErrorResponse(c, http.StatusForbidden, "forbidden", traceID)
		return
	}

	if err := h.db.Delete(&member).Error; err != nil {
		h.log.Error("api", traceID, "failed to leave group", "error", err.Error())
		writeErrorResponse(c, http.StatusInternalServerError, "failed to leave group", traceID)
		return
	}

	// Publish event
	if err := h.publisher.PublishGroupMemberDelete(groupID, memberID); err != nil {
		h.log.Warn("api", traceID, "failed to publish member leave event", "error", err.Error())
	}

	h.log.Info("api", traceID, "member left group", "group_id", groupID, "member_id", memberID)
	c.AbortWithStatus(http.StatusNoContent)
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
