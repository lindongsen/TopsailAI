package nats

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/trigger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// ---------- Fakes ----------

type fakeAutoTriggerPublisher struct {
	published []publishAutoTriggerCall
	err       error
}

type publishAutoTriggerCall struct {
	groupID string
	msg     *models.GroupMessage
	trigger interface{}
}

func (f *fakeAutoTriggerPublisher) PublishAutoTriggerPendingMessage(groupID string, msg *models.GroupMessage, trigger interface{}) error {
	f.published = append(f.published, publishAutoTriggerCall{groupID: groupID, msg: msg, trigger: trigger})
	return f.err
}

type fakeAutoTriggerEvaluator struct {
	result *trigger.TriggerResult
	err    error
}

func (f *fakeAutoTriggerEvaluator) EvaluateAutoTriggerTimeout(ctx context.Context, lastMessage *models.GroupMessage, members []models.GroupMember) (*trigger.TriggerResult, error) {
	return f.result, f.err
}

type fakeAutoTriggerLock struct {
	releaseErr error
}

func (f *fakeAutoTriggerLock) Release() error {
	return f.releaseErr
}

type fakeAutoTriggerLockManager struct {
	lock AutoTriggerLock
	err  error
}

func (f *fakeAutoTriggerLockManager) Acquire(ctx context.Context, lockType, resourceID string) (AutoTriggerLock, error) {
	return f.lock, f.err
}

// ---------- Test helpers ----------

func setupAutoTriggerTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	require.NoError(t, err)
	err = db.AutoMigrate(
		&models.Group{},
		&models.GroupMember{},
		&models.GroupMessage{},
		&models.AgentMessageProcessing{},
	)
	require.NoError(t, err)
	t.Cleanup(func() {
		sqlDB, err := db.DB()
		if err == nil {
			_ = sqlDB.Close()
		}
	})
	return db
}

func newAutoTriggerWithFakes(t *testing.T, db *gorm.DB, pub *fakeAutoTriggerPublisher, eval *fakeAutoTriggerEvaluator, lm *fakeAutoTriggerLockManager, interval, timeout time.Duration) *AutoTrigger {
	t.Helper()
	if pub == nil {
		pub = &fakeAutoTriggerPublisher{}
	}
	if eval == nil {
		eval = &fakeAutoTriggerEvaluator{}
	}
	if lm == nil {
		lm = &fakeAutoTriggerLockManager{lock: &fakeAutoTriggerLock{}}
	}
	at := NewAutoTrigger(db, nil, pub, eval, lm, interval, timeout)
	t.Cleanup(func() {
		at.Stop()
	})
	return at
}

func createGroup(t *testing.T, db *gorm.DB, groupID string) *models.Group {
	t.Helper()
	g := &models.Group{
		GroupID:   groupID,
		GroupName: "test-group",
	}
	require.NoError(t, db.Create(g).Error)
	return g
}

func createMember(t *testing.T, db *gorm.DB, groupID, memberID string, memberType models.MemberType) *models.GroupMember {
	t.Helper()
	m := &models.GroupMember{
		GroupID:    groupID,
		MemberID:   memberID,
		MemberName: memberID,
		MemberType: memberType,
	}
	require.NoError(t, db.Create(m).Error)
	return m
}

func createMessage(t *testing.T, db *gorm.DB, groupID, senderID string, senderType models.MemberType, createAtMs int64) *models.GroupMessage {
	t.Helper()
	msg := &models.GroupMessage{
		GroupID:     groupID,
		MessageID:   uuid.New().String(),
		MessageText: "hello",
		SenderID:    senderID,
		SenderType:  senderType,
		CreateAtMs:  createAtMs,
		UpdateAtMs:  createAtMs,
	}
	require.NoError(t, db.Create(msg).Error)
	return msg
}

func createMessageWithID(t *testing.T, db *gorm.DB, groupID, messageID, senderID string, senderType models.MemberType, createAtMs int64) *models.GroupMessage {
	t.Helper()
	msg := &models.GroupMessage{
		GroupID:     groupID,
		MessageID:   messageID,
		MessageText: "hello",
		SenderID:    senderID,
		SenderType:  senderType,
		CreateAtMs:  createAtMs,
		UpdateAtMs:  createAtMs,
	}
	require.NoError(t, db.Create(msg).Error)
	return msg
}

func triggerResult(agentID string) *trigger.TriggerResult {
	return &trigger.TriggerResult{
		ShouldTrigger: true,
		Trigger:       trigger.TriggerInfo{Type: trigger.TriggerTypeAuto, AgentID: agentID},
		Targets:       []trigger.AgentTarget{{AgentID: agentID, Mode: "agent"}},
	}
}

// ---------- NewAutoTrigger tests ----------

