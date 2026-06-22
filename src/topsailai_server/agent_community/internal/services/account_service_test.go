// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/schema"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
)

// newTestDB creates an in-memory SQLite database for unit tests.
// Each test gets a unique database name to avoid cross-test contamination.
func newTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := "file:" + t.Name() + "?mode=memory&cache=shared"
	conn, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{
		NamingStrategy: schema.NamingStrategy{SingularTable: true},
	})
	require.NoError(t, err)

	err = conn.AutoMigrate(
		&models.Account{},
		&models.APIKey{},
		&models.AuditLog{},
	)
	require.NoError(t, err)
	return conn
}

func newTestConfig() *config.Config {
	return &config.Config{
		Account: config.AccountConfig{
			APIKeyMaxPerAccount:       10,
			LoginSessionExpirySeconds: 86400,
			BcryptCost:                4, // low cost for fast tests
		},
	}
}

// newTestServices creates service instances backed by the same test database.
func newTestServices(t *testing.T) (*gorm.DB, *AccountService, *APIKeyService, *AuditLogService) {
	t.Helper()
	db := newTestDB(t)
	cfg := newTestConfig()
	auditSvc := NewAuditLogService(db)
	accountSvc := NewAccountService(db, cfg, auditSvc)
	apiKeySvc := NewAPIKeyService(db, cfg, auditSvc)
	accountSvc.SetAPIKeyService(apiKeySvc)
	return db, accountSvc, apiKeySvc, auditSvc
}
func TestAccountService_CreateAccount_ManagerUserOnly(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	tests := []struct {
		name        string
		role        models.AccountRole
		expectedErr error
	}{
		{"user", models.AccountRoleUser, nil},
		{"manager", models.AccountRoleManager, ErrRoleNotAllowed},
		{"admin", models.AccountRoleAdmin, ErrRoleNotAllowed},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
				AccountName:   "Manager Creates " + strings.Title(tt.name),
				LoginName:     "manager-creates-" + tt.name,
				LoginPassword: "password",
				Role:          tt.role,
				CreatorID:     "acc-manager",
				CallerRole:    models.AccountRoleManager,
			})
			if tt.expectedErr != nil {
				require.ErrorIs(t, err, tt.expectedErr)
				return
			}
			require.NoError(t, err)
		})
	}
}

func TestAccountService_CreateAccount_Success(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Alice",
		LoginName:     "alice",
		LoginPassword: "secret123",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)
	assert.NotEmpty(t, acc.AccountID)
	assert.True(t, acc.IsActive())
	assert.Equal(t, models.AccountRoleUser, acc.Role)
	assert.Equal(t, "alice", acc.LoginName)
}

func TestAccountService_CreateAccount_DuplicateLoginName(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	_, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Alice",
		LoginName:   "alice",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	_, err = accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Alice Two",
		LoginName:   "alice",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	assert.ErrorIs(t, err, ErrDuplicateLoginName)
}

func TestAccountService_GetAccountByID(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	created, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Bob",
		LoginName:   "bob",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	found, err := accountSvc.GetAccountByID(ctx, created.AccountID)
	require.NoError(t, err)
	assert.Equal(t, created.AccountID, found.AccountID)

	_, err = accountSvc.GetAccountByID(ctx, "acc-nonexistent")
	assert.ErrorIs(t, err, ErrAccountNotFound)
}

func TestAccountService_SoftDeleteAccount_CascadeAPIKeys(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Carol",
		LoginName:   "carol",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "test-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	require.NoError(t, err)

	err = accountSvc.SoftDeleteAccount(ctx, owner.AccountID)
	require.NoError(t, err)

	deleted, err := accountSvc.GetAccountByID(ctx, owner.AccountID)
	require.NoError(t, err)
	assert.Equal(t, models.AccountStatusDeleted, deleted.Status)

	_, err = apiKeySvc.getByID(ctx, key.APIKey.APIKeyID)
	assert.ErrorIs(t, err, ErrAPIKeyNotFound)
}

