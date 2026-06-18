// Package handlers provides group handler tests.
package handlers

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// TestParseTimeRangeValid verifies a valid time range string is parsed correctly.
func TestParseTimeRangeValid(t *testing.T) {
	start, end, err := parseTimeRange("1000-2000")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if start != 1000 {
		t.Errorf("start = %d, want 1000", start)
	}
	if end != 2000 {
		t.Errorf("end = %d, want 2000", end)
	}
}

// TestParseTimeRangeEmpty verifies empty string returns error.
func TestParseTimeRangeEmpty(t *testing.T) {
	_, _, err := parseTimeRange("")
	if err == nil {
		t.Error("expected error for empty string")
	}
}

// TestParseTimeRangeInvalidFormat verifies error on invalid format.
func TestParseTimeRangeInvalidFormat(t *testing.T) {
	_, _, err := parseTimeRange("invalid")
	if err == nil {
		t.Error("expected error for invalid format")
	}
}

// TestParseTimeRangeInvalidStart verifies error on non-numeric start.
func TestParseTimeRangeInvalidStart(t *testing.T) {
	_, _, err := parseTimeRange("abc-2000")
	if err == nil {
		t.Error("expected error for non-numeric start")
	}
}

// TestParseTimeRangeInvalidEnd verifies error on non-numeric end.
func TestParseTimeRangeInvalidEnd(t *testing.T) {
	_, _, err := parseTimeRange("1000-xyz")
	if err == nil {
		t.Error("expected error for non-numeric end")
	}
}

// TestParseTimeRangeNegativeValues verifies error on negative values.
func TestParseTimeRangeNegativeValues(t *testing.T) {
	_, _, err := parseTimeRange("-1000-2000")
	if err == nil {
		t.Error("expected error for negative start value")
	}

	_, _, err = parseTimeRange("1000--2000")
	if err == nil {
		t.Error("expected error for negative end value")
	}
}

// TestParseTimeRangeSingleValue verifies error on single value.
func TestParseTimeRangeSingleValue(t *testing.T) {
	_, _, err := parseTimeRange("1000")
	if err == nil {
		t.Error("expected error for single value")
	}
}

// TestParseTimeRangeExtraParts verifies error on extra parts.
func TestParseTimeRangeExtraParts(t *testing.T) {
	_, _, err := parseTimeRange("1000-2000-3000")
	if err == nil {
		t.Error("expected error for extra parts")
	}
}

// TestParseTimeRangeStartGreaterThanEnd verifies start > end is allowed (just a range).
func TestParseTimeRangeStartGreaterThanEnd(t *testing.T) {
	start, end, err := parseTimeRange("2000-1000")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if start != 2000 {
		t.Errorf("start = %d, want 2000", start)
	}
	if end != 1000 {
		t.Errorf("end = %d, want 1000", end)
	}
}

// TestGroupResponseStructure verifies group response structure.
func TestGroupResponseStructure(t *testing.T) {
	now := time.Now().UnixMilli()
	resp := GroupResponse{
		GroupID:      "g1",
		GroupName:    "Test Group",
		GroupContext: "Test context",
		GroupKey:     "hashed_key",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}

	if resp.GroupID != "g1" {
		t.Errorf("group_id = %v", resp.GroupID)
	}
	if resp.GroupName != "Test Group" {
		t.Errorf("group_name = %v", resp.GroupName)
	}
	if resp.GroupContext != "Test context" {
		t.Errorf("group_context = %v", resp.GroupContext)
	}
	if resp.GroupKey != "hashed_key" {
		t.Errorf("group_key = %v", resp.GroupKey)
	}
	if resp.CreateAtMs != now {
		t.Errorf("create_at_ms = %d", resp.CreateAtMs)
	}
	if resp.UpdateAtMs != now {
		t.Errorf("update_at_ms = %d", resp.UpdateAtMs)
	}
}

// TestGroupListResponseStructure verifies group list response structure.
func TestGroupListResponseStructure(t *testing.T) {
	resp := ListGroupsResponse{
		Total: 2,
		Items: []GroupResponse{
			{GroupID: "g1", GroupName: "Group 1"},
			{GroupID: "g2", GroupName: "Group 2"},
		},
	}

	if resp.Total != 2 {
		t.Errorf("total = %d, want 2", resp.Total)
	}
	if len(resp.Items) != 2 {
		t.Errorf("items length = %d, want 2", len(resp.Items))
	}
	if resp.Items[0].GroupID != "g1" {
		t.Errorf("first item group_id = %v", resp.Items[0].GroupID)
	}
	if resp.Items[1].GroupID != "g2" {
		t.Errorf("second item group_id = %v", resp.Items[1].GroupID)
	}
}

