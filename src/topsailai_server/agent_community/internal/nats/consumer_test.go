// Package nats provides NATS consumer tests.
package nats

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/agent"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// setupConsumerTestDB creates an in-memory SQLite database and auto-migrates models.
func setupConsumerTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open("file::memory:?cache=shared"), &gorm.Config{})
	require.NoError(t, err)

	err = db.AutoMigrate(
		&models.Group{},
		&models.GroupMember{},
		&models.GroupMessage{},
		&models.AgentMessageProcessing{},
	)
	require.NoError(t, err)

	return db
}

// createTestGroup creates a test group in the database.
func createTestGroup(t *testing.T, db *gorm.DB, groupID, groupName string) *models.Group {
	group := &models.Group{
		GroupID:      groupID,
		GroupName:    groupName,
		CreateAtMs:   time.Now().UnixMilli(),
		UpdateAtMs:   time.Now().UnixMilli(),
	}
	err := db.Create(group).Error
	require.NoError(t, err)
	return group
}

// createTestAgentMember creates a test agent member in the database.
func createTestAgentMember(t *testing.T, db *gorm.DB, groupID, memberID, iface string) *models.GroupMember {
	member := &models.GroupMember{
		GroupID:         groupID,
		MemberID:        memberID,
		MemberName:      "Test Agent " + memberID,
		MemberType:      models.MemberTypeWorkerAgent,
		MemberStatus:    models.MemberStatusOnline,
		MemberInterface: iface,
		CreateAtMs:      time.Now().UnixMilli(),
		UpdateAtMs:      time.Now().UnixMilli(),
	}
	err := db.Create(member).Error
	require.NoError(t, err)
	return member
}

// createTestUserMember creates a test user member in the database.
func createTestUserMember(t *testing.T, db *gorm.DB, groupID, memberID string) *models.GroupMember {
	member := &models.GroupMember{
		GroupID:      groupID,
		MemberID:     memberID,
		MemberName:   "Test User " + memberID,
		MemberType:   models.MemberTypeUser,
		MemberStatus: models.MemberStatusOnline,
		CreateAtMs:   time.Now().UnixMilli(),
		UpdateAtMs:   time.Now().UnixMilli(),
	}
	err := db.Create(member).Error
	require.NoError(t, err)
	return member
}

// createTestPendingMessage creates a test pending message in the database.
func createTestPendingMessage(t *testing.T, db *gorm.DB, groupID, messageID, senderID string) *models.GroupMessage {
	msg := &models.GroupMessage{
		GroupID:     groupID,
		MessageID:   messageID,
		MessageText: "test message",
		SenderID:    senderID,
		SenderType:  models.MemberTypeUser,
		CreateAtMs:  time.Now().UnixMilli(),
		UpdateAtMs:  time.Now().UnixMilli(),
	}
	err := db.Create(msg).Error
	require.NoError(t, err)
	return msg
}

// TestUpdateMemberStatusToProcessing verifies status is updated to processing.
func TestUpdateMemberStatusToProcessing(t *testing.T) {
	db := setupConsumerTestDB(t)
	consumer := NewConsumer(db, nil, nil, nil, nil)

	group := createTestGroup(t, db, "g-processing", "Test Group")
	member := createTestAgentMember(t, db, group.GroupID, "agent-processing", "")

	traceID := "test-trace-1"
	err := consumer.updateMemberStatus(group.GroupID, member.MemberID, models.MemberStatusProcessing, traceID)
	require.NoError(t, err)

	// Verify status in DB
	var updated models.GroupMember
	err = db.First(&updated, "group_id = ? AND member_id = ?", group.GroupID, member.MemberID).Error
	require.NoError(t, err)
	assert.Equal(t, models.MemberStatusProcessing, updated.MemberStatus)
	assert.True(t, updated.UpdateAtMs >= member.UpdateAtMs, "update_at_ms should be updated")
}

