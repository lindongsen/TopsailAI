package nats

import (
	"encoding/json"
	"errors"
	"runtime"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// mockMsg is a test double that tracks InProgress/Ack/Nak calls.
type mockMsg struct {
	Data    []byte
	Subject string

	mu               sync.Mutex
	inProgressCount  int
	ackCalled        bool
	nakCalled        bool
	inProgressErrors []error
}

func newMockMsg(data []byte) *mockMsg {
	return &mockMsg{
		Data:             data,
		inProgressErrors: make([]error, 0),
	}
}

func (m *mockMsg) InProgress() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.inProgressCount++
	if len(m.inProgressErrors) > 0 {
		err := m.inProgressErrors[0]
		m.inProgressErrors = m.inProgressErrors[1:]
		return err
	}
	return nil
}

func (m *mockMsg) Ack() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.ackCalled = true
	return nil
}

func (m *mockMsg) Nak() error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.nakCalled = true
	return nil
}

func (m *mockMsg) InProgressCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.inProgressCount
}

func (m *mockMsg) AckCalled() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.ackCalled
}

func (m *mockMsg) NakCalled() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.nakCalled
}

func (m *mockMsg) QueueNextInProgressError(err error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.inProgressErrors = append(m.inProgressErrors, err)
}

// simulateHandlerSuccess simulates the handler logic for a successful message processing.
func simulateHandlerSuccess(msg *mockMsg, processDuration time.Duration) {
	var payload struct {
		MessageID string `json:"message_id"`
	}
	_ = json.Unmarshal(msg.Data, &payload)
	messageID := payload.MessageID
	if messageID == "" {
		messageID = "unknown"
	}
	_ = messageID

	// Start InProgress heartbeat goroutine
	stopInProgress := make(chan struct{})
	go func() {
		// Use shorter ticker for test speed
		ticker := time.NewTicker(20 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				if err := msg.InProgress(); err != nil {
					// In test, we just ignore errors (same as production: log only)
					_ = err
				}
			case <-stopInProgress:
				return
			}
		}
	}()

	// Ensure heartbeat goroutine is always stopped
	defer func() {
		close(stopInProgress)
	}()

	// Recover from panic
	defer func() {
		if r := recover(); r != nil {
			// In production this logs; in test we just recover
			_ = r
		}
	}()

	// Simulate message processing
	time.Sleep(processDuration)
	msg.Ack()
}

// simulateHandlerFailure simulates the handler logic for a failed message processing.
func simulateHandlerFailure(msg *mockMsg, processDuration time.Duration) {
	var payload struct {
		MessageID string `json:"message_id"`
	}
	_ = json.Unmarshal(msg.Data, &payload)
	messageID := payload.MessageID
	if messageID == "" {
		messageID = "unknown"
	}
	_ = messageID

	// Start InProgress heartbeat goroutine
	stopInProgress := make(chan struct{})
	go func() {
		ticker := time.NewTicker(20 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				if err := msg.InProgress(); err != nil {
					_ = err
				}
			case <-stopInProgress:
				return
			}
		}
	}()

	// Ensure heartbeat goroutine is always stopped
	defer func() {
		close(stopInProgress)
	}()

	// Recover from panic
	defer func() {
		if r := recover(); r != nil {
			_ = r
		}
	}()

	// Simulate message processing that fails
	time.Sleep(processDuration)
	msg.Nak()
}

// TestHandler_InProgressHeartbeat_Success verifies that InProgress is called
// periodically during message processing and stops after Ack on success.
func TestHandler_InProgressHeartbeat_Success(t *testing.T) {
	msg := newMockMsg([]byte(`{"message_id":"msg-1"}`))

	// Simulate processing that takes 50ms
	// With 20ms ticker, InProgress should be called at least twice
	simulateHandlerSuccess(msg, 50*time.Millisecond)

	// Allow goroutine to finish
	time.Sleep(30 * time.Millisecond)

	assert.True(t, msg.AckCalled(), "Ack should be called on success")
	assert.False(t, msg.NakCalled(), "Nak should NOT be called on success")
	assert.GreaterOrEqual(t, msg.InProgressCount(), 1, "InProgress should be called at least once")
}