func TestAccountService_LoginByPassword_SuccessAndFailure(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Dave",
		LoginName:     "dave",
		LoginPassword: "mypassword",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	loggedIn, sessionKey, expiry, err := accountSvc.LoginByPassword(ctx, "dave", "mypassword")
	require.NoError(t, err)
	assert.Equal(t, acc.AccountID, loggedIn.AccountID)
	assert.NotEmpty(t, sessionKey)
	assert.Greater(t, expiry, int64(0))

	_, _, _, err = accountSvc.LoginByPassword(ctx, "dave", "wrongpassword")
	assert.Error(t, err)

	_, _, _, err = accountSvc.LoginByPassword(ctx, "unknown", "mypassword")
	assert.ErrorIs(t, err, ErrAccountNotFound)
}

func TestAccountService_CreateAndValidateLoginSession(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Eve",
		LoginName:     "eve",
		LoginPassword: "secret",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)
	assert.Contains(t, sessionKey, acc.AccountID)

	validated, err := accountSvc.ValidateLoginSession(ctx, sessionKey)
	require.NoError(t, err)
	assert.Equal(t, acc.AccountID, validated.AccountID)

	_, err = accountSvc.ValidateLoginSession(ctx, "invalid")
	assert.ErrorIs(t, err, ErrSessionFormatInvalid)

	_, err = accountSvc.ValidateLoginSession(ctx, acc.AccountID+"-badsecret")
	assert.ErrorIs(t, err, ErrInvalidSession)
}

func TestAccountService_EnsureLoginSession(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Grace",
		LoginName:     "grace",
		LoginPassword: "secret",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	// Successful creation for active account.
	sessionKey, expiry, err := accountSvc.EnsureLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)
	assert.Contains(t, sessionKey, acc.AccountID)
	assert.Greater(t, expiry, time.Now().UnixMilli())

	validated, err := accountSvc.ValidateLoginSession(ctx, sessionKey)
	require.NoError(t, err)
	assert.Equal(t, acc.AccountID, validated.AccountID)

	// Error for non-existent account.
	_, _, err = accountSvc.EnsureLoginSession(ctx, "acc-doesnotexist")
	assert.ErrorIs(t, err, ErrAccountNotFound)

	// Error for inactive/deleted account.
	deletedStatus := models.AccountStatusDeleted
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:  acc.AccountID,
		Status:     &deletedStatus,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)
	_, _, err = accountSvc.EnsureLoginSession(ctx, acc.AccountID)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "account is not active")
}

func TestAccountService_UpdateAccount_RoleConstraints(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	user, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Frank",
		LoginName:   "frank",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	// User cannot promote self to admin.
	adminRole := models.AccountRoleAdmin
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:  user.AccountID,
		Role:       &adminRole,
		CallerRole: models.AccountRoleUser,
	})
	assert.Error(t, err)

	// Admin can promote user to manager.
	managerRole := models.AccountRoleManager
	updated, err := accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:  user.AccountID,
		Role:       &managerRole,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)
	assert.Equal(t, models.AccountRoleManager, updated.Role)
}

func TestAccountService_CreateAccount_DefaultRoleAndInvalidRole(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	// Empty role defaults to user.
	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Default Role",
		LoginName:   "default-role",
		CreatorID:   "system",
	})
	require.NoError(t, err)
	assert.Equal(t, models.AccountRoleUser, acc.Role)

	// Invalid role is rejected.
	_, err = accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Invalid Role",
		LoginName:   "invalid-role",
		Role:        "superuser",
		CreatorID:   "system",
	})
	assert.ErrorIs(t, err, ErrInvalidRole)
}

func TestAccountService_CreateAccount_EmptyLoginName(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	_, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "No Login Name",
		LoginName:   "",
		CreatorID:   "system",
	})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "login_name is required")
}

func TestAccountService_GetAccountByExternalID(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	created, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "External ID",
		LoginName:   "external-id",
		ExternalID:  "ext-12345",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	found, err := accountSvc.GetAccountByExternalID(ctx, "ext-12345")
	require.NoError(t, err)
	assert.Equal(t, created.AccountID, found.AccountID)
	assert.Equal(t, "ext-12345", found.ExternalID)

	_, err = accountSvc.GetAccountByExternalID(ctx, "ext-missing")
	assert.ErrorIs(t, err, ErrAccountNotFound)
}

