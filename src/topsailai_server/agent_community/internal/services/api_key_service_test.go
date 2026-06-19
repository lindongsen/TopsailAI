// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"fmt"
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

func TestAPIKeyService_CreateAPIKey_EmptyOwnerID(t *testing.T) {
	_, _, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	_, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "no-owner",
		Role:       models.APIKeyRoleUser,
		OwnerID:    "",
		CreatorID:  "system",
	})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "owner_id is required")
}

func TestAPIKeyService_CreateAPIKey_OwnerNotFound(t *testing.T) {
	_, _, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	_, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "missing-owner",
		Role:       models.APIKeyRoleUser,
		OwnerID:    "acc-doesnotexist",
		CreatorID:  "system",
	})
	assert.ErrorIs(t, err, ErrAccountNotFound)
}

func TestAPIKeyService_CreateAPIKey_InvalidRole(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Invalid Key Role",
		LoginName:   "invalid-key-role",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	_, err = apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "bad-role",
		Role:       models.APIKeyRole("superuser"),
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "invalid api key role")
}

func TestAPIKeyService_CreateAPIKey_ManagerOwnerAdminKey(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	manager, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Manager Owner",
		LoginName:   "manager-owner",
		Role:        models.AccountRoleManager,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	// Admin-role key for manager owner is too high.
	_, err = apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "admin-key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    manager.AccountID,
		CreatorID:  "system",
	})
	assert.ErrorIs(t, err, ErrAPIKeyRoleTooHigh)

	// Manager-role key for manager owner is allowed.
	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "manager-key",
		Role:       models.APIKeyRoleManager,
		OwnerID:    manager.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)
	assert.Equal(t, models.APIKeyRoleManager, key.APIKey.Role)
}

func TestAPIKeyService_CreateAPIKey_MaxKeysDefault(t *testing.T) {
	db, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Default Limit",
		LoginName:   "default-limit",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	// Zero or negative max keys should fall back to the default of 10.
	cfg := newTestConfig()
	cfg.Account.APIKeyMaxPerAccount = 0
	svc := NewAPIKeyService(db, cfg, nil)

	for i := 0; i < 10; i++ {
		_, err := svc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
			APIKeyName: "key",
			Role:       models.APIKeyRoleUser,
			OwnerID:    owner.AccountID,
			CreatorID:  owner.AccountID,
		})
		require.NoError(t, err)
	}

	_, err = svc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "overflow",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	assert.ErrorIs(t, err, ErrAPIKeyLimitReached)
}

func TestAPIKeyService_CreateAPIKey_CountError(t *testing.T) {
	db, accountSvc, _, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Count Error",
		LoginName:   "count-error",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	// Drop the api_keys table to force a count error.
	require.NoError(t, db.Exec("DROP TABLE api_keys").Error)

	_, err = NewAPIKeyService(db, newTestConfig(), nil).CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "count-error-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "failed to count api keys")
}

func TestAPIKeyService_VerifyAPIKey_MalformedToken(t *testing.T) {
	_, _, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	_, _, err := apiKeySvc.VerifyAPIKey(ctx, "missing-separator")
	assert.ErrorIs(t, err, ErrAPIKeyInvalidToken)

	_, _, err = apiKeySvc.VerifyAPIKey(ctx, "not-ak-id.secret")
	assert.ErrorIs(t, err, ErrAPIKeyInvalidToken)
}

func TestAPIKeyService_VerifyAPIKey_NotFound(t *testing.T) {
	_, _, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	_, _, err := apiKeySvc.VerifyAPIKey(ctx, "ak-doesnotexist.secretvalue")
	assert.ErrorIs(t, err, ErrAPIKeyNotFound)
}

func TestAPIKeyService_VerifyAPIKey_InactiveKey(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Inactive Key Owner",
		LoginName:   "inactive-key-owner",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "inactive-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	require.NoError(t, err)

	require.NoError(t, apiKeySvc.db.Model(&models.APIKey{}).
		Where("api_key_id = ?", key.APIKey.APIKeyID).
		Update("status", models.APIKeyStatusInactive).Error)

	_, _, err = apiKeySvc.VerifyAPIKey(ctx, key.Token)
	assert.ErrorIs(t, err, ErrAPIKeyInactive)
}

func TestAPIKeyService_VerifyAPIKey_OwnerInactive(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Inactive Owner",
		LoginName:   "inactive-owner",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "owner-inactive-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	require.NoError(t, err)

	inactiveStatus := models.AccountStatusInactive
	_, err = accountSvc.UpdateAccount(ctx, &UpdateAccountRequest{
		AccountID:  owner.AccountID,
		Status:     &inactiveStatus,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)

	_, _, err = apiKeySvc.VerifyAPIKey(ctx, key.Token)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "owner account is not active")
}

