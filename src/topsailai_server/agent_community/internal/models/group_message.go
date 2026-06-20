// Package models defines GORM database models for the ACS service.
package models

import (
	"strings"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"
)

// Mention represents a mention in a message.
type Mention struct {
	MemberID   string `json:"member_id"`
	MemberName string `json:"member_name"`
	MemberType string `json:"member_type"`
}

// Attachment represents a file attachment in a message.
type Attachment struct {
	Data   string `json:"data"`
	Size   int64  `json:"size"`
	Format string `json:"format"`
}

// GroupMessage represents a message sent within a group.
type GroupMessage struct {
	GroupID            string         `gorm:"column:group_id;type:varchar(64);not null;index:idx_group_message_group_id" json:"group_id"`
	MessageID          string         `gorm:"column:message_id;type:varchar(64);primaryKey" json:"message_id"`
	MessageText        string         `gorm:"column:message_text;type:text" json:"message_text"`
	MessageAttachments string         `gorm:"column:message_attachments;type:text;default:'[]'" json:"message_attachments"`
	SenderID           string         `gorm:"column:sender_id;type:varchar(64);not null" json:"sender_id"`
	SenderType         MemberType     `gorm:"column:sender_type;type:varchar(32);not null" json:"sender_type"`
	ProcessedMsgID     string         `gorm:"column:processed_msg_id;type:varchar(64);default:''" json:"processed_msg_id"`
	Mentions           string         `gorm:"column:mentions;type:text;default:'[]'" json:"mentions"`
	IsDeleted          bool           `gorm:"column:is_deleted;type:boolean;not null;default:false" json:"is_deleted"`
	DeleteAtMs         int64          `gorm:"column:delete_at_ms;type:bigint;default:0" json:"delete_at_ms"`
	CreateAtMs         int64          `gorm:"column:create_at_ms;type:bigint;not null;index:idx_group_message_create_at" json:"create_at_ms"`
	UpdateAtMs         int64          `gorm:"column:update_at_ms;type:bigint;not null" json:"update_at_ms"`
	DeletedAt          gorm.DeletedAt `gorm:"column:deleted_at;index" json:"-"`
}

// TableName specifies the table name for GroupMessage.
func (GroupMessage) TableName() string {
	return "group_messages"
}

// BeforeCreate hook generates the message_id and sets timestamps.
func (gm *GroupMessage) BeforeCreate(tx *gorm.DB) error {
	if gm.MessageID == "" {
		gm.MessageID = generateMessageID()
	}
	now := time.Now().UnixMilli()
	gm.CreateAtMs = now
	gm.UpdateAtMs = now
	return nil
}

// BeforeUpdate hook sets update timestamp.
func (gm *GroupMessage) BeforeUpdate(tx *gorm.DB) error {
	gm.UpdateAtMs = time.Now().UnixMilli()
	return nil
}

// isDeleted returns true if the message has been soft-deleted.
func (gm *GroupMessage) isDeleted() bool {
	return gm.IsDeleted || gm.DeleteAtMs > 0
}

// IsFromAgent returns true if the message sender is an agent type.
func (gm *GroupMessage) IsFromAgent() bool {
	return gm.SenderType == MemberTypeManagerAgent || gm.SenderType == MemberTypeWorkerAgent
}

// generateMessageID returns a unique message identifier with format msg-{alphanumeric}.
func generateMessageID() string {
	return "msg-" + strings.ReplaceAll(uuid.New().String(), "-", "")
}