// TestUpdateMemberStatusToIdle verifies status is updated to idle.
func TestUpdateMemberStatusToIdle(t *testing.T) {
	db := setupConsumerTestDB(t)
	consumer := NewConsumer(db, nil, nil, nil, nil)

	group := createTestGroup(t, db, "g-idle", "Test Group")
	member := createTestAgentMember(t, db, group.GroupID, "agent-idle", "")

	// First set to processing
	traceID := "test-trace-2"
	err := consumer.updateMemberStatus(group.GroupID, member.MemberID, models.MemberStatusProcessing, traceID)
	require.NoError(t, err)

	// Then set to idle
	err = consumer.updateMemberStatus(group.GroupID, member.MemberID, models.MemberStatusIdle, traceID)
	require.NoError(t, err)

	// Verify status in DB
	var updated models.GroupMember
	err = db.First(&updated, "group_id = ? AND member_id = ?", group.GroupID, member.MemberID).Error
	require.NoError(t, err)
	assert.Equal(t, models.MemberStatusIdle, updated.MemberStatus)
}

// TestUpdateMemberStatusNotFound verifies error when member does not exist.
func TestUpdateMemberStatusNotFound(t *testing.T) {
	db := setupConsumerTestDB(t)
	consumer := NewConsumer(db, nil, nil, nil, nil)

	traceID := "test-trace-3"
	err := consumer.updateMemberStatus("nonexistent-group", "nonexistent-agent", models.MemberStatusProcessing, traceID)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "member not found")
}

// TestUpdateMemberStatusUpdatesTimestamp verifies update_at_ms is refreshed.
func TestUpdateMemberStatusUpdatesTimestamp(t *testing.T) {
	db := setupConsumerTestDB(t)
	consumer := NewConsumer(db, nil, nil, nil, nil)

	group := createTestGroup(t, db, "g-timestamp", "Test Group")
	member := createTestAgentMember(t, db, group.GroupID, "agent-timestamp", "")

	// Wait a bit to ensure timestamp difference
	time.Sleep(10 * time.Millisecond)

	beforeMs := member.UpdateAtMs
	traceID := "test-trace-4"
	err := consumer.updateMemberStatus(group.GroupID, member.MemberID, models.MemberStatusProcessing, traceID)
	require.NoError(t, err)

	var updated models.GroupMember
	err = db.First(&updated, "group_id = ? AND member_id = ?", group.GroupID, member.MemberID).Error
	require.NoError(t, err)
	assert.True(t, updated.UpdateAtMs > beforeMs, "update_at_ms should be greater than before")
}

// TestUpdateMemberStatusSequence verifies processing -> idle sequence.
func TestUpdateMemberStatusSequence(t *testing.T) {
	db := setupConsumerTestDB(t)
	consumer := NewConsumer(db, nil, nil, nil, nil)

	group := createTestGroup(t, db, "g-sequence", "Test Group")
	member := createTestAgentMember(t, db, group.GroupID, "agent-sequence", "")
	traceID := "test-trace-5"

	// Simulate the sequence: processing then idle (as in processAgentTarget)
	err := consumer.updateMemberStatus(group.GroupID, member.MemberID, models.MemberStatusProcessing, traceID)
	require.NoError(t, err)

	var midState models.GroupMember
	err = db.First(&midState, "group_id = ? AND member_id = ?", group.GroupID, member.MemberID).Error
	require.NoError(t, err)
	assert.Equal(t, models.MemberStatusProcessing, midState.MemberStatus)

	err = consumer.updateMemberStatus(group.GroupID, member.MemberID, models.MemberStatusIdle, traceID)
	require.NoError(t, err)

	var finalState models.GroupMember
	err = db.First(&finalState, "group_id = ? AND member_id = ?", group.GroupID, member.MemberID).Error
	require.NoError(t, err)
	assert.Equal(t, models.MemberStatusIdle, finalState.MemberStatus)
	assert.True(t, finalState.UpdateAtMs >= midState.UpdateAtMs, "final update_at_ms should be >= mid state")
}

