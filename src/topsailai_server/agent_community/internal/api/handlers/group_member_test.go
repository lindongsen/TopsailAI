// Package handlers provides group member handler tests.
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
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/utils"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// listGroupMembersResponseWrapper mirrors the envelope produced by writeListResponse.
type listGroupMembersResponseWrapper struct {
	Data struct {
		Items  []GroupMemberResponse `json:"items"`
		Total  int64                 `json:"total"`
		Offset int                   `json:"offset"`
		Limit  int                   `json:"limit"`
	} `json:"data"`
	TraceID string `json:"trace_id"`
}

// groupMemberResponseWrapper mirrors the standard envelope produced by writeJSON.
type groupMemberResponseWrapper struct {
	Data    GroupMemberResponse `json:"data"`
	Error   string              `json:"error"`
	TraceID string              `json:"trace_id"`
}


const testAdminAccountID = "acc-admin"
const testUserAccountID = "acc-user"
const testOtherUserAccountID = "acc-other"

// setupGroupMemberTestDB creates an in-memory SQLite database and auto-migrates models.
func setupGroupMemberTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open("file::memory:"), &gorm.Config{})
	require.NoError(t, err)

	err = db.AutoMigrate(&models.Group{}, &models.GroupMember{})
	require.NoError(t, err)

	return db
}

// setupGroupMemberTestHandler creates a GroupMemberHandler for tests.
func setupGroupMemberTestHandler(t *testing.T, db *gorm.DB, pub GroupMemberPublisher) *GroupMemberHandler {
	if pub == nil {
		pub = &mockGroupMemberPublisher{}
	}
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	return NewGroupMemberHandler(db, pub, log)
}

// createTestGroupForMembers creates a group owned by the test admin account.
func createTestGroupForMembers(t *testing.T, db *gorm.DB, groupID string) {
	createTestGroupForMembersWithOwner(t, db, groupID, testAdminAccountID)
}

// createTestGroupForMembersWithOwner creates a group with a specific owner.
func createTestGroupForMembersWithOwner(t *testing.T, db *gorm.DB, groupID, ownerID string) {
	now := time.Now().UnixMilli()
	group := models.Group{
		GroupID:    groupID,
		GroupName:  "Test Group",
		CreatorID:  ownerID,
		OwnerID:    ownerID,
		CreateAtMs: now,
		UpdateAtMs: now,
	}
	require.NoError(t, db.Create(&group).Error)
}
// createTestGroupForMembersWithKey creates a group with a specific owner and a bcrypt-hashed group_key.
func createTestGroupForMembersWithKey(t *testing.T, db *gorm.DB, groupID, key string) {
	now := time.Now().UnixMilli()
	hash, err := utils.HashGroupKey(key)
	require.NoError(t, err)
	group := models.Group{
		GroupID:    groupID,
		GroupName:  "Test Group",
		CreatorID:  testAdminAccountID,
		OwnerID:    testAdminAccountID,
		GroupKey:   hash,
		CreateAtMs: now,
		UpdateAtMs: now,
	}
	require.NoError(t, db.Create(&group).Error)
}


// createTestGroupMember creates a group member record.
func createTestGroupMemberForMemberHandler(t *testing.T, db *gorm.DB, groupID, memberID string, memberType models.MemberType) {
	now := time.Now().UnixMilli()
	member := models.GroupMember{
		GroupID:      groupID,
		MemberID:     memberID,
		MemberName:   memberID,
		MemberType:   memberType,
		MemberStatus: models.MemberStatusOnline,
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}
	require.NoError(t, db.Create(&member).Error)
}

// setAdminAuth injects an admin AuthContext into the Gin context.
func setAdminAuth(c *gin.Context, accountID string) {
	c.Set("auth_context", middleware.AuthContext{
		IsAuthenticated: true,
		Account: &models.Account{
			AccountID:   accountID,
			AccountName: accountID,
			Role:        models.AccountRoleAdmin,
			Status:      models.AccountStatusActive,
		},
	})
}

