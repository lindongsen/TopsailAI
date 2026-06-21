package handlers

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
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
// listGroupsResponseWrapper mirrors the envelope produced by writeListResponse.
type listGroupsResponseWrapper struct {
	Data struct {
		Items  []GroupResponse `json:"items"`
		Total  int64        `json:"total"`
		Offset int          `json:"offset"`
		Limit  int          `json:"limit"`
	} `json:"data"`
	TraceID string `json:"trace_id"`
}


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
		CreatorID:    "acc-creator",
		OwnerID:      "acc-owner",
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
	if resp.CreatorID != "acc-creator" {
		t.Errorf("creator_id = %v", resp.CreatorID)
	}
	if resp.OwnerID != "acc-owner" {
		t.Errorf("owner_id = %v", resp.OwnerID)
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
	resp := listGroupsResponseWrapper{}
	resp.Data.Total = 2
	resp.Data.Items = []GroupResponse{
		{GroupID: "g1", GroupName: "Group 1"},
		{GroupID: "g2", GroupName: "Group 2"},
	}

	if resp.Data.Total != 2 {
		t.Errorf("total = %d, want 2", resp.Data.Total)
	}
	if len(resp.Data.Items) != 2 {
		t.Errorf("items length = %d, want 2", len(resp.Data.Items))
	}
	if resp.Data.Items[0].GroupID != "g1" {
		t.Errorf("first item group_id = %v", resp.Data.Items[0].GroupID)
	}
	if resp.Data.Items[1].GroupID != "g2" {
		t.Errorf("second item group_id = %v", resp.Data.Items[1].GroupID)
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
	pub := &mockGroupPublisher{}
	return NewGroupHandler(db, pub, cfg, log)
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
	if response.CreatorID != creator.AccountID {
		t.Errorf("expected creator_id %s, got %s", creator.AccountID, response.CreatorID)
	}
	if response.OwnerID != creator.AccountID {
		t.Errorf("expected owner_id %s, got %s", creator.AccountID, response.OwnerID)
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

	// Verify CreatorID and OwnerID are set to the authenticated account.
	var stored models.Group
	require.NoError(t, db.First(&stored, "group_id = ?", groupID).Error)
	assert.Equal(t, creator.AccountID, stored.CreatorID)
	assert.Equal(t, creator.AccountID, stored.OwnerID)
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
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
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
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
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

	var resp listGroupsResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Data.Total)
	require.Len(t, resp.Data.Items, 1)
	assert.Equal(t, joinedGroupID, resp.Data.Items[0].GroupID)
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

	var resp listGroupsResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(2), resp.Data.Total)
	require.Len(t, resp.Data.Items, 2)
}

// mockGroupPublisher is a test double for the GroupPublisher interface.
type mockGroupPublisher struct {
	createErr          error
	modifyErr          error
	deleteErr          error
	memberCreateErr    error
	createCalled       bool
	modifyCalled       bool
	deleteCalled       bool
	memberCreateCalled bool
}

func (m *mockGroupPublisher) PublishGroupCreate(group *models.Group) error {
	m.createCalled = true
	return m.createErr
}

func (m *mockGroupPublisher) PublishGroupModify(group *models.Group) error {
	m.modifyCalled = true
	return m.modifyErr
}

func (m *mockGroupPublisher) PublishGroupDelete(groupID string) error {
	m.deleteCalled = true
	return m.deleteErr
}

func (m *mockGroupPublisher) PublishGroupMemberCreate(member *models.GroupMember) error {
	m.memberCreateCalled = true
	return m.memberCreateErr
}

