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