// setUserAuth injects a user AuthContext into the Gin context.
func setUserAuth(c *gin.Context, accountID string) {
	c.Set("auth_context", middleware.AuthContext{
		IsAuthenticated: true,
		Account: &models.Account{
			AccountID:   accountID,
			AccountName: accountID,
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
	})
}

// mockGroupMemberPublisher records publish calls and can return errors.
type mockGroupMemberPublisher struct {
	createCalled       bool
	modifyCalled       bool
	deleteCalled       bool
	lastDeleteGroupID  string
	lastDeleteMemberID string
	createErr          error
	modifyErr          error
	deleteErr          error
}

func (m *mockGroupMemberPublisher) PublishGroupMemberCreate(member *models.GroupMember) error {
	m.createCalled = true
	return m.createErr
}

func (m *mockGroupMemberPublisher) PublishGroupMemberModify(member *models.GroupMember) error {
	m.modifyCalled = true
	return m.modifyErr
}

func (m *mockGroupMemberPublisher) PublishGroupMemberDelete(groupID, memberID string) error {
	m.deleteCalled = true
	m.lastDeleteGroupID = groupID
	m.lastDeleteMemberID = memberID
	return m.deleteErr
}

func TestJoinGroupValidatesMemberID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "invalid id!",
		MemberName: "valid_name",
		MemberType: string(models.MemberTypeUser),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

func TestJoinGroupValidatesMemberName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "valid_id",
		MemberName: "invalid name!",
		MemberType: string(models.MemberTypeUser),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

func TestJoinGroupAcceptsValidMemberIDAndName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "valid_id-123",
		MemberName: "valid_name-123",
		MemberType: string(models.MemberTypeUser),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
}

func TestJoinGroupAcceptsMemberInterfaceAsObject(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := `{
		"member_id": "agent-001",
		"member_name": "AgentOne",
		"member_type": "worker-agent",
		"member_interface": {"adaptor": "mock_agent", "timeout_chat": 30}
	}`
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBufferString(body))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)

	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	require.NotEmpty(t, resp.Data.MemberInterface)
	require.True(t, json.Valid([]byte(resp.Data.MemberInterface)))
}

func TestJoinGroupAcceptsMemberInterfaceAsString(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := `{
		"member_id": "agent-002",
		"member_name": "AgentTwo",
		"member_type": "worker-agent",
		"member_interface": "{\"adaptor\":\"mock_agent\",\"timeout_chat\":30}"
	}`
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBufferString(body))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)

	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	expected := `{"adaptor":"mock_agent","timeout_chat":30}`
	assert.Equal(t, expected, resp.Data.MemberInterface)
}

func TestJoinGroupRejectsInvalidMemberInterfaceString(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := `{
		"member_id": "agent-003",
		"member_name": "AgentThree",
		"member_type": "worker-agent",
		"member_interface": "not-json"
	}`
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBufferString(body))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

