// Package handlers provides message handler tests.
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
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)
// setupMessageTestDB creates an in-memory SQLite database and auto-migrates models.
func setupMessageTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open("file::memory:"), &gorm.Config{})
	require.NoError(t, err)

	err = db.AutoMigrate(&models.Group{}, &models.GroupMember{}, &models.GroupMessage{})
	require.NoError(t, err)

	return db
}
func setupMessageTestRouter(t *testing.T, db *gorm.DB) (*gin.Engine, *MessageHandler) {
	gin.SetMode(gin.TestMode)
	r := gin.New()

	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewMessageHandler(db, nil, nil, log)

	return r, handler
}

// createTestGroup creates a test group in the database.
func createTestGroup(t *testing.T, db *gorm.DB, groupID, groupName string) *models.Group {
	group := &models.Group{
		GroupID:    groupID,
		GroupName:  groupName,
		CreateAtMs: time.Now().UnixMilli(),
		UpdateAtMs: time.Now().UnixMilli(),
	}
	err := db.Create(group).Error
	require.NoError(t, err)
	return group
}

// createTestGroupMember creates a test group member in the database.
func createTestGroupMember(t *testing.T, db *gorm.DB, groupID, memberID string, memberType models.MemberType) *models.GroupMember {
	member := &models.GroupMember{
		GroupID:      groupID,
		MemberID:     memberID,
		MemberName:   "Test Member " + memberID,
		MemberType:   memberType,
		MemberStatus: models.MemberStatusOnline,
		CreateAtMs:   time.Now().UnixMilli(),
		UpdateAtMs:   time.Now().UnixMilli(),
	}
	err := db.Create(member).Error
	require.NoError(t, err)
	return member
}

// createTestMessage creates a test message in the database.
func createTestMessage(t *testing.T, db *gorm.DB, groupID, messageID, senderID string, senderType models.MemberType, processedMsgID string) *models.GroupMessage {
	msg := &models.GroupMessage{
		GroupID:         groupID,
		MessageID:       messageID,
		MessageText:     "Test message " + messageID,
		SenderID:        senderID,
		SenderType:      senderType,
		ProcessedMsgID:  processedMsgID,
		MessageAttachments: "[]",
		Mentions:        "[]",
		CreateAtMs:      time.Now().UnixMilli(),
		UpdateAtMs:      time.Now().UnixMilli(),
	}
	err := db.Create(msg).Error
	require.NoError(t, err)
	return msg
}

// TestListMessagesWithProcessedMsgIDFilter verifies filtering by processed_msg_id returns only matching messages.
func TestListMessagesWithProcessedMsgIDFilter(t *testing.T) {
	db := setupMessageTestDB(t)

	groupID := "group-1"
	createTestGroup(t, db, groupID, "Test Group")
	createTestGroupMember(t, db, groupID, "user-1", models.MemberTypeUser)

	// Create a user message that will be processed
	originalMsg := createTestMessage(t, db, groupID, "msg-original", "user-1", models.MemberTypeUser, "")

	// Create an agent response message with processed_msg_id pointing to the original message
	agentMsg := createTestMessage(t, db, groupID, "msg-agent-1", "agent-1", models.MemberTypeWorkerAgent, originalMsg.MessageID)

	// Create another unrelated message
	createTestMessage(t, db, groupID, "msg-unrelated", "user-1", models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db)
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	// Query with processed_msg_id filter
	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?processed_msg_id="+originalMsg.MessageID, nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp ListMessagesResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	// Should return exactly 1 message: the agent response
	assert.Equal(t, int64(1), resp.Total)
	assert.Len(t, resp.Items, 1)
	assert.Equal(t, agentMsg.MessageID, resp.Items[0].MessageID)
	assert.Equal(t, originalMsg.MessageID, resp.Items[0].ProcessedMsgID)
	assert.Equal(t, "agent-1", resp.Items[0].SenderID)
	assert.Equal(t, string(models.MemberTypeWorkerAgent), resp.Items[0].SenderType)
}

// TestListMessagesWithoutProcessedMsgIDFilter verifies that omitting processed_msg_id returns all messages.
func TestListMessagesWithoutProcessedMsgIDFilter(t *testing.T) {
	db := setupMessageTestDB(t)

	groupID := "group-2"
	createTestGroup(t, db, groupID, "Test Group 2")
	createTestGroupMember(t, db, groupID, "user-2", models.MemberTypeUser)

	// Create messages with and without processed_msg_id
	createTestMessage(t, db, groupID, "msg-1", "user-2", models.MemberTypeUser, "")
	createTestMessage(t, db, groupID, "msg-2", "user-2", models.MemberTypeUser, "")
	createTestMessage(t, db, groupID, "msg-3", "agent-2", models.MemberTypeWorkerAgent, "msg-1")

	router, handler := setupMessageTestRouter(t, db)
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	// Query without processed_msg_id filter
	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp ListMessagesResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	// Should return all 3 messages
	assert.Equal(t, int64(3), resp.Total)
	assert.Len(t, resp.Items, 3)
}

