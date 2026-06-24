package services

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/models"
)

// TestBootstrapService_Run_ExistingAccountsMissingACSFile verifies that when
// default accounts already exist but their .acs plaintext key files are missing,
// bootstrap regenerates the files so CLI/API authentication can proceed.
func TestBootstrapService_Run_ExistingAccountsMissingACSFile(t *testing.T) {
	t.Chdir(t.TempDir())
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()

	admin, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Existing Admin",
		LoginName:   "existing-admin",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	manager, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Existing Manager",
		LoginName:   "existing-manager",
		Role:        models.AccountRoleManager,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	_, err = apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "Default Admin Key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    admin.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	_, err = apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "Default Manager Key",
		Role:       models.APIKeyRoleManager,
		OwnerID:    manager.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, nil, newDiscardLogger(t))
	require.NoError(t, svc.Run(ctx))

	pwd, _ := os.Getwd()
	adminFile := filepath.Join(pwd, "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	managerFile := filepath.Join(pwd, "ACS_ACCOUNT_MANAGER_API_KEY.acs")

	adminData, err := os.ReadFile(adminFile)
	require.NoError(t, err, "admin .acs file should be regenerated when missing")
	assert.True(t, strings.HasPrefix(string(adminData), "ak-"))

	managerData, err := os.ReadFile(managerFile)
	require.NoError(t, err, "manager .acs file should be regenerated when missing")
	assert.True(t, strings.HasPrefix(string(managerData), "ak-"))
}

// TestBootstrapService_Run_ExistingAccountsWithValidACSFile verifies that a
// valid existing .acs file is preserved and the underlying API key is not
// rotated.
func TestBootstrapService_Run_ExistingAccountsWithValidACSFile(t *testing.T) {
	t.Chdir(t.TempDir())
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()

	admin, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Existing Admin",
		LoginName:   "existing-admin",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	manager, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Existing Manager",
		LoginName:   "existing-manager",
		Role:        models.AccountRoleManager,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	adminKey, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "Default Admin Key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    admin.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	managerKey, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "Default Manager Key",
		Role:       models.APIKeyRoleManager,
		OwnerID:    manager.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	pwd, _ := os.Getwd()
	adminFile := filepath.Join(pwd, "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	managerFile := filepath.Join(pwd, "ACS_ACCOUNT_MANAGER_API_KEY.acs")

	require.NoError(t, os.WriteFile(adminFile, []byte(adminKey.Token), 0600))
	require.NoError(t, os.WriteFile(managerFile, []byte(managerKey.Token), 0600))

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, nil, newDiscardLogger(t))
	require.NoError(t, svc.Run(ctx))

	adminData, err := os.ReadFile(adminFile)
	require.NoError(t, err)
	assert.Equal(t, adminKey.Token, string(adminData), "valid admin .acs file should not be overwritten")

	managerData, err := os.ReadFile(managerFile)
	require.NoError(t, err)
	assert.Equal(t, managerKey.Token, string(managerData), "valid manager .acs file should not be overwritten")

	adminKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, admin.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, adminKeys, 1)
	assert.Equal(t, adminKey.APIKey.APIKeyID, adminKeys[0].APIKeyID)
}

// TestBootstrapService_Run_ExistingAccountsWithInvalidACSFile verifies that an
// invalid .acs file is replaced with a new token and the old system-created API
// key is rotated.
func TestBootstrapService_Run_ExistingAccountsWithInvalidACSFile(t *testing.T) {
	t.Chdir(t.TempDir())
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()

	admin, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Existing Admin",
		LoginName:   "existing-admin",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	manager, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Existing Manager",
		LoginName:   "existing-manager",
		Role:        models.AccountRoleManager,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	oldAdminKey, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "Default Admin Key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    admin.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	oldManagerKey, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "Default Manager Key",
		Role:       models.APIKeyRoleManager,
		OwnerID:    manager.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	pwd, _ := os.Getwd()
	adminFile := filepath.Join(pwd, "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	managerFile := filepath.Join(pwd, "ACS_ACCOUNT_MANAGER_API_KEY.acs")

	require.NoError(t, os.WriteFile(adminFile, []byte("ak-invalid.invalidsecret"), 0600))
	require.NoError(t, os.WriteFile(managerFile, []byte("ak-invalid.invalidsecret"), 0600))

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, nil, newDiscardLogger(t))
	require.NoError(t, svc.Run(ctx))

	adminData, err := os.ReadFile(adminFile)
	require.NoError(t, err)
	assert.True(t, strings.HasPrefix(string(adminData), "ak-"))
	assert.NotEqual(t, "ak-invalid.invalidsecret", string(adminData), "invalid admin .acs file should be regenerated")

	managerData, err := os.ReadFile(managerFile)
	require.NoError(t, err)
	assert.True(t, strings.HasPrefix(string(managerData), "ak-"))
	assert.NotEqual(t, "ak-invalid.invalidsecret", string(managerData), "invalid manager .acs file should be regenerated")

	adminKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, admin.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, adminKeys, 1)
	assert.NotEqual(t, oldAdminKey.APIKey.APIKeyID, adminKeys[0].APIKeyID)

	managerKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, manager.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, managerKeys, 1)
	assert.NotEqual(t, oldManagerKey.APIKey.APIKeyID, managerKeys[0].APIKeyID)
}
