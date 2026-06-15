// Package nats provides NATS consumer tests.
package nats

import (
	"fmt"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/models"
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