// TestCreateGroupRequestStructure verifies create group request structure.
func TestCreateGroupRequestStructure(t *testing.T) {
	req := CreateGroupRequest{
		GroupName:    "New Group",
		GroupContext: "Group context",
		GroupKey:     "secret_key",
	}

	if req.GroupName != "New Group" {
		t.Errorf("group_name = %v", req.GroupName)
	}
	if req.GroupContext != "Group context" {
		t.Errorf("group_context = %v", req.GroupContext)
	}
	if req.GroupKey != "secret_key" {
		t.Errorf("group_key = %v", req.GroupKey)
	}
}

// TestUpdateGroupRequestStructure verifies update group request structure.
func TestUpdateGroupRequestStructure(t *testing.T) {
	req := UpdateGroupRequest{
		GroupName:    "Updated Group",
		GroupContext: "Updated context",
	}

	if req.GroupName != "Updated Group" {
		t.Errorf("group_name = %v", req.GroupName)
	}
	if req.GroupContext != "Updated context" {
		t.Errorf("group_context = %v", req.GroupContext)
	}
}

// TestBuildManagerAgentMemberInterface_Full verifies the interface JSON contains
// all configured fields when every option is set.
func TestBuildManagerAgentMemberInterface_Full(t *testing.T) {
	cfg := &config.ManagerAgentConfig{
		Adaptor:            "topsailai_agent",
		CmdChat:            "topsailai_agent_cmd_chat",
		CmdCheckHealth:     "topsailai_agent_cmd_check_health",
		CmdCheckStatus:     "topsailai_agent_cmd_check_status",
		APIBase:            "http://manager.example.com:7373",
		APIKey:             "secret-key",
		APIAuth:            "bearer",
		TimeoutChat:        600 * time.Second,
		TimeoutCheckHealth: 5 * time.Second,
		TimeoutCheckStatus: 5 * time.Second,
	}

	ifaceStr, err := buildManagerAgentMemberInterface(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var iface map[string]interface{}
	if err := json.Unmarshal([]byte(ifaceStr), &iface); err != nil {
		t.Fatalf("failed to unmarshal interface: %v", err)
	}

	if iface["adaptor"] != "topsailai_agent" {
		t.Errorf("adaptor = %v", iface["adaptor"])
	}
	if iface["cmd_chat"] != "topsailai_agent_cmd_chat" {
		t.Errorf("cmd_chat = %v", iface["cmd_chat"])
	}
	if iface["cmd_check_health"] != "topsailai_agent_cmd_check_health" {
		t.Errorf("cmd_check_health = %v", iface["cmd_check_health"])
	}
	if iface["cmd_check_status"] != "topsailai_agent_cmd_check_status" {
		t.Errorf("cmd_check_status = %v", iface["cmd_check_status"])
	}
	if iface["timeout_chat"] != float64(600) {
		t.Errorf("timeout_chat = %v", iface["timeout_chat"])
	}
	if iface["timeout_check_health"] != float64(5) {
		t.Errorf("timeout_check_health = %v", iface["timeout_check_health"])
	}
	if iface["timeout_check_status"] != float64(5) {
		t.Errorf("timeout_check_status = %v", iface["timeout_check_status"])
	}

	envs, ok := iface["environments"].(map[string]interface{})
	if !ok {
		t.Fatalf("environments not found or wrong type")
	}
	if envs["ACS_AGENT_API_BASE"] != "http://manager.example.com:7373" {
		t.Errorf("ACS_AGENT_API_BASE = %v", envs["ACS_AGENT_API_BASE"])
	}
	if envs["ACS_AGENT_API_KEY"] != "secret-key" {
		t.Errorf("ACS_AGENT_API_KEY = %v", envs["ACS_AGENT_API_KEY"])
	}
	if envs["ACS_AGENT_API_AUTH"] != "bearer" {
		t.Errorf("ACS_AGENT_API_AUTH = %v", envs["ACS_AGENT_API_AUTH"])
	}
}

// TestBuildManagerAgentMemberInterface_Minimal verifies the interface JSON omits
// empty API environment values and still includes required cmd_chat.
func TestBuildManagerAgentMemberInterface_Minimal(t *testing.T) {
	cfg := &config.ManagerAgentConfig{
		Adaptor:     "topsailai_agent",
		CmdChat:     "topsailai_agent_cmd_chat",
		TimeoutChat: 600 * time.Second,
	}

	ifaceStr, err := buildManagerAgentMemberInterface(cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	var iface map[string]interface{}
	if err := json.Unmarshal([]byte(ifaceStr), &iface); err != nil {
		t.Fatalf("failed to unmarshal interface: %v", err)
	}

	if iface["cmd_chat"] != "topsailai_agent_cmd_chat" {
		t.Errorf("cmd_chat = %v", iface["cmd_chat"])
	}

	envs, ok := iface["environments"].(map[string]interface{})
	if !ok {
		t.Fatalf("environments not found or wrong type")
	}
	if len(envs) != 0 {
		t.Errorf("expected empty environments, got %v", envs)
	}
}

// setupGroupTestDB creates an in-memory SQLite database and auto-migrates models.
func setupGroupTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open("file::memory:"), &gorm.Config{})
	if err != nil {
		t.Fatalf("failed to open sqlite database: %v", err)
	}
	if err := db.AutoMigrate(&models.Group{}, &models.GroupMember{}, &models.GroupMessage{}); err != nil {
		t.Fatalf("failed to migrate database: %v", err)
	}
	return db
}

