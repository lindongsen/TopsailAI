// Package handlers provides message handler tests.
package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)
// listMessagesResponseWrapper mirrors the envelope produced by writeListResponse.
type listMessagesResponseWrapper struct {
	Data struct {
		Items  []MessageResponse `json:"items"`
		Total  int64             `json:"total"`
		Offset int               `json:"offset"`
		Limit  int               `json:"limit"`
	} `json:"data"`
	TraceID string `json:"trace_id"`
}

// messageResponseWrapper mirrors the envelope produced by writeDataResponse.
type messageResponseWrapper struct {
	Data    MessageResponse `json:"data"`
	TraceID string          `json:"trace_id"`
}

// setupMessageTestDB creates an in-memory SQLite database and auto-migrates models.
func setupMessageTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open("file::memory:"), &gorm.Config{})
	require.NoError(t, err)

	err = db.AutoMigrate(&models.Group{}, &models.GroupMember{}, &models.GroupMessage{})
	require.NoError(t, err)

	return db
}

// setupMessageTestRouter creates a gin engine and a MessageHandler with optional mocks.
func setupMessageTestRouter(t *testing.T, db *gorm.DB, pub Publisher, eval Evaluator) (*gin.Engine, *MessageHandler) {
	gin.SetMode(gin.TestMode)
	r := gin.New()

	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	if pub == nil {
		pub = &mockMessagePublisher{}
	}
	if eval == nil {
		eval = trigger.NewEvaluator(10 * time.Minute)
	}
	handler := NewMessageHandler(db, pub, eval, log)

	return r, handler
}

// mockMessagePublisher records publish calls and can return errors.
type mockMessagePublisher struct {
	createCalls  []*models.GroupMessage
	modifyCalls  []*models.GroupMessage
	deleteCalls  []*models.GroupMessage
	pendingCalls []pendingCall
	createErr    error
	modifyErr    error
	deleteErr    error
	pendingErr   error
}

type pendingCall struct {
	GroupID string
	Msg     *models.GroupMessage
	Trigger interface{}
	AgentID string
}

func (m *mockMessagePublisher) PublishMessageCreate(msg *models.GroupMessage) error {
	m.createCalls = append(m.createCalls, msg)
	return m.createErr
}

func (m *mockMessagePublisher) PublishMessageModify(msg *models.GroupMessage) error {
	m.modifyCalls = append(m.modifyCalls, msg)
	return m.modifyErr
}

func (m *mockMessagePublisher) PublishMessageDelete(msg *models.GroupMessage) error {
	m.deleteCalls = append(m.deleteCalls, msg)
	return m.deleteErr
}

func (m *mockMessagePublisher) PublishPendingMessageWithAgentID(groupID string, msg *models.GroupMessage, trigger interface{}, agentID string) error {
	m.pendingCalls = append(m.pendingCalls, pendingCall{GroupID: groupID, Msg: msg, Trigger: trigger, AgentID: agentID})
	return m.pendingErr
}

// mockMessageEvaluator is a deterministic evaluator for trigger tests.
type mockMessageEvaluator struct {
	result *trigger.TriggerResult
	err    error
}

func (m *mockMessageEvaluator) Evaluate(ctx context.Context, msg *models.GroupMessage, members []models.GroupMember, contextMessages []models.GroupMessage) (*trigger.TriggerResult, error) {
	if m.err != nil {
		return nil, m.err
	}
	if m.result != nil {
		return m.result, nil
	}
	return &trigger.TriggerResult{ShouldTrigger: false}, nil
}

func (m *mockMessageEvaluator) ResolveAgents(ctx context.Context, msg *models.GroupMessage, members []models.GroupMember) (*trigger.TriggerResult, error) {
	if m.err != nil {
		return nil, m.err
	}
	if m.result != nil {
		return m.result, nil
	}
	return &trigger.TriggerResult{ShouldTrigger: false}, nil
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
		GroupID:            groupID,
		MessageID:          messageID,
		MessageText:        "Test message " + messageID,
		SenderID:           senderID,
		SenderType:         senderType,
		ProcessedMsgID:     processedMsgID,
		MessageAttachments: "[]",
		Mentions:           "[]",
		CreateAtMs:         time.Now().UnixMilli(),
		UpdateAtMs:         time.Now().UnixMilli(),
	}
	err := db.Create(msg).Error
	require.NoError(t, err)
	return msg
}

// authContextMiddleware returns a Gin middleware that injects the provided
// AuthContext for handler tests.
func authContextMiddleware(ac middleware.AuthContext) gin.HandlerFunc {
	return func(c *gin.Context) {
		c.Set("auth_context", ac)
		c.Next()
	}
}

// newTestGinContext creates a minimal gin context for direct handler method tests.
func newTestGinContext() *gin.Context {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodPost, "/test", nil)
	return c
}

func testAuthContext(accountID string, role models.AccountRole) middleware.AuthContext {
	return middleware.AuthContext{
		Account: &models.Account{
			AccountID: accountID,
			Role:      role,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}
}

// TestCreateMessage_AdminCanSendToAnyGroup verifies admin can send without membership.
func TestCreateMessage_AdminCanSendToAnyGroup(t *testing.T) {
	db := setupMessageTestDB(t)
	adminID := "acc-admin-001"
	groupID := "group-create-admin"
	createTestGroup(t, db, groupID, "Admin Send Group")
	// Admin is NOT a member

	pub := &mockMessagePublisher{}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(adminID, models.AccountRoleAdmin)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "admin message"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, adminID, resp.Data.SenderID)
	assert.Equal(t, string(models.MemberTypeUser), resp.Data.SenderType)
	assert.Equal(t, "admin message", resp.Data.MessageText)
}

// TestCreateMessage_UserCanSendOnlyToMemberGroup verifies user membership restriction.
func TestCreateMessage_UserCanSendOnlyToMemberGroup(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-001"
	memberGroupID := "group-member"
	nonMemberGroupID := "group-non-member"
	createTestGroup(t, db, memberGroupID, "Member Group")
	createTestGroup(t, db, nonMemberGroupID, "Non Member Group")
	createTestGroupMember(t, db, memberGroupID, userID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello"}
	bodyJSON, _ := json.Marshal(body)

	// Member group: should succeed
	req1 := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+memberGroupID+"/messages", bytes.NewReader(bodyJSON))
	req1.Header.Set("Content-Type", "application/json")
	w1 := httptest.NewRecorder()
	router.ServeHTTP(w1, req1)
	require.Equal(t, http.StatusCreated, w1.Code, "body: %s", w1.Body.String())

	// Non-member group: should fail with 403
	req2 := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+nonMemberGroupID+"/messages", bytes.NewReader(bodyJSON))
	req2.Header.Set("Content-Type", "application/json")
	w2 := httptest.NewRecorder()
	router.ServeHTTP(w2, req2)
	require.Equal(t, http.StatusForbidden, w2.Code, "body: %s", w2.Body.String())
}

