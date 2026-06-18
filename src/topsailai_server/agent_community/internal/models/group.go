// Package models defines GORM database models for the ACS service.
package models

import (
	"strings"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"
)

// Group represents a community/session in the ACS system.
type Group struct {
	GroupID      string         `gorm:"column:group_id;type:varchar(64);primaryKey" json:"group_id"`
	GroupName    string         `gorm:"column:group_name;type:varchar(255);not null" json:"group_name"`
	GroupContext string         `gorm:"column:group_context;type:text" json:"group_context"`
	GroupKey     string         `gorm:"column:group_key;type:varchar(255);default:null" json:"group_key"`
	CreatorID    string         `gorm:"column:creator_id;type:varchar(64)" json:"creator_id"`
	OwnerID      string         `gorm:"column:owner_id;type:varchar(64)" json:"owner_id"`
	CreateAtMs   int64          `gorm:"column:create_at_ms;type:bigint;not null" json:"create_at_ms"`
	UpdateAtMs   int64          `gorm:"column:update_at_ms;type:bigint;not null" json:"update_at_ms"`
	DeletedAt    gorm.DeletedAt `gorm:"column:deleted_at;index" json:"-"`
}

// TableName specifies the table name for Group.
func (Group) TableName() string {
	return "groups"
}

// BeforeCreate hook sets create and update timestamps and generates a group ID if missing.
func (g *Group) BeforeCreate(tx *gorm.DB) error {
	if g.GroupID == "" {
		g.GroupID = GenerateGroupID()
	}
	now := time.Now().UnixMilli()
	g.CreateAtMs = now
	g.UpdateAtMs = now
	return nil
}

// BeforeUpdate hook sets update timestamp.
func (g *Group) BeforeUpdate(tx *gorm.DB) error {
	g.UpdateAtMs = time.Now().UnixMilli()
	return nil
}

// GenerateGroupID returns a unique group identifier with format group-{alphanumeric}.
func GenerateGroupID() string {
	return "group-" + strings.ReplaceAll(uuid.New().String(), "-", "")
}