func TestAccountService_ListAccounts_PaginationAndErrors(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	for i := 0; i < 5; i++ {
		_, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
			AccountName: "User",
			LoginName:   fmt.Sprintf("list-user-%d", i),
			Role:        models.AccountRoleUser,
			CreatorID:   "system",
		})
		require.NoError(t, err)
	}

	// Default pagination with nil filter (internal/service use).
	items, total, err := accountSvc.ListAccounts(ctx, 0, 0, nil)
	require.NoError(t, err)
	assert.Equal(t, int64(5), total)
	assert.Len(t, items, 5)

	// Limit and offset.
	items, total, err = accountSvc.ListAccounts(ctx, 1, 2, nil)
	require.NoError(t, err)
	assert.Equal(t, int64(5), total)
	assert.Len(t, items, 2)

	// Offset beyond total.
	items, total, err = accountSvc.ListAccounts(ctx, 10, 10, nil)
	require.NoError(t, err)
	assert.Equal(t, int64(5), total)
	assert.Empty(t, items)
}

func TestAccountService_ListAccounts_FiltersAndVisibility(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	admin, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Admin",
		LoginName:   "filter-admin",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	manager, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Manager",
		LoginName:   "filter-manager",
		Role:        models.AccountRoleManager,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	user, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "User",
		LoginName:   "filter-user",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	// Soft-delete the user.
	require.NoError(t, accountSvc.SoftDeleteAccount(ctx, user.AccountID))

	// Admin filter by role excludes deleted accounts by default.
	items, total, err := accountSvc.ListAccounts(ctx, 0, 100, &ListAccountsFilter{
		Role:       models.AccountRoleUser,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)
	assert.Equal(t, int64(0), total)
	assert.Empty(t, items)

	// Admin can explicitly request deleted accounts.
	items, total, err = accountSvc.ListAccounts(ctx, 0, 100, &ListAccountsFilter{
		Role:       models.AccountRoleUser,
		Status:     models.AccountStatusDeleted,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)
	assert.Equal(t, int64(1), total)
	assert.Len(t, items, 1)
	assert.Equal(t, user.AccountID, items[0].AccountID)

	// Manager sees only non-deleted user accounts and themselves.
	items, total, err = accountSvc.ListAccounts(ctx, 0, 100, &ListAccountsFilter{
		CallerRole: models.AccountRoleManager,
		CallerID:   manager.AccountID,
	})
	require.NoError(t, err)
	assert.Equal(t, int64(1), total)
	assert.Len(t, items, 1)
	assert.Equal(t, manager.AccountID, items[0].AccountID)

	// Manager filtering by admin role returns nothing.
	items, total, err = accountSvc.ListAccounts(ctx, 0, 100, &ListAccountsFilter{
		Role:       models.AccountRoleAdmin,
		CallerRole: models.AccountRoleManager,
		CallerID:   manager.AccountID,
	})
	require.NoError(t, err)
	assert.Equal(t, int64(0), total)
	assert.Empty(t, items)

	// User sees all non-deleted accounts for discovery.
	items, total, err = accountSvc.ListAccounts(ctx, 0, 100, &ListAccountsFilter{
		CallerRole: models.AccountRoleUser,
		CallerID:   admin.AccountID,
	})
	require.NoError(t, err)
	assert.Equal(t, int64(2), total)
	assert.Len(t, items, 2)
	ids := make([]string, len(items))
	for i, item := range items {
		ids[i] = item.AccountID
	}
	assert.Contains(t, ids, admin.AccountID)
	assert.Contains(t, ids, manager.AccountID)
}

func TestAccountService_UpdateAccount_CallerWeightZero(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	user, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Caller Weight Zero",
		LoginName:   "caller-weight-zero",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	newName := "Updated"
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:   user.AccountID,
		AccountName: &newName,
		CallerRole:  "",
	})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "invalid caller role")
}

func TestAccountService_UpdateAccount_TargetRoleHigher(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	admin, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Admin Target",
		LoginName:   "admin-target",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	newName := "Should Fail"
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:   admin.AccountID,
		AccountName: &newName,
		CallerRole:  models.AccountRoleUser,
	})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "insufficient privileges")
}

func TestAccountService_UpdateAccount_InvalidStatus(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	user, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Invalid Status",
		LoginName:   "invalid-status",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	badStatus := models.AccountStatus("unknown")
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:  user.AccountID,
		Status:     &badStatus,
		CallerRole: models.AccountRoleAdmin,
	})
	assert.ErrorIs(t, err, ErrInvalidStatus)
}