// setupGroupTestHandler creates a GroupHandler with the given config for testing.
func setupGroupTestHandler(t *testing.T, db *gorm.DB, cfg *config.Config) *GroupHandler {
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	return NewGroupHandler(db, nil, cfg, log)
}

// TestCreateGroupAutoJoinsManagerAgent verifies that creating a group automatically
// joins a manager-agent member when ACS_GROUP_MANAGER_AGENT_CMD_CHAT is configured.
func TestCreateGroupAutoJoinsManagerAgent(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	cfg := &config.Config{
		Agent: config.AgentConfig{
			ManagerAgent: config.ManagerAgentConfig{
				Adaptor:            "topsailai_agent",
				MemberID:           "manager-agent",
				MemberName:         "manager-agent",
				MemberDescription:  "Default group manager agent",
				CmdChat:            "topsailai_agent_cmd_chat",
				CmdCheckHealth:     "topsailai_agent_cmd_check_health",
				CmdCheckStatus:     "topsailai_agent_cmd_check_status",
				APIBase:            "http://manager.example.com:7373",
				APIKey:             "secret-key",
				APIAuth:            "bearer",
				TimeoutChat:        600 * time.Second,
				TimeoutCheckHealth: 5 * time.Second,
				TimeoutCheckStatus: 5 * time.Second,
			},
		},
	}
	handler := setupGroupTestHandler(t, db, cfg)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	creator := &models.Account{
		AccountID:   "acc-creator-001",
		AccountName: "Test Creator",
		Role:        models.AccountRoleUser,
		Status:      models.AccountStatusActive,
	}
	c.Set("auth_context", middleware.AuthContext{
		Account:         creator,
		IsAuthenticated: true,
	})
	body := CreateGroupRequest{
		GroupName:    "Test Group",
		GroupContext: "test context",
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateGroup(c)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected status %d, got %d: %s", http.StatusCreated, w.Code, w.Body.String())
	}

	var response GroupResponse
	if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	groupID := response.GroupID
	if groupID == "" {
		t.Fatal("expected group_id in response")
	}

	var members []models.GroupMember
	if err := db.Where("group_id = ?", groupID).Find(&members).Error; err != nil {
		t.Fatalf("failed to query members: %v", err)
	}
	if len(members) != 2 {
		t.Fatalf("expected 2 members (creator + manager-agent), got %d", len(members))
	}

	var managerMember *models.GroupMember
	var creatorMember *models.GroupMember
	for i := range members {
		if members[i].MemberType == models.MemberTypeManagerAgent {
			managerMember = &members[i]
		} else if members[i].MemberType == models.MemberTypeUser {
			creatorMember = &members[i]
		}
	}
	if managerMember == nil {
		t.Fatal("expected manager-agent member")
	}
	if creatorMember == nil {
		t.Fatal("expected creator user member")
	}
	if creatorMember.MemberID != creator.AccountID {
		t.Errorf("expected creator member_id %s, got %s", creator.AccountID, creatorMember.MemberID)
	}
	if managerMember.MemberID != "manager-agent" {
		t.Errorf("expected manager-agent member_id manager-agent, got %s", managerMember.MemberID)
	}
	if managerMember.MemberName != "manager-agent" {
		t.Errorf("expected manager-agent member_name manager-agent, got %s", managerMember.MemberName)
	}
	if managerMember.MemberDescription != "Default group manager agent" {
		t.Errorf("expected manager-agent member_description 'Default group manager agent', got %s", managerMember.MemberDescription)
	}
	if managerMember.MemberStatus != models.MemberStatusOnline {
		t.Errorf("expected manager-agent member_status %s, got %s", models.MemberStatusOnline, managerMember.MemberStatus)
	}
	if managerMember.MemberInterface == "" {
		t.Error("expected non-empty manager-agent member_interface")
	}
}