// TestCreateGroup_Unauthorized verifies that creating a group without an auth
// context returns 401 Unauthorized.
func TestCreateGroup_Unauthorized(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	handler := setupGroupTestHandler(t, db, &config.Config{})

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	body := CreateGroupRequest{GroupName: "Unauthorized Group"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateGroup(c)

	require.Equal(t, http.StatusUnauthorized, w.Code)
}

// TestCreateGroup_InvalidJSON verifies that malformed JSON returns 400.
func TestCreateGroup_InvalidJSON(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	handler := setupGroupTestHandler(t, db, &config.Config{})

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID:   "acc-001",
			AccountName: "Test",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBufferString("{invalid json"))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateGroup(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestCreateGroup_HashKeyFailure verifies that a bcrypt failure during group
// key hashing returns 500 Internal Server Error.
func TestCreateGroup_HashKeyFailure(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	handler := setupGroupTestHandler(t, db, &config.Config{})

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID:   "acc-001",
			AccountName: "Test",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	body := CreateGroupRequest{GroupName: "Secret Group", GroupKey: "secret"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	oldCost := bcryptCost
	bcryptCost = 32 // invalid cost > bcrypt.MaxCost
	defer func() { bcryptCost = oldCost }()

	handler.CreateGroup(c)

	require.Equal(t, http.StatusInternalServerError, w.Code)
}

// TestCreateGroup_PublisherFailureStillSucceeds verifies that group creation
// succeeds even when NATS publishing fails.
func TestCreateGroup_PublisherFailureStillSucceeds(t *testing.T) {
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
				TimeoutChat:        600 * time.Second,
			},
		},
	}
	pub := &mockGroupPublisher{
		createErr:       errors.New("nats create failure"),
		memberCreateErr: errors.New("nats member create failure"),
	}
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewGroupHandler(db, pub, cfg, log)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID:   "acc-001",
			AccountName: "Test",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	body := CreateGroupRequest{GroupName: "Publisher Failure Group"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
	assert.True(t, pub.createCalled)
	assert.True(t, pub.memberCreateCalled)
}

// TestGetGroup_Success verifies retrieving an existing group by ID.
func TestGetGroup_Success(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	now := time.Now().UnixMilli()
	group := models.Group{
		GroupID:      "group-get-success",
		GroupName:    "Get Group",
		GroupContext: "context",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&group).Error)

	handler := setupGroupTestHandler(t, db, &config.Config{})
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+group.GroupID, nil)
	c.Params = gin.Params{{Key: "group_id", Value: group.GroupID}}

	handler.GetGroup(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp GroupResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, group.GroupID, resp.GroupID)
	assert.Equal(t, group.GroupName, resp.GroupName)
	assert.Equal(t, group.GroupContext, resp.GroupContext)
}

// TestGetGroup_NotFound verifies that a missing group returns 404.
func TestGetGroup_NotFound(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	handler := setupGroupTestHandler(t, db, &config.Config{})

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/non-existent", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "non-existent"}}

	handler.GetGroup(c)

	require.Equal(t, http.StatusNotFound, w.Code)
}


// TestUpdateGroup_Success verifies updating group name and context.
func TestUpdateGroup_Success(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	now := time.Now().UnixMilli()
	group := models.Group{
		GroupID:      "group-update-success",
		GroupName:    "Old Name",
		GroupContext: "Old Context",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&group).Error)

	handler := setupGroupTestHandler(t, db, &config.Config{})
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	body := UpdateGroupRequest{GroupName: "New Name", GroupContext: "New Context"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+group.GroupID, bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: group.GroupID}}

	handler.UpdateGroup(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp GroupResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "New Name", resp.GroupName)
	assert.Equal(t, "New Context", resp.GroupContext)
}

// TestUpdateGroup_UpdateKey verifies that updating the group key re-hashes it.
func TestUpdateGroup_UpdateKey(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	now := time.Now().UnixMilli()
	group := models.Group{
		GroupID:    "group-update-key",
		GroupName:  "Key Group",
		GroupKey:   "",
		CreateAtMs: now,
		UpdateAtMs: now,
	}
	require.NoError(t, db.Create(&group).Error)

	handler := setupGroupTestHandler(t, db, &config.Config{})
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	body := UpdateGroupRequest{GroupKey: "new-secret"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+group.GroupID, bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: group.GroupID}}

	handler.UpdateGroup(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp GroupResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Empty(t, resp.GroupKey, "response must not expose group_key")

	var stored models.Group
	require.NoError(t, db.First(&stored, "group_id = ?", group.GroupID).Error)
	assert.NotEmpty(t, stored.GroupKey)
	assert.NotEqual(t, "new-secret", stored.GroupKey)
}

