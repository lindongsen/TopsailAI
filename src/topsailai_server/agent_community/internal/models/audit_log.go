// Package models defines GORM database models for the ACS service.
package models

import (
	"strings"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"
)

// AuditLog records security and lifecycle events in the ACS system.
type AuditLog struct {
	AuditLogID   string `gorm:"column:audit_log_id;type:varchar(64);primaryKey" json:"audit_log_id"`
	AccountID    string `gorm:"column:account_id;type:varchar(64);not null;index:idx_audit_logs_account_id" json:"account_id"`
	APIKeyID     string `gorm:"column:api_key_id;type:varchar(64);not null;index:idx_audit_logs_api_key_id" json:"api_key_id"`
	Action       string `gorm:"column:action;type:varchar(255);not null" json:"action"`
	ResourceType string `gorm:"column:resource_type;type:varchar(255);not null" json:"resource_type"`
	ResourceID   string `gorm:"column:resource_id;type:varchar(255);not null" json:"resource_id"`
	ResourceName string `gorm:"column:resource_name;type:varchar(255)" json:"resource_name"`
	Detail       string `gorm:"column:detail;type:text" json:"detail"`
	ClientIP     string `gorm:"column:client_ip;type:varchar(64)" json:"client_ip"`
	CreateAtMs   int64  `gorm:"column:create_at_ms;type:bigint;not null;index:idx_audit_logs_create_at_ms" json:"create_at_ms"`
}

// TableName specifies the table name for AuditLog.
func (AuditLog) TableName() string {
	return "audit_logs"
}

// BeforeCreate hook generates the audit_log_id and timestamp.
func (al *AuditLog) BeforeCreate(tx *gorm.DB) error {
	if al.AuditLogID == "" {
		al.AuditLogID = generateAuditLogID()
	}
	if al.CreateAtMs == 0 {
		al.CreateAtMs = time.Now().UnixMilli()
	}
	return nil
}

// generateAuditLogID returns a unique audit log identifier with format al-{id}.
func generateAuditLogID() string {
	return "al-" + strings.ReplaceAll(uuid.New().String(), "-", "")
}