// TestCreateMessage_ExtractsMentions verifies @member_id mentions are parsed and stored.
func TestCreateMessage_ExtractsMentions(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-mentions"
	groupID := "group-create-mentions"
	createTestGroup(t, db, groupID, "Mentions Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "agent-1", models.MemberTypeWorkerAgent)

	pub := &mockMessagePublisher{}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello @agent-1 please help"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	mentions, ok := resp.Data.Mentions.([]interface{})
	require.True(t, ok, "mentions should be an array")
	require.Len(t, mentions, 1)
	mention := mentions[0].(map[string]interface{})
	assert.Equal(t, "agent-1", mention["member_id"])
	assert.Equal(t, string(models.MemberTypeWorkerAgent), mention["member_type"])
}

// TestCreateMessage_TriggersAgentWhenMentioned verifies evaluator trigger leads to pending publish.
func TestCreateMessage_TriggersAgentWhenMentioned(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-trigger"
	groupID := "group-create-trigger"
	createTestGroup(t, db, groupID, "Trigger Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "agent-1", models.MemberTypeWorkerAgent)

	pub := &mockMessagePublisher{}
	eval := &mockMessageEvaluator{
		result: &trigger.TriggerResult{
			ShouldTrigger: true,
			Trigger:       trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: "agent-1"},
			Targets:       []trigger.AgentTarget{{AgentID: "agent-1", Mode: "agent"}},
		},
	}
	router, handler := setupMessageTestRouter(t, db, pub, eval)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello @agent-1"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	require.Len(t, pub.pendingCalls, 1)
	assert.Equal(t, "agent-1", pub.pendingCalls[0].AgentID)
	assert.Equal(t, groupID, pub.pendingCalls[0].GroupID)
	assert.NotNil(t, pub.pendingCalls[0].Msg)
}

// TestCreateMessage_NoTriggerForAgentSender verifies agent sender does not trigger.
// Because the HTTP API always derives sender_type=user, we test evaluateAndTrigger directly.
func TestCreateMessage_NoTriggerForAgentSender(t *testing.T) {
	db := setupMessageTestDB(t)
	agentID := "agent-no-trigger"
	groupID := "group-no-trigger-agent"
	createTestGroup(t, db, groupID, "No Trigger Agent Group")

	pub := &mockMessagePublisher{}
	eval := trigger.NewEvaluator(10 * time.Minute)
	handler := NewMessageHandler(db, pub, eval, logger.New(logger.Config{Output: "stdout", Level: "error"}))

	msg := &models.GroupMessage{
		GroupID:     groupID,
		MessageID:   "msg-agent-sender",
		MessageText: "hello @agent-1",
		SenderID:    agentID,
		SenderType:  models.MemberTypeWorkerAgent,
	}
	err := db.Create(msg).Error
	require.NoError(t, err)

	c := newTestGinContext()
	handler.evaluateAndTrigger(c, "trace-1", msg, nil)

	assert.Empty(t, pub.pendingCalls)
}

// TestEvaluateAndTrigger_ProcessedMsgIDBlocksTrigger verifies the handler-level
// defense-in-depth guard: even if an evaluator returns ShouldTrigger=true, a
// message with non-empty processed_msg_id must not publish pending messages.
func TestEvaluateAndTrigger_ProcessedMsgIDBlocksTrigger(t *testing.T) {
	db := setupMessageTestDB(t)
	groupID := "group-eval-processed"
	createTestGroup(t, db, groupID, "Eval Processed Group")

	pub := &mockMessagePublisher{}
	// Evaluator claims the message should trigger; the handler guard must override it.
	eval := &mockMessageEvaluator{
		result: &trigger.TriggerResult{
			ShouldTrigger: true,
			Trigger:       trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: "agent-1"},
			Targets:       []trigger.AgentTarget{{AgentID: "agent-1", Mode: "agent"}},
		},
	}
	handler := NewMessageHandler(db, pub, eval, logger.New(logger.Config{Output: "stdout", Level: "error"}))

	msg := &models.GroupMessage{
		GroupID:        groupID,
		MessageID:      "msg-eval-processed",
		MessageText:    "hello @agent-1",
		SenderID:       "user-1",
		SenderType:     models.MemberTypeUser,
		ProcessedMsgID: "msg-original",
	}
	err := db.Create(msg).Error
	require.NoError(t, err)

	c := newTestGinContext()
	handler.evaluateAndTrigger(c, "trace-1", msg, nil)

	assert.Empty(t, pub.pendingCalls)
}

// TestCreateMessage_NoTriggerForProcessedMsgID verifies processed_msg_id blocks trigger.
func TestCreateMessage_NoTriggerForProcessedMsgID(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-processed"
	groupID := "group-processed"
	createTestGroup(t, db, groupID, "Processed Group")

	pub := &mockMessagePublisher{}
	eval := trigger.NewEvaluator(10 * time.Minute)
	handler := NewMessageHandler(db, pub, eval, logger.New(logger.Config{Output: "stdout", Level: "error"}))

	msg := &models.GroupMessage{
		GroupID:        groupID,
		MessageID:      "msg-processed",
		MessageText:    "hello",
		SenderID:       userID,
		SenderType:     models.MemberTypeUser,
		ProcessedMsgID: "msg-original",
	}
	err := db.Create(msg).Error
	require.NoError(t, err)

	c := newTestGinContext()
	handler.evaluateAndTrigger(c, "trace-1", msg, nil)

	assert.Empty(t, pub.pendingCalls)
}

// TestCreateMessage_NoTriggerForLongAgentChain verifies >10 consecutive agent messages block trigger.
func TestCreateMessage_NoTriggerForLongAgentChain(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-chain"
	groupID := "group-chain"
	createTestGroup(t, db, groupID, "Chain Group")

	pub := &mockMessagePublisher{}
	eval := trigger.NewEvaluator(10 * time.Minute)
	handler := NewMessageHandler(db, pub, eval, logger.New(logger.Config{Output: "stdout", Level: "error"}))

	// Seed 11 consecutive agent messages
	for i := 0; i < 11; i++ {
		msg := &models.GroupMessage{
			GroupID:     groupID,
			MessageID:   "msg-agent-" + strconv.Itoa(i),
			MessageText: "agent reply",
			SenderID:    "agent-1",
			SenderType:  models.MemberTypeWorkerAgent,
		}
		err := db.Create(msg).Error
		require.NoError(t, err)
	}

	// User message after long agent chain
	userMsg := &models.GroupMessage{
		GroupID:     groupID,
		MessageID:   "msg-user-chain",
		MessageText: "user message after chain",
		SenderID:    userID,
		SenderType:  models.MemberTypeUser,
	}
	err := db.Create(userMsg).Error
	require.NoError(t, err)

	c := newTestGinContext()
	handler.evaluateAndTrigger(c, "trace-1", userMsg, nil)

	assert.Empty(t, pub.pendingCalls)
}

// TestCreateMessage_InvalidGroup verifies 404 when the group does not exist.
func TestCreateMessage_InvalidGroup(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-notfound"

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/non-existent-group/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusNotFound, w.Code)
}

// TestCreateMessage_EmptyText verifies empty message_text returns 400.
func TestCreateMessage_EmptyText(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-empty"
	groupID := "group-create-empty"
	createTestGroup(t, db, groupID, "Empty Text Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": ""}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestCreateMessage_Unauthenticated verifies 401 when auth context is missing.
func TestCreateMessage_Unauthenticated(t *testing.T) {
	db := setupMessageTestDB(t)
	groupID := "group-create-unauth"
	createTestGroup(t, db, groupID, "Unauthenticated Group")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusUnauthorized, w.Code)
}