func TestJoinGroup_AgentRequiresInterface(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "agent-no-interface",
		MemberName: "AgentNoInterface",
		MemberType: string(models.MemberTypeWorkerAgent),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

func TestUpdateMemberAcceptsMemberInterfaceAsObject(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	member := models.GroupMember{
		GroupID:         "group-001",
		MemberID:        "agent-004",
		MemberName:      "AgentFour",
		MemberType:      models.MemberTypeWorkerAgent,
		MemberStatus:    models.MemberStatusOnline,
		MemberInterface: "{}",
	}
	require.NoError(t, db.Create(&member).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := `{"member_interface": {"adaptor": "updated_agent"}}`
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/agent-004", bytes.NewBufferString(body))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "agent-004"}}

	handler.UpdateMember(c)

	require.Equal(t, http.StatusOK, w.Code)

	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	expected := `{"adaptor":"updated_agent"}`
	assert.Equal(t, expected, resp.Data.MemberInterface)
}

func TestUpdateMemberAcceptsMemberInterfaceAsString(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	member := models.GroupMember{
		GroupID:         "group-001",
		MemberID:        "agent-005",
		MemberName:      "AgentFive",
		MemberType:      models.MemberTypeWorkerAgent,
		MemberStatus:    models.MemberStatusOnline,
		MemberInterface: "{}",
	}
	require.NoError(t, db.Create(&member).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := `{"member_interface": "{\"adaptor\":\"updated_agent\"}"}`
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/agent-005", bytes.NewBufferString(body))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "agent-005"}}

	handler.UpdateMember(c)

	require.Equal(t, http.StatusOK, w.Code)

	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	expected := `{"adaptor":"updated_agent"}`
	assert.Equal(t, expected, resp.Data.MemberInterface)
}

// TestJoinGroup_GroupNotFound verifies that joining a non-existent group returns 404.
func TestJoinGroup_GroupNotFound(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "user-001",
		MemberName: "Alice",
		MemberType: string(models.MemberTypeUser),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/non-existent/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "non-existent"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusNotFound, w.Code)
}

// TestJoinGroup_InvalidMemberType verifies that an unknown member_type returns 400.
func TestJoinGroup_InvalidMemberType(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "user-001",
		MemberName: "Alice",
		MemberType: "bot",
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestJoinGroup_InvalidJSON verifies that malformed JSON returns 400.
func TestJoinGroup_InvalidJSON(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBufferString("not json"))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestJoinGroup_DuplicateMember verifies that joining with an existing member_id returns 409.
func TestJoinGroup_DuplicateMember(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	existing := models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-001",
		MemberName:   "Alice",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
	}
	require.NoError(t, db.Create(&existing).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "user-001",
		MemberName: "Alice2",
		MemberType: string(models.MemberTypeUser),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusConflict, w.Code)
}

// TestJoinGroup_PublisherFailureStillSucceeds verifies that join succeeds even when NATS publishing fails.
func TestJoinGroup_PublisherFailureStillSucceeds(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	pub := &mockGroupMemberPublisher{createErr: errors.New("nats failure")}
	handler := setupGroupMemberTestHandler(t, db, pub)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "user-002",
		MemberName: "Bob",
		MemberType: string(models.MemberTypeUser),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-001/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
	assert.True(t, pub.createCalled)
}

// TestListGroupMembers_Success verifies listing members of a group.
func TestListGroupMembers_Success(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	now := time.Now().UnixMilli()
	require.NoError(t, db.Create(&models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-003",
		MemberName:   "Charlie",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
		CreateAtMs:   now,
		UpdateAtMs:   now,
	}).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-001/members", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.ListGroupMembers(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp listGroupMembersResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Data.Total)
	require.Len(t, resp.Data.Items, 1)
	assert.Equal(t, "user-003", resp.Data.Items[0].MemberID)
}

// TestListGroupMembers_InvalidSortKey verifies that an unknown sort_key returns 400.
func TestListGroupMembers_InvalidSortKey(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-001/members?sort_key=invalid", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.ListGroupMembers(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestListGroupMembers_TimeRangeFilter verifies create_at_ms filtering.
func TestListGroupMembers_TimeRangeFilter(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	now := time.Now().UnixMilli()
	oldMember := models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-old",
		MemberName:   "Old",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
	}
	require.NoError(t, db.Create(&oldMember).Error)
	require.NoError(t, db.Model(&oldMember).UpdateColumns(map[string]interface{}{
		"create_at_ms": now - 1000,
		"update_at_ms": now - 1000,
	}).Error)

	newMember := models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-new",
		MemberName:   "New",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
	}
	require.NoError(t, db.Create(&newMember).Error)
	require.NoError(t, db.Model(&newMember).UpdateColumns(map[string]interface{}{
		"create_at_ms": now + 1000,
		"update_at_ms": now + 1000,
	}).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-001/members?create_at_ms="+timeRange(now-2000, now-500), nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.ListGroupMembers(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp listGroupMembersResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Data.Total)
	require.Len(t, resp.Data.Items, 1)
	assert.Equal(t, "user-old", resp.Data.Items[0].MemberID)
}

func timeRange(start, end int64) string {
	return fmt.Sprintf("%d-%d", start, end)
}

// TestUpdateMember_Success verifies updating member fields.
func TestUpdateMember_Success(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	pub := &mockGroupMemberPublisher{}
	handler := setupGroupMemberTestHandler(t, db, pub)

	member := models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-004",
		MemberName:   "Dave",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
	}
	require.NoError(t, db.Create(&member).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := UpdateMemberRequest{
		MemberName:        "David",
		MemberDescription: "Updated description",
		MemberStatus:      string(models.MemberStatusIdle),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/user-004", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "user-004"}}

	handler.UpdateMember(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "David", resp.Data.MemberName)
	assert.Equal(t, "Updated description", resp.Data.MemberDescription)
	assert.Equal(t, string(models.MemberStatusIdle), resp.Data.MemberStatus)
	assert.True(t, pub.modifyCalled)
}

// TestUpdateMember_InvalidMemberName verifies that an invalid member_name returns 400.
func TestUpdateMember_InvalidMemberName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	member := models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-005",
		MemberName:   "Eve",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
	}
	require.NoError(t, db.Create(&member).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := UpdateMemberRequest{MemberName: "invalid name!"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/user-005", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "user-005"}}

	handler.UpdateMember(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestUpdateMember_InvalidStatus verifies that an invalid member_status returns 400.
func TestUpdateMember_InvalidStatus(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	member := models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-status-invalid",
		MemberName:   "InvalidStatus",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
	}
	require.NoError(t, db.Create(&member).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := UpdateMemberRequest{MemberStatus: "unknown-status"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/user-status-invalid", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "user-status-invalid"}}

	handler.UpdateMember(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestUpdateMember_PublisherOnlyOnStatusChange verifies that modify event is only published when status changes.
func TestUpdateMember_PublisherOnlyOnStatusChange(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	pub := &mockGroupMemberPublisher{}
	handler := setupGroupMemberTestHandler(t, db, pub)

	member := models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-006",
		MemberName:   "Frank",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
	}
	require.NoError(t, db.Create(&member).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := UpdateMemberRequest{MemberDescription: "Only description changed"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/user-006", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "user-006"}}

	handler.UpdateMember(c)

	require.Equal(t, http.StatusOK, w.Code)
	assert.False(t, pub.modifyCalled)
}

// TestLeaveGroup_Success verifies deleting a member returns 204 with no body
// and without a text/plain content-type.
func TestLeaveGroup_Success(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	pub := &mockGroupMemberPublisher{}
	handler := setupGroupMemberTestHandler(t, db, pub)

	member := models.GroupMember{
		GroupID:      "group-001",
		MemberID:     "user-007",
		MemberName:   "Grace",
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
	}
	require.NoError(t, db.Create(&member).Error)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/group-001/members/user-007", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "user-007"}}

	handler.LeaveGroup(c)

	require.Equal(t, http.StatusNoContent, w.Code)
	assert.Empty(t, w.Body.String())
	assert.NotContains(t, w.Header().Get("Content-Type"), "text/plain")
	assert.True(t, pub.deleteCalled)
	assert.Equal(t, "group-001", pub.lastDeleteGroupID)
	assert.Equal(t, "user-007", pub.lastDeleteMemberID)
}

// TestLeaveGroup_NotFound verifies that leaving a non-existent member returns 404.
func TestLeaveGroup_NotFound(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-001")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/group-001/members/non-existent", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "non-existent"}}

	handler.LeaveGroup(c)

	require.Equal(t, http.StatusNotFound, w.Code)
}

// TestToGroupMemberResponse verifies conversion from model to response.
func TestToGroupMemberResponse(t *testing.T) {
	now := time.Now().UnixMilli()
	member := &models.GroupMember{
		GroupID:           "group-001",
		MemberID:          "user-008",
		MemberName:        "Hank",
		MemberDescription: "Test member",
		MemberStatus:      models.MemberStatusProcessing,
		MemberType:        models.MemberTypeManagerAgent,
		MemberInterface:   `{"adaptor":"mock"}`,
		LastReadMessageID: "msg-001",
		CreateAtMs:        now,
		UpdateAtMs:        now,
	}
	resp := toGroupMemberResponse(member)

	assert.Equal(t, "group-001", resp.GroupID)
	assert.Equal(t, "user-008", resp.MemberID)
	assert.Equal(t, "Hank", resp.MemberName)
	assert.Equal(t, "Test member", resp.MemberDescription)
	assert.Equal(t, string(models.MemberStatusProcessing), resp.MemberStatus)
	assert.Equal(t, string(models.MemberTypeManagerAgent), resp.MemberType)
	assert.Equal(t, `{"adaptor":"mock"}`, resp.MemberInterface)
	assert.Equal(t, "msg-001", resp.LastReadMessageID)
	assert.Equal(t, now, resp.CreateAtMs)
	assert.Equal(t, now, resp.UpdateAtMs)
}

// TestMemberRegexes verifies member_id and member_name regex patterns.
func TestMemberRegexes(t *testing.T) {
	valid := []string{"a", "A", "user_123", "agent-001", "test_name-1", "1", "_", "-"}
	for _, v := range valid {
		assert.True(t, memberIDRegex.MatchString(v), "expected %q to match memberIDRegex", v)
		assert.True(t, memberNameRegex.MatchString(v), "expected %q to match memberNameRegex", v)
	}

	invalid := []string{"", "user 1", "agent.001", "test@name", "foo/bar", "日本語", "foo bar"}
	for _, v := range invalid {
		assert.False(t, memberIDRegex.MatchString(v), "expected %q to not match memberIDRegex", v)
		assert.False(t, memberNameRegex.MatchString(v), "expected %q to not match memberNameRegex", v)
	}
}

// --- Authorization boundary tests ---

func TestGroupMemberHandler_Join_AdminAnyGroup(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-admin-join")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := JoinGroupRequest{
		MemberID:   "user-admin-join",
		MemberName: "AdminJoin",
		MemberType: string(models.MemberTypeUser),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-admin-join/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-admin-join"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
}

func TestGroupMemberHandler_Join_UserOwnGroupOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembersWithOwner(t, db, "group-user-own", testUserAccountID)
	createTestGroupForMembers(t, db, "group-user-other-public")
	createTestGroupForMembersWithKey(t, db, "group-user-other-private", "secret-key")
	handler := setupGroupMemberTestHandler(t, db, nil)

	// User can add member to own group.
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	body := JoinGroupRequest{
		MemberID:   "user-join-own",
		MemberName: "JoinOwn",
		MemberType: string(models.MemberTypeUser),
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-user-own/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-own"}}
	handler.JoinGroup(c)
	require.Equal(t, http.StatusCreated, w.Code)

	// User can self-join a public group they do not own (no member_id/member_type).
	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	selfJoinBody := JoinGroupRequest{
		MemberName: "SelfJoin",
	}
	jsonBody, _ = json.Marshal(selfJoinBody)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-user-other-public/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-other-public"}}
	handler.JoinGroup(c)
	require.Equal(t, http.StatusCreated, w.Code)
	var joinResp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &joinResp))
	require.Equal(t, testUserAccountID, joinResp.Data.MemberID)
	require.Equal(t, string(models.MemberTypeUser), joinResp.Data.MemberType)

	// User cannot self-join a public group while supplying member_id/member_type
	// (treated as an attempt to add a member).
	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	jsonBody, _ = json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-user-other-public/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-other-public"}}
	handler.JoinGroup(c)
	require.Equal(t, http.StatusForbidden, w.Code)

	// User cannot self-join (self-join) a private group they do not own without the key.
	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-user-other-private/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-other-private"}}
	handler.JoinGroup(c)
	require.Equal(t, http.StatusForbidden, w.Code)

	// User can self-join a private group with the correct key.
	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	privateJoinBody := JoinGroupRequest{
		MemberName: "SelfJoinPrivate",
		GroupKey:   "secret-key",
	}
	jsonBody, _ = json.Marshal(privateJoinBody)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-user-other-private/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-other-private"}}
	handler.JoinGroup(c)
	require.Equal(t, http.StatusCreated, w.Code)

	// User cannot self-join a private group with the wrong key.
	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	privateJoinBody.GroupKey = "wrong-key"
	jsonBody, _ = json.Marshal(privateJoinBody)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-user-other-private/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-other-private"}}
	handler.JoinGroup(c)
	require.Equal(t, http.StatusForbidden, w.Code)
}

func TestGroupMemberHandler_List_AdminAnyGroup(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-admin-list")
	createTestGroupMemberForMemberHandler(t, db, "group-admin-list", "user-list", models.MemberTypeUser)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-admin-list/members", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-admin-list"}}
	handler.ListGroupMembers(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp listGroupMembersResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Data.Total)
}

func TestGroupMemberHandler_List_UserMemberGroupOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-user-member")
	createTestGroupForMembers(t, db, "group-user-not-member")
	createTestGroupMemberForMemberHandler(t, db, "group-user-member", testUserAccountID, models.MemberTypeUser)
	handler := setupGroupMemberTestHandler(t, db, nil)

	// User can list members of a group they belong to.
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-user-member/members", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-member"}}
	handler.ListGroupMembers(c)
	require.Equal(t, http.StatusOK, w.Code)

	// User cannot list members of a group they do not belong to.
	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-user-not-member/members", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-not-member"}}
	handler.ListGroupMembers(c)
	require.Equal(t, http.StatusForbidden, w.Code)
}