// TestCreateGroupDoesNotAutoJoinManagerAgentWhenDisabled verifies that no manager-agent
// member is created when ACS_GROUP_MANAGER_AGENT_CMD_CHAT is not configured.
func TestCreateGroupDoesNotAutoJoinManagerAgentWhenDisabled(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	cfg := &config.Config{
		Agent: config.AgentConfig{
			ManagerAgent: config.ManagerAgentConfig{
				Adaptor:     "topsailai_agent",
				CmdChat:     "", // not configured
				TimeoutChat: 600 * time.Second,
			},
		},
	}
	handler := setupGroupTestHandler(t, db, cfg)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	creator := &models.Account{
		AccountID:   "acc-creator-002",
		AccountName: "Test Creator Two",
		Role:        models.AccountRoleUser,
		Status:      models.AccountStatusActive,
	}
	c.Set("auth_context", middleware.AuthContext{
		Account:         creator,
		IsAuthenticated: true,
	})
	body := CreateGroupRequest{
		GroupName:    "Test Group No Manager",
		GroupContext: "test context",
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateGroup(c)

	if w.Code != http.StatusCreated {
		t.Fatalf("expected status %d, got %d: %s", http.StatusCreated, w.Code, w.Body.String())
	}

	var response GroupResponse
	if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	groupID := response.GroupID
	if groupID == "" {
		t.Fatal("expected group_id in response")
	}

	var members []models.GroupMember
	if err := db.Where("group_id = ?", groupID).Find(&members).Error; err != nil {
		t.Fatalf("failed to query members: %v", err)
	}

	if len(members) != 1 {
		t.Fatalf("expected 1 member (creator), got %d", len(members))
	}
	if members[0].MemberID != creator.AccountID {
		t.Errorf("expected creator member_id %s, got %s", creator.AccountID, members[0].MemberID)
	}
}

// TestDeleteGroupNotFound verifies that deleting a non-existent group returns 404.
func TestDeleteGroupNotFound(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	cfg := &config.Config{}
	handler := setupGroupTestHandler(t, db, cfg)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/non-existent-group-id", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "non-existent-group-id"}}

	handler.DeleteGroup(c)

	if w.Code != http.StatusNotFound {
		t.Fatalf("expected status %d, got %d: %s", http.StatusNotFound, w.Code, w.Body.String())
	}
}

// TestDeleteGroupCascade verifies that deleting an existing group removes the group,
// its members, and its messages, and returns 204 No Content.
func TestDeleteGroupCascade(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	cfg := &config.Config{}
	handler := setupGroupTestHandler(t, db, cfg)

	// Create a group with a member and a message.
	group := models.Group{
		GroupID:      "group-to-delete",
		GroupName:    "Delete Me",
		GroupContext: "context",
		GroupKey:     "",
		CreateAtMs:   time.Now().UnixMilli(),
		UpdateAtMs:   time.Now().UnixMilli(),
	}
	if err := db.Create(&group).Error; err != nil {
		t.Fatalf("failed to create group: %v", err)
	}
	member := models.GroupMember{
		GroupID:     group.GroupID,
		MemberID:    "user-001",
		MemberName:  "Alice",
		MemberType:  models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
		CreateAtMs:  time.Now().UnixMilli(),
		UpdateAtMs:  time.Now().UnixMilli(),
	}
	if err := db.Create(&member).Error; err != nil {
		t.Fatalf("failed to create member: %v", err)
	}
	msg := models.GroupMessage{
		MessageID:    "msg-001",
		GroupID:      group.GroupID,
		MessageText:  "hello",
		SenderID:     member.MemberID,
		SenderType:   models.MemberTypeUser,
		CreateAtMs:   time.Now().UnixMilli(),
		UpdateAtMs:   time.Now().UnixMilli(),
	}
	if err := db.Create(&msg).Error; err != nil {
		t.Fatalf("failed to create message: %v", err)
	}

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/"+group.GroupID, nil)
	c.Params = gin.Params{{Key: "group_id", Value: group.GroupID}}

	handler.DeleteGroup(c)

	if c.Writer.Status() != http.StatusNoContent {
		t.Fatalf("expected status %d, got %d: %s", http.StatusNoContent, c.Writer.Status(), w.Body.String())
	}

	var remainingGroups int64
	if err := db.Model(&models.Group{}).Where("group_id = ?", group.GroupID).Count(&remainingGroups).Error; err != nil {
		t.Fatalf("failed to count groups: %v", err)
	}
	if remainingGroups != 0 {
		t.Errorf("expected 0 groups, got %d", remainingGroups)
	}

	var remainingMembers int64
	if err := db.Model(&models.GroupMember{}).Where("group_id = ?", group.GroupID).Count(&remainingMembers).Error; err != nil {
		t.Fatalf("failed to count members: %v", err)
	}
	if remainingMembers != 0 {
		t.Errorf("expected 0 members, got %d", remainingMembers)
	}

	var remainingMessages int64
	if err := db.Model(&models.GroupMessage{}).Where("group_id = ?", group.GroupID).Count(&remainingMessages).Error; err != nil {
		t.Fatalf("failed to count messages: %v", err)
	}
	if remainingMessages != 0 {
		t.Errorf("expected 0 messages, got %d", remainingMessages)
	}
}

// TestListGroups_UserOnlyJoined verifies that a non-admin caller only sees
// groups they are a member of.
func TestListGroups_UserOnlyJoined(t *testing.T) {
	db := setupGroupTestDB(t)

	userID := "acc-user-list-001"
	joinedGroupID := "group-joined-001"
	otherGroupID := "group-other-001"

	now := time.Now().UnixMilli()
	require.NoError(t, db.Create(&models.Group{
		GroupID:    joinedGroupID,
		GroupName:  "Joined Group",
		CreateAtMs: now,
		UpdateAtMs: now,
	}).Error)
	require.NoError(t, db.Create(&models.Group{
		GroupID:    otherGroupID,
		GroupName:  "Other Group",
		CreateAtMs: now,
		UpdateAtMs: now,
	}).Error)
	require.NoError(t, db.Create(&models.GroupMember{
		GroupID:      joinedGroupID,
		MemberID:     userID,
		MemberName:   "Joined User",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}).Error)

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(authContextMiddleware(middleware.AuthContext{
		Account: &models.Account{
			AccountID: userID,
			Role:      models.AccountRoleUser,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}))
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewGroupHandler(db, nil, &config.Config{}, log)
	r.GET("/api/v1/groups", handler.ListGroups)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())

	var resp ListGroupsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Total)
	require.Len(t, resp.Items, 1)
	assert.Equal(t, joinedGroupID, resp.Items[0].GroupID)
}

// TestListGroups_AdminSeesAll verifies that an admin caller sees every group
// regardless of membership.
func TestListGroups_AdminSeesAll(t *testing.T) {
	db := setupGroupTestDB(t)

	adminID := "acc-admin-list-001"
	groupA := "group-admin-a"
	groupB := "group-admin-b"

	now := time.Now().UnixMilli()
	require.NoError(t, db.Create(&models.Group{
		GroupID:    groupA,
		GroupName:  "Group A",
		CreateAtMs: now,
		UpdateAtMs: now,
	}).Error)
	require.NoError(t, db.Create(&models.Group{
		GroupID:    groupB,
		GroupName:  "Group B",
		CreateAtMs: now,
		UpdateAtMs: now,
	}).Error)
	// Admin is not a member of any group.

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(authContextMiddleware(middleware.AuthContext{
		Account: &models.Account{
			AccountID: adminID,
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}))
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewGroupHandler(db, nil, &config.Config{}, log)
	r.GET("/api/v1/groups", handler.ListGroups)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())

	var resp ListGroupsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(2), resp.Total)
	require.Len(t, resp.Items, 2)
}