// TestUpdateGroup_NotFound verifies that updating a missing group returns 404.
func TestUpdateGroup_NotFound(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	handler := setupGroupTestHandler(t, db, &config.Config{})

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	body := UpdateGroupRequest{GroupName: "New Name"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/non-existent", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "non-existent"}}

	handler.UpdateGroup(c)

	require.Equal(t, http.StatusNotFound, w.Code)
}

// TestListGroups_InvalidSortKey verifies that an unknown sort_key returns 400.
func TestListGroups_InvalidSortKey(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	r := gin.New()
	r.Use(authContextMiddleware(middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}))
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewGroupHandler(db, nil, &config.Config{}, log)
	r.GET("/api/v1/groups", handler.ListGroups)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups?sort_key=invalid", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestListGroups_TimeRangeFilter verifies create_at_ms filtering.
func TestListGroups_TimeRangeFilter(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	now := time.Now().UnixMilli()

	oldGroup := models.Group{GroupID: "group-time-old", GroupName: "Old Group"}
	require.NoError(t, db.Create(&oldGroup).Error)
	require.NoError(t, db.Model(&oldGroup).UpdateColumns(map[string]interface{}{
		"create_at_ms": now - 1000,
		"update_at_ms": now - 1000,
	}).Error)

	newGroup := models.Group{GroupID: "group-time-new", GroupName: "New Group"}
	require.NoError(t, db.Create(&newGroup).Error)
	require.NoError(t, db.Model(&newGroup).UpdateColumns(map[string]interface{}{
		"create_at_ms": now + 1000,
		"update_at_ms": now + 1000,
	}).Error)

	r := gin.New()
	r.Use(authContextMiddleware(middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}))
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewGroupHandler(db, nil, &config.Config{}, log)
	r.GET("/api/v1/groups", handler.ListGroups)

	req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/v1/groups?create_at_ms=%d-%d", now-2000, now-500), nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	var resp listGroupsResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Data.Total)
	require.Len(t, resp.Data.Items, 1)
	assert.Equal(t, "group-time-old", resp.Data.Items[0].GroupID)
}

// TestListGroups_PaginationClamping verifies negative offset and zero limit
// are clamped to their defaults.
func TestListGroups_PaginationClamping(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	now := time.Now().UnixMilli()
	for i := 0; i < 5; i++ {
		require.NoError(t, db.Create(&models.Group{
			GroupID:    fmt.Sprintf("group-page-%d", i),
			GroupName:  fmt.Sprintf("Group %d", i),
			CreateAtMs: now,
			UpdateAtMs: now,
		}).Error)
	}

	r := gin.New()
	r.Use(authContextMiddleware(middleware.AuthContext{
		Account: &models.Account{
			AccountID: "acc-admin",
			Role:      models.AccountRoleAdmin,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}))
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewGroupHandler(db, nil, &config.Config{}, log)
	r.GET("/api/v1/groups", handler.ListGroups)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups?offset=-1&limit=0", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	var resp listGroupsResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Data.Offset)
	assert.Equal(t, 1000, resp.Data.Limit)
	assert.Equal(t, int64(5), resp.Data.Total)
}

// TestHashGroupKey verifies empty and non-empty key hashing behavior.
func TestHashGroupKey(t *testing.T) {
	empty, err := hashGroupKey("")
	require.NoError(t, err)
	assert.Empty(t, empty)

	hashed, err := hashGroupKey("secret-key")
	require.NoError(t, err)
	assert.NotEmpty(t, hashed)
	assert.NotEqual(t, "secret-key", hashed)
}

// TestSanitizeMemberName verifies member name sanitization rules.
func TestSanitizeMemberName(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"Alice", "Alice"},
		{"Alice Smith", "Alice_Smith"},
		{"", "user"},
		{"!@#$%", "_____"},
		{"user_123-test", "user_123-test"},
		{"日本語", "___"},
	}
	for _, tc := range tests {
		t.Run(tc.input, func(t *testing.T) {
			assert.Equal(t, tc.want, sanitizeMemberName(tc.input))
		})
	}
}