func TestNewAutoTrigger_Defaults(t *testing.T) {
	at := NewAutoTrigger(nil, nil, nil, nil, nil, 0, 0)
	assert.Equal(t, 1*time.Minute, at.interval)
	assert.Equal(t, 10*time.Minute, at.timeout)
	// Stop should be safe even if Start was never called.
	at.Stop()
}

func TestNewAutoTrigger_CustomValues(t *testing.T) {
	at := NewAutoTrigger(nil, nil, nil, nil, nil, 5*time.Second, 3*time.Minute)
	assert.Equal(t, 5*time.Second, at.interval)
	assert.Equal(t, 3*time.Minute, at.timeout)
}

// ---------- Start / Stop / run lifecycle tests ----------

func TestAutoTrigger_StartStop(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	at := newAutoTriggerWithFakes(t, db, nil, nil, nil, 10*time.Millisecond, 10*time.Minute)

	at.Start()
	// Give the background goroutine time to run at least one checkAllGroups.
	time.Sleep(25 * time.Millisecond)
	at.Stop()

	// Stop should be idempotent
	at.Stop()
}

func TestAutoTrigger_RunCallsCheckAllGroupsImmediately(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	pub := &fakeAutoTriggerPublisher{}
	eval := &fakeAutoTriggerEvaluator{result: triggerResult("manager-1")}
	at := newAutoTriggerWithFakes(t, db, pub, eval, nil, time.Hour, time.Nanosecond)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	old := time.Now().Add(-2 * time.Minute).UnixMilli()
	createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, old)

	at.checkAllGroups()

	require.Len(t, pub.published, 1)
	assert.Equal(t, g.GroupID, pub.published[0].groupID)
}

// ---------- checkAllGroups tests ----------
func TestCheckAllGroups_DBError(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	// Close underlying connection to force error.
	sqlDB, err := db.DB()
	require.NoError(t, err)
	require.NoError(t, sqlDB.Close())

	at := newAutoTriggerWithFakes(t, db, nil, nil, nil, time.Minute, time.Minute)

	// Should not panic.
	at.checkAllGroups()
}

// ---------- checkGroup tests ----------

func TestCheckGroup_LockHeld(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	lm := &fakeAutoTriggerLockManager{lock: nil}
	at := newAutoTriggerWithFakes(t, db, nil, nil, lm, time.Minute, time.Minute)

	g := createGroup(t, db, "group-1")
	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err)
	assert.Equal(t, checkResultLockHeld, res)
}

func TestCheckGroup_LockError(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	lm := &fakeAutoTriggerLockManager{err: errors.New("lock failure")}
	at := newAutoTriggerWithFakes(t, db, nil, nil, lm, time.Minute, time.Minute)

	g := createGroup(t, db, "group-1")
	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.Error(t, err)
	assert.Equal(t, checkResultSkipped, res)
}

func TestCheckGroup_NilEvaluator(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	at := newAutoTriggerWithFakes(t, db, nil, nil, nil, time.Minute, time.Minute)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err)
	assert.Equal(t, checkResultSkipped, res)
}

func TestCheckGroup_NilResult(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	eval := &fakeAutoTriggerEvaluator{result: nil}
	at := newAutoTriggerWithFakes(t, db, nil, eval, nil, time.Minute, time.Minute)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err)
	assert.Equal(t, checkResultSkipped, res)
}

func TestCheckGroup_NoManagerAgent(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	eval := &fakeAutoTriggerEvaluator{result: &trigger.TriggerResult{ShouldTrigger: false}}
	at := newAutoTriggerWithFakes(t, db, nil, eval, nil, time.Minute, time.Minute)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err)
	assert.Equal(t, checkResultSkipped, res)
}

func TestCheckGroup_NoMessages(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	at := newAutoTriggerWithFakes(t, db, nil, nil, nil, time.Minute, time.Minute)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err)
	assert.Equal(t, checkResultSkipped, res)
}

func TestCheckGroup_NoTrigger(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	eval := &fakeAutoTriggerEvaluator{result: &trigger.TriggerResult{ShouldTrigger: false}}
	at := newAutoTriggerWithFakes(t, db, nil, eval, nil, time.Minute, time.Minute)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err)
	assert.Equal(t, checkResultSkipped, res)
}

func TestCheckGroup_AlreadyPending(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	pub := &fakeAutoTriggerPublisher{}
	eval := &fakeAutoTriggerEvaluator{result: triggerResult("manager-1")}
	at := newAutoTriggerWithFakes(t, db, pub, eval, nil, time.Minute, time.Nanosecond)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	msg := createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	existing := &models.AgentMessageProcessing{
		GroupID:   g.GroupID,
		MessageID: msg.MessageID,
		AgentID:   "manager-1",
		Status:    models.ProcessingStatusPending,
	}
	require.NoError(t, db.Create(existing).Error)

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err)
	assert.Equal(t, checkResultSkipped, res)
	assert.Empty(t, pub.published)
}

