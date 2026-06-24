// Package nats provides NATS consumer tests.
package nats

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/agent"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/internal/workpool"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// setupConsumerTestDB creates an in-memory SQLite database and auto-migrates models.
func setupConsumerTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
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

// setupConsumerTestDBFile creates a file-backed SQLite database with WAL mode
// and a busy timeout enabled. This is required for tests that exercise
// concurrent goroutines because the default in-memory SQLite driver serializes
// writes and quickly returns "database table is locked" errors.
func setupConsumerTestDBFile(t *testing.T) *gorm.DB {
	tmpFile := filepath.Join(t.TempDir(), "acs-consumer-test.db")
	db, err := gorm.Open(sqlite.Open(tmpFile+"?_journal_mode=WAL&_busy_timeout=5000"), &gorm.Config{})
	require.NoError(t, err)

	sqlDB, err := db.DB()
	require.NoError(t, err)
	sqlDB.SetMaxOpenConns(10)
	sqlDB.SetMaxIdleConns(5)

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
		GroupID:    groupID,
		GroupName:  groupName,
		CreateAtMs: time.Now().UnixMilli(),
		UpdateAtMs: time.Now().UnixMilli(),
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
	consumer := NewConsumer(db, nil, nil, nil, nil, nil)

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
	consumer := NewConsumer(db, nil, nil, nil, nil, nil)

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
	consumer := NewConsumer(db, nil, nil, nil, nil, nil)

	traceID := "test-trace-3"
	err := consumer.updateMemberStatus("nonexistent-group", "nonexistent-agent", models.MemberStatusProcessing, traceID)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "member not found")
}

// TestUpdateMemberStatusUpdatesTimestamp verifies update_at_ms is refreshed.
func TestUpdateMemberStatusUpdatesTimestamp(t *testing.T) {
	db := setupConsumerTestDB(t)
	consumer := NewConsumer(db, nil, nil, nil, nil, nil)

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
	consumer := NewConsumer(db, nil, nil, nil, nil, nil)

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
	consumer := NewConsumer(db, nil, nil, nil, nil, nil)

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
	consumer := NewConsumer(db, pub, exec, nil, nil, testConsumerConfig())

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
	consumer := NewConsumer(db, pub, exec, nil, nil, testConsumerConfig())

	group := createTestGroup(t, db, "g-dup", "Test Group")
	agent := createTestAgentMember(t, db, group.GroupID, "agent-dup", `{"adaptor":"topsailai_agent","environments":{"ACS_AGENT_API_BASE":"http://localhost:1"}}`)
	user := createTestUserMember(t, db, group.GroupID, "user-dup")
	msg := createTestPendingMessage(t, db, group.GroupID, "msg-dup", user.MemberID)

	// Pre-create a running record to simulate duplicate execution.
	running := &models.AgentMessageProcessing{
		GroupID:    group.GroupID,
		MessageID:  msg.MessageID,
		AgentID:    agent.MemberID,
		Status:     models.ProcessingStatusRunning,
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
	consumer := NewConsumer(db, pub, exec, nil, nil, testConsumerConfig())

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
	consumer := NewConsumer(db, pub, exec, nil, nil, testConsumerConfig())

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

// TestDispatchTargets_ExecutesConcurrently proves that dispatchTargets runs
// each agent target in its own goroutine. A stub process function sleeps for a
// fixed duration; if targets ran sequentially the elapsed time would be at
// least 2*sleepDuration, while concurrent execution completes in roughly one
// sleepDuration. This test intentionally avoids any database I/O so it is
// stable under the Go race detector.
func TestDispatchTargets_ExecutesConcurrently(t *testing.T) {
	sleepDuration := 200 * time.Millisecond

	var calledMu sync.Mutex
	called := make(map[string]bool)

	stubProcess := func(
		ctx context.Context,
		group *models.Group,
		members []models.GroupMember,
		pendingMsg *models.GroupMessage,
		triggerInfo trigger.TriggerInfo,
		target trigger.AgentTarget,
		traceID string,
	) error {
		calledMu.Lock()
		called[target.AgentID] = true
		calledMu.Unlock()
		select {
		case <-time.After(sleepDuration):
		case <-ctx.Done():
			return ctx.Err()
		}
		return nil
	}

	consumer := NewConsumer(nil, nil, nil, nil, nil, testConsumerConfig())

	group := &models.Group{GroupID: "group-concurrent", GroupName: "Concurrent Test Group"}
	pendingMsg := &models.GroupMessage{MessageID: "msg-concurrent", GroupID: group.GroupID, SenderID: "user-1"}
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeMention}
	targets := []trigger.AgentTarget{
		{AgentID: "agent-1", Mode: "agent"},
		{AgentID: "agent-2", Mode: "agent"},
	}

	start := time.Now()
	err := consumer.dispatchTargets(context.Background(), group, nil, pendingMsg, triggerInfo, targets, "trace-concurrent", stubProcess)
	elapsed := time.Since(start)

	require.NoError(t, err)

	calledMu.Lock()
	assert.True(t, called["agent-1"], "agent-1 should have been processed")
	assert.True(t, called["agent-2"], "agent-2 should have been processed")
	calledMu.Unlock()

	// Sequential execution would take at least 2*sleepDuration. Concurrent
	// execution should complete in roughly sleepDuration plus scheduling overhead.
	assert.Less(t, elapsed, 2*sleepDuration,
		"targets should execute concurrently, expected elapsed < %v but got %v", 2*sleepDuration, elapsed)
}

// TestDispatchTargets_PropagatesError verifies that dispatchTargets returns an
// error when at least one target fails, while still waiting for all targets.
func TestDispatchTargets_PropagatesError(t *testing.T) {
	stubProcess := func(
		ctx context.Context,
		group *models.Group,
		members []models.GroupMember,
		pendingMsg *models.GroupMessage,
		triggerInfo trigger.TriggerInfo,
		target trigger.AgentTarget,
		traceID string,
	) error {
		if target.AgentID == "agent-bad" {
			return errors.New("intentional failure")
		}
		return nil
	}

	consumer := NewConsumer(nil, nil, nil, nil, nil, testConsumerConfig())
	group := &models.Group{GroupID: "group-err", GroupName: "Error Test Group"}
	pendingMsg := &models.GroupMessage{MessageID: "msg-err", GroupID: group.GroupID, SenderID: "user-1"}
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeMention}
	targets := []trigger.AgentTarget{
		{AgentID: "agent-good", Mode: "agent"},
		{AgentID: "agent-bad", Mode: "agent"},
	}

	err := consumer.dispatchTargets(context.Background(), group, nil, pendingMsg, triggerInfo, targets, "trace-err", stubProcess)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "intentional failure")
}