// TestUpdateMemberStatusMultipleTransitions verifies multiple status transitions.
func TestUpdateMemberStatusMultipleTransitions(t *testing.T) {
	db := setupConsumerTestDB(t)
	consumer := NewConsumer(db, nil, nil, nil, nil)

	group := createTestGroup(t, db, "g-multi", "Test Group")
	member := createTestAgentMember(t, db, group.GroupID, "agent-multi", "")
	traceID := "test-trace-6"

	// online -> processing -> idle -> processing -> idle
	transitions := []models.MemberStatus{
		models.MemberStatusProcessing,
		models.MemberStatusIdle,
		models.MemberStatusProcessing,
		models.MemberStatusIdle,
	}

	for i, status := range transitions {
		err := consumer.updateMemberStatus(group.GroupID, member.MemberID, status, traceID)
		require.NoError(t, err, fmt.Sprintf("transition %d to %s failed", i, status))

		var updated models.GroupMember
		err = db.First(&updated, "group_id = ? AND member_id = ?", group.GroupID, member.MemberID).Error
		require.NoError(t, err)
		assert.Equal(t, status, updated.MemberStatus, fmt.Sprintf("transition %d status mismatch", i))
	}
}

// mockPublisherForConsumer records published events for verification.
type mockPublisherForConsumer struct {
	PublishGroupMemberModifyCalled bool
	LastPublishedMember            *models.GroupMember
	PublishedMembers               []*models.GroupMember
	PublishShouldErr               error
}

func (m *mockPublisherForConsumer) PublishPendingMessageWithAgentID(groupID string, msg *models.GroupMessage, trigger interface{}, agentID string) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishMessageCreate(msg *models.GroupMessage) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishMessageModify(msg *models.GroupMessage) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishMessageDelete(msg *models.GroupMessage) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishGroupCreate(group *models.Group) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishGroupModify(group *models.Group) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishGroupDelete(groupID string) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishGroupMemberCreate(member *models.GroupMember) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishGroupMemberModify(member *models.GroupMember) error {
	m.PublishGroupMemberModifyCalled = true
	m.LastPublishedMember = member
	// Clone the member to preserve state at the time of publication.
	clone := *member
	m.PublishedMembers = append(m.PublishedMembers, &clone)
	return m.PublishShouldErr
}

func (m *mockPublisherForConsumer) PublishGroupMemberDelete(groupID, memberID string) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishAgentResponse(msg *models.GroupMessage) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishSystemError(msg *models.GroupMessage) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishAutoTriggerPendingMessage(groupID string, msg *models.GroupMessage, trigger interface{}) error {
	return nil
}

func (m *mockPublisherForConsumer) PublishHeartbeat(nodeID string) error {
	return nil
}

// mockExecutorForConsumer is a test double for agent.Executor.
type mockExecutorForConsumer struct {
	CheckHealthCalled bool
	CheckStatusCalled bool
	ChatCalled        bool
	HealthResult      *agent.ExecutionResult
	HealthErr         error
	ChatResult        *agent.ExecutionResult
	ChatErr           error
}

func (m *mockExecutorForConsumer) CheckHealth(ctx context.Context, iface *agent.Interface, env map[string]string, traceID string) (*agent.ExecutionResult, error) {
	m.CheckHealthCalled = true
	if m.HealthResult == nil {
		return &agent.ExecutionResult{ExitCode: 0}, m.HealthErr
	}
	return m.HealthResult, m.HealthErr
}

func (m *mockExecutorForConsumer) CheckStatus(ctx context.Context, iface *agent.Interface, env map[string]string, traceID string) (*agent.ExecutionResult, error) {
	m.CheckStatusCalled = true
	return &agent.ExecutionResult{ExitCode: 0}, nil
}

func (m *mockExecutorForConsumer) Chat(ctx context.Context, iface *agent.Interface, env map[string]string, traceID string) (*agent.ExecutionResult, error) {
	m.ChatCalled = true
	if m.ChatResult == nil {
		return &agent.ExecutionResult{ExitCode: 0, Stdout: "ok"}, m.ChatErr
	}
	return m.ChatResult, m.ChatErr
}

// testConsumerConfig returns a minimal config for consumer tests.
func testConsumerConfig() *config.Config {
	return &config.Config{
		Agent: config.AgentConfig{
			AgentPrompt: "test prompt",
		},
	}
}