// TestListMessagesWithEmptyProcessedMsgID verifies that empty processed_msg_id returns all messages.
func TestListMessagesWithEmptyProcessedMsgID(t *testing.T) {
	db := setupMessageTestDB(t)

	groupID := "group-3"
	createTestGroup(t, db, groupID, "Test Group 3")
	createTestGroupMember(t, db, groupID, "user-3", models.MemberTypeUser)

	createTestMessage(t, db, groupID, "msg-a", "user-3", models.MemberTypeUser, "")
	createTestMessage(t, db, groupID, "msg-b", "agent-3", models.MemberTypeWorkerAgent, "msg-a")

	router, handler := setupMessageTestRouter(t, db)
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	// Query with empty processed_msg_id
	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?processed_msg_id=", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp ListMessagesResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	// Empty string should be treated as "not provided" and return all messages
	assert.Equal(t, int64(2), resp.Total)
	assert.Len(t, resp.Items, 2)
}

// TestListMessagesResponseIncludesProcessedMsgID verifies the response includes processed_msg_id field.
func TestListMessagesResponseIncludesProcessedMsgID(t *testing.T) {
	db := setupMessageTestDB(t)

	groupID := "group-4"
	createTestGroup(t, db, groupID, "Test Group 4")
	createTestGroupMember(t, db, groupID, "user-4", models.MemberTypeUser)

	originalMsg := createTestMessage(t, db, groupID, "msg-original-4", "user-4", models.MemberTypeUser, "")
	agentMsg := createTestMessage(t, db, groupID, "msg-agent-4", "agent-4", models.MemberTypeWorkerAgent, originalMsg.MessageID)

	router, handler := setupMessageTestRouter(t, db)
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	// Query all messages
	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp ListMessagesResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	require.Len(t, resp.Items, 2)

	// Find the agent message in the response
	var foundAgentMsg bool
	for _, item := range resp.Items {
		if item.MessageID == agentMsg.MessageID {
			foundAgentMsg = true
			assert.Equal(t, originalMsg.MessageID, item.ProcessedMsgID)
			assert.Equal(t, "agent-4", item.SenderID)
			assert.Equal(t, string(models.MemberTypeWorkerAgent), item.SenderType)
		}
	}
	assert.True(t, foundAgentMsg, "agent message should be present in response")
}

// TestListMessagesWithNonExistentProcessedMsgID verifies filtering by a non-existent processed_msg_id returns empty.
func TestListMessagesWithNonExistentProcessedMsgID(t *testing.T) {
	db := setupMessageTestDB(t)

	groupID := "group-5"
	createTestGroup(t, db, groupID, "Test Group 5")
	createTestGroupMember(t, db, groupID, "user-5", models.MemberTypeUser)

	createTestMessage(t, db, groupID, "msg-5", "user-5", models.MemberTypeUser, "")
	createTestMessage(t, db, groupID, "msg-6", "agent-5", models.MemberTypeWorkerAgent, "msg-5")

	router, handler := setupMessageTestRouter(t, db)
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	// Query with a processed_msg_id that does not exist
	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?processed_msg_id=non-existent-id", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp ListMessagesResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	assert.Equal(t, int64(0), resp.Total)
	assert.Len(t, resp.Items, 0)
}

// authContextMiddleware returns a Gin middleware that injects the provided
// AuthContext for handler tests.
func authContextMiddleware(ac middleware.AuthContext) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Set("auth_context", ac)
		c.Next()
	}
}

// TestCreateMessage_DerivesSenderFromAuth verifies that the handler derives
// sender_id and sender_type from the authenticated account and does not read
// them from the request body.
func TestCreateMessage_DerivesSenderFromAuth(t *testing.T) {
	db := setupMessageTestDB(t)

	accountID := "acc-test-user-001"
	groupID := "group-create-1"
	createTestGroup(t, db, groupID, "Create Message Test Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(authContextMiddleware(middleware.AuthContext{
		Account: &models.Account{
			AccountID: accountID,
			Role:      models.AccountRoleUser,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}))
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewMessageHandler(db, nil, nil, log)
	r.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "hello from auth",
		// Intentionally omit sender_id and sender_type; the server must derive them.
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	var resp MessageResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, accountID, resp.SenderID)
	assert.Equal(t, string(models.MemberTypeUser), resp.SenderType)
	assert.Equal(t, "hello from auth", resp.MessageText)
}

// TestCreateMessage_RejectNonMember verifies that an authenticated user who is
// not a member of the group receives 403 Forbidden.
func TestCreateMessage_RejectNonMember(t *testing.T) {
	db := setupMessageTestDB(t)

	memberID := "acc-member-002"
	nonMemberID := "acc-non-member-002"
	groupID := "group-create-2"
	createTestGroup(t, db, groupID, "Create Message Non Member Group")
	createTestGroupMember(t, db, groupID, memberID, models.MemberTypeUser)

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(authContextMiddleware(middleware.AuthContext{
		Account: &models.Account{
			AccountID: nonMemberID,
			Role:      models.AccountRoleUser,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}))
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	handler := NewMessageHandler(db, nil, nil, log)
	r.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello from non-member"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}