func TestCheckGroup_TriggerSuccess(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	pub := &fakeAutoTriggerPublisher{}
	eval := &fakeAutoTriggerEvaluator{result: triggerResult("manager-1")}
	at := newAutoTriggerWithFakes(t, db, pub, eval, nil, time.Minute, time.Nanosecond)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	msg := createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err)
	assert.Equal(t, checkResultTriggered, res)

	require.Len(t, pub.published, 1)
	assert.Equal(t, g.GroupID, pub.published[0].groupID)
	assert.Equal(t, msg.MessageID, pub.published[0].msg.ProcessedMsgID)

	var records []models.AgentMessageProcessing
	require.NoError(t, db.Where("group_id = ?", g.GroupID).Find(&records).Error)
	require.Len(t, records, 1)
	assert.Equal(t, models.ProcessingStatusPending, records[0].Status)
	assert.Equal(t, "manager-1", records[0].AgentID)
	assert.Equal(t, msg.MessageID, records[0].MessageID)
}

func TestCheckGroup_DuplicatePrevention(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	pub := &fakeAutoTriggerPublisher{}
	eval := &fakeAutoTriggerEvaluator{result: triggerResult("manager-1")}
	at := newAutoTriggerWithFakes(t, db, pub, eval, nil, time.Minute, time.Nanosecond)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	msg := createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	res1, err1 := at.checkGroup(context.Background(), g, "trace-1")
	assert.NoError(t, err1)
	assert.Equal(t, checkResultTriggered, res1)
	require.Len(t, pub.published, 1)

	// Second call with the same last message should detect existing pending record and skip.
	res2, err2 := at.checkGroup(context.Background(), g, "trace-2")
	assert.NoError(t, err2)
	assert.Equal(t, checkResultSkipped, res2)
	assert.Len(t, pub.published, 1, "should not publish duplicate pending message")

	var records []models.AgentMessageProcessing
	require.NoError(t, db.Where("group_id = ? AND message_id = ?", g.GroupID, msg.MessageID).Find(&records).Error)
	assert.Len(t, records, 1, "should not create duplicate processing record")
	assert.Equal(t, msg.MessageID, records[0].MessageID)
}

func TestCheckGroup_PendingMessageCreateError(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	pub := &fakeAutoTriggerPublisher{}
	eval := &fakeAutoTriggerEvaluator{result: triggerResult("manager-1")}
	at := newAutoTriggerWithFakes(t, db, pub, eval, nil, time.Minute, time.Nanosecond)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	// Drop group_messages table to force create error.
	require.NoError(t, db.Migrator().DropTable(&models.GroupMessage{}))

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.Error(t, err)
	assert.Equal(t, checkResultSkipped, res)
	assert.Empty(t, pub.published)
}

func TestCheckGroup_ProcessingRecordCreateError(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	pub := &fakeAutoTriggerPublisher{}
	eval := &fakeAutoTriggerEvaluator{result: triggerResult("manager-1")}
	at := newAutoTriggerWithFakes(t, db, pub, eval, nil, time.Minute, time.Nanosecond)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	// Drop agent_message_processing table to force processing record create error.
	require.NoError(t, db.Migrator().DropTable(&models.AgentMessageProcessing{}))

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	// Current production code logs the error but still publishes.
	assert.NoError(t, err)
	assert.Equal(t, checkResultTriggered, res)
	assert.Len(t, pub.published, 1)
}

func TestCheckGroup_PublishError(t *testing.T) {
	db := setupAutoTriggerTestDB(t)
	pub := &fakeAutoTriggerPublisher{err: errors.New("publish failure")}
	eval := &fakeAutoTriggerEvaluator{result: triggerResult("manager-1")}
	at := newAutoTriggerWithFakes(t, db, pub, eval, nil, time.Minute, time.Nanosecond)

	g := createGroup(t, db, "group-1")
	createMember(t, db, g.GroupID, "user-1", models.MemberTypeUser)
	createMember(t, db, g.GroupID, "manager-1", models.MemberTypeManagerAgent)
	createMessage(t, db, g.GroupID, "user-1", models.MemberTypeUser, time.Now().Add(-2*time.Minute).UnixMilli())

	res, err := at.checkGroup(context.Background(), g, "trace-1")
	assert.Error(t, err)
	assert.Equal(t, checkResultSkipped, res)
	// The publisher was called even though it returned an error; the fake records the attempt.
	assert.Len(t, pub.published, 1)
}
