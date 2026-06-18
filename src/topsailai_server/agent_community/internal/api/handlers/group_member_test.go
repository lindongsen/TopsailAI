package handlers

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
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

func setupGroupMemberTestHandler(t *testing.T, db *gorm.DB) *GroupMemberHandler {
	t.Helper()
	group := models.Group{
		GroupID:   "group-001",
		GroupName: "Test Group",
	}
	if err := db.Create(&group).Error; err != nil {
		t.Fatalf("failed to create test group: %v", err)
	}
	log := logger.New(logger.Config{Level: "debug", Output: "stdout"})
	return NewGroupMemberHandler(db, nil, log)
}

func TestJoinGroupValidatesMemberID(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupGroupMemberTestDB(t)
	handler := setupGroupMemberTestHandler(t, db)

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
	handler := setupGroupMemberTestHandler(t, db)

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
	handler := setupGroupMemberTestHandler(t, db)

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
	handler := setupGroupMemberTestHandler(t, db)

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
	handler := setupGroupMemberTestHandler(t, db)

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
	handler := setupGroupMemberTestHandler(t, db)

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
	handler := setupGroupMemberTestHandler(t, db)

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
	handler := setupGroupMemberTestHandler(t, db)

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