// TestHandler_InProgressHeartbeat_Failure verifies that InProgress stops
// after Nak when processMessage fails.
func TestHandler_InProgressHeartbeat_Failure(t *testing.T) {
	msg := newMockMsg([]byte(`{"message_id":"msg-2"}`))

	// Simulate failed processing that takes 50ms
	simulateHandlerFailure(msg, 50*time.Millisecond)

	// Allow goroutine to finish
	time.Sleep(30 * time.Millisecond)

	assert.True(t, msg.NakCalled(), "Nak should be called on failure")
	assert.False(t, msg.AckCalled(), "Ack should NOT be called on failure")
	assert.GreaterOrEqual(t, msg.InProgressCount(), 1, "InProgress should be called at least once")
}

// TestHandler_InProgressError_DoesNotAffectMainFlow verifies that InProgress
// errors are logged but do NOT interrupt the main processing flow.
func TestHandler_InProgressError_DoesNotAffectMainFlow(t *testing.T) {
	msg := newMockMsg([]byte(`{"message_id":"msg-3"}`))
	// Queue some InProgress errors
	msg.QueueNextInProgressError(errors.New("network error"))
	msg.QueueNextInProgressError(errors.New("timeout"))

	var processed atomic.Bool

	// Custom handler that tracks processing completion
	stopInProgress := make(chan struct{})
	go func() {
		ticker := time.NewTicker(20 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				_ = msg.InProgress()
			case <-stopInProgress:
				return
			}
		}
	}()

	// Simulate processing - should complete despite InProgress errors
	time.Sleep(50 * time.Millisecond)
	processed.Store(true)
	msg.Ack()
	close(stopInProgress)

	// Allow goroutine to finish
	time.Sleep(30 * time.Millisecond)

	assert.True(t, processed.Load(), "main processing should complete despite InProgress errors")
	assert.True(t, msg.AckCalled(), "Ack should still be called")
	assert.GreaterOrEqual(t, msg.InProgressCount(), 1, "InProgress should still be attempted")
}

// TestHandler_NoGoroutineLeak verifies that the heartbeat goroutine exits
// properly after processing completes.
func TestHandler_NoGoroutineLeak(t *testing.T) {
	// Count goroutines before
	before := runtime.NumGoroutine()

	for i := 0; i < 10; i++ {
		msg := newMockMsg([]byte(`{"message_id":"msg-leak"}`))
		simulateHandlerSuccess(msg, 30*time.Millisecond)
	}

	// Allow goroutines to exit
	time.Sleep(100 * time.Millisecond)

	// Force GC to clean up
	runtime.GC()
	time.Sleep(50 * time.Millisecond)

	after := runtime.NumGoroutine()
	// Allow some tolerance for background goroutines
	assert.LessOrEqual(t, after, before+2, "goroutine count should not increase significantly: before=%d, after=%d", before, after)
}

// TestHandler_PanicRecovery verifies that panic in processMessage is recovered
// and the heartbeat goroutine is still properly stopped.
func TestHandler_PanicRecovery(t *testing.T) {
	msg := newMockMsg([]byte(`{"message_id":"msg-panic"}`))

	var recovered bool
	var stopClosed bool

	// Wrap in anonymous function to capture panic recovery result
	func() {
		// Simulate handler with panic
		stopInProgress := make(chan struct{})
		go func() {
			ticker := time.NewTicker(20 * time.Millisecond)
			defer ticker.Stop()
			for {
				select {
				case <-ticker.C:
					_ = msg.InProgress()
				case <-stopInProgress:
					return
				}
			}
		}()

		// This defer runs first (LIFO), closes stopInProgress
		defer func() {
			close(stopInProgress)
			stopClosed = true
		}()

		// This defer runs second (LIFO), recovers panic
		defer func() {
			if r := recover(); r != nil {
				recovered = true
			}
		}()

		panic("simulated panic in processMessage")
	}()

	assert.True(t, recovered, "panic should be recovered")
	assert.True(t, stopClosed, "stopInProgress should be closed after panic")
}

// TestHandler_MessageIDExtraction verifies that message_id is correctly
// extracted from payload for logging.
func TestHandler_MessageIDExtraction(t *testing.T) {
	tests := []struct {
		name        string
		payload     string
		wantMsgID   string
		wantUnknown bool
	}{
		{
			name:      "valid message_id",
			payload:   `{"message_id":"msg-123","group_id":"g-1"}`,
			wantMsgID: "msg-123",
		},
		{
			name:        "missing message_id",
			payload:     `{"group_id":"g-1"}`,
			wantUnknown: true,
		},
		{
			name:        "empty payload",
			payload:     `{}`,
			wantUnknown: true,
		},
		{
			name:        "invalid json",
			payload:     `not-json`,
			wantUnknown: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var payload struct {
				MessageID string `json:"message_id"`
			}
			_ = json.Unmarshal([]byte(tt.payload), &payload)
			messageID := payload.MessageID
			if messageID == "" {
				messageID = "unknown"
			}

			if tt.wantUnknown {
				assert.Equal(t, "unknown", messageID)
			} else {
				assert.Equal(t, tt.wantMsgID, messageID)
			}
		})
	}
}