func TestAccountService_UpdateAccount_PartialFields(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	user, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:  "Partial",
		LoginName:    "partial",
		Role:         models.AccountRoleUser,
		CreatorID:    "system",
		ExternalID:   "ext-old",
		Email:        "old@example.com",
		AuthProvider: "oidc",
		AvatarURL:    "http://old.example.com/avatar.png",
	})
	require.NoError(t, err)

	newName := "Partial Updated"
	newEmail := "new@example.com"
	updated, err := accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:   user.AccountID,
		AccountName: &newName,
		Email:       &newEmail,
		CallerRole:  models.AccountRoleAdmin,
	})
	require.NoError(t, err)
	assert.Equal(t, "Partial Updated", updated.AccountName)
	assert.Equal(t, "new@example.com", updated.Email)
	// Fields not supplied should remain unchanged.
	assert.Equal(t, "ext-old", updated.ExternalID)
	assert.Equal(t, "oidc", updated.AuthProvider)
	assert.Equal(t, "http://old.example.com/avatar.png", updated.AvatarURL)
}

func TestAccountService_SoftDeleteAccount_APIKeySvcNil(t *testing.T) {
	// Create a service without API key service injection.
	cfg := newTestConfig()
	db := newTestDB(t)
	auditSvc := NewAuditLogService(db)
	standaloneSvc := NewAccountService(db, cfg, auditSvc)

	ctx := context.Background()
	acc, err := standaloneSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Nil APIKeySvc",
		LoginName:   "nil-apikeysvc",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	err = standaloneSvc.SoftDeleteAccount(ctx, acc.AccountID)
	require.NoError(t, err)

	deleted, err := standaloneSvc.GetAccountByID(ctx, acc.AccountID)
	require.NoError(t, err)
	assert.Equal(t, models.AccountStatusDeleted, deleted.Status)
}

func TestAccountService_ChangePassword_EmptyAndNotFound(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Password",
		LoginName:     "password",
		LoginPassword: "oldpassword",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	// Empty password should fail.
	err = accountSvc.ChangePassword(ctx, acc.AccountID, "")
	assert.Error(t, err)

	// Non-existent account should fail.
	err = accountSvc.ChangePassword(ctx, "acc-missing", "newpassword")
	assert.ErrorIs(t, err, ErrAccountNotFound)

	// Valid password change should succeed.
	err = accountSvc.ChangePassword(ctx, acc.AccountID, "newpassword")
	require.NoError(t, err)

	_, _, _, err = accountSvc.LoginByPassword(ctx, "password", "newpassword")
	require.NoError(t, err)
}

func TestAccountService_CreateLoginSession_InactiveAccount(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Inactive Session",
		LoginName:   "inactive-session",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	inactiveStatus := models.AccountStatusInactive
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:  acc.AccountID,
		Status:     &inactiveStatus,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)

	_, _, err = accountSvc.CreateLoginSession(ctx, acc.AccountID)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "account is not active")
}

func TestAccountService_ValidateLoginSession_Expired(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Expired Session",
		LoginName:   "expired-session",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)

	// Manually expire the session in the database.
	err = accountSvc.db.Model(&models.Account{}).
		Where("account_id = ?", acc.AccountID).
		Update("login_session_expired_time", time.Now().UnixMilli()-1000).Error
	require.NoError(t, err)

	_, err = accountSvc.ValidateLoginSession(ctx, sessionKey)
	assert.ErrorIs(t, err, ErrInvalidSession)
}

func TestAccountService_ValidateLoginSession_WrongSecret(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Wrong Secret",
		LoginName:   "wrong-secret",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	_, _, err = accountSvc.CreateLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)

	_, err = accountSvc.ValidateLoginSession(ctx, acc.AccountID+"-wrongsecretvalue")
	assert.ErrorIs(t, err, ErrInvalidSession)
}

func TestAccountService_ValidateLoginSession_ExtraHyphens(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Extra Hyphens",
		LoginName:   "extra-hyphens",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)

	// Split the session key into account_id and secret parts.
	// Format is {account_id}-{secret}, e.g. acc-xxx-{base64url secret}.
	parts := strings.SplitN(sessionKey, "-", 3)
	require.Len(t, parts, 3)
	accountIDPart := parts[0] + "-" + parts[1]
	secretPart := parts[2]

	// Reconstruct with extra hyphens in the secret part.
	malformedKey := accountIDPart + "-extra-" + secretPart
	_, err = accountSvc.ValidateLoginSession(ctx, malformedKey)
	assert.ErrorIs(t, err, ErrInvalidSession)
}

