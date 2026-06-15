// Package models provides GORM database model tests.
package models

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

// TestIsTerminalStatus_Completed verifies completed is a terminal status.
func TestIsTerminalStatus_Completed(t *testing.T) {
	amp := &AgentMessageProcessing{Status: ProcessingStatusCompleted}
	assert.True(t, amp.IsTerminalStatus())
}

// TestIsTerminalStatus_Failed verifies failed is a terminal status.
func TestIsTerminalStatus_Failed(t *testing.T) {
	amp := &AgentMessageProcessing{Status: ProcessingStatusFailed}
	assert.True(t, amp.IsTerminalStatus())
}

// TestIsTerminalStatus_Pending verifies pending is NOT a terminal status.
func TestIsTerminalStatus_Pending(t *testing.T) {
	amp := &AgentMessageProcessing{Status: ProcessingStatusPending}
	assert.False(t, amp.IsTerminalStatus())
}

// TestIsTerminalStatus_Running verifies running is NOT a terminal status.
func TestIsTerminalStatus_Running(t *testing.T) {
	amp := &AgentMessageProcessing{Status: ProcessingStatusRunning}
	assert.False(t, amp.IsTerminalStatus())
}

// TestIsTerminalStatus_Unknown verifies unknown status is NOT a terminal status.
func TestIsTerminalStatus_Unknown(t *testing.T) {
	amp := &AgentMessageProcessing{Status: "unknown"}
	assert.False(t, amp.IsTerminalStatus())
}