func TestGroupMemberHandler_Update_AdminAny(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-admin-update")
	createTestGroupMemberForMemberHandler(t, db, "group-admin-update", "user-update", models.MemberTypeUser)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	body := UpdateMemberRequest{MemberName: "UpdatedByAdmin"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-admin-update/members/user-update", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-admin-update"}, {Key: "member_id", Value: "user-update"}}
	handler.UpdateMember(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "UpdatedByAdmin", resp.Data.MemberName)
}

func TestGroupMemberHandler_Update_UserOwnOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-user-update")
	createTestGroupMemberForMemberHandler(t, db, "group-user-update", testUserAccountID, models.MemberTypeUser)
	createTestGroupMemberForMemberHandler(t, db, "group-user-update", testOtherUserAccountID, models.MemberTypeUser)
	handler := setupGroupMemberTestHandler(t, db, nil)

	// User can update their own member record.
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	body := UpdateMemberRequest{MemberName: "UpdatedBySelf"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-user-update/members/"+testUserAccountID, bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-update"}, {Key: "member_id", Value: testUserAccountID}}
	handler.UpdateMember(c)
	require.Equal(t, http.StatusOK, w.Code)

	// User cannot update another member's record.
	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-user-update/members/"+testOtherUserAccountID, bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-update"}, {Key: "member_id", Value: testOtherUserAccountID}}
	handler.UpdateMember(c)
	require.Equal(t, http.StatusForbidden, w.Code)
}