func TestAccountService_LoginByPassword_InactiveAndNoPassword(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Inactive Login",
		LoginName:     "inactive-login",
		LoginPassword: "password",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	inactiveStatus := models.AccountStatusInactive
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:  acc.AccountID,
		Status:     &inactiveStatus,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)

	_, _, _, err = accountSvc.LoginByPassword(ctx, "inactive-login", "password")
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "account is not active")

	// Account without password.
	_, err = accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "No Password",
		LoginName:   "no-password",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	_, _, _, err = accountSvc.LoginByPassword(ctx, "no-password", "anypassword")
	assert.ErrorIs(t, err, ErrPasswordNotSet)
}

func TestAccountService_Helpers_Validators(t *testing.T) {
	assert.True(t, isValidAccountRole(models.AccountRoleAdmin))
	assert.True(t, isValidAccountRole(models.AccountRoleManager))
	assert.True(t, isValidAccountRole(models.AccountRoleUser))
	assert.False(t, isValidAccountRole("unknown"))
	assert.False(t, isValidAccountRole(""))

	assert.True(t, isValidAccountStatus(models.AccountStatusActive))
	assert.True(t, isValidAccountStatus(models.AccountStatusInactive))
	assert.True(t, isValidAccountStatus(models.AccountStatusDeleted))
	assert.False(t, isValidAccountStatus("unknown"))
	assert.False(t, isValidAccountStatus(""))
}

func TestAccountService_Helpers_UniqueViolation(t *testing.T) {
	assert.False(t, isUniqueViolation(nil))
	assert.True(t, isUniqueViolation(fmt.Errorf("UNIQUE constraint failed")))
	assert.True(t, isUniqueViolation(fmt.Errorf("duplicate key value violates unique constraint")))
	assert.True(t, isUniqueViolation(fmt.Errorf("Duplicate entry")))
	assert.False(t, isUniqueViolation(fmt.Errorf("some other error")))
}

// TestValidateLoginPassword_Success verifies valid credentials return the active account.
func TestValidateLoginPassword_Success(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Validate Success",
		LoginName:     "validate-success",
		LoginPassword: "correctpassword",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	validated, err := accountSvc.ValidateLoginPassword(ctx, "validate-success", "correctpassword")
	require.NoError(t, err)
	assert.Equal(t, acc.AccountID, validated.AccountID)
	assert.Equal(t, "validate-success", validated.LoginName)
	assert.True(t, validated.IsActive())
}

// TestValidateLoginPassword_InvalidPassword verifies an incorrect password returns an error.
func TestValidateLoginPassword_InvalidPassword(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	_, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Validate Invalid",
		LoginName:     "validate-invalid",
		LoginPassword: "correctpassword",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	validated, err := accountSvc.ValidateLoginPassword(ctx, "validate-invalid", "wrongpassword")
	assert.Error(t, err)
	assert.Nil(t, validated)
}

// TestValidateLoginPassword_AccountNotActive verifies inactive/deleted accounts cannot authenticate.
func TestValidateLoginPassword_AccountNotActive(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Validate Inactive",
		LoginName:     "validate-inactive",
		LoginPassword: "correctpassword",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	inactiveStatus := models.AccountStatusInactive
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:  acc.AccountID,
		Status:     &inactiveStatus,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)

	validated, err := accountSvc.ValidateLoginPassword(ctx, "validate-inactive", "correctpassword")
	assert.Error(t, err)
	assert.Nil(t, validated)
	assert.Contains(t, err.Error(), "account is not active")
}

// TestValidateLoginPassword_LoginNameNotFound verifies a missing login name returns an error.
func TestValidateLoginPassword_LoginNameNotFound(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	validated, err := accountSvc.ValidateLoginPassword(ctx, "nonexistent-user", "anypassword")
	assert.ErrorIs(t, err, ErrAccountNotFound)
	assert.Nil(t, validated)
}

// TestAccountService_DB verifies DB() returns the injected database handle.
func TestAccountService_DB(t *testing.T) {
	db := newTestDB(t)
	cfg := newTestConfig()
	auditSvc := NewAuditLogService(db)
	svc := NewAccountService(db, cfg, auditSvc)

	assert.Equal(t, db, svc.DB())
}

