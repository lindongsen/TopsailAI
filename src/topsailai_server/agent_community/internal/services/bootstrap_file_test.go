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

// TestBootstrapService_Run_FollowerDoesNotRegenerateMissingACSFile verifies that
// when default accounts already exist (created by another node) but the local
// .acs plaintext key files are missing, bootstrap does NOT regenerate keys or
// files. This prevents follower nodes from invalidating the leader's keys.
func TestBootstrapService_Run_FollowerDoesNotRegenerateMissingACSFile(t *testing.T) {
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

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
	require.NoError(t, svc.Run(ctx))

	pwd, _ := os.Getwd()
	adminFile := filepath.Join(pwd, "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	managerFile := filepath.Join(pwd, "ACS_ACCOUNT_MANAGER_API_KEY.acs")

	_, err = os.Stat(adminFile)
	assert.True(t, os.IsNotExist(err), "follower should not create admin .acs file when account already exists")
	_, err = os.Stat(managerFile)
	assert.True(t, os.IsNotExist(err), "follower should not create manager .acs file when account already exists")

	adminKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, admin.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, adminKeys, 1)
	assert.Equal(t, adminKey.APIKey.APIKeyID, adminKeys[0].APIKeyID, "follower should not rotate existing admin key")

	managerKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, manager.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, managerKeys, 1)
	assert.Equal(t, managerKey.APIKey.APIKeyID, managerKeys[0].APIKeyID, "follower should not rotate existing manager key")
}

// TestBootstrapService_Run_ExistingAccountsWithValidACSFile verifies that a
// valid existing .acs file is preserved and the underlying API key is not
// rotated when the default account already exists.
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

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
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

// TestBootstrapService_Run_FollowerDoesNotReplaceInvalidACSFile verifies that
// when default accounts already exist, an invalid local .acs file is NOT
// replaced and the existing system API keys are NOT rotated. This prevents
// follower nodes from invalidating keys created by the leader.
func TestBootstrapService_Run_FollowerDoesNotReplaceInvalidACSFile(t *testing.T) {
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

	require.NoError(t, os.WriteFile(adminFile, []byte("ak-invalid.invalidsecret"), 0600))
	require.NoError(t, os.WriteFile(managerFile, []byte("ak-invalid.invalidsecret"), 0600))

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
	require.NoError(t, svc.Run(ctx))

	adminData, err := os.ReadFile(adminFile)
	require.NoError(t, err)
	assert.Equal(t, "ak-invalid.invalidsecret", string(adminData), "invalid admin .acs file should not be replaced by follower")

	managerData, err := os.ReadFile(managerFile)
	require.NoError(t, err)
	assert.Equal(t, "ak-invalid.invalidsecret", string(managerData), "invalid manager .acs file should not be replaced by follower")

	adminKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, admin.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, adminKeys, 1)
	assert.Equal(t, adminKey.APIKey.APIKeyID, adminKeys[0].APIKeyID, "follower should not rotate existing admin key")

	managerKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, manager.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, managerKeys, 1)
	assert.Equal(t, managerKey.APIKey.APIKeyID, managerKeys[0].APIKeyID, "follower should not rotate existing manager key")
}

// TestBootstrapService_Run_DefaultKeysAuthenticate verifies that the plaintext
// tokens written to both .acs files successfully authenticate against the
// stored API key hashes and return the expected roles.
func TestBootstrapService_Run_DefaultKeysAuthenticate(t *testing.T) {
	t.Chdir(t.TempDir())
	svc := newTestBootstrapService(t, nil)
	ctx := context.Background()

	require.NoError(t, svc.Run(ctx))

	pwd, _ := os.Getwd()
	adminFile := filepath.Join(pwd, "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	managerFile := filepath.Join(pwd, "ACS_ACCOUNT_MANAGER_API_KEY.acs")

	adminData, err := os.ReadFile(adminFile)
	require.NoError(t, err)
	managerData, err := os.ReadFile(managerFile)
	require.NoError(t, err)

	adminToken := strings.TrimSpace(string(adminData))
	managerToken := strings.TrimSpace(string(managerData))

	adminKey, adminOwner, err := svc.apiKeySvc.VerifyAPIKey(ctx, adminToken)
	require.NoError(t, err, "admin default key token should authenticate")
	assert.Equal(t, models.APIKeyRoleAdmin, adminKey.Role)
	assert.Equal(t, models.AccountRoleAdmin, adminOwner.Role)

	managerKey, managerOwner, err := svc.apiKeySvc.VerifyAPIKey(ctx, managerToken)
	require.NoError(t, err, "manager default key token should authenticate")
	assert.Equal(t, models.APIKeyRoleManager, managerKey.Role)
	assert.Equal(t, models.AccountRoleManager, managerOwner.Role)
}