// TestProcessAgentTarget_AcquireTimeoutWaits verifies that when
// ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT is positive and the pool is saturated,
// processAgentTarget waits for approximately the configured timeout before
// returning ErrPoolLimitReached.
func TestProcessAgentTarget_AcquireTimeoutWaits(t *testing.T) {
	db := setupConsumerTestDB(t)
	pool := workpool.NewPool(1, 1, 1)
	cfg := &config.Config{
		AgentWorkPool: config.AgentWorkPoolConfig{
			AcquireTimeout: 150 * time.Millisecond,
		},
	}
	consumer := NewConsumer(db, nil, nil, nil, pool, cfg)

	group := createTestGroup(t, db, "g-timeout", "Test Group")
	agent := createTestAgentMember(t, db, group.GroupID, "agent-timeout", `{"adaptor":"topsailai_agent","environments":{"ACS_AGENT_API_BASE":"http://localhost:1"}}`)
	user := createTestUserMember(t, db, group.GroupID, "user-timeout")
	msg := createTestPendingMessage(t, db, group.GroupID, "msg-timeout", user.MemberID)

	// Exhaust the only global slot so the target cannot acquire.
	err := pool.Acquire(context.Background(), user.MemberID, group.GroupID)
	require.NoError(t, err)
	defer pool.Release(user.MemberID, group.GroupID, "hold")

	target := trigger.AgentTarget{AgentID: agent.MemberID, Mode: "agent"}
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: agent.MemberID}

	start := time.Now()
	err = consumer.processAgentTarget(context.Background(), group, []models.GroupMember{*agent, *user}, msg, triggerInfo, target, "trace-timeout")
	elapsed := time.Since(start)

	require.Error(t, err)
	assert.True(t, errors.Is(err, workpool.ErrPoolLimitReached), "expected ErrPoolLimitReached, got %v", err)
	assert.GreaterOrEqual(t, elapsed, 100*time.Millisecond, "should wait at least the configured timeout")
}

// TestProcessAgentTarget_ZeroAcquireTimeoutFailsFast verifies that when
// ACS_AGENT_WORK_POOL_ACQUIRE_TIMEOUT is zero and the pool is saturated,
// processAgentTarget returns ErrPoolLimitReached immediately without blocking.
func TestProcessAgentTarget_ZeroAcquireTimeoutFailsFast(t *testing.T) {
	db := setupConsumerTestDB(t)
	pool := workpool.NewPool(1, 1, 1)
	cfg := &config.Config{
		AgentWorkPool: config.AgentWorkPoolConfig{
			AcquireTimeout: 0,
		},
	}
	consumer := NewConsumer(db, nil, nil, nil, pool, cfg)

	group := createTestGroup(t, db, "g-no-timeout", "Test Group")
	agent := createTestAgentMember(t, db, group.GroupID, "agent-no-timeout", `{"adaptor":"topsailai_agent","environments":{"ACS_AGENT_API_BASE":"http://localhost:1"}}`)
	user := createTestUserMember(t, db, group.GroupID, "user-no-timeout")
	msg := createTestPendingMessage(t, db, group.GroupID, "msg-no-timeout", user.MemberID)

	// Exhaust the only global slot.
	err := pool.Acquire(context.Background(), user.MemberID, group.GroupID)
	require.NoError(t, err)
	defer pool.Release(user.MemberID, group.GroupID, "hold")

	target := trigger.AgentTarget{AgentID: agent.MemberID, Mode: "agent"}
	triggerInfo := trigger.TriggerInfo{Type: trigger.TriggerTypeMention, AgentID: agent.MemberID}

	start := time.Now()
	err = consumer.processAgentTarget(context.Background(), group, []models.GroupMember{*agent, *user}, msg, triggerInfo, target, "trace-no-timeout")
	elapsed := time.Since(start)

	require.Error(t, err)
	assert.True(t, errors.Is(err, workpool.ErrPoolLimitReached), "expected ErrPoolLimitReached, got %v", err)
	assert.Less(t, elapsed, 50*time.Millisecond, "should fail immediately with zero timeout")
}