// TestListMessages_UserCanListMemberGroupOnly verifies list authorization.
func TestListMessages_UserCanListMemberGroupOnly(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-list-user"
	memberGroupID := "group-list-member"
	nonMemberGroupID := "group-list-non-member"
	createTestGroup(t, db, memberGroupID, "List Member Group")
	createTestGroup(t, db, nonMemberGroupID, "List Non Member Group")
	createTestGroupMember(t, db, memberGroupID, userID, models.MemberTypeUser)
	createTestMessage(t, db, memberGroupID, "msg-list-1", userID, models.MemberTypeUser, "")
	createTestMessage(t, db, nonMemberGroupID, "msg-list-2", "other-user", models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	// Member group
	req1 := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+memberGroupID+"/messages", nil)
	w1 := httptest.NewRecorder()
	router.ServeHTTP(w1, req1)
	require.Equal(t, http.StatusOK, w1.Code, "body: %s", w1.Body.String())

	var resp1 listMessagesResponseWrapper
	err := json.Unmarshal(w1.Body.Bytes(), &resp1)
	require.NoError(t, err)
	assert.Equal(t, int64(1), resp1.Data.Total)

	// Non-member group
	req2 := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+nonMemberGroupID+"/messages", nil)
	w2 := httptest.NewRecorder()
	router.ServeHTTP(w2, req2)
	require.Equal(t, http.StatusForbidden, w2.Code, "body: %s", w2.Body.String())
}

