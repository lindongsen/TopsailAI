// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/models"
)

func TestAPIKeyService_CreateAPIKey_Success(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Key Owner",
		LoginName:   "keyowner",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "my-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	require.NoError(t, err)
	assert.NotEmpty(t, key.APIKey.APIKeyID)
	assert.Contains(t, key.Token, key.APIKey.APIKeyID)
	assert.Equal(t, models.APIKeyRoleUser, key.APIKey.Role)
}

func TestAPIKeyService_VerifyAPIKey_SuccessAndFailure(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Verifier",
		LoginName:   "verifier",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "verify-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	require.NoError(t, err)

	verifiedKey, verifiedOwner, err := apiKeySvc.VerifyAPIKey(ctx, key.Token)
	require.NoError(t, err)
	assert.Equal(t, key.APIKey.APIKeyID, verifiedKey.APIKeyID)
	assert.Equal(t, owner.AccountID, verifiedOwner.AccountID)

	_, _, err = apiKeySvc.VerifyAPIKey(ctx, "bad-token")
	assert.ErrorIs(t, err, ErrAPIKeyInvalidToken)

	_, _, err = apiKeySvc.VerifyAPIKey(ctx, key.APIKey.APIKeyID+".wrongsecret")
	assert.ErrorIs(t, err, ErrAPIKeyInvalidToken)
}

func TestAPIKeyService_PerOwnerLimit(t *testing.T) {
	db, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Limited",
		LoginName:   "limited",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	cfg := newTestConfig()
	cfg.Account.APIKeyMaxPerAccount = 2
	limitedKeySvc := NewAPIKeyService(db, cfg, nil)

	for i := 0; i < 2; i++ {
		_, err := limitedKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
			APIKeyName: "key",
			Role:       models.APIKeyRoleUser,
			OwnerID:    owner.AccountID,
			CreatorID:  owner.AccountID,
		})
		require.NoError(t, err)
	}

	_, err = limitedKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "overflow",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	assert.ErrorIs(t, err, ErrAPIKeyLimitReached)
}

func TestAPIKeyService_RoleConstraint(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	user, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "User",
		LoginName:   "useronly",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	_, err = apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "admin-key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    user.AccountID,
		CreatorID:  user.AccountID,
	})
	assert.ErrorIs(t, err, ErrAPIKeyRoleTooHigh)

	admin, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Admin",
		LoginName:   "adminuser",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	_, err = apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "admin-key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    admin.AccountID,
		CreatorID:  admin.AccountID,
	})
	require.NoError(t, err)
}

func TestAPIKeyService_ManagerAccountCanReceiveKey(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	manager, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Manager",
		LoginName:   "manageruser",
		Role:        models.AccountRoleManager,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	// Admin should be able to create a manager-role key for a manager account.
	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "manager-key",
		Role:       models.APIKeyRoleManager,
		OwnerID:    manager.AccountID,
		CreatorID:  "system-admin",
	})
	require.NoError(t, err)
	assert.Equal(t, models.APIKeyRoleManager, key.APIKey.Role)
	assert.Equal(t, manager.AccountID, key.APIKey.OwnerID)

	// Admin cannot create an admin-role key for a manager account (role too high).
	_, err = apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "admin-key-for-manager",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    manager.AccountID,
		CreatorID:  "system-admin",
	})
	assert.ErrorIs(t, err, ErrAPIKeyRoleTooHigh)
}
