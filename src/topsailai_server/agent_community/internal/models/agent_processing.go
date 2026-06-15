// Package models defines GORM database models for the ACS service.
package models

import (
	"time"

	"gorm.io/gorm"
)

// AgentMessageProcessing tracks agent message processing to prevent duplicates and loops.
type AgentMessageProcessing struct {
	ID            uint64    `gorm:"column:id;type:bigint;primaryKey;autoIncrement" json:"id"`
	GroupID       string    `gorm:"column:group_id;type:varchar(64);not null;index:idx_amp_group_msg" json:"group_id"`
	MessageID     string    `gorm:"column:message_id;type:varchar(64);not null;index:idx_amp_group_msg" json:"message_id"`
	AgentID       string    `gorm:"column:agent_id;type:varchar(64);not null" json:"agent_id"`
	Status        string    `gorm:"column:status;type:varchar(32);not null;default:'pending'" json:"status"`
	ErrorMessage  string    `gorm:"column:error_message;type:text" json:"error_message"`
	ProcessedAtMs int64     `gorm:"column:processed_at_ms;type:bigint;default:0" json:"processed_at_ms"`
	CreateAtMs    int64     `gorm:"column:create_at_ms;type:bigint;not null" json:"create_at_ms"`
	UpdateAtMs    int64     `gorm:"column:update_at_ms;type:bigint;not null" json:"update_at_ms"`
}

// TableName specifies the table name for AgentMessageProcessing.
func (AgentMessageProcessing) TableName() string {
	return "agent_message_processing"
}

// BeforeCreate hook sets create and update timestamps.
func (amp *AgentMessageProcessing) BeforeCreate(tx *gorm.DB) error {
	now := time.Now().UnixMilli()
	amp.CreateAtMs = now
	amp.UpdateAtMs = now
	return nil
}

// BeforeUpdate hook sets update timestamp.
func (amp *AgentMessageProcessing) BeforeUpdate(tx *gorm.DB) error {
	amp.UpdateAtMs = time.Now().UnixMilli()
	return nil
}

// Processing status constants.
const (
	ProcessingStatusPending   = "pending"
	ProcessingStatusRunning   = "running"
	ProcessingStatusCompleted = "completed"
	ProcessingStatusFailed    = "failed"
)
// IsTerminalStatus returns true if the status is a terminal state (completed or failed).
func (amp *AgentMessageProcessing) IsTerminalStatus() bool {
	return amp.Status == ProcessingStatusCompleted || amp.Status == ProcessingStatusFailed
}

