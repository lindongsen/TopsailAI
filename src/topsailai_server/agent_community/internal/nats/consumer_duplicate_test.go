package nats

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/topsailai/agent-community/internal/models"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

func setupDuplicateTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open(":memory:"), &gorm.Config{})
	if err != nil {
		t.Fatalf("failed to open in-memory db: %v", err)
	}
	if err := db.AutoMigrate(&models.AgentMessageProcessing{}); err != nil {
		t.Fatalf("failed to migrate: %v", err)
	}
	return db
}

// ===== isAgentAlreadyRunning tests =====

func TestIsAgentAlreadyRunning_NoRecord(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)
	assert.False(t, isRunning)
}

func TestIsAgentAlreadyRunning_SameAgentRunning(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	record := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(record).Error)

	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)
	assert.True(t, isRunning)
}

func TestIsAgentAlreadyRunning_DifferentAgentRunning(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	// Running record for agent a1
	runningRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(runningRecord).Error)

	// Check for same message but different agent (a2) - should NOT find running
	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a2", "trace-1")
	assert.NoError(t, err)
	assert.False(t, isRunning)
}

func TestIsAgentAlreadyRunning_CompletedRecord(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	record := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusCompleted,
	}
	assert.NoError(t, db.Create(record).Error)

	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)
	assert.False(t, isRunning)
}

func TestIsAgentAlreadyRunning_FailedRecord(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	record := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusFailed,
	}
	assert.NoError(t, db.Create(record).Error)

	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)
	assert.False(t, isRunning)
}

// ===== createRunningRecord tests =====

func TestCreateRunningRecord(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	err := c.createRunningRecord("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)

	var record models.AgentMessageProcessing
	assert.NoError(t, db.First(&record, "group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Error)
	assert.Equal(t, models.ProcessingStatusRunning, record.Status)
}

// ===== recordProcessingStatus tests =====

func TestRecordProcessingStatus_UpdateRunningRecord(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	// Create running record first
	runningRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(runningRecord).Error)

	// Update to completed
	c.recordProcessingStatus("g1", "m1", "a1", true, "", "trace-1")

	var record models.AgentMessageProcessing
	assert.NoError(t, db.First(&record, "group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Error)
	assert.Equal(t, models.ProcessingStatusCompleted, record.Status)
	assert.Greater(t, record.ProcessedAtMs, int64(0))
}

func TestRecordProcessingStatus_UpdateRunningRecordToFailed(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	// Create running record first
	runningRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(runningRecord).Error)

	// Update to failed
	c.recordProcessingStatus("g1", "m1", "a1", false, "agent timeout", "trace-1")

	var record models.AgentMessageProcessing
	assert.NoError(t, db.First(&record, "group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Error)
	assert.Equal(t, models.ProcessingStatusFailed, record.Status)
	assert.Equal(t, "agent timeout", record.ErrorMessage)
	assert.Greater(t, record.ProcessedAtMs, int64(0))
}

func TestRecordProcessingStatus_NoRunningRecord_CreatesNew(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	// No running record exists, recordProcessingStatus should create a new one
	c.recordProcessingStatus("g1", "m1", "a1", true, "", "trace-1")

	var records []models.AgentMessageProcessing
	assert.NoError(t, db.Where("group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Find(&records).Error)
	assert.Len(t, records, 1)
	assert.Equal(t, models.ProcessingStatusCompleted, records[0].Status)
}

func TestRecordProcessingStatus_UpdatesTimestamp(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	runningRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(runningRecord).Error)

	beforeUpdate := time.Now().UnixMilli()
	time.Sleep(10 * time.Millisecond)

	c.recordProcessingStatus("g1", "m1", "a1", true, "", "trace-1")

	var record models.AgentMessageProcessing
	assert.NoError(t, db.First(&record, "group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Error)
	assert.Greater(t, record.ProcessedAtMs, beforeUpdate)
	assert.Greater(t, record.UpdateAtMs, beforeUpdate)
}

// ===== Agent-level deduplication integration tests =====

func TestAgentLevelDeduplication_SameAgentSameMessage(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	// Simulate first node creating running record for agent a1 on message m1
	runningRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(runningRecord).Error)

	// Second node checks same agent on same message - should find it running
	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a1", "trace-2")
	assert.NoError(t, err)
	assert.True(t, isRunning)
}

func TestAgentLevelDeduplication_DifferentAgentsSameMessage(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	// Simulate first node creating running record for agent a1 on message m1
	runningRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(runningRecord).Error)

	// Second node checks different agent (a2) on same message - should NOT find it running
	// This allows multiple different agents to process the same message concurrently
	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a2", "trace-2")
	assert.NoError(t, err)
	assert.False(t, isRunning)
}

func TestAgentLevelDeduplication_MultipleAgentsCanRun(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	// Create running records for multiple agents on the same message
	agents := []string{"a1", "a2", "a3"}
	for _, agentID := range agents {
		record := &models.AgentMessageProcessing{
			GroupID:   "g1",
			MessageID: "m1",
			AgentID:   agentID,
			Status:    models.ProcessingStatusRunning,
		}
		assert.NoError(t, db.Create(record).Error)
	}

	// Verify each agent is found running
	for _, agentID := range agents {
		isRunning, err := c.isAgentAlreadyRunning("g1", "m1", agentID, "trace-1")
		assert.NoError(t, err)
		assert.True(t, isRunning, "agent %s should be running", agentID)
	}

	// Verify a new agent (a4) is NOT found running
	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a4", "trace-1")
	assert.NoError(t, err)
	assert.False(t, isRunning)
}