func TestGroupMemberHandler_Leave_AdminAny(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-admin-leave")
	createTestGroupMemberForMemberHandler(t, db, "group-admin-leave", "user-leave", models.MemberTypeUser)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setAdminAuth(c, testAdminAccountID)
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/group-admin-leave/members/user-leave", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-admin-leave"}, {Key: "member_id", Value: "user-leave"}}
	handler.LeaveGroup(c)

	require.Equal(t, http.StatusNoContent, w.Code)
}

func TestGroupMemberHandler_Leave_UserOwnOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembers(t, db, "group-user-leave")
	createTestGroupMemberForMemberHandler(t, db, "group-user-leave", testUserAccountID, models.MemberTypeUser)
	createTestGroupMemberForMemberHandler(t, db, "group-user-leave", testOtherUserAccountID, models.MemberTypeUser)
	handler := setupGroupMemberTestHandler(t, db, nil)

	// User can leave their own member record.
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/group-user-leave/members/"+testUserAccountID, nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-leave"}, {Key: "member_id", Value: testUserAccountID}}
	handler.LeaveGroup(c)
	require.Equal(t, http.StatusNoContent, w.Code)

	// User cannot remove another member's record.
	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/group-user-leave/members/"+testOtherUserAccountID, nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-user-leave"}, {Key: "member_id", Value: testOtherUserAccountID}}
	handler.LeaveGroup(c)
	require.Equal(t, http.StatusForbidden, w.Code)
}

