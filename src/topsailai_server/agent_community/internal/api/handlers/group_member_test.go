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
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func setupGroupMemberTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	if err != nil {
		t.Fatalf("failed to open test database: %v", err)
	}
	if err := db.AutoMigrate(&models.Group{}, &models.GroupMember{}); err != nil {
		t.Fatalf("failed to migrate test database: %v", err)
	}
	return db
}

func setupGroupMemberTestHandler(t *testing.T, db *gorm.DB, pub GroupMemberPublisher) *GroupMemberHandler {
	t.Helper()
	group := models.Group{
		GroupID:   "group-001",
		GroupName: "Test Group",
	}
	if err := db.Create(&group).Error; err != nil {
		t.Fatalf("failed to create test group: %v", err)
	}
	log := logger.New(logger.Config{Level: "debug", Output: "stdout"})
	return NewGroupMemberHandler(db, pub, log)
}

// mockGroupMemberPublisher is a test double for GroupMemberPublisher.
type mockGroupMemberPublisher struct {
	createErr          error
	modifyErr          error
	deleteErr          error
	createCalled       bool
	modifyCalled       bool
	deleteCalled       bool
	lastCreateMember   *models.GroupMember
	lastModifyMember   *models.GroupMember
	lastDeleteGroupID  string
	lastDeleteMemberID string
}

func (m *mockGroupMemberPublisher) PublishGroupMemberCreate(member *models.GroupMember) error {
	m.createCalled = true
	m.lastCreateMember = member
	return m.createErr
}

func (m *mockGroupMemberPublisher) PublishGroupMemberModify(member *models.GroupMember) error {
	m.modifyCalled = true
	m.lastModifyMember = member
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
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status %d, got %d: %s", http.StatusBadRequest, w.Code, w.Body.String())
	}
}

func TestJoinGroupValidatesMemberName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status %d, got %d: %s", http.StatusBadRequest, w.Code, w.Body.String())
	}
}

func TestJoinGroupAcceptsValidMemberIDAndName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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

	if w.Code != http.StatusCreated {
		t.Fatalf("expected status %d, got %d: %s", http.StatusCreated, w.Code, w.Body.String())
	}
}

func TestJoinGroupAcceptsMemberInterfaceAsObject(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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

	if w.Code != http.StatusCreated {
		t.Fatalf("expected status %d, got %d: %s", http.StatusCreated, w.Code, w.Body.String())
	}

	var resp GroupMemberResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	if resp.MemberInterface == "" {
		t.Fatalf("expected member_interface to be stored as JSON string, got empty")
	}
	if !json.Valid([]byte(resp.MemberInterface)) {
		t.Fatalf("expected member_interface to be valid JSON, got %s", resp.MemberInterface)
	}
}

func TestJoinGroupAcceptsMemberInterfaceAsString(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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

	if w.Code != http.StatusCreated {
		t.Fatalf("expected status %d, got %d: %s", http.StatusCreated, w.Code, w.Body.String())
	}

	var resp GroupMemberResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	expected := `{"adaptor":"mock_agent","timeout_chat":30}`
	if resp.MemberInterface != expected {
		t.Fatalf("expected member_interface %s, got %s", expected, resp.MemberInterface)
	}
}

func TestJoinGroupRejectsInvalidMemberInterfaceString(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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

	if w.Code != http.StatusBadRequest {
		t.Fatalf("expected status %d, got %d: %s", http.StatusBadRequest, w.Code, w.Body.String())
	}
}

func TestUpdateMemberAcceptsMemberInterfaceAsObject(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	member := models.GroupMember{
		GroupID:         "group-001",
		MemberID:        "agent-004",
		MemberName:      "AgentFour",
		MemberType:      models.MemberTypeWorkerAgent,
		MemberStatus:    models.MemberStatusOnline,
		MemberInterface: "{}",
	}
	if err := db.Create(&member).Error; err != nil {
		t.Fatalf("failed to create test member: %v", err)
	}

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	body := `{"member_interface": {"adaptor": "updated_agent"}}`
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/agent-004", bytes.NewBufferString(body))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "agent-004"}}

	handler.UpdateMember(c)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d: %s", http.StatusOK, w.Code, w.Body.String())
	}

	var resp GroupMemberResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	expected := `{"adaptor":"updated_agent"}`
	if resp.MemberInterface != expected {
		t.Fatalf("expected member_interface %s, got %s", expected, resp.MemberInterface)
	}
}

