// Package handlers provides message trigger handler tests.
package handlers

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// mockPublisher is a test double for nats.Publisher.
type mockPublisher struct {
	published        bool
	lastGroupID      string
	lastMsg          *models.GroupMessage
	lastTrigger      interface{}
	lastAgentID      string
	publishShouldErr error
}

func (m *mockPublisher) PublishPendingMessageWithAgentID(groupID string, msg *models.GroupMessage, trigger interface{}, agentID string) error {
	m.published = true
	m.lastGroupID = groupID
	m.lastMsg = msg
	m.lastTrigger = trigger
	m.lastAgentID = agentID
	return m.publishShouldErr
}

func (m *mockPublisher) PublishMessageCreate(msg *models.GroupMessage) error {
	return m.publishShouldErr
}

func (m *mockPublisher) PublishMessageModify(msg *models.GroupMessage) error {
	return m.publishShouldErr
}

func (m *mockPublisher) PublishMessageDelete(msg *models.GroupMessage) error {
	return m.publishShouldErr
}

// setupTriggerTestDB creates an in-memory SQLite database and auto-migrates models.
func setupTriggerTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open("file::memory:?cache=shared"), &gorm.Config{})
	require.NoError(t, err)

	err = db.AutoMigrate(&models.Group{}, &models.GroupMember{}, &models.GroupMessage{})
	require.NoError(t, err)

	return db
}

// setupTriggerTestRouter creates a gin router with the message handler and mock publisher for testing.
func setupTriggerTestRouter(t *testing.T, db *gorm.DB, pub *mockPublisher) (*gin.Engine, *MessageHandler) {
	gin.SetMode(gin.TestMode)
	r := gin.New()

	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	evaluator := trigger.NewEvaluator(10 * time.Minute)
	handler := NewMessageHandler(db, pub, evaluator, log)

	return r, handler
}

// TestTriggerMessage_WithAgentID verifies manual trigger with a specific agent_id returns 202.
func TestTriggerMessage_WithAgentID(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-1"
	createTestGroup(t, db, groupID, "Trigger Test Group")
	createTestGroupMember(t, db, groupID, "user-1", models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "agent-1", models.MemberTypeWorkerAgent)
	msg := createTestMessage(t, db, groupID, "msg-1", "user-1", models.MemberTypeUser, "")

	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	body := map[string]string{"agent_id": "agent-1"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusAccepted, w.Code)
	assert.True(t, mockPub.published)
	assert.Equal(t, groupID, mockPub.lastGroupID)
	assert.Equal(t, "agent-1", mockPub.lastAgentID)

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, msg.MessageID, resp["message_id"])
	assert.Equal(t, groupID, resp["group_id"])
	assert.Equal(t, "pending", resp["status"])
}

// TestTriggerMessage_WithoutAgentID verifies manual trigger without agent_id resolves agents automatically.
func TestTriggerMessage_WithoutAgentID(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-2"
	createTestGroup(t, db, groupID, "Trigger Test Group 2")
	createTestGroupMember(t, db, groupID, "user-2", models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "manager-2", models.MemberTypeManagerAgent)
	msg := createTestMessage(t, db, groupID, "msg-2", "user-2", models.MemberTypeUser, "")

	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusAccepted, w.Code)
	assert.True(t, mockPub.published)
	assert.Equal(t, "manager-2", mockPub.lastAgentID)

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, "pending", resp["status"])
}

// TestTriggerMessage_NonExistentGroup returns 404.
func TestTriggerMessage_NonExistentGroup(t *testing.T) {
	db := setupTriggerTestDB(t)
	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/non-existent/messages/msg-1/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusNotFound, w.Code)
	assert.False(t, mockPub.published)
}

// TestTriggerMessage_NonExistentMessage returns 404.
func TestTriggerMessage_NonExistentMessage(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-3"
	createTestGroup(t, db, groupID, "Trigger Test Group 3")
	createTestGroupMember(t, db, groupID, "user-3", models.MemberTypeUser)

	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/non-existent/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusNotFound, w.Code)
	assert.False(t, mockPub.published)
}

