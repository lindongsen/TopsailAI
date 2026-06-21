package nats

import (
	"path/filepath"
	"sync"
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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

	isRunning, err := c.isAgentAlreadyRunning("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)
	assert.False(t, isRunning)
}

func TestIsAgentAlreadyRunning_SameAgentRunning(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

	err := c.createRunningRecord("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)

	var record models.AgentMessageProcessing
	assert.NoError(t, db.First(&record, "group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Error)
	assert.Equal(t, models.ProcessingStatusRunning, record.Status)
}

// ===== recordProcessingStatus tests =====

func TestRecordProcessingStatus_UpdateRunningRecord(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

	// No running record exists, recordProcessingStatus should create a new one
	c.recordProcessingStatus("g1", "m1", "a1", true, "", "trace-1")

	var records []models.AgentMessageProcessing
	assert.NoError(t, db.Where("group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Find(&records).Error)
	assert.Len(t, records, 1)
	assert.Equal(t, models.ProcessingStatusCompleted, records[0].Status)
}

func TestRecordProcessingStatus_UpdatesTimestamp(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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
	c := NewConsumer(db, nil, nil, nil, nil, nil)

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

// ===== checkAndCreateRunningRecord tests =====

func TestCheckAndCreateRunningRecord_NewRecord(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil, nil)

	created, err := c.checkAndCreateRunningRecord("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)
	assert.True(t, created)

	var record models.AgentMessageProcessing
	assert.NoError(t, db.First(&record, "group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Error)
	assert.Equal(t, models.ProcessingStatusRunning, record.Status)
}

func TestCheckAndCreateRunningRecord_AlreadyRunning(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil, nil)

	// Pre-create a running record
	runningRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(runningRecord).Error)

	// Should return false since agent is already running
	created, err := c.checkAndCreateRunningRecord("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)
	assert.False(t, created)

	// Verify only one record exists
	var records []models.AgentMessageProcessing
	assert.NoError(t, db.Where("group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Find(&records).Error)
	assert.Len(t, records, 1)
}

func TestCheckAndCreateRunningRecord_CompletedRecord(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil, nil)

	// Pre-create a completed record
	completedRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusCompleted,
	}
	assert.NoError(t, db.Create(completedRecord).Error)

	// Should return false since the message-agent pair was already processed.
	created, err := c.checkAndCreateRunningRecord("g1", "m1", "a1", "trace-1")
	assert.NoError(t, err)
	assert.False(t, created)

	// Verify only the completed record exists.
	var records []models.AgentMessageProcessing
	assert.NoError(t, db.Where("group_id = ? AND message_id = ? AND agent_id = ?", "g1", "m1", "a1").Find(&records).Error)
	assert.Len(t, records, 1)
	assert.Equal(t, models.ProcessingStatusCompleted, records[0].Status)
}

func TestCheckAndCreateRunningRecord_DifferentAgentRunning(t *testing.T) {
	db := setupDuplicateTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil, nil)

	// Pre-create a running record for a different agent
	runningRecord := &models.AgentMessageProcessing{
		GroupID:   "g1",
		MessageID: "m1",
		AgentID:   "a1",
		Status:    models.ProcessingStatusRunning,
	}
	assert.NoError(t, db.Create(runningRecord).Error)

	// Should create a new running record for a different agent
	created, err := c.checkAndCreateRunningRecord("g1", "m1", "a2", "trace-1")
	assert.NoError(t, err)
	assert.True(t, created)

	// Verify two records exist
	var records []models.AgentMessageProcessing
	assert.NoError(t, db.Where("group_id = ? AND message_id = ?", "g1", "m1").Find(&records).Error)
	assert.Len(t, records, 2)
}

func TestCheckAndCreateRunningRecord_Concurrent(t *testing.T) {
	// Use a unique file-backed SQLite database per test run so that state from
	// one execution (e.g. under -count=N) cannot leak into the next. WAL mode
	// and a busy timeout keep concurrent goroutines stable, while limiting the
	// pool to a single connection serializes access so the transaction's
	// atomicity guarantees that exactly one goroutine creates the record.
	tmpFile := filepath.Join(t.TempDir(), "acs-duplicate-concurrent-test.db")
	db, err := gorm.Open(sqlite.Open(tmpFile+"?_journal_mode=WAL&_busy_timeout=5000"), &gorm.Config{})
	if err != nil {
		t.Fatalf("failed to open file-backed db: %v", err)
	}
	if err := db.AutoMigrate(&models.AgentMessageProcessing{}); err != nil {
		t.Fatalf("failed to migrate: %v", err)
	}

	sqlDB, err := db.DB()
	if err != nil {
		t.Fatalf("failed to get sql.DB: %v", err)
	}
	sqlDB.SetMaxOpenConns(1)
	sqlDB.SetMaxIdleConns(1)

	c := NewConsumer(db, nil, nil, nil, nil, nil)

	const numGoroutines = 10
	results := make(chan bool, numGoroutines)
	var startWg sync.WaitGroup
	startWg.Add(numGoroutines)
	var doneWg sync.WaitGroup
	doneWg.Add(numGoroutines)

	// Launch multiple goroutines trying to create the same running record
	for i := 0; i < numGoroutines; i++ {
		go func() {
			defer doneWg.Done()
			startWg.Done()
			startWg.Wait()
			created, err := c.checkAndCreateRunningRecord("g1", "m1", "a1", "trace-1")
			if err != nil {
				results <- false
				return
			}
			results <- created
		}()
	}
	doneWg.Wait()
	close(results)

	// Collect results
	var successCount int
	for created := range results {
		if created {
			successCount++
		}
	}

	// Only one goroutine should have successfully created the record
	assert.Equal(t, 1, successCount, "exactly one goroutine should create the record")

	// Verify only one running record exists
	var records []models.AgentMessageProcessing
	assert.NoError(t, db.Where("group_id = ? AND message_id = ? AND agent_id = ? AND status = ?", "g1", "m1", "a1", models.ProcessingStatusRunning).Find(&records).Error)
	assert.Len(t, records, 1)
}