// createTestGroupWithKey creates a group with a hashed group_key.
func createTestGroupWithKey(t *testing.T, db *gorm.DB, groupID, ownerID, plainKey string) {
	now := time.Now().UnixMilli()
	var keyHash string
	if plainKey != "" {
		var err error
		keyHash, err = utils.HashGroupKey(plainKey)
		require.NoError(t, err)
	}
	group := models.Group{
		GroupID:    groupID,
		GroupName:  "Test Group",
		GroupKey:   keyHash,
		CreatorID:  ownerID,
		OwnerID:    ownerID,
		CreateAtMs: now,
		UpdateAtMs: now,
	}
	require.NoError(t, db.Create(&group).Error)
}

func TestJoinGroup_SelfJoinPublicGroup(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembersWithOwner(t, db, "group-public", testAdminAccountID)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	body := JoinGroupRequest{}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-public/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-public"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, testUserAccountID, resp.Data.MemberID)
	assert.Equal(t, string(models.MemberTypeUser), resp.Data.MemberType)
}

func TestJoinGroup_SelfJoinPrivateGroupWithCorrectKey(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupWithKey(t, db, "group-private", testAdminAccountID, "secret-key")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	body := JoinGroupRequest{GroupKey: "secret-key"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-private/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-private"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, testUserAccountID, resp.Data.MemberID)
}

func TestJoinGroup_SelfJoinPrivateGroupWithWrongKey(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupWithKey(t, db, "group-private", testAdminAccountID, "secret-key")
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	body := JoinGroupRequest{GroupKey: "wrong-key"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-private/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-private"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusForbidden, w.Code)
}

func TestJoinGroup_SelfJoinAlreadyMember(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembersWithOwner(t, db, "group-public", testAdminAccountID)
	createTestGroupMemberForMemberHandler(t, db, "group-public", testUserAccountID, models.MemberTypeUser)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	body := JoinGroupRequest{}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-public/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-public"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusForbidden, w.Code)
}

func TestJoinGroup_OwnerCanStillAddMember(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembersWithOwner(t, db, "group-owned", testUserAccountID)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	setUserAuth(c, testUserAccountID)
	body := JoinGroupRequest{
		MemberID:   "agent-001",
		MemberName: "AgentOne",
		MemberType: string(models.MemberTypeWorkerAgent),
		MemberInterface: MemberInterfaceField{value: `{"adaptor":"mock"}`},
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-owned/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-owned"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "agent-001", resp.Data.MemberID)
	assert.Equal(t, string(models.MemberTypeWorkerAgent), resp.Data.MemberType)
}

// TestJoinGroup_SelfJoinSanitizesAccountName verifies that when a user self-joins
// a group without providing member_name, the account name is sanitized to only
// contain alphanumeric characters, hyphens, and underscores.
func TestJoinGroup_SelfJoinSanitizesAccountName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembersWithOwner(t, db, "group-sanitize", testAdminAccountID)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		IsAuthenticated: true,
		Account: &models.Account{
			AccountID:   testUserAccountID,
			AccountName: "Alice Smith!@#",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
	})
	body := JoinGroupRequest{}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-sanitize/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-sanitize"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, testUserAccountID, resp.Data.MemberID)
	assert.Equal(t, "Alice_Smith___", resp.Data.MemberName)
}

// TestJoinGroup_SelfJoin_EmptyAccountNameDefaultsToUser verifies that when a
// user self-joins without member_name and their account name is empty, the
// stored member_name falls back to "user".
func TestJoinGroup_SelfJoin_EmptyAccountNameDefaultsToUser(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembersWithOwner(t, db, "group-empty-name", testAdminAccountID)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		IsAuthenticated: true,
		Account: &models.Account{
			AccountID:   testUserAccountID,
			AccountName: "",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
	})
	body := JoinGroupRequest{}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-empty-name/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-empty-name"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, testUserAccountID, resp.Data.MemberID)
	assert.Equal(t, "user", resp.Data.MemberName)
}