// TestTriggerMessage_NonExistentAgentID returns 404.
func TestTriggerMessage_NonExistentAgentID(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-4"
	createTestGroup(t, db, groupID, "Trigger Test Group 4")
	createTestGroupMember(t, db, groupID, "user-4", models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-4", "user-4", models.MemberTypeUser, "")

	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	body := map[string]string{"agent_id": "non-existent-agent"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusNotFound, w.Code)
	assert.False(t, mockPub.published)
}

// TestTriggerMessage_NonAgentMemberID returns 400.
func TestTriggerMessage_NonAgentMemberID(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-5"
	createTestGroup(t, db, groupID, "Trigger Test Group 5")
	createTestGroupMember(t, db, groupID, "user-5", models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "human-5", models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-5", "user-5", models.MemberTypeUser, "")

	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	body := map[string]string{"agent_id": "human-5"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code)
	assert.False(t, mockPub.published)
}

// TestTriggerMessage_AgentSentMessageBypassesNO_TRIGGER_CASES returns 202 for agent-sent message.
func TestTriggerMessage_AgentSentMessageBypassesNO_TRIGGER_CASES(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-6"
	createTestGroup(t, db, groupID, "Trigger Test Group 6")
	createTestGroupMember(t, db, groupID, "agent-6", models.MemberTypeWorkerAgent)
	createTestGroupMember(t, db, groupID, "manager-6", models.MemberTypeManagerAgent)
	// Message sent by an agent — normally blocked by NO_TRIGGER_CASES
	msg := createTestMessage(t, db, groupID, "msg-6", "agent-6", models.MemberTypeWorkerAgent, "")

	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusAccepted, w.Code)
	assert.True(t, mockPub.published)

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, "pending", resp["status"])
}

// TestTriggerMessage_ProcessedMsgIDBypassesNO_TRIGGER_CASES returns 202 for message with processed_msg_id.
func TestTriggerMessage_ProcessedMsgIDBypassesNO_TRIGGER_CASES(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-7"
	createTestGroup(t, db, groupID, "Trigger Test Group 7")
	createTestGroupMember(t, db, groupID, "user-7", models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "manager-7", models.MemberTypeManagerAgent)
	// Message with processed_msg_id — normally blocked by NO_TRIGGER_CASES
	msg := createTestMessage(t, db, groupID, "msg-7", "user-7", models.MemberTypeUser, "original-msg-id")

	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusAccepted, w.Code)
	assert.True(t, mockPub.published)
}

// TestTriggerMessage_PublishError returns 500.
func TestTriggerMessage_PublishError(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-8"
	createTestGroup(t, db, groupID, "Trigger Test Group 8")
	createTestGroupMember(t, db, groupID, "user-8", models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "agent-8", models.MemberTypeWorkerAgent)
	msg := createTestMessage(t, db, groupID, "msg-8", "user-8", models.MemberTypeUser, "")

	mockPub := &mockPublisher{publishShouldErr: errors.New("nats connection refused")}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	body := map[string]string{"agent_id": "agent-8"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusInternalServerError, w.Code)
}

// TestTriggerMessage_NoAgentsInGroup returns 202 with no_agents_to_trigger status.
func TestTriggerMessage_NoAgentsInGroup(t *testing.T) {
	db := setupTriggerTestDB(t)
	groupID := "group-trigger-9"
	createTestGroup(t, db, groupID, "Trigger Test Group 9")
	createTestGroupMember(t, db, groupID, "user-9", models.MemberTypeUser)
	// No agents in group
	msg := createTestMessage(t, db, groupID, "msg-9", "user-9", models.MemberTypeUser, "")

	mockPub := &mockPublisher{}
	router, handler := setupTriggerTestRouter(t, db, mockPub)
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusAccepted, w.Code)
	assert.False(t, mockPub.published)

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, "no_agents_to_trigger", resp["status"])
}
