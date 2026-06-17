// Package models defines GORM database models for the ACS service.
package models

import (
	"strings"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"
)

// APIKeyRole represents the role granted to an API key.
type APIKeyRole string

const (
	// APIKeyRoleAdmin grants administrative access.
	APIKeyRoleAdmin APIKeyRole = "admin"
	// APIKeyRoleManager grants manager access.
	APIKeyRoleManager APIKeyRole = "manager"
	// APIKeyRoleUser grants user access.
	APIKeyRoleUser APIKeyRole = "user"
)

// APIKeyStatus represents the status of an API key.
type APIKeyStatus string

const (
	// APIKeyStatusActive allows the key to authenticate requests.
	APIKeyStatusActive APIKeyStatus = "active"
	// APIKeyStatusInactive disables the key.
	APIKeyStatusInactive APIKeyStatus = "inactive"
)

// APIKey represents an authorization token for an account.
type APIKey struct {
	APIKeyID   string       `gorm:"column:api_key_id;type:varchar(64);primaryKey" json:"api_key_id"`
	APIKeyName string       `gorm:"column:api_key_name;type:varchar(255);not null" json:"api_key_name"`
	APIKeyHash string       `gorm:"column:api_key_hash;type:varchar(255);not null" json:"-"`
	Role       APIKeyRole   `gorm:"column:role;type:varchar(32);not null" json:"role"`
	Status     APIKeyStatus `gorm:"column:status;type:varchar(32);not null;default:'active'" json:"status"`
	CreatorID  string       `gorm:"column:creator_id;type:varchar(64);not null" json:"creator_id"`
	OwnerID    string       `gorm:"column:owner_id;type:varchar(64);not null;index:idx_api_keys_owner_id" json:"owner_id"`
	CreateAtMs int64        `gorm:"column:create_at_ms;type:bigint;not null" json:"create_at_ms"`
	UpdateAtMs int64        `gorm:"column:update_at_ms;type:bigint;not null" json:"update_at_ms"`
}

// TableName specifies the table name for APIKey.
func (APIKey) TableName() string {
	return "api_keys"
}

// BeforeCreate hook generates the api_key_id and timestamps.
func (k *APIKey) BeforeCreate(tx *gorm.DB) error {
	now := time.Now().UnixMilli()
	k.APIKeyID = generateAPIKeyID()
	k.CreateAtMs = now
	k.UpdateAtMs = now
	return nil
}

// BeforeUpdate hook sets the update timestamp.
func (k *APIKey) BeforeUpdate(tx *gorm.DB) error {
	k.UpdateAtMs = time.Now().UnixMilli()
	return nil
}

// IsActive returns true when the API key can authenticate requests.
func (k *APIKey) IsActive() bool {
	return k.Status == APIKeyStatusActive
}

// generateAPIKeyID returns a unique API key identifier with format ak-{alphanumeric}.
func generateAPIKeyID() string {
	return "ak-" + strings.ReplaceAll(uuid.New().String(), "-", "")
}
