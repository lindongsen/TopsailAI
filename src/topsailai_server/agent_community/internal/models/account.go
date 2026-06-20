// Package models defines GORM database models for the ACS service.
package models

import (
	"strings"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"
)

// AccountRole represents the role of an account.
type AccountRole string

const (
	// AccountRoleAdmin has full permissions.
	AccountRoleAdmin AccountRole = "admin"
	// AccountRoleManager can create user accounts and manage user sessions.
	AccountRoleManager AccountRole = "manager"
	// AccountRoleUser can manage own resources.
	AccountRoleUser AccountRole = "user"
)

// AccountStatus represents the status of an account.
type AccountStatus string

const (
	// AccountStatusActive allows authentication and resource access.
	AccountStatusActive AccountStatus = "active"
	// AccountStatusInactive disables authentication.
	AccountStatusInactive AccountStatus = "inactive"
	// AccountStatusDeleted marks a soft-deleted account.
	AccountStatusDeleted AccountStatus = "deleted"
)

// Account represents a user account in the ACS system.
type Account struct {
	AccountID               string        `gorm:"column:account_id;type:varchar(64);primaryKey" json:"account_id"`
	AccountName             string        `gorm:"column:account_name;type:varchar(255);not null" json:"account_name"`
	AccountDescription      string        `gorm:"column:account_description;type:text" json:"account_description"`
	Role                    AccountRole   `gorm:"column:role;type:varchar(32);not null" json:"role"`
	Status                  AccountStatus `gorm:"column:status;type:varchar(32);not null;default:'active'" json:"status"`
	DeleteAtMs              int64         `gorm:"column:delete_at_ms;type:bigint;default:0" json:"delete_at_ms"`
	CreatorID               string        `gorm:"column:creator_id;type:varchar(64);not null" json:"creator_id"`
	ExternalID              string        `gorm:"column:external_id;type:varchar(255)" json:"external_id"`
	Email                   string        `gorm:"column:email;type:varchar(255)" json:"email"`
	AuthProvider            string        `gorm:"column:auth_provider;type:varchar(64)" json:"auth_provider"`
	AvatarURL               string        `gorm:"column:avatar_url;type:text" json:"avatar_url"`
	LoginName               string        `gorm:"column:login_name;type:varchar(255);not null;uniqueIndex:idx_accounts_login_name" json:"login_name"`
	LoginPassword           string        `gorm:"column:login_password;type:varchar(255)" json:"-"`
	LoginSessionKey         string        `gorm:"column:login_session_key;type:varchar(255)" json:"-"`
	LoginSessionExpiredTime int64         `gorm:"column:login_session_expired_time;type:bigint;default:0" json:"-"`
	CreateAtMs              int64         `gorm:"column:create_at_ms;type:bigint;not null" json:"create_at_ms"`
	UpdateAtMs              int64         `gorm:"column:update_at_ms;type:bigint;not null" json:"update_at_ms"`
}

// TableName specifies the table name for Account.
func (Account) TableName() string {
	return "accounts"
}

// BeforeCreate hook generates the account_id and timestamps.
func (a *Account) BeforeCreate(tx *gorm.DB) error {
	now := time.Now().UnixMilli()
	if a.AccountID == "" {
		a.AccountID = generateAccountID()
	}
	a.CreateAtMs = now
	a.UpdateAtMs = now
	return nil
}

// BeforeUpdate hook sets the update timestamp.
func (a *Account) BeforeUpdate(tx *gorm.DB) error {
	a.UpdateAtMs = time.Now().UnixMilli()
	return nil
}

// IsActive returns true when the account can authenticate.
func (a *Account) IsActive() bool {
	return a.Status == AccountStatusActive
}

// IsDeleted returns true when the account has been soft-deleted.
func (a *Account) IsDeleted() bool {
	return a.Status == AccountStatusDeleted || a.DeleteAtMs > 0
}

// ValidRole returns true if the account role is one of the supported values.
func (a *Account) ValidRole() bool {
	switch a.Role {
	case AccountRoleAdmin, AccountRoleManager, AccountRoleUser:
		return true
	default:
		return false
	}
}

// RoleRank returns the numeric rank of the account role for hierarchy comparisons.
// Admin > Manager > User. Unknown roles return 0.
func (a *Account) RoleRank() int {
	switch a.Role {
	case AccountRoleAdmin:
		return 3
	case AccountRoleManager:
		return 2
	case AccountRoleUser:
		return 1
	default:
		return 0
	}
}

// generateAccountID returns a unique account identifier with format acc-{alphanumeric}.
func generateAccountID() string {
	return "acc-" + strings.ReplaceAll(uuid.New().String(), "-", "")
}
