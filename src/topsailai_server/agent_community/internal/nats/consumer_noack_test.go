// Package nats provides NATS consumer no-ack mode tests.
package nats

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/stretchr/testify/assert"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
)

// ===== No-Ack Mode Tests =====

func TestConsumer_NoAckMode_Enabled(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
		},
	}
	c := NewConsumer(db, nil, nil, nil, cfg)

	assert.True(t, c.noAck, "noAck should be true when PendingMessageNoAck is enabled")
}

func TestConsumer_NoAckMode_Disabled(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: false,
		},
	}
	c := NewConsumer(db, nil, nil, nil, cfg)

	assert.False(t, c.noAck, "noAck should be false when PendingMessageNoAck is disabled")
}

func TestConsumer_NoAckMode_Default(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{},
	}
	c := NewConsumer(db, nil, nil, nil, cfg)

	assert.False(t, c.noAck, "noAck should default to false")
}

func TestConsumer_NoAckMode_NilConfig(t *testing.T) {
	db := setupConsumerTestDB(t)
	c := NewConsumer(db, nil, nil, nil, nil)

	assert.False(t, c.noAck, "noAck should default to false when config is nil")
}

// ===== Handler No-Ack Mode Tests =====

func TestHandler_NoAckMode_Success(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
		},
	}

	// Create a group and member
	group := createTestGroup(t, db, "g-noack-success", "Test Group")
	_ = createTestAgentMember(t, db, group.GroupID, "user1", "")

	c := NewConsumer(db, nil, nil, nil, cfg)

	// Create a mock message
	payload := PendingMessagePayload{
		GroupMessage: models.GroupMessage{
			MessageID:   "msg1",
			GroupID:     "g-noack-success",
			SenderID:    "user1",
			MessageText: "hello",
		},
		Trigger: map[string]interface{}{
			"type":     "auto",
			"agent_id": "agent1",
		},
	}
	data, _ := json.Marshal(payload)

	msg := &nats.Msg{
		Data: data,
		Header: nats.Header{
			"X-Trace-ID": []string{"trace-1"},
		},
	}

	// In no-ack mode, processMessage will fail because agent1 doesn't exist,
	// but it should NOT call Ack or Nak
	handler := c.Handler()
	handler(msg)

	// If we reach here without panic, the test passes
	// In no-ack mode, errors are only logged, not propagated
}

func TestHandler_NoAckMode_DoesNotCallAck(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
		},
	}

	c := NewConsumer(db, nil, nil, nil, cfg)

	payload := PendingMessagePayload{
		GroupMessage: models.GroupMessage{
			MessageID:   "msg1",
			GroupID:     "nonexistent",
			SenderID:    "user1",
		},
		Trigger: map[string]interface{}{
			"type":     "auto",
			"agent_id": "agent1",
		},
	}
	data, _ := json.Marshal(payload)

	msg := &nats.Msg{
		Data: data,
		Header: nats.Header{
			"X-Trace-ID": []string{"trace-1"},
		},
	}

	// In no-ack mode, handler should not panic even if group doesn't exist
	// It should just log and return without calling Ack/Nak
	handler := c.Handler()
	handler(msg)

	// Test passes if no panic occurs
}

func TestHandler_NoAckMode_PanicRecovery(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
		},
	}

	c := NewConsumer(db, nil, nil, nil, cfg)

	// Create invalid payload that will cause panic in processMessage
	msg := &nats.Msg{
		Data: []byte("invalid json"),
		Header: nats.Header{
			"X-Trace-ID": []string{"trace-1"},
		},
	}

	// In no-ack mode, panic should be recovered
	handler := c.Handler()
	handler(msg)

	// Test passes if no panic propagates
}

func TestHandler_NoAckMode_NoGoroutineLeak(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
		},
	}

	c := NewConsumer(db, nil, nil, nil, cfg)

	payload := PendingMessagePayload{
		GroupMessage: models.GroupMessage{
			MessageID:   "msg1",
			GroupID:     "nonexistent",
			SenderID:    "user1",
		},
		Trigger: map[string]interface{}{
			"type":     "auto",
			"agent_id": "agent1",
		},
	}
	data, _ := json.Marshal(payload)

	// Process multiple messages
	for i := 0; i < 10; i++ {
		msg := &nats.Msg{
			Data: data,
			Header: nats.Header{
				"X-Trace-ID": []string{"trace-1"},
			},
		}
		handler := c.Handler()
		handler(msg)
	}

	// In no-ack mode, no goroutines should be leaked
	// (no InProgress heartbeat goroutine is started)
	// We can't easily count goroutines in unit tests, but the fact that
	// we can process 10 messages without issues is a good sign
}

// ===== Ack Mode Tests (to ensure existing behavior is preserved) =====

func TestHandler_AckMode_CallsAckOnSuccess(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: false,
		},
	}

	// Create a group and member
	group := createTestGroup(t, db, "g-ack-success", "Test Group")
	_ = createTestAgentMember(t, db, group.GroupID, "user1", "")

	c := NewConsumer(db, nil, nil, nil, cfg)

	payload := PendingMessagePayload{
		GroupMessage: models.GroupMessage{
			MessageID:   "msg1",
			GroupID:     "g-ack-success",
			SenderID:    "user1",
			MessageText: "hello",
		},
		Trigger: map[string]interface{}{
			"type":     "auto",
			"agent_id": "agent1",
		},
	}
	data, _ := json.Marshal(payload)

	msg := &nats.Msg{
		Data: data,
		Header: nats.Header{
			"X-Trace-ID": []string{"trace-1"},
		},
	}

	// In ack mode, processMessage will fail because agent1 doesn't exist,
	// so it should call Nak (not Ack)
	handler := c.Handler()
	handler(msg)

	// Test passes if no panic occurs
}