// TestJoinGroup_SelfJoin_ProvidedMemberNamePreserved verifies that when a user
// self-joins with a valid member_name, the provided name is stored unchanged.
func TestJoinGroup_SelfJoin_ProvidedMemberNamePreserved(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembersWithOwner(t, db, "group-provided-name", testAdminAccountID)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		IsAuthenticated: true,
		Account: &models.Account{
			AccountID:   testUserAccountID,
			AccountName: "Alice Smith!@#",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
	})
	body := JoinGroupRequest{MemberName: "Custom_Name-123"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-provided-name/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-provided-name"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusCreated, w.Code)
	var resp groupMemberResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, testUserAccountID, resp.Data.MemberID)
	assert.Equal(t, "Custom_Name-123", resp.Data.MemberName)
}

// TestJoinGroup_SelfJoin_InvalidProvidedMemberNameRejected verifies that when a
// user self-joins with a member_name containing disallowed characters, the
// request is rejected rather than stored.
func TestJoinGroup_SelfJoin_InvalidProvidedMemberNameRejected(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	createTestGroupForMembersWithOwner(t, db, "group-invalid-name", testAdminAccountID)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{
		IsAuthenticated: true,
		Account: &models.Account{
			AccountID:   testUserAccountID,
			AccountName: "Alice",
			Role:        models.AccountRoleUser,
			Status:      models.AccountStatusActive,
		},
	})
	body := JoinGroupRequest{MemberName: "Invalid Name!"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-invalid-name/members", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-invalid-name"}}

	handler.JoinGroup(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}