func TestAPIKeyService_ListAPIKeysByOwner_PaginationAndErrors(t *testing.T) {
	_, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "List Owner",
		LoginName:   "list-owner",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	for i := 0; i < 5; i++ {
		_, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
			APIKeyName: "key",
			Role:       models.APIKeyRoleUser,
			OwnerID:    owner.AccountID,
			CreatorID:  owner.AccountID,
		})
		require.NoError(t, err)
	}

	// Default pagination.
	keys, total, err := apiKeySvc.ListAPIKeysByOwner(ctx, owner.AccountID, 0, 0)
	require.NoError(t, err)
	assert.Equal(t, int64(5), total)
	assert.Len(t, keys, 5)

	// Limit and offset.
	keys, total, err = apiKeySvc.ListAPIKeysByOwner(ctx, owner.AccountID, 1, 2)
	require.NoError(t, err)
	assert.Equal(t, int64(5), total)
	assert.Len(t, keys, 2)

	// Offset beyond total.
	keys, total, err = apiKeySvc.ListAPIKeysByOwner(ctx, owner.AccountID, 10, 10)
	require.NoError(t, err)
	assert.Equal(t, int64(5), total)
	assert.Empty(t, keys)

	// Error path: drop table and expect count to fail.
	require.NoError(t, apiKeySvc.db.Exec("DROP TABLE api_keys").Error)
	_, _, err = apiKeySvc.ListAPIKeysByOwner(ctx, owner.AccountID, 0, 10)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "failed to count api keys")
}

func TestAPIKeyService_DeleteAPIKey_NotFound(t *testing.T) {
	_, _, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	err := apiKeySvc.DeleteAPIKey(ctx, "ak-doesnotexist")
	assert.ErrorIs(t, err, ErrAPIKeyNotFound)
}

func TestAPIKeyService_DeleteAPIKeysByOwner_SuccessAndError(t *testing.T) {
	db, accountSvc, apiKeySvc, _ := newTestServices(t)
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Delete By Owner",
		LoginName:   "delete-by-owner",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	for i := 0; i < 3; i++ {
		_, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
			APIKeyName: "key",
			Role:       models.APIKeyRoleUser,
			OwnerID:    owner.AccountID,
			CreatorID:  owner.AccountID,
		})
		require.NoError(t, err)
	}

	err = apiKeySvc.DeleteAPIKeysByOwner(ctx, owner.AccountID)
	require.NoError(t, err)

	keys, total, err := apiKeySvc.ListAPIKeysByOwner(ctx, owner.AccountID, 0, 100)
	require.NoError(t, err)
	assert.Equal(t, int64(0), total)
	assert.Empty(t, keys)

	// Error path: drop table and expect delete to fail.
	require.NoError(t, db.Exec("DROP TABLE api_keys").Error)
	err = NewAPIKeyService(db, newTestConfig(), nil).DeleteAPIKeysByOwner(ctx, owner.AccountID)
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "failed to delete api keys by owner")
}

func TestAPIKeyService_roleLE_AllCombinations(t *testing.T) {
	_, _, apiKeySvc, _ := newTestServices(t)

	cases := []struct {
		keyRole   models.APIKeyRole
		ownerRole models.AccountRole
		expected  bool
	}{
		{models.APIKeyRoleUser, models.AccountRoleUser, true},
		{models.APIKeyRoleManager, models.AccountRoleManager, true},
		{models.APIKeyRoleAdmin, models.AccountRoleAdmin, true},
		{models.APIKeyRoleUser, models.AccountRoleManager, true},
		{models.APIKeyRoleUser, models.AccountRoleAdmin, true},
		{models.APIKeyRoleManager, models.AccountRoleAdmin, true},
		{models.APIKeyRoleAdmin, models.AccountRoleUser, false},
		{models.APIKeyRoleManager, models.AccountRoleUser, false},
		{models.APIKeyRoleAdmin, models.AccountRoleManager, false},
	}

	for _, tc := range cases {
		t.Run(fmt.Sprintf("%s_vs_%s", tc.keyRole, tc.ownerRole), func(t *testing.T) {
			assert.Equal(t, tc.expected, apiKeySvc.roleLE(tc.keyRole, tc.ownerRole))
		})
	}
}

func TestAPIKeyService_isValidAPIKeyRole(t *testing.T) {
	assert.True(t, isValidAPIKeyRole(models.APIKeyRoleAdmin))
	assert.True(t, isValidAPIKeyRole(models.APIKeyRoleManager))
	assert.True(t, isValidAPIKeyRole(models.APIKeyRoleUser))
	assert.False(t, isValidAPIKeyRole("unknown"))
	assert.False(t, isValidAPIKeyRole(""))
}