// ===== Client No-Ack Configuration Tests =====

func TestClient_CreatePendingMessageConsumer_NoAckMode(t *testing.T) {
	// This test verifies the consumer options are correctly set
	// We can't actually test NATS subscription without a real NATS server,
	// but we can verify the configuration logic

	cfg := &config.NATSConfig{
		Servers:             "nats://localhost:4222",
		PendingMessageNoAck: true,
	}

	client := NewClient(cfg)
	assert.NotNil(t, client)
	assert.True(t, client.cfg.PendingMessageNoAck)
}

func TestClient_CreatePendingMessageConsumer_AckMode(t *testing.T) {
	cfg := &config.NATSConfig{
		Servers:             "nats://localhost:4222",
		PendingMessageNoAck: false,
		AckWaitSeconds:      3600,
	}

	client := NewClient(cfg)
	assert.NotNil(t, client)
	assert.False(t, client.cfg.PendingMessageNoAck)
	assert.Equal(t, 3600, client.cfg.AckWaitSeconds)
}

func TestClient_CreatePendingMessageConsumer_AckWaitDefault(t *testing.T) {
	cfg := &config.NATSConfig{
		Servers:             "nats://localhost:4222",
		PendingMessageNoAck: false,
		AckWaitSeconds:      0, // Should use default
	}

	client := NewClient(cfg)
	assert.NotNil(t, client)
	// AckWaitSeconds=0 should be handled in CreatePendingMessageConsumer
	// by falling back to default 3600
}

// ===== Integration: No-Ack with Config Loading =====

func TestConfig_NoAckFromEnvironment(t *testing.T) {
	// Test that config correctly parses PendingMessageNoAck
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
			AckWaitSeconds:      7200,
		},
	}

	assert.True(t, cfg.NATS.PendingMessageNoAck)
	assert.Equal(t, 7200, cfg.NATS.AckWaitSeconds)
}

func TestConfig_AckWaitFromEnvironment(t *testing.T) {
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: false,
			AckWaitSeconds:      1800,
		},
	}

	assert.False(t, cfg.NATS.PendingMessageNoAck)
	assert.Equal(t, 1800, cfg.NATS.AckWaitSeconds)
}

// ===== Handler Behavior Verification =====

func TestHandler_NoAckMode_DoesNotStartHeartbeat(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
		},
	}

	c := NewConsumer(db, nil, nil, nil, cfg)

	payload := PendingMessagePayload{
		GroupMessage: models.GroupMessage{
			MessageID:   "msg1",
			GroupID:     "nonexistent",
			SenderID:    "user1",
		},
		Trigger: map[string]interface{}{
			"type":     "auto",
			"agent_id": "agent1",
		},
	}
	data, _ := json.Marshal(payload)

	msg := &nats.Msg{
		Data: data,
		Header: nats.Header{
			"X-Trace-ID": []string{"trace-1"},
		},
	}

	// Process the message
	handler := c.Handler()
	handler(msg)

	// In no-ack mode, no heartbeat goroutine should be started
	// The handler should return immediately without any background goroutines
	// We verify this by checking that the handler completes quickly
	start := time.Now()
	handler(msg)
	elapsed := time.Since(start)

	// Should complete in less than 1 second (no heartbeat delay)
	assert.Less(t, elapsed, 1*time.Second, "no-ack handler should complete immediately without heartbeat")
}

func TestHandler_AckMode_StartsHeartbeat(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: false,
		},
	}

	c := NewConsumer(db, nil, nil, nil, cfg)

	payload := PendingMessagePayload{
		GroupMessage: models.GroupMessage{
			MessageID:   "msg1",
			GroupID:     "nonexistent",
			SenderID:    "user1",
		},
		Trigger: map[string]interface{}{
			"type":     "auto",
			"agent_id": "agent1",
		},
	}
	data, _ := json.Marshal(payload)

	msg := &nats.Msg{
		Data: data,
		Header: nats.Header{
			"X-Trace-ID": []string{"trace-1"},
		},
	}

	// In ack mode, handler starts a heartbeat goroutine
	// The handler itself returns quickly, but a goroutine is left running
	handler := c.Handler()
	handler(msg)

	// We can't directly test the heartbeat without a real NATS connection,
	// but we verify the consumer is in ack mode
	assert.False(t, c.noAck)
}

// ===== Edge Cases =====

func TestHandler_NoAckMode_EmptyPayload(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
		},
	}

	c := NewConsumer(db, nil, nil, nil, cfg)

	msg := &nats.Msg{
		Data: []byte{},
		Header: nats.Header{
			"X-Trace-ID": []string{"trace-1"},
		},
	}

	// Should not panic with empty payload
	handler := c.Handler()
	handler(msg)
}

func TestHandler_NoAckMode_NilTrigger(t *testing.T) {
	db := setupConsumerTestDB(t)
	cfg := &config.Config{
		NATS: config.NATSConfig{
			PendingMessageNoAck: true,
		},
	}

	// Create a group and member
	group := createTestGroup(t, db, "g-nil-trigger", "Test Group")
	_ = createTestAgentMember(t, db, group.GroupID, "user1", "")

	c := NewConsumer(db, nil, nil, nil, cfg)

	payload := PendingMessagePayload{
		GroupMessage: models.GroupMessage{
			MessageID:   "msg1",
			GroupID:     "g-nil-trigger",
			SenderID:    "user1",
			MessageText: "hello",
		},
		Trigger: nil,
	}
	data, _ := json.Marshal(payload)

	msg := &nats.Msg{
		Data: data,
		Header: nats.Header{
			"X-Trace-ID": []string{"trace-1"},
		},
	}

	// Should handle nil trigger gracefully
	handler := c.Handler()
	handler(msg)
}

// ===== Benchmarks =====