// TestProcessAgentTarget_HealthCheckFailed_StatusUnchanged verifies that when
// the agent health check fails, member_status is not updated and no modify
// event is published.
func TestProcessAgentTarget_HealthCheckFailed_StatusUnchanged(t *testing.T) {
	db := setupConsumerTestDB(t)
	mockPub := &mockPublisherForConsumer{}
	mockExec := &mockExecutorForConsumer{
		HealthResult: &agent.ExecutionResult{ExitCode: 1, Stderr: "unhealthy"},
	}
	pub := EventPublisher(mockPub)
	exec := AgentExecutor(mockExec)
	consumer := NewConsumer(db, pub, exec, nil, testConsumerConfig())

	group := createTestGroup(t, db, "g-health-fail", "Test Group")
	agent := createTestAgentMember(t, db, group.GroupID, "agent-health-fail", `{"adaptor":"topsailai_agent","environments":{"ACS_AGENT_API_BASE":"http://localhost:1"}}`)
	user := createTestUserMember(t, db, group.GroupID, "user-health-fail")
	msg := createTestPendingMessage(t, db, group.GroupID, "msg-health-fail", user.MemberID)

	target := trigger.AgentTarget{AgentID: agent.MemberID, Mode: "agent"}
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: agent.MemberID}

	err := consumer.processAgentTarget(context.Background(), group, []models.GroupMember{*agent, *user}, msg, triggerInfo, target, "trace-health-fail")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "health check failed")

	// Status should remain online.
	var updated models.GroupMember
	err = db.First(&updated, "group_id = ? AND member_id = ?", group.GroupID, agent.MemberID).Error
	require.NoError(t, err)
	assert.Equal(t, models.MemberStatusOnline, updated.MemberStatus)

	// No modify event should be published.
	assert.False(t, mockPub.PublishGroupMemberModifyCalled)
	assert.Len(t, mockPub.PublishedMembers, 0)
}

// TestProcessAgentTarget_DuplicateRunningRecord_StatusUnchanged verifies that
// when the agent is already processing this message, member_status is not
// updated and no modify event is published.
func TestProcessAgentTarget_DuplicateRunningRecord_StatusUnchanged(t *testing.T) {
	db := setupConsumerTestDB(t)
	mockPub := &mockPublisherForConsumer{}
	mockExec := &mockExecutorForConsumer{
		HealthResult: &agent.ExecutionResult{ExitCode: 0},
	}
	pub := EventPublisher(mockPub)
	exec := AgentExecutor(mockExec)
	consumer := NewConsumer(db, pub, exec, nil, testConsumerConfig())

	group := createTestGroup(t, db, "g-dup", "Test Group")
	agent := createTestAgentMember(t, db, group.GroupID, "agent-dup", `{"adaptor":"topsailai_agent","environments":{"ACS_AGENT_API_BASE":"http://localhost:1"}}`)
	user := createTestUserMember(t, db, group.GroupID, "user-dup")
	msg := createTestPendingMessage(t, db, group.GroupID, "msg-dup", user.MemberID)

	// Pre-create a running record to simulate duplicate execution.
	running := &models.AgentMessageProcessing{
		GroupID:   group.GroupID,
		MessageID: msg.MessageID,
		AgentID:   agent.MemberID,
		Status:    models.ProcessingStatusRunning,
		CreateAtMs: time.Now().UnixMilli(),
		UpdateAtMs: time.Now().UnixMilli(),
	}
	err := db.Create(running).Error
	require.NoError(t, err)

	target := trigger.AgentTarget{AgentID: agent.MemberID, Mode: "agent"}
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: agent.MemberID}

	err = consumer.processAgentTarget(context.Background(), group, []models.GroupMember{*agent, *user}, msg, triggerInfo, target, "trace-dup")
	require.NoError(t, err)

	// Status should remain online because the agent was already running.
	var updated models.GroupMember
	err = db.First(&updated, "group_id = ? AND member_id = ?", group.GroupID, agent.MemberID).Error
	require.NoError(t, err)
	assert.Equal(t, models.MemberStatusOnline, updated.MemberStatus)

	// No modify event should be published.
	assert.False(t, mockPub.PublishGroupMemberModifyCalled)
	assert.Len(t, mockPub.PublishedMembers, 0)
}