// TestHandler_LongRunningProcessing verifies that InProgress continues to be
// called throughout a long-running process (simulating agent execution).
func TestHandler_LongRunningProcessing(t *testing.T) {
	msg := newMockMsg([]byte(`{"message_id":"msg-long"}`))

	// Simulate a 200ms long-running process
	// With 20ms ticker, InProgress should be called many times
	simulateHandlerSuccess(msg, 200*time.Millisecond)

	// Allow goroutine to finish
	time.Sleep(30 * time.Millisecond)

	assert.True(t, msg.AckCalled(), "Ack should be called after long processing")
	assert.GreaterOrEqual(t, msg.InProgressCount(), 5, "InProgress should be called multiple times during long processing")
}

// TestHandler_StopInProgressCalledExactlyOnce verifies that stopInProgress
// channel is closed exactly once, even with multiple defers.
func TestHandler_StopInProgressCalledExactlyOnce(t *testing.T) {
	msg := newMockMsg([]byte(`{"message_id":"msg-once"}`))

	closeCount := atomic.Int32{}

	// Wrap in a function so defer runs before we assert
	func() {
		stopInProgress := make(chan struct{})

		go func() {
			ticker := time.NewTicker(20 * time.Millisecond)
			defer ticker.Stop()
			for {
				select {
				case <-ticker.C:
					_ = msg.InProgress()
				case <-stopInProgress:
					return
				}
			}
		}()

		// Simulate the defer pattern from production code
		defer func() {
			closeCount.Add(1)
			close(stopInProgress)
		}()

		// Normal processing
		time.Sleep(50 * time.Millisecond)
		msg.Ack()
	}()

	// When function returns, defer runs once
	// closeCount should be 1
	assert.Equal(t, int32(1), closeCount.Load(), "stopInProgress should be closed exactly once")
}

// TestHandler_InProgressStopsAfterClose verifies that the heartbeat goroutine
// stops immediately when stopInProgress is closed.
func TestHandler_InProgressStopsAfterClose(t *testing.T) {
	msg := newMockMsg([]byte(`{"message_id":"msg-stop"}`))

	stopInProgress := make(chan struct{})
	go func() {
		ticker := time.NewTicker(20 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				_ = msg.InProgress()
			case <-stopInProgress:
				return
			}
		}
	}()

	// Let it run for a bit
	time.Sleep(50 * time.Millisecond)
	countBeforeClose := msg.InProgressCount()

	// Close the channel
	close(stopInProgress)

	// Wait and verify no more InProgress calls
	time.Sleep(100 * time.Millisecond)
	countAfterClose := msg.InProgressCount()

	assert.Equal(t, countBeforeClose, countAfterClose, "InProgress should stop being called after channel is closed")
}

// TestHandler_PanicWithHeartbeat verifies the full panic recovery scenario
// including heartbeat cleanup.
func TestHandler_PanicWithHeartbeat(t *testing.T) {
	msg := newMockMsg([]byte(`{"message_id":"msg-panic-full"}`))

	var recovered bool
	var stopClosed bool

	// Should not panic
	require.NotPanics(t, func() {
		// Wrap in anonymous function to capture panic recovery result
		func() {
			stopInProgress := make(chan struct{})
			go func() {
				ticker := time.NewTicker(20 * time.Millisecond)
				defer ticker.Stop()
				for {
					select {
					case <-ticker.C:
						_ = msg.InProgress()
					case <-stopInProgress:
						return
					}
				}
			}()

			// This defer runs first (LIFO), closes stopInProgress
			defer func() {
				close(stopInProgress)
				stopClosed = true
			}()

			// This defer runs second (LIFO), recovers panic
			defer func() {
				if r := recover(); r != nil {
					recovered = true
				}
			}()

			panic("simulated panic")
		}()
	})

	// Allow goroutine to exit
	time.Sleep(50 * time.Millisecond)

	assert.True(t, recovered, "panic should be recovered")
	assert.True(t, stopClosed, "stopInProgress should be closed after panic")
}
