// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"testing"

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