// TestBuildCreatorMember verifies the creator member built from an account.
func TestBuildCreatorMember(t *testing.T) {
	group := &models.Group{GroupID: "group-1", GroupName: "Test Group"}
	account := &models.Account{AccountID: "acc-creator", AccountName: "Alice Smith"}
	member := buildCreatorMember(group, account)

	assert.Equal(t, group.GroupID, member.GroupID)
	assert.Equal(t, account.AccountID, member.MemberID)
	assert.Equal(t, "Alice_Smith", member.MemberName)
	assert.Equal(t, models.MemberTypeUser, member.MemberType)
	assert.Equal(t, models.MemberStatusOnline, member.MemberStatus)
	assert.Equal(t, "Group creator", member.MemberDescription)
	assert.NotZero(t, member.CreateAtMs)
	assert.NotZero(t, member.UpdateAtMs)
}

// TestCreateGroup_ManagerAgentInvalidMemberID verifies that creating a group
// with an invalid configured manager-agent member_id returns 500 and does not
// persist the group.
func TestCreateGroup_ManagerAgentInvalidMemberID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	cfg := &config.Config{
		Agent: config.AgentConfig{
			ManagerAgent: config.ManagerAgentConfig{
				Adaptor:           "topsailai_agent",
				MemberID:          "manager agent!",
				MemberName:        "manager-agent",
				MemberDescription: "Default group manager agent",
				CmdChat:           "topsailai_agent_cmd_chat",
				TimeoutChat:       600 * time.Second,
			},
		},
	}
	handler := setupGroupTestHandler(t, db, cfg)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID:   "acc-001",
			AccountName: "Test",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	body := CreateGroupRequest{GroupName: "Invalid Manager ID Group"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateGroup(c)

	require.Equal(t, http.StatusInternalServerError, w.Code)

	var count int64
	require.NoError(t, db.Model(&models.Group{}).Count(&count).Error)
	assert.Equal(t, int64(0), count)
}

// TestCreateGroup_ManagerAgentInvalidMemberName verifies that creating a group
// with an invalid configured manager-agent member_name returns 500 and does not
// persist the group.
func TestCreateGroup_ManagerAgentInvalidMemberName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	cfg := &config.Config{
		Agent: config.AgentConfig{
			ManagerAgent: config.ManagerAgentConfig{
				Adaptor:           "topsailai_agent",
				MemberID:          "manager-agent",
				MemberName:        "manager agent!",
				MemberDescription: "Default group manager agent",
				CmdChat:           "topsailai_agent_cmd_chat",
				TimeoutChat:       600 * time.Second,
			},
		},
	}
	handler := setupGroupTestHandler(t, db, cfg)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID:   "acc-001",
			AccountName: "Test",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	body := CreateGroupRequest{GroupName: "Invalid Manager Name Group"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateGroup(c)

	require.Equal(t, http.StatusInternalServerError, w.Code)

	var count int64
	require.NoError(t, db.Model(&models.Group{}).Count(&count).Error)
	assert.Equal(t, int64(0), count)
}