// TestListMessages_ProcessedMsgIDFilter verifies filtering by processed_msg_id returns only matching messages.
func TestListMessages_ProcessedMsgIDFilter(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-1"
	groupID := "group-1"
	createTestGroup(t, db, groupID, "Test Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	originalMsg := createTestMessage(t, db, groupID, "msg-original", userID, models.MemberTypeUser, "")
	agentMsg := createTestMessage(t, db, groupID, "msg-agent-1", "agent-1", models.MemberTypeWorkerAgent, originalMsg.MessageID)
	createTestMessage(t, db, groupID, "msg-unrelated", userID, models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?processed_msg_id="+originalMsg.MessageID, nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp listMessagesResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	assert.Equal(t, int64(1), resp.Data.Total)
	assert.Len(t, resp.Data.Items, 1)
	assert.Equal(t, agentMsg.MessageID, resp.Data.Items[0].MessageID)
	assert.Equal(t, originalMsg.MessageID, resp.Data.Items[0].ProcessedMsgID)
}

// TestListMessages_TimeRangeFilter verifies create_at_ms range filtering.
func TestListMessages_TimeRangeFilter(t *testing.T) {
	db := setupMessageTestDB(t)
	groupID := "group-list-range"
	userID := "user-range"
	createTestGroup(t, db, groupID, "Range Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	now := time.Now().UnixMilli()
	createTestMessageAt(t, db, groupID, "msg-early", userID, models.MemberTypeUser, now-2000)
	createTestMessageAt(t, db, groupID, "msg-mid", userID, models.MemberTypeUser, now)
	createTestMessageAt(t, db, groupID, "msg-late", userID, models.MemberTypeUser, now+2000)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	start := strconv.FormatInt(now-1000, 10)
	end := strconv.FormatInt(now+1000, 10)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?create_at_ms="+start+"-"+end, nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp listMessagesResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, int64(1), resp.Data.Total)
	require.Len(t, resp.Data.Items, 1)
	assert.Equal(t, "msg-mid", resp.Data.Items[0].MessageID)
}

// TestListMessages_InvalidSortKey verifies 400 for an invalid sort_key.
func TestListMessages_InvalidSortKey(t *testing.T) {
	db := setupMessageTestDB(t)
	groupID := "group-list-sort"
	userID := "user-sort"
	createTestGroup(t, db, groupID, "Sort Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?sort_key=invalid", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestUpdateMessage_UserCanUpdateOwnOnly verifies user can only update own messages.
func TestUpdateMessage_UserCanUpdateOwnOnly(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-update-user"
	otherID := "acc-update-other"
	groupID := "group-update-own"
	createTestGroup(t, db, groupID, "Update Own Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, otherID, models.MemberTypeUser)
	ownMsg := createTestMessage(t, db, groupID, "msg-own", userID, models.MemberTypeUser, "")
	otherMsg := createTestMessage(t, db, groupID, "msg-other", otherID, models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.PUT("/api/v1/groups/:group_id/messages/:message_id", handler.UpdateMessage)

	body := map[string]interface{}{"message_text": "updated text"}
	bodyJSON, _ := json.Marshal(body)

	// Own message: should succeed
	req1 := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+ownMsg.MessageID, bytes.NewReader(bodyJSON))
	req1.Header.Set("Content-Type", "application/json")
	w1 := httptest.NewRecorder()
	router.ServeHTTP(w1, req1)
	require.Equal(t, http.StatusOK, w1.Code, "body: %s", w1.Body.String())

	// Other user's message: should fail with 403
	req2 := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+otherMsg.MessageID, bytes.NewReader(bodyJSON))
	req2.Header.Set("Content-Type", "application/json")
	w2 := httptest.NewRecorder()
	router.ServeHTTP(w2, req2)
	require.Equal(t, http.StatusForbidden, w2.Code, "body: %s", w2.Body.String())
}

// TestUpdateMessage_AdminCanUpdateAny verifies admin can update any message.
func TestUpdateMessage_AdminCanUpdateAny(t *testing.T) {
	db := setupMessageTestDB(t)
	adminID := "acc-update-admin"
	otherID := "acc-update-other"
	groupID := "group-update-admin"
	createTestGroup(t, db, groupID, "Update Admin Group")
	otherMsg := createTestMessage(t, db, groupID, "msg-admin-update", otherID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(adminID, models.AccountRoleAdmin)))
	router.PUT("/api/v1/groups/:group_id/messages/:message_id", handler.UpdateMessage)

	body := map[string]interface{}{"message_text": "admin updated"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+otherMsg.MessageID, bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, "admin updated", resp.Data.MessageText)
}

// TestDeleteMessage_UserCanDeleteOwnOnly verifies user can only delete own messages.
func TestDeleteMessage_UserCanDeleteOwnOnly(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-delete-user"
	otherID := "acc-delete-other"
	groupID := "group-delete-own"
	createTestGroup(t, db, groupID, "Delete Own Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, otherID, models.MemberTypeUser)
	ownMsg := createTestMessage(t, db, groupID, "msg-delete-own", userID, models.MemberTypeUser, "")
	otherMsg := createTestMessage(t, db, groupID, "msg-delete-other", otherID, models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.DELETE("/api/v1/groups/:group_id/messages/:message_id", handler.DeleteMessage)

	// Own message: should succeed
	req1 := httptest.NewRequest(http.MethodDelete, "/api/v1/groups/"+groupID+"/messages/"+ownMsg.MessageID, nil)
	w1 := httptest.NewRecorder()
	router.ServeHTTP(w1, req1)
	require.Equal(t, http.StatusOK, w1.Code, "body: %s", w1.Body.String())
	var deleteResp1 map[string]interface{}
	err := json.Unmarshal(w1.Body.Bytes(), &deleteResp1)
	require.NoError(t, err)
	require.NotNil(t, deleteResp1["data"])
	assert.Equal(t, "message deleted", deleteResp1["data"].(map[string]interface{})["message"])

	// Other user's message: should fail with 403
	req2 := httptest.NewRequest(http.MethodDelete, "/api/v1/groups/"+groupID+"/messages/"+otherMsg.MessageID, nil)
	w2 := httptest.NewRecorder()
	router.ServeHTTP(w2, req2)
	require.Equal(t, http.StatusForbidden, w2.Code, "body: %s", w2.Body.String())
}

// TestDeleteMessage_AdminCanDeleteAny verifies admin can delete any message.
func TestDeleteMessage_AdminCanDeleteAny(t *testing.T) {
	db := setupMessageTestDB(t)
	adminID := "acc-delete-admin"
	otherID := "acc-delete-other"
	groupID := "group-delete-admin"
	createTestGroup(t, db, groupID, "Delete Admin Group")
	otherMsg := createTestMessage(t, db, groupID, "msg-admin-delete", otherID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(adminID, models.AccountRoleAdmin)))
	router.DELETE("/api/v1/groups/:group_id/messages/:message_id", handler.DeleteMessage)

	req := httptest.NewRequest(http.MethodDelete, "/api/v1/groups/"+groupID+"/messages/"+otherMsg.MessageID, nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var deleteResp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &deleteResp)
	require.NoError(t, err)
	require.NotNil(t, deleteResp["data"])
	assert.Equal(t, "message deleted", deleteResp["data"].(map[string]interface{})["message"])
	assert.Len(t, pub.deleteCalls, 1)
}

// TestTriggerMessage_AdminCanTriggerAny verifies admin can trigger any message.
func TestTriggerMessage_AdminCanTriggerAny(t *testing.T) {
	db := setupMessageTestDB(t)
	adminID := "acc-trigger-admin"
	otherID := "acc-trigger-other"
	groupID := "group-trigger-admin"
	agentID := "agent-trigger"
	createTestGroup(t, db, groupID, "Trigger Admin Group")
	createTestGroupMember(t, db, groupID, agentID, models.MemberTypeWorkerAgent)
	msg := createTestMessage(t, db, groupID, "msg-trigger-admin", otherID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	eval := &mockMessageEvaluator{
		result: &trigger.TriggerResult{
			ShouldTrigger: true,
			Trigger:       trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: agentID},
			Targets:       []trigger.AgentTarget{{AgentID: agentID, Mode: "agent"}},
		},
	}
	router, handler := setupMessageTestRouter(t, db, pub, eval)
	router.Use(authContextMiddleware(testAuthContext(adminID, models.AccountRoleAdmin)))
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusAccepted, w.Code, "body: %s", w.Body.String())
	require.Len(t, pub.pendingCalls, 1)
	assert.Equal(t, agentID, pub.pendingCalls[0].AgentID)
}

// TestTriggerMessage_UserCanTriggerMemberGroup verifies user can trigger member group messages.
func TestTriggerMessage_UserCanTriggerMemberGroup(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-trigger-user"
	groupID := "group-trigger-user"
	agentID := "agent-trigger-user"
	createTestGroup(t, db, groupID, "Trigger User Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, agentID, models.MemberTypeWorkerAgent)
	msg := createTestMessage(t, db, groupID, "msg-trigger-user", userID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	eval := &mockMessageEvaluator{
		result: &trigger.TriggerResult{
			ShouldTrigger: true,
			Trigger:       trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: agentID},
			Targets:       []trigger.AgentTarget{{AgentID: agentID, Mode: "agent"}},
		},
	}
	router, handler := setupMessageTestRouter(t, db, pub, eval)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusAccepted, w.Code, "body: %s", w.Body.String())
	require.Len(t, pub.pendingCalls, 1)
}

// TestTriggerMessage_NoAgentsToTrigger verifies response when no agents resolved.
func TestTriggerMessage_NoAgentsToTrigger(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-trigger-none"
	groupID := "group-trigger-none"
	createTestGroup(t, db, groupID, "Trigger None Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-trigger-none", userID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	eval := &mockMessageEvaluator{result: &trigger.TriggerResult{ShouldTrigger: false}}
	router, handler := setupMessageTestRouter(t, db, pub, eval)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusAccepted, w.Code, "body: %s", w.Body.String())

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	data, ok := resp["data"].(map[string]interface{})
	require.True(t, ok, "response should contain data object")
	assert.Equal(t, "no_agents_to_trigger", data["status"])
}

// TestTriggerMessage_InvalidAgentID verifies error for non-agent or non-member agent_id.
func TestTriggerMessage_InvalidAgentID(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-trigger-invalid"
	groupID := "group-trigger-invalid"
	createTestGroup(t, db, groupID, "Trigger Invalid Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "regular-user", models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-trigger-invalid", userID, models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages/:message_id/trigger", handler.TriggerMessage)

	body := map[string]interface{}{"agent_id": "regular-user"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID+"/trigger", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestListMessagesWithoutProcessedMsgIDFilter verifies that omitting processed_msg_id returns all messages.
func TestListMessagesWithoutProcessedMsgIDFilter(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-2"
	groupID := "group-2"
	createTestGroup(t, db, groupID, "Test Group 2")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	createTestMessage(t, db, groupID, "msg-1", userID, models.MemberTypeUser, "")
	createTestMessage(t, db, groupID, "msg-2", userID, models.MemberTypeUser, "")
	createTestMessage(t, db, groupID, "msg-3", "agent-2", models.MemberTypeWorkerAgent, "msg-1")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp listMessagesResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	assert.Equal(t, int64(3), resp.Data.Total)
	assert.Len(t, resp.Data.Items, 3)
}

// TestListMessagesWithEmptyProcessedMsgID verifies that empty processed_msg_id returns all messages.
func TestListMessagesWithEmptyProcessedMsgID(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-3"
	groupID := "group-3"
	createTestGroup(t, db, groupID, "Test Group 3")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	createTestMessage(t, db, groupID, "msg-a", userID, models.MemberTypeUser, "")
	createTestMessage(t, db, groupID, "msg-b", "agent-3", models.MemberTypeWorkerAgent, "msg-a")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?processed_msg_id=", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp listMessagesResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	assert.Equal(t, int64(2), resp.Data.Total)
	assert.Len(t, resp.Data.Items, 2)
}

// TestListMessagesResponseIncludesProcessedMsgID verifies the response includes processed_msg_id field.
func TestListMessagesResponseIncludesProcessedMsgID(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-4"
	groupID := "group-4"
	createTestGroup(t, db, groupID, "Test Group 4")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	originalMsg := createTestMessage(t, db, groupID, "msg-original-4", userID, models.MemberTypeUser, "")
	agentMsg := createTestMessage(t, db, groupID, "msg-agent-4", "agent-4", models.MemberTypeWorkerAgent, originalMsg.MessageID)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp listMessagesResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	require.Len(t, resp.Data.Items, 2)

	var foundAgentMsg bool
	for _, item := range resp.Data.Items {
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
	userID := "user-5"
	groupID := "group-5"
	createTestGroup(t, db, groupID, "Test Group 5")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	createTestMessage(t, db, groupID, "msg-5", userID, models.MemberTypeUser, "")
	createTestMessage(t, db, groupID, "msg-6", "agent-5", models.MemberTypeWorkerAgent, "msg-5")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?processed_msg_id=non-existent-id", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var resp listMessagesResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	assert.Equal(t, int64(0), resp.Data.Total)
	assert.Len(t, resp.Data.Items, 0)
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

	r, handler := setupMessageTestRouter(t, db, nil, nil)
	r.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
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

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, accountID, resp.Data.SenderID)
	assert.Equal(t, string(models.MemberTypeUser), resp.Data.SenderType)
	assert.Equal(t, "hello from auth", resp.Data.MessageText)
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

	r, handler := setupMessageTestRouter(t, db, nil, nil)
	r.Use(authContextMiddleware(middleware.AuthContext{
		Account: &models.Account{
			AccountID: nonMemberID,
			Role:      models.AccountRoleUser,
			Status:    models.AccountStatusActive,
		},
		IsAuthenticated: true,
	}))
	r.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello from non-member"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_AttachmentsDefaultEmpty verifies empty attachments default to [].
func TestCreateMessage_AttachmentsDefaultEmpty(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-attach"
	groupID := "group-create-attach"
	createTestGroup(t, db, groupID, "Attachments Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "no attachments"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Empty(t, resp.Data.MessageAttachments)
}

// TestCreateMessage_AttachmentsArrayInput verifies array input is stored and returned as array.
func TestCreateMessage_AttachmentsArrayInput(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-attach-array"
	groupID := "group-create-attach-array"
	createTestGroup(t, db, groupID, "Attachments Array Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "with attachments",
		"message_attachments": []map[string]interface{}{
			{"data": "base64", "size": 1024, "format": "image/png"},
		},
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	attachments, ok := resp.Data.MessageAttachments.([]interface{})
	require.True(t, ok, "attachments should be returned as array")
	require.Len(t, attachments, 1)
	att := attachments[0].(map[string]interface{})
	assert.Equal(t, "base64", att["data"])
	assert.Equal(t, float64(1024), att["size"])
	assert.Equal(t, "image/png", att["format"])
}

// TestCreateMessage_AttachmentsStringifiedArrayInput verifies backward-compatible stringified array input.
func TestCreateMessage_AttachmentsStringifiedArrayInput(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-attach-string"
	groupID := "group-create-attach-string"
	createTestGroup(t, db, groupID, "Attachments String Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "with stringified attachments",
		"message_attachments": "[{\"data\":\"base64\",\"size\":2048,\"format\":\"image/jpeg\"}]",
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)

	attachments, ok := resp.Data.MessageAttachments.([]interface{})
	require.True(t, ok, "attachments should be returned as array")
	require.Len(t, attachments, 1)
	att := attachments[0].(map[string]interface{})
	assert.Equal(t, "base64", att["data"])
	assert.Equal(t, float64(2048), att["size"])
	assert.Equal(t, "image/jpeg", att["format"])
}

// TestCreateMessage_AttachmentsInvalidJSON verifies invalid JSON is rejected.
func TestCreateMessage_AttachmentsInvalidJSON(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-attach-invalid"
	groupID := "group-create-attach-invalid"
	createTestGroup(t, db, groupID, "Attachments Invalid Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "bad attachments",
		"message_attachments": "not-json",
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_AttachmentsNonArrayJSON verifies non-array JSON is rejected.
func TestCreateMessage_AttachmentsNonArrayJSON(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-attach-obj"
	groupID := "group-create-attach-obj"
	createTestGroup(t, db, groupID, "Attachments Object Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "object attachment",
		"message_attachments": map[string]interface{}{"data": "base64"},
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestUpdateMessage_AttachmentsArrayInput verifies update accepts array input and returns array.
func TestUpdateMessage_AttachmentsArrayInput(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-update-attach"
	groupID := "group-update-attach"
	createTestGroup(t, db, groupID, "Update Attach Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-update-attach", userID, models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.PUT("/api/v1/groups/:group_id/messages/:message_id", handler.UpdateMessage)

	body := map[string]interface{}{
		"message_attachments": []map[string]interface{}{
			{"data": "updated-base64", "size": 512, "format": "image/gif"},
		},
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())

	var resp dataResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	data, ok := resp.Data.(map[string]interface{})
	require.True(t, ok, "response data should be object")

	attachments, ok := data["message_attachments"].([]interface{})
	require.True(t, ok, "attachments should be returned as array")
	require.Len(t, attachments, 1)
	att := attachments[0].(map[string]interface{})
	assert.Equal(t, "updated-base64", att["data"])
	assert.Equal(t, float64(512), att["size"])
	assert.Equal(t, "image/gif", att["format"])
}

// TestUpdateMessage_AttachmentsEmptyArrayRemoves verifies empty array removes attachments.
func TestUpdateMessage_AttachmentsEmptyArrayRemoves(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-update-attach-empty"
	groupID := "group-update-attach-empty"
	createTestGroup(t, db, groupID, "Update Attach Empty Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-update-attach-empty", userID, models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.PUT("/api/v1/groups/:group_id/messages/:message_id", handler.UpdateMessage)

	body := map[string]interface{}{"message_attachments": []interface{}{}}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())

	var resp dataResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	data, ok := resp.Data.(map[string]interface{})
	require.True(t, ok, "response data should be object")
	assert.Empty(t, data["message_attachments"])
}

// TestNormalizeMessageAttachments verifies helper behavior for edge cases.
func TestNormalizeMessageAttachments(t *testing.T) {
	cases := []struct {
		name    string
		input   string
		want    string
		wantErr bool
	}{
		{"empty", "", "[]", false},
		{"null", "null", "[]", false},
		{"empty array", "[]", "[]", false},
		{"array", `[{"data":"x","size":1}]`, `[{"data":"x","size":1}]`, false},
		{"stringified array", `"[{\"data\":\"x\",\"size\":1}]"`, `[{"data":"x","size":1}]`, false},
		{"invalid json", "not-json", "", true},
		{"object", `{"data":"x"}`, "", true},
		{"string not array", `"hello"`, "", true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := normalizeMessageAttachments(json.RawMessage(tc.input))
			if tc.wantErr {
				require.Error(t, err)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, tc.want, got)
		})
	}
}

// TestCreateMessage_EvaluatorErrorStillReturns201 verifies evaluator errors do not fail the request.
func TestCreateMessage_EvaluatorErrorStillReturns201(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-eval-err"
	groupID := "group-create-eval-err"
	createTestGroup(t, db, groupID, "Evaluator Error Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	pub := &mockMessagePublisher{}
	eval := &mockMessageEvaluator{err: errors.New("evaluator failure")}
	router, handler := setupMessageTestRouter(t, db, pub, eval)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	assert.Empty(t, pub.pendingCalls)
}

// TestCreateMessage_PublisherCreateFailureStillReturns201 verifies create publish failure does not fail request.
func TestCreateMessage_PublisherCreateFailureStillReturns201(t *testing.T) {
	db := setupMessageTestDB(t)
	accountID := "acc-create-pub-err"
	groupID := "group-create-pub-err"
	createTestGroup(t, db, groupID, "Publisher Error Group")
	createTestGroupMember(t, db, groupID, accountID, models.MemberTypeUser)

	pub := &mockMessagePublisher{createErr: errors.New("nats down")}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(accountID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{"message_text": "hello"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	assert.Len(t, pub.createCalls, 1)
}

// TestListMessages_PaginationClamping verifies offset/limit clamping behavior.
func TestListMessages_PaginationClamping(t *testing.T) {
	db := setupMessageTestDB(t)
	groupID := "group-list-page"
	userID := "user-page"
	createTestGroup(t, db, groupID, "Pagination Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	for i := 1; i <= 5; i++ {
		createTestMessage(t, db, groupID, "msg-page-"+strconv.Itoa(i), userID, models.MemberTypeUser, "")
	}

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	tests := []struct {
		name           string
		query          string
		expectedLimit  int
		expectedOffset int
		expectedTotal  int64
	}{
		{"negative offset", "offset=-1&limit=2", 2, 0, 5},
		{"zero limit", "offset=0&limit=0", 1000, 0, 5},
		{"oversized limit", "offset=0&limit=5000", 1000, 0, 5},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages?"+tt.query, nil)
			w := httptest.NewRecorder()
			router.ServeHTTP(w, req)

			require.Equal(t, http.StatusOK, w.Code)

			var resp listMessagesResponseWrapper
			err := json.Unmarshal(w.Body.Bytes(), &resp)
			require.NoError(t, err)
			assert.Equal(t, tt.expectedTotal, resp.Data.Total)
			assert.Equal(t, tt.expectedLimit, resp.Data.Limit)
			assert.Equal(t, tt.expectedOffset, resp.Data.Offset)
		})
	}
}

// TestUpdateMessage_Success verifies message update and publish modify event.
func TestUpdateMessage_Success(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-update"
	groupID := "group-update"
	createTestGroup(t, db, groupID, "Update Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-update", userID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.PUT("/api/v1/groups/:group_id/messages/:message_id", handler.UpdateMessage)

	body := map[string]interface{}{"message_text": "updated text"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())

	var resp dataResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	data, ok := resp.Data.(map[string]interface{})
	require.True(t, ok, "response data should be object")
	assert.Equal(t, "updated text", data["message_text"])
	assert.Len(t, pub.modifyCalls, 1)
	assert.Equal(t, msg.MessageID, pub.modifyCalls[0].MessageID)
}

// TestUpdateMessage_NotFound verifies 404 for non-existent message.
func TestUpdateMessage_NotFound(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-update-notfound"
	groupID := "group-update-notfound"
	createTestGroup(t, db, groupID, "Update Not Found Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.PUT("/api/v1/groups/:group_id/messages/:message_id", handler.UpdateMessage)

	body := map[string]interface{}{"message_text": "updated text"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/non-existent", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusNotFound, w.Code)
}

// TestUpdateMessage_PublisherFailureStillSucceeds verifies modify publish failure does not fail request.
func TestUpdateMessage_PublisherFailureStillSucceeds(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-update-pub"
	groupID := "group-update-pub-err"
	createTestGroup(t, db, groupID, "Update Pub Err Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-update-pub", userID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{modifyErr: errors.New("nats down")}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.PUT("/api/v1/groups/:group_id/messages/:message_id", handler.UpdateMessage)

	body := map[string]interface{}{"message_text": "updated text"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	assert.Len(t, pub.modifyCalls, 1)
}

// TestDeleteMessage_Success verifies soft delete returns 200 with envelope and publishes delete event.
func TestDeleteMessage_Success(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-delete"
	groupID := "group-delete"
	createTestGroup(t, db, groupID, "Delete Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-delete", userID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.DELETE("/api/v1/groups/:group_id/messages/:message_id", handler.DeleteMessage)

	req := httptest.NewRequest(http.MethodDelete, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	var resp dataResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	data, ok := resp.Data.(map[string]interface{})
	require.True(t, ok, "response data should be object")
	assert.Equal(t, "message deleted", data["message"])
	assert.Len(t, pub.deleteCalls, 1)
	assert.Equal(t, msg.MessageID, pub.deleteCalls[0].MessageID)
}

// TestDeleteMessage_NotFound verifies 404 for non-existent message.
func TestDeleteMessage_NotFound(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-delete-notfound"
	groupID := "group-delete-notfound"
	createTestGroup(t, db, groupID, "Delete Not Found Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.DELETE("/api/v1/groups/:group_id/messages/:message_id", handler.DeleteMessage)

	req := httptest.NewRequest(http.MethodDelete, "/api/v1/groups/"+groupID+"/messages/non-existent", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusNotFound, w.Code)
}

// TestDeleteMessage_SoftDeleteFields verifies the record is marked deleted and content cleared.
func TestDeleteMessage_SoftDeleteFields(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-delete-soft"
	groupID := "group-delete-soft"
	createTestGroup(t, db, groupID, "Soft Delete Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	msg := createTestMessage(t, db, groupID, "msg-delete-soft", userID, models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.DELETE("/api/v1/groups/:group_id/messages/:message_id", handler.DeleteMessage)

	req := httptest.NewRequest(http.MethodDelete, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)

	var updated models.GroupMessage
	err := db.Where("group_id = ? AND message_id = ?", groupID, msg.MessageID).First(&updated).Error
	require.NoError(t, err)
	assert.True(t, updated.IsDeleted)
	assert.Greater(t, updated.DeleteAtMs, int64(0))
	assert.Empty(t, updated.MessageText)
	assert.Equal(t, "[]", updated.MessageAttachments)
}

// TestToMessageResponse_InvalidJSON verifies invalid JSON fields are handled gracefully.
func TestToMessageResponse_InvalidJSON(t *testing.T) {
	msg := &models.GroupMessage{
		GroupID:            "group-invalid",
		MessageID:          "msg-invalid",
		MessageText:        "text",
		MessageAttachments: "not-json",
		Mentions:           "not-json",
		SenderID:           "user-1",
		SenderType:         models.MemberTypeUser,
	}

	resp := toMessageResponse(msg)
	assert.Nil(t, resp.MessageAttachments)
	assert.Nil(t, resp.Mentions)
	assert.Equal(t, "text", resp.MessageText)
	assert.Equal(t, "user-1", resp.SenderID)
}

// TestEvaluateAndTrigger_NoTrigger verifies no pending publish when evaluator returns false.
func TestEvaluateAndTrigger_NoTrigger(t *testing.T) {
	db := setupMessageTestDB(t)
	groupID := "group-eval-no"
	createTestGroup(t, db, groupID, "Eval No Trigger Group")
	msg := createTestMessage(t, db, groupID, "msg-eval-no", "user-1", models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	eval := &mockMessageEvaluator{result: &trigger.TriggerResult{ShouldTrigger: false}}
	handler := NewMessageHandler(db, pub, eval, logger.New(logger.Config{Output: "stdout", Level: "error"}))

	c := newTestGinContext()
	handler.evaluateAndTrigger(c, "trace-1", msg, nil)

	assert.Empty(t, pub.pendingCalls)
}

// TestEvaluateAndTrigger_MultipleTargets verifies one pending publish per target.
func TestEvaluateAndTrigger_MultipleTargets(t *testing.T) {
	db := setupMessageTestDB(t)
	groupID := "group-eval-multi"
	createTestGroup(t, db, groupID, "Eval Multi Target Group")
	msg := createTestMessage(t, db, groupID, "msg-eval-multi", "user-1", models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	eval := &mockMessageEvaluator{
		result: &trigger.TriggerResult{
			ShouldTrigger: true,
			Trigger:       trigger.TriggerInfo{Type: trigger.TriggerTypeMention},
			Targets: []trigger.AgentTarget{
				{AgentID: "agent-1", Mode: "agent"},
				{AgentID: "agent-2", Mode: "agent"},
			},
		},
	}
	handler := NewMessageHandler(db, pub, eval, logger.New(logger.Config{Output: "stdout", Level: "error"}))

	c := newTestGinContext()
	handler.evaluateAndTrigger(c, "trace-1", msg, nil)

	require.Len(t, pub.pendingCalls, 2)
	agentIDs := []string{pub.pendingCalls[0].AgentID, pub.pendingCalls[1].AgentID}
	assert.Contains(t, agentIDs, "agent-1")
	assert.Contains(t, agentIDs, "agent-2")
}

func createTestMessageAt(t *testing.T, db *gorm.DB, groupID, messageID, senderID string, senderType models.MemberType, createAtMs int64) *models.GroupMessage {
	msg := &models.GroupMessage{
		GroupID:            groupID,
		MessageID:          messageID,
		MessageText:        "Test message " + messageID,
		SenderID:           senderID,
		SenderType:         senderType,
		MessageAttachments: "[]",
		Mentions:           "[]",
	}
	err := db.Create(msg).Error
	require.NoError(t, err)

	// Override the timestamp set by BeforeCreate hook.
	err = db.Model(msg).UpdateColumns(map[string]interface{}{
		"create_at_ms": createAtMs,
		"update_at_ms": createAtMs,
	}).Error
	require.NoError(t, err)

	msg.CreateAtMs = createAtMs
	msg.UpdateAtMs = createAtMs
	return msg
}

// TestUpdateMessage_ReextractMentions verifies that updating message_text
// re-extracts mentions from the new text and persists them.
func TestUpdateMessage_ReextractMentions(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "user-update-mentions"
	groupID := "group-update-mentions"
	createTestGroup(t, db, groupID, "Update Mentions Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "agent-1", models.MemberTypeWorkerAgent)
	createTestGroupMember(t, db, groupID, "agent-2", models.MemberTypeWorkerAgent)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.PUT("/api/v1/groups/:group_id/messages/:message_id", handler.UpdateMessage)

	// Case 1: add a mention on edit
	msg := createTestMessage(t, db, groupID, "msg-update-mentions", userID, models.MemberTypeUser, "")
	body := map[string]interface{}{"message_text": "hello @agent-1"}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp1 dataResponse
	err := json.Unmarshal(w.Body.Bytes(), &resp1)
	require.NoError(t, err)
	data1, ok := resp1.Data.(map[string]interface{})
	require.True(t, ok, "response data should be object")
	mentions1, ok := data1["mentions"].([]interface{})
	require.True(t, ok, "mentions should be an array")
	require.Len(t, mentions1, 1)
	assert.Equal(t, "agent-1", mentions1[0].(map[string]interface{})["member_id"])

	// Case 2: remove the mention on edit
	body = map[string]interface{}{"message_text": "just a plain message"}
	bodyJSON, _ = json.Marshal(body)
	req = httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp2 dataResponse
	err = json.Unmarshal(w.Body.Bytes(), &resp2)
	require.NoError(t, err)
	data2, ok := resp2.Data.(map[string]interface{})
	require.True(t, ok, "response data should be object")
	assert.Empty(t, data2["mentions"])

	// Case 3: edit only attachments should preserve existing mentions
	msgWithMention := createTestMessage(t, db, groupID, "msg-update-attachments", userID, models.MemberTypeUser, "")
	// Manually set mentions to simulate a message that already mentions agent-2
	err = db.Model(&models.GroupMessage{}).Where("message_id = ?", msgWithMention.MessageID).UpdateColumn("mentions", `[{"member_id":"agent-2","member_name":"Agent 2","member_type":"worker-agent"}]`).Error
	require.NoError(t, err)

	body = map[string]interface{}{"message_attachments": []map[string]interface{}{{"data": "base64", "size": 1, "format": "image/png"}}}
	bodyJSON, _ = json.Marshal(body)
	req = httptest.NewRequest(http.MethodPut, "/api/v1/groups/"+groupID+"/messages/"+msgWithMention.MessageID, bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w = httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp3 dataResponse
	err = json.Unmarshal(w.Body.Bytes(), &resp3)
	require.NoError(t, err)
	data3, ok := resp3.Data.(map[string]interface{})
	require.True(t, ok, "response data should be object")
	mentions3, ok := data3["mentions"].([]interface{})
	require.True(t, ok, "mentions should be preserved as array")
	require.Len(t, mentions3, 1)
	assert.Equal(t, "agent-2", mentions3[0].(map[string]interface{})["member_id"])
}

// TestGetMessage_AgentMessageVisible verifies that agent-generated response
// messages can be retrieved by GET /groups/:group_id/messages/:message_id.
func TestGetMessage_AgentMessageVisible(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-get-agent-user"
	agentID := "agent-get-response"
	groupID := "group-get-agent"
	createTestGroup(t, db, groupID, "Get Agent Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, agentID, models.MemberTypeWorkerAgent)

	// Simulate an agent response message as produced by the NATS consumer.
	agentMsg := &models.GroupMessage{
		GroupID:            groupID,
		MessageID:          "d0763fa3-74b1-48b6-bb37-fe4d844bf8e4",
		MessageText:        "Agent response text",
		SenderID:           agentID,
		SenderType:         models.MemberTypeWorkerAgent,
		ProcessedMsgID:     "msg-user-prompt",
		MessageAttachments: "",
		Mentions:           "",
		IsDeleted:          false,
	}
	err := db.Create(agentMsg).Error
	require.NoError(t, err)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages/:message_id", handler.GetMessage)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages/"+agentMsg.MessageID, nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp messageResponseWrapper
	err = json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, agentMsg.MessageID, resp.Data.MessageID)
	assert.Equal(t, agentID, resp.Data.SenderID)
	assert.Equal(t, string(models.MemberTypeWorkerAgent), resp.Data.SenderType)
	assert.Equal(t, "Agent response text", resp.Data.MessageText)
}

// TestGetMessage_SoftDeletedNotFound verifies that soft-deleted messages are
// not returned by GET /groups/:group_id/messages/:message_id.
func TestGetMessage_SoftDeletedNotFound(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-get-deleted-user"
	groupID := "group-get-deleted"
	createTestGroup(t, db, groupID, "Get Deleted Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	msg := createTestMessage(t, db, groupID, "msg-deleted", userID, models.MemberTypeUser, "")
	// Soft-delete using the same fields as DeleteMessage handler.
	err := db.Model(&models.GroupMessage{}).Where("message_id = ?", msg.MessageID).Updates(map[string]interface{}{
		"is_deleted":   true,
		"delete_at_ms": time.Now().UnixMilli(),
		"update_at_ms": time.Now().UnixMilli(),
	}).Error
	require.NoError(t, err)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages/:message_id", handler.GetMessage)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages/"+msg.MessageID, nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusNotFound, w.Code, "body: %s", w.Body.String())
}

// TestListMessages_IncludesAgentMessages verifies that list endpoints return
// messages sent by worker-agents and manager-agents alongside user messages.
func TestListMessages_IncludesAgentMessages(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-list-agent-user"
	workerID := "worker-list"
	managerID := "manager-list"
	groupID := "group-list-agent"
	createTestGroup(t, db, groupID, "List Agent Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, workerID, models.MemberTypeWorkerAgent)
	createTestGroupMember(t, db, groupID, managerID, models.MemberTypeManagerAgent)

	userMsg := createTestMessage(t, db, groupID, "msg-user-list", userID, models.MemberTypeUser, "")
	workerMsg := createTestMessage(t, db, groupID, "msg-worker-list", workerID, models.MemberTypeWorkerAgent, userMsg.MessageID)
	managerMsg := createTestMessage(t, db, groupID, "msg-manager-list", managerID, models.MemberTypeManagerAgent, userMsg.MessageID)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp listMessagesResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, int64(3), resp.Data.Total)
	require.Len(t, resp.Data.Items, 3)

	ids := make(map[string]bool)
	for _, item := range resp.Data.Items {
		ids[item.MessageID] = true
	}
	assert.True(t, ids[userMsg.MessageID], "user message should be listed")
	assert.True(t, ids[workerMsg.MessageID], "worker-agent message should be listed")
	assert.True(t, ids[managerMsg.MessageID], "manager-agent message should be listed")
}

// TestListMessages_SoftDeletedExcluded verifies that soft-deleted messages are
// omitted from list results.
func TestListMessages_SoftDeletedExcluded(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-list-deleted-user"
	groupID := "group-list-deleted"
	createTestGroup(t, db, groupID, "List Deleted Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	visibleMsg := createTestMessage(t, db, groupID, "msg-visible", userID, models.MemberTypeUser, "")
	deletedMsg := createTestMessage(t, db, groupID, "msg-deleted-list", userID, models.MemberTypeUser, "")
	err := db.Model(&models.GroupMessage{}).Where("message_id = ?", deletedMsg.MessageID).Updates(map[string]interface{}{
		"is_deleted":   true,
		"delete_at_ms": time.Now().UnixMilli(),
		"update_at_ms": time.Now().UnixMilli(),
	}).Error
	require.NoError(t, err)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.GET("/api/v1/groups/:group_id/messages", handler.ListMessages)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/groups/"+groupID+"/messages", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp listMessagesResponseWrapper
	err = json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, int64(1), resp.Data.Total)
	require.Len(t, resp.Data.Items, 1)
	assert.Equal(t, visibleMsg.MessageID, resp.Data.Items[0].MessageID)
}

// TestCreateMessage_SenderOverrideAsOwnMember verifies a group member can send
// a message using their own member_id and member_type, and set processed_msg_id.
func TestCreateMessage_SenderOverrideAsOwnMember(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-override"
	groupID := "group-sender-override"
	createTestGroup(t, db, groupID, "Sender Override Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	parentMsg := createTestMessage(t, db, groupID, "msg-parent", userID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text":     "reply with override",
		"sender_id":        userID,
		"sender_type":      string(models.MemberTypeUser),
		"processed_msg_id": parentMsg.MessageID,
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, userID, resp.Data.SenderID)
	assert.Equal(t, string(models.MemberTypeUser), resp.Data.SenderType)
	assert.Equal(t, parentMsg.MessageID, resp.Data.ProcessedMsgID)
	assert.Equal(t, "reply with override", resp.Data.MessageText)
}

// TestCreateMessage_SenderOverrideAsManagerAgent verifies any group member can
// send a message on behalf of a manager-agent member.
func TestCreateMessage_SenderOverrideAsManagerAgent(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-manager"
	managerID := "manager-agent"
	groupID := "group-manager-override"
	createTestGroup(t, db, groupID, "Manager Override Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, managerID, models.MemberTypeManagerAgent)

	pub := &mockMessagePublisher{}
	router, handler := setupMessageTestRouter(t, db, pub, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "manager agent reply",
		"sender_id":    managerID,
		"sender_type":  string(models.MemberTypeManagerAgent),
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	var resp messageResponseWrapper
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	require.NoError(t, err)
	assert.Equal(t, managerID, resp.Data.SenderID)
	assert.Equal(t, string(models.MemberTypeManagerAgent), resp.Data.SenderType)
}

// TestCreateMessage_SenderOverrideAsOtherUserForbidden verifies a member cannot
// impersonate another user member.
func TestCreateMessage_SenderOverrideAsOtherUserForbidden(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-self"
	otherUserID := "acc-user-other"
	groupID := "group-other-user"
	createTestGroup(t, db, groupID, "Other User Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, otherUserID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "impersonating other user",
		"sender_id":    otherUserID,
		"sender_type":  string(models.MemberTypeUser),
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_SenderOverrideAsOtherWorkerAgentForbidden verifies a member
// cannot send as a worker-agent member they do not represent.
func TestCreateMessage_SenderOverrideAsOtherWorkerAgentForbidden(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-worker"
	workerID := "worker-agent-1"
	groupID := "group-other-worker"
	createTestGroup(t, db, groupID, "Other Worker Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, workerID, models.MemberTypeWorkerAgent)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "impersonating worker agent",
		"sender_id":    workerID,
		"sender_type":  string(models.MemberTypeWorkerAgent),
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_ProcessedMsgIDNonExistent verifies 400 when processed_msg_id
// references a message that does not exist.
func TestCreateMessage_ProcessedMsgIDNonExistent(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-processed-missing"
	groupID := "group-processed-missing"
	createTestGroup(t, db, groupID, "Processed Missing Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text":     "reply to missing",
		"processed_msg_id": "msg-does-not-exist",
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_ProcessedMsgIDDeletedMessage verifies 400 when processed_msg_id
// references a soft-deleted message.
func TestCreateMessage_ProcessedMsgIDDeletedMessage(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-processed-deleted"
	groupID := "group-processed-deleted"
	createTestGroup(t, db, groupID, "Processed Deleted Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	deletedMsg := createTestMessage(t, db, groupID, "msg-deleted", userID, models.MemberTypeUser, "")
	err := db.Model(&models.GroupMessage{}).Where("message_id = ?", deletedMsg.MessageID).Updates(map[string]interface{}{
		"is_deleted":   true,
		"delete_at_ms": time.Now().UnixMilli(),
		"update_at_ms": time.Now().UnixMilli(),
	}).Error
	require.NoError(t, err)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text":     "reply to deleted",
		"processed_msg_id": deletedMsg.MessageID,
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_ProcessedMsgIDOtherGroup verifies 400 when processed_msg_id
// references a message from a different group.
func TestCreateMessage_ProcessedMsgIDOtherGroup(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-processed-other"
	groupID := "group-processed-other"
	otherGroupID := "group-other"
	createTestGroup(t, db, groupID, "Processed Other Group")
	createTestGroup(t, db, otherGroupID, "Other Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	otherMsg := createTestMessage(t, db, otherGroupID, "msg-other-group", userID, models.MemberTypeUser, "")

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text":     "reply to other group",
		"processed_msg_id": otherMsg.MessageID,
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_SenderOverridePartialFields verifies 400 when only one of
// sender_id/sender_type is provided.
func TestCreateMessage_SenderOverridePartialFields(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-partial"
	groupID := "group-partial"
	createTestGroup(t, db, groupID, "Partial Sender Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "partial sender",
		"sender_id":    userID,
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_SenderOverrideCallerNotMember verifies 403 when a caller
// tries to use sender override but is not a member of the group.
func TestCreateMessage_SenderOverrideCallerNotMember(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-not-member"
	managerID := "manager-agent"
	groupID := "group-not-member"
	createTestGroup(t, db, groupID, "Not Member Group")
	createTestGroupMember(t, db, groupID, managerID, models.MemberTypeManagerAgent)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "not a member",
		"sender_id":    managerID,
		"sender_type":  string(models.MemberTypeManagerAgent),
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_SenderTypeMismatch verifies 400 when sender_type does not
// match the actual member type of sender_id.
func TestCreateMessage_SenderTypeMismatch(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-mismatch"
	groupID := "group-mismatch"
	createTestGroup(t, db, groupID, "Mismatch Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)

	router, handler := setupMessageTestRouter(t, db, nil, nil)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text": "type mismatch",
		"sender_id":    userID,
		"sender_type":  string(models.MemberTypeManagerAgent),
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestCreateMessage_ProcessedMsgIDBlocksAutoTrigger verifies that a message
// created with processed_msg_id is not auto-triggered, even when it mentions an agent.
func TestCreateMessage_ProcessedMsgIDBlocksAutoTrigger(t *testing.T) {
	db := setupMessageTestDB(t)
	userID := "acc-user-processed-notrigger"
	groupID := "group-processed-notrigger"
	createTestGroup(t, db, groupID, "Processed No Trigger Group")
	createTestGroupMember(t, db, groupID, userID, models.MemberTypeUser)
	createTestGroupMember(t, db, groupID, "agent-1", models.MemberTypeWorkerAgent)
	parentMsg := createTestMessage(t, db, groupID, "msg-parent-notrigger", userID, models.MemberTypeUser, "")

	pub := &mockMessagePublisher{}
	eval := trigger.NewEvaluator(10 * time.Minute)
	router, handler := setupMessageTestRouter(t, db, pub, eval)
	router.Use(authContextMiddleware(testAuthContext(userID, models.AccountRoleUser)))
	router.POST("/api/v1/groups/:group_id/messages", handler.CreateMessage)

	body := map[string]interface{}{
		"message_text":     "hello @agent-1",
		"processed_msg_id": parentMsg.MessageID,
	}
	bodyJSON, _ := json.Marshal(body)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups/"+groupID+"/messages", bytes.NewReader(bodyJSON))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	assert.Empty(t, pub.pendingCalls, "processed messages should not be auto-triggered")
}