func TestUpdateMemberAcceptsMemberInterfaceAsString(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	member := models.GroupMember{
		GroupID:         "group-001",
		MemberID:        "agent-005",
		MemberName:      "AgentFive",
		MemberType:      models.MemberTypeWorkerAgent,
		MemberStatus:    models.MemberStatusOnline,
		MemberInterface: "{}",
	}
	if err := db.Create(&member).Error; err != nil {
		t.Fatalf("failed to create test member: %v", err)
	}

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	body := `{"member_interface": "{\"adaptor\":\"updated_agent\"}"}`
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/agent-005", bytes.NewBufferString(body))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "agent-005"}}

	handler.UpdateMember(c)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d: %s", http.StatusOK, w.Code, w.Body.String())
	}

	var resp GroupMemberResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to unmarshal response: %v", err)
	}
	expected := `{"adaptor":"updated_agent"}`
	if resp.MemberInterface != expected {
		t.Fatalf("expected member_interface %s, got %s", expected, resp.MemberInterface)
	}
}

// TestJoinGroup_GroupNotFound verifies that joining a non-existent group returns 404.
func TestJoinGroup_GroupNotFound(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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

// TestJoinGroup_DuplicateMember verifies that joining with an existing member_id returns 409.
func TestJoinGroup_DuplicateMember(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
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
	pub := &mockGroupMemberPublisher{createErr: errors.New("nats failure")}
	handler := setupGroupMemberTestHandler(t, db, pub)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-001/members", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.ListGroupMembers(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp ListGroupMembersResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Total)
	require.Len(t, resp.Items, 1)
	assert.Equal(t, "user-003", resp.Items[0].MemberID)
}

// TestListGroupMembers_InvalidSortKey verifies that an unknown sort_key returns 400.
func TestListGroupMembers_InvalidSortKey(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-001/members?sort_key=invalid", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.ListGroupMembers(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestListGroupMembers_TimeRangeFilter verifies create_at_ms filtering.
func TestListGroupMembers_TimeRangeFilter(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
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
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/groups/group-001/members?create_at_ms="+timeRange(now-2000, now-500), nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}}

	handler.ListGroupMembers(c)

	require.Equal(t, http.StatusOK, w.Code)
	var resp ListGroupMembersResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Total)
	require.Len(t, resp.Items, 1)
	assert.Equal(t, "user-old", resp.Items[0].MemberID)
}

func timeRange(start, end int64) string {
	return fmt.Sprintf("%d-%d", start, end)
}

// TestUpdateMember_Success verifies updating member fields.
func TestUpdateMember_Success(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
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
	var resp GroupMemberResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "David", resp.MemberName)
	assert.Equal(t, "Updated description", resp.MemberDescription)
	assert.Equal(t, string(models.MemberStatusIdle), resp.MemberStatus)
	assert.True(t, pub.modifyCalled)
}

// TestUpdateMember_InvalidMemberName verifies that an invalid member_name returns 400.
func TestUpdateMember_InvalidMemberName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
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
	body := UpdateMemberRequest{MemberName: "invalid name!"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/user-005", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "user-005"}}

	handler.UpdateMember(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestUpdateMember_PublisherOnlyOnStatusChange verifies that modify event is only published when status changes.
func TestUpdateMember_PublisherOnlyOnStatusChange(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
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
	body := UpdateMemberRequest{MemberDescription: "Only description changed"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001/members/user-006", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "user-006"}}

	handler.UpdateMember(c)

	require.Equal(t, http.StatusOK, w.Code)
	assert.False(t, pub.modifyCalled)
}

// TestLeaveGroup_Success verifies deleting a member returns 204.
func TestLeaveGroup_Success(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
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
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/groups/group-001/members/user-007", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-001"}, {Key: "member_id", Value: "user-007"}}

	handler.LeaveGroup(c)

	require.Equal(t, http.StatusNoContent, w.Code)
	assert.True(t, pub.deleteCalled)
	assert.Equal(t, "group-001", pub.lastDeleteGroupID)
	assert.Equal(t, "user-007", pub.lastDeleteMemberID)
}

// TestLeaveGroup_NotFound verifies that leaving a non-existent member returns 404.
func TestLeaveGroup_NotFound(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db, nil)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
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