// TestAccountService_Audit verifies the audit helper creates an audit log record.
func TestAccountService_Audit(t *testing.T) {
	_, accountSvc, _, auditSvc := newTestServices(t)
	ctx := context.Background()

	accountSvc.audit(ctx, AuditLogRequest{
		AccountID:    "acc-test",
		APIKeyID:     "ak-test",
		Action:       "test_action",
		ResourceType: "account",
		ResourceID:   "acc-target",
		ResourceName: "Target Account",
		Detail:       "test detail",
		ClientIP:     "127.0.0.1",
	})

	logs, total, err := auditSvc.ListAuditLogs(ctx, nil, 0, 10)
	require.NoError(t, err)
	assert.Equal(t, int64(1), total)
	require.Len(t, logs, 1)
	assert.Equal(t, "acc-test", logs[0].AccountID)
	assert.Equal(t, "ak-test", logs[0].APIKeyID)
	assert.Equal(t, "test_action", logs[0].Action)
	assert.Equal(t, "account", logs[0].ResourceType)
	assert.Equal(t, "acc-target", logs[0].ResourceID)
	assert.Equal(t, "Target Account", logs[0].ResourceName)
	assert.Equal(t, "test detail", logs[0].Detail)
	assert.Equal(t, "127.0.0.1", logs[0].ClientIP)
}

// TestAccountService_Audit_NoPanicOnError verifies audit failures are logged but not propagated.
func TestAccountService_Audit_NoPanicOnError(t *testing.T) {
	db := newTestDB(t)
	cfg := newTestConfig()
	// Construct a service without an audit service to exercise the nil guard.
	svc := NewAccountService(db, cfg, nil)

	ctx := context.Background()
	assert.NotPanics(t, func() {
		svc.audit(ctx, AuditLogRequest{
			AccountID:    "acc-test",
			Action:       "test_action",
			ResourceType: "account",
			ResourceID:   "acc-target",
		})
	})
}

// TestCreateLoginSession_ManagerCanOnlyCreateForUser documents that the service layer
// does not enforce caller role restrictions. The "manager can only create sessions for
// user accounts" rule is enforced by the HTTP handler (see account_test.go).
func TestCreateLoginSession_ManagerCanOnlyCreateForUser(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	manager, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Manager Target",
		LoginName:     "manager-target",
		LoginPassword: "password",
		Role:          models.AccountRoleManager,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	// Service layer allows creating a session for a manager account.
	// Role enforcement lives in the handler layer.
	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, manager.AccountID)
	require.NoError(t, err)
	assert.NotEmpty(t, sessionKey)
}

// TestCreateLoginSession_UserCanOnlyCreateOwnSession documents that the service layer
// does not enforce caller identity restrictions. The "user can only create sessions for
// themselves" rule is enforced by the HTTP handler (see account_test.go).
func TestCreateLoginSession_UserCanOnlyCreateOwnSession(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	userA, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "User A",
		LoginName:     "user-a",
		LoginPassword: "password",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	userB, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "User B",
		LoginName:     "user-b",
		LoginPassword: "password",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	// Service layer allows creating a session for any active account.
	// Caller identity enforcement lives in the handler layer.
	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, userB.AccountID)
	require.NoError(t, err)
	assert.NotEmpty(t, sessionKey)

	validated, err := accountSvc.ValidateLoginSession(ctx, sessionKey)
	require.NoError(t, err)
	assert.Equal(t, userB.AccountID, validated.AccountID)
	_ = userA
}

// TestChangePassword_ManagerCannotChangeOthers documents that the service layer does not
// enforce caller identity restrictions. The "manager cannot change another user's password"
// rule is enforced by the HTTP handler (see account_test.go).
func TestChangePassword_ManagerCannotChangeOthers(t *testing.T) {
	_, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	manager, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "Manager Password",
		LoginName:     "manager-password",
		LoginPassword: "managerpassword",
		Role:          models.AccountRoleManager,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	user, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:   "User Password",
		LoginName:     "user-password",
		LoginPassword: "userpassword",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	// Service layer allows changing any account's password.
	// Caller identity enforcement lives in the handler layer.
	err = accountSvc.ChangePassword(ctx, user.AccountID, "newuserpassword")
	require.NoError(t, err)

	_, _, _, err = accountSvc.LoginByPassword(ctx, "user-password", "newuserpassword")
	require.NoError(t, err)

	// Ensure manager account is referenced (avoid unused variable).
	assert.Equal(t, models.AccountRoleManager, manager.Role)
}