// TestProcessAgentTarget_Success_PublishesProcessingAndIdle verifies that on
// successful execution, member_status transitions processing -> idle and both
// modify events carry the correct member_status value.
func TestProcessAgentTarget_Success_PublishesProcessingAndIdle(t *testing.T) {
	db := setupConsumerTestDB(t)
	mockPub := &mockPublisherForConsumer{}
	mockExec := &mockExecutorForConsumer{
		HealthResult: &agent.ExecutionResult{ExitCode: 0},
		ChatResult:   &agent.ExecutionResult{ExitCode: 0, Stdout: "agent response"},
	}
	pub := EventPublisher(mockPub)
	exec := AgentExecutor(mockExec)
	consumer := NewConsumer(db, pub, exec, nil, testConsumerConfig())

	group := createTestGroup(t, db, "g-success", "Test Group")
	agent := createTestAgentMember(t, db, group.GroupID, "agent-success", `{"adaptor":"topsailai_agent","environments":{"ACS_AGENT_API_BASE":"http://localhost:1"}}`)
	user := createTestUserMember(t, db, group.GroupID, "user-success")
	msg := createTestPendingMessage(t, db, group.GroupID, "msg-success", user.MemberID)

	target := trigger.AgentTarget{AgentID: agent.MemberID, Mode: "agent"}
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: agent.MemberID}

	err := consumer.processAgentTarget(context.Background(), group, []models.GroupMember{*agent, *user}, msg, triggerInfo, target, "trace-success")
	require.NoError(t, err)

	// Final DB status should be idle.
	var updated models.GroupMember
	err = db.First(&updated, "group_id = ? AND member_id = ?", group.GroupID, agent.MemberID).Error
	require.NoError(t, err)
	assert.Equal(t, models.MemberStatusIdle, updated.MemberStatus)

	// Two modify events should be published: processing then idle.
	require.Len(t, mockPub.PublishedMembers, 2)
	assert.Equal(t, models.MemberStatusProcessing, mockPub.PublishedMembers[0].MemberStatus)
	assert.Equal(t, models.MemberStatusIdle, mockPub.PublishedMembers[1].MemberStatus)
	assert.Equal(t, agent.MemberID, mockPub.PublishedMembers[0].MemberID)
	assert.Equal(t, agent.MemberID, mockPub.PublishedMembers[1].MemberID)
}

// TestProcessAgentTarget_PublishModifyErrorDoesNotFailExecution verifies that a
// failure to publish the modify event does not fail the agent execution.
func TestProcessAgentTarget_PublishModifyErrorDoesNotFailExecution(t *testing.T) {
	db := setupConsumerTestDB(t)
	mockPub := &mockPublisherForConsumer{PublishShouldErr: fmt.Errorf("publish error")}
	mockExec := &mockExecutorForConsumer{
		HealthResult: &agent.ExecutionResult{ExitCode: 0},
		ChatResult:   &agent.ExecutionResult{ExitCode: 0, Stdout: "agent response"},
	}
	pub := EventPublisher(mockPub)
	exec := AgentExecutor(mockExec)
	consumer := NewConsumer(db, pub, exec, nil, testConsumerConfig())

	group := createTestGroup(t, db, "g-pub-err", "Test Group")
	agent := createTestAgentMember(t, db, group.GroupID, "agent-pub-err", `{"adaptor":"topsailai_agent","environments":{"ACS_AGENT_API_BASE":"http://localhost:1"}}`)
	user := createTestUserMember(t, db, group.GroupID, "user-pub-err")
	msg := createTestPendingMessage(t, db, group.GroupID, "msg-pub-err", user.MemberID)

	target := trigger.AgentTarget{AgentID: agent.MemberID, Mode: "agent"}
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: agent.MemberID}

	err := consumer.processAgentTarget(context.Background(), group, []models.GroupMember{*agent, *user}, msg, triggerInfo, target, "trace-pub-err")
	require.NoError(t, err)

	// Final DB status should still be idle.
	var updated models.GroupMember
	err = db.First(&updated, "group_id = ? AND member_id = ?", group.GroupID, agent.MemberID).Error
	require.NoError(t, err)
	assert.Equal(t, models.MemberStatusIdle, updated.MemberStatus)
}
