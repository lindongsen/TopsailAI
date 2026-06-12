// Package models defines GORM database models for the ACS service.
package models

import (
	"time"

	"gorm.io/gorm"
)

// MemberStatus represents the status of a group member.
type MemberStatus string

const (
	MemberStatusOnline     MemberStatus = "online"
	MemberStatusOffline    MemberStatus = "offline"
	MemberStatusIdle       MemberStatus = "idle"
	MemberStatusProcessing MemberStatus = "processing"
)

// MemberType represents the type of a group member.
type MemberType string

const (
	MemberTypeUser        MemberType = "user"
	MemberTypeManagerAgent MemberType = "manager-agent"
	MemberTypeWorkerAgent  MemberType = "worker-agent"
)

// GroupMember represents a member in a group.
type GroupMember struct {
	GroupID            string       `gorm:"column:group_id;type:varchar(64);primaryKey" json:"group_id"`
	MemberID           string       `gorm:"column:member_id;type:varchar(64);primaryKey" json:"member_id"`
	MemberName         string       `gorm:"column:member_name;type:varchar(255);not null" json:"member_name"`
	MemberDescription  string       `gorm:"column:member_description;type:text" json:"member_description"`
	MemberStatus       MemberStatus `gorm:"column:member_status;type:varchar(32);not null;default:'offline'" json:"member_status"`
	MemberType         MemberType   `gorm:"column:member_type;type:varchar(32);not null" json:"member_type"`
	MemberInterface    string       `gorm:"column:member_interface;type:text" json:"member_interface"`
	LastReadMessageID  string       `gorm:"column:last_read_message_id;type:varchar(64);default:''" json:"last_read_message_id"`
	CreateAtMs         int64        `gorm:"column:create_at_ms;type:bigint;not null" json:"create_at_ms"`
	UpdateAtMs         int64        `gorm:"column:update_at_ms;type:bigint;not null" json:"update_at_ms"`
	DeletedAt          gorm.DeletedAt `gorm:"column:deleted_at;index" json:"-"`
}

// TableName specifies the table name for GroupMember.
func (GroupMember) TableName() string {
	return "group_member"
}

// BeforeCreate hook sets create and update timestamps.
func (gm *GroupMember) BeforeCreate(tx *gorm.DB) error {
	now := time.Now().UnixMilli()
	gm.CreateAtMs = now
	gm.UpdateAtMs = now
	return nil
}

// BeforeUpdate hook sets update timestamp.
func (gm *GroupMember) BeforeUpdate(tx *gorm.DB) error {
	gm.UpdateAtMs = time.Now().UnixMilli()
	return nil
}

// IsAgent returns true if the member is an agent type.
func (gm *GroupMember) IsAgent() bool {
	return gm.MemberType == MemberTypeManagerAgent || gm.MemberType == MemberTypeWorkerAgent
}