// TestGroupHandler_GetGroup_UserMemberOnly verifies that a non-admin user can
// only retrieve groups they are a member of.
func TestGroupHandler_GetGroup_UserMemberOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	now := time.Now().UnixMilli()

	memberGroup := models.Group{
		GroupID:      "group-member-get",
		GroupName:    "Member Group",
		GroupContext: "context",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&memberGroup).Error)
	require.NoError(t, db.Create(&models.GroupMember{
		GroupID:      memberGroup.GroupID,
		MemberID:     "acc-user-get",
		MemberName:   "User",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}).Error)

	otherGroup := models.Group{
		GroupID:      "group-other-get",
		GroupName:    "Other Group",
		GroupContext: "context",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&otherGroup).Error)

	handler := setupGroupTestHandler(t, db, &config.Config{})

	tests := []struct {
		name           string
		groupID        string
		expectedStatus int
	}{
		{"member group", memberGroup.GroupID, http.StatusOK},
		{"non-member group", otherGroup.GroupID, http.StatusForbidden},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", middleware.AuthContext{
				Account: &models.Account{
					AccountID: "acc-user-get",
					Role:      models.AccountRoleUser,
					Status:    models.AccountStatusActive,
				},
				IsAuthenticated: true,
			})
			c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+tt.groupID, nil)
			c.Params = gin.Params{{Key: "group_id", Value: tt.groupID}}

			handler.GetGroup(c)

			require.Equal(t, tt.expectedStatus, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestGroupHandler_UpdateGroup_UserOwnOnly verifies that a non-admin user can
// only update groups they own.
func TestGroupHandler_UpdateGroup_UserOwnOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	now := time.Now().UnixMilli()

	ownGroup := models.Group{
		GroupID:      "group-own-update",
		GroupName:    "Own Group",
		GroupContext: "context",
		CreatorID:    "acc-user-update",
		OwnerID:      "acc-user-update",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&ownGroup).Error)

	otherGroup := models.Group{
		GroupID:      "group-other-update",
		GroupName:    "Other Group",
		GroupContext: "context",
		CreatorID:    "acc-other",
		OwnerID:      "acc-other",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&otherGroup).Error)

	handler := setupGroupTestHandler(t, db, &config.Config{})

	tests := []struct {
		name           string
		groupID        string
		expectedStatus int
	}{
		{"own group", ownGroup.GroupID, http.StatusOK},
		{"other group", otherGroup.GroupID, http.StatusForbidden},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			body := UpdateGroupRequest{GroupName: "Updated Name"}
			jsonBody, _ := json.Marshal(body)
			c.Set("auth_context", middleware.AuthContext{
				Account: &models.Account{
					AccountID: "acc-user-update",
					Role:      models.AccountRoleUser,
					Status:    models.AccountStatusActive,
				},
				IsAuthenticated: true,
			})
			c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+tt.groupID, bytes.NewBuffer(jsonBody))
			c.Request.Header.Set("Content-Type", "application/json")
			c.Params = gin.Params{{Key: "group_id", Value: tt.groupID}}

			handler.UpdateGroup(c)

			require.Equal(t, tt.expectedStatus, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestGroupHandler_DeleteGroup_UserOwnOnly verifies that a non-admin user can
// only delete groups they own.
func TestGroupHandler_DeleteGroup_UserOwnOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	now := time.Now().UnixMilli()

	ownGroup := models.Group{
		GroupID:      "group-own-delete",
		GroupName:    "Own Group",
		GroupContext: "context",
		CreatorID:    "acc-user-delete",
		OwnerID:      "acc-user-delete",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&ownGroup).Error)

	otherGroup := models.Group{
		GroupID:      "group-other-delete",
		GroupName:    "Other Group",
		GroupContext: "context",
		CreatorID:    "acc-other",
		OwnerID:      "acc-other",
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&otherGroup).Error)

	handler := setupGroupTestHandler(t, db, &config.Config{})

	tests := []struct {
		name           string
		groupID        string
		expectedStatus int
	}{
		{"own group", ownGroup.GroupID, http.StatusNoContent},
		{"other group", otherGroup.GroupID, http.StatusForbidden},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", middleware.AuthContext{
				Account: &models.Account{
					AccountID: "acc-user-delete",
					Role:      models.AccountRoleUser,
					Status:    models.AccountStatusActive,
				},
				IsAuthenticated: true,
			})
			c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/"+tt.groupID, nil)
			c.Params = gin.Params{{Key: "group_id", Value: tt.groupID}}

			handler.DeleteGroup(c)

			require.Equal(t, tt.expectedStatus, c.Writer.Status(), "body: %s", w.Body.String())
		})
	}
}

// TestGroupHandler_CreateGroup_GroupKeyHashed verifies that the plaintext
// group_key is never returned in the API response.
func TestGroupHandler_CreateGroup_GroupKeyHashed(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupTestDB(t)
	handler := setupGroupTestHandler(t, db, &config.Config{})

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		Account: &models.Account{
			AccountID:   "acc-key-create",
			AccountName: "Key Creator",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
		IsAuthenticated: true,
	})
	body := CreateGroupRequest{
		GroupName:    "Secret Group",
		GroupContext: "secret context",
		GroupKey:     "super-secret-key",
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateGroup(c)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	var resp GroupResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Empty(t, resp.GroupKey, "response must not expose group_key")

	var stored models.Group
	require.NoError(t, db.First(&stored, "group_id = ?", resp.GroupID).Error)
	assert.NotEmpty(t, stored.GroupKey, "stored group_key must be hashed")
	assert.NotEqual(t, "super-secret-key", stored.GroupKey, "stored group_key must not be plaintext")
}
