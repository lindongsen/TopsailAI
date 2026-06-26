// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
)

// newTestBootstrapConfig returns a minimal config with low bcrypt cost for fast tests.
func newTestBootstrapConfig() *config.Config {
	return &config.Config{
		Account: config.AccountConfig{
			APIKeyMaxPerAccount:       10,
			LoginSessionExpirySeconds: 86400,
			BcryptCost:                4,
		},
	}
}

// newTestBootstrapServices creates real services backed by an in-memory SQLite DB.
func newTestBootstrapServices(t *testing.T) (*gorm.DB, *AccountService, *APIKeyService, *AuditLogService) {
	t.Helper()
	db := newTestDB(t)
	cfg := newTestBootstrapConfig()
	auditSvc := NewAuditLogService(db)
	accountSvc := NewAccountService(db, cfg)
	apiKeySvc := NewAPIKeyService(db, cfg)
	accountSvc.SetAPIKeyService(apiKeySvc)
	return db, accountSvc, apiKeySvc, auditSvc
}

// newDiscardLogger returns a logger that writes to stdout at error level.
// stdout is used because the logger does not support a discard writer directly.
func newDiscardLogger(t *testing.T) *logger.Logger {
	t.Helper()
	return logger.New(logger.Config{Output: "stdout", Level: "error"})
}

// stubKVEntry implements nats.KeyValueEntry for testing.
type stubKVEntry struct {
	bucket   string
	key      string
	value    []byte
	revision uint64
	created  time.Time
}

func (e *stubKVEntry) Bucket() string     { return e.bucket }
func (e *stubKVEntry) Key() string        { return e.key }
func (e *stubKVEntry) Value() []byte      { return e.value }
func (e *stubKVEntry) Revision() uint64   { return e.revision }
func (e *stubKVEntry) Created() time.Time { return e.created }
func (e *stubKVEntry) Delta() uint64      { return 0 }
func (e *stubKVEntry) Operation() nats.KeyValueOp {
	return nats.KeyValuePut
}

// stubKeyValue is a minimal in-memory implementation of nats.KeyValue for bootstrap lock tests.
type stubKeyValue struct {
	mu       sync.Mutex
	data     map[string]*stubKVEntry
	bucket   string
	createErr error
	getErr    error
	updateErr error
	deleteErr error
	revision  uint64
}

func newStubKeyValue() *stubKeyValue {
	return &stubKeyValue{
		data:   make(map[string]*stubKVEntry),
		bucket: "test-bucket",
	}
}

func (kv *stubKeyValue) Create(key string, value []byte) (uint64, error) {
	kv.mu.Lock()
	defer kv.mu.Unlock()
	if kv.createErr != nil {
		return 0, kv.createErr
	}
	if _, exists := kv.data[key]; exists {
		return 0, nats.ErrKeyExists
	}
	kv.revision++
	kv.data[key] = &stubKVEntry{
		bucket:   kv.bucket,
		key:      key,
		value:    value,
		revision: kv.revision,
		created:  time.Now(),
	}
	return kv.revision, nil
}

func (kv *stubKeyValue) Get(key string) (nats.KeyValueEntry, error) {
	kv.mu.Lock()
	defer kv.mu.Unlock()
	if kv.getErr != nil {
		return nil, kv.getErr
	}
	entry, exists := kv.data[key]
	if !exists {
		return nil, nats.ErrKeyNotFound
	}
	return entry, nil
}

func (kv *stubKeyValue) Update(key string, value []byte, last uint64) (uint64, error) {
	kv.mu.Lock()
	defer kv.mu.Unlock()
	if kv.updateErr != nil {
		return 0, kv.updateErr
	}
	entry, exists := kv.data[key]
	if !exists {
		return 0, nats.ErrKeyNotFound
	}
	if entry.Revision() != last {
		return 0, errors.New("revision mismatch")
	}
	kv.revision++
	entry.value = value
	entry.revision = kv.revision
	return kv.revision, nil
}

func (kv *stubKeyValue) Delete(key string, opts ...nats.DeleteOpt) error {
	kv.mu.Lock()
	defer kv.mu.Unlock()
	if kv.deleteErr != nil {
		return kv.deleteErr
	}
	delete(kv.data, key)
	return nil
}

func (kv *stubKeyValue) Put(key string, value []byte) (uint64, error) {
	return kv.Create(key, value)
}

func (kv *stubKeyValue) PutString(key string, value string) (uint64, error) {
	return kv.Put(key, []byte(value))
}

func (kv *stubKeyValue) GetRevision(key string, revision uint64) (nats.KeyValueEntry, error) {
	return nil, errors.New("not implemented")
}

func (kv *stubKeyValue) Purge(key string, opts ...nats.DeleteOpt) error {
	return kv.Delete(key)
}

func (kv *stubKeyValue) Watch(keys string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return nil, errors.New("not implemented")
}

func (kv *stubKeyValue) WatchAll(opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return nil, errors.New("not implemented")
}

func (kv *stubKeyValue) WatchFiltered(keys []string, opts ...nats.WatchOpt) (nats.KeyWatcher, error) {
	return nil, errors.New("not implemented")
}

func (kv *stubKeyValue) Keys(opts ...nats.WatchOpt) ([]string, error) {
	kv.mu.Lock()
	defer kv.mu.Unlock()
	keys := make([]string, 0, len(kv.data))
	for k := range kv.data {
		keys = append(keys, k)
	}
	return keys, nil
}

func (kv *stubKeyValue) ListKeys(opts ...nats.WatchOpt) (nats.KeyLister, error) {
	return nil, errors.New("not implemented")
}

func (kv *stubKeyValue) History(key string, opts ...nats.WatchOpt) ([]nats.KeyValueEntry, error) {
	return nil, errors.New("not implemented")
}

func (kv *stubKeyValue) Bucket() string {
	return kv.bucket
}

func (kv *stubKeyValue) PurgeDeletes(opts ...nats.PurgeOpt) error {
	return nil
}

func (kv *stubKeyValue) Status() (nats.KeyValueStatus, error) {
	return nil, errors.New("not implemented")
}

// newTestBootstrapService builds a BootstrapService with the provided NATS KV.
// If kv is nil, a stub KeyValue implementation is used so that the distributed
// lock can be exercised without a real NATS server.
func newTestBootstrapService(t *testing.T, kv nats.KeyValue) *BootstrapService {
	t.Helper()
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	if kv == nil {
		kv = newStubKeyValue()
	}
	return NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, kv, newDiscardLogger(t))
}

func TestBootstrapService_Run_CreatesDefaultAdminAndManager(t *testing.T) {
	t.Chdir(t.TempDir())
	svc := newTestBootstrapService(t, nil)
	ctx := context.Background()

	err := svc.Run(ctx)
	require.NoError(t, err)

	adminExists, err := svc.hasAccountWithRole(ctx, models.AccountRoleAdmin)
	require.NoError(t, err)
	assert.True(t, adminExists)

	managerExists, err := svc.hasAccountWithRole(ctx, models.AccountRoleManager)
	require.NoError(t, err)
	assert.True(t, managerExists)

	adminFile := filepath.Join(t.TempDir(), "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	// The file is written to the working directory set by t.Chdir, not t.TempDir() above.
	pwd, _ := os.Getwd()
	adminFile = filepath.Join(pwd, "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	managerFile := filepath.Join(pwd, "ACS_ACCOUNT_MANAGER_API_KEY.acs")

	adminData, err := os.ReadFile(adminFile)
	require.NoError(t, err)
	assert.True(t, strings.HasPrefix(string(adminData), "ak-"))

	managerData, err := os.ReadFile(managerFile)
	require.NoError(t, err)
	assert.True(t, strings.HasPrefix(string(managerData), "ak-"))
}

// TestBootstrapService_Run_LeaderCreatesDefaultAccountAndWritesACSFile verifies
// that the node which creates the default accounts also generates API keys and
// writes the plaintext .acs files to the working directory.
func TestBootstrapService_Run_LeaderCreatesDefaultAccountAndWritesACSFile(t *testing.T) {
	t.Chdir(t.TempDir())
	svc := newTestBootstrapService(t, nil)
	ctx := context.Background()

	require.NoError(t, svc.Run(ctx))

	adminExists, err := svc.hasAccountWithRole(ctx, models.AccountRoleAdmin)
	require.NoError(t, err)
	assert.True(t, adminExists, "leader should create admin account")

	managerExists, err := svc.hasAccountWithRole(ctx, models.AccountRoleManager)
	require.NoError(t, err)
	assert.True(t, managerExists, "leader should create manager account")

	pwd, _ := os.Getwd()
	adminFile := filepath.Join(pwd, "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	managerFile := filepath.Join(pwd, "ACS_ACCOUNT_MANAGER_API_KEY.acs")

	adminData, err := os.ReadFile(adminFile)
	require.NoError(t, err, "leader should write admin .acs file")
	adminToken := strings.TrimSpace(string(adminData))
	assert.True(t, strings.HasPrefix(adminToken, "ak-"))

	managerData, err := os.ReadFile(managerFile)
	require.NoError(t, err, "leader should write manager .acs file")
	managerToken := strings.TrimSpace(string(managerData))
	assert.True(t, strings.HasPrefix(managerToken, "ak-"))

	verifiedAdminKey, verifiedAdminOwner, err := svc.apiKeySvc.VerifyAPIKey(ctx, adminToken)
	require.NoError(t, err, "leader admin token must authenticate")
	assert.Equal(t, models.APIKeyRoleAdmin, verifiedAdminKey.Role)
	assert.Equal(t, models.AccountRoleAdmin, verifiedAdminOwner.Role)

	verifiedManagerKey, verifiedManagerOwner, err := svc.apiKeySvc.VerifyAPIKey(ctx, managerToken)
	require.NoError(t, err, "leader manager token must authenticate")
	assert.Equal(t, models.APIKeyRoleManager, verifiedManagerKey.Role)
	assert.Equal(t, models.AccountRoleManager, verifiedManagerOwner.Role)
}

// TestBootstrapService_Run_FollowerFindsExistingAccountAndDoesNotRegenerateKeys
// verifies that a follower node which finds default accounts already created
// does not delete, rotate, or recreate API keys and does not write .acs files.
func TestBootstrapService_Run_FollowerFindsExistingAccountAndDoesNotRegenerateKeys(t *testing.T) {
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
	assert.True(t, os.IsNotExist(err), "follower should not write admin .acs file")
	_, err = os.Stat(managerFile)
	assert.True(t, os.IsNotExist(err), "follower should not write manager .acs file")

	adminKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, admin.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, adminKeys, 1)
	assert.Equal(t, adminKey.APIKey.APIKeyID, adminKeys[0].APIKeyID, "follower should not rotate admin key")

	managerKeys, _, err := apiKeySvc.ListAPIKeysByOwner(ctx, manager.AccountID, 0, 1000)
	require.NoError(t, err)
	require.Len(t, managerKeys, 1)
	assert.Equal(t, managerKey.APIKey.APIKeyID, managerKeys[0].APIKeyID, "follower should not rotate manager key")
}

func TestBootstrapService_Run_ValidatesConfiguredAdminKey(t *testing.T) {
	t.Chdir(t.TempDir())
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()

	// Create an admin account and key manually.
	admin, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Configured Admin",
		LoginName:   "configured-admin",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "Configured Admin Key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    admin.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	cfg := newTestBootstrapConfig()
	cfg.Account.AdminAPIKey = key.Token

	svc := NewBootstrapService(db, cfg, accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
	err = svc.Run(ctx)
	require.NoError(t, err)

	// No new admin account should be created; only the configured one exists.
	accounts, _, err := accountSvc.ListAccounts(ctx, 0, 1000, nil)
	require.NoError(t, err)
	adminCount := 0
	for _, acc := range accounts {
		if acc.Role == models.AccountRoleAdmin {
			adminCount++
		}
	}
	assert.Equal(t, 1, adminCount)
}

func TestBootstrapService_Run_InvalidConfiguredAdminKeyFails(t *testing.T) {
	t.Chdir(t.TempDir())
	svc := newTestBootstrapService(t, nil)
	ctx := context.Background()

	svc.cfg.Account.AdminAPIKey = "ak-invalid.wrongsecret"
	err := svc.Run(ctx)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "configured admin api key mismatch")
}

func TestBootstrapService_Run_AdminExistsSkipsCreation(t *testing.T) {
	t.Chdir(t.TempDir())
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()

	_, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Existing Admin",
		LoginName:   "existing-admin",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
	err = svc.Run(ctx)
	require.NoError(t, err)

	accounts, _, err := accountSvc.ListAccounts(ctx, 0, 1000, nil)
	require.NoError(t, err)
	adminCount := 0
	for _, acc := range accounts {
		if acc.Role == models.AccountRoleAdmin {
			adminCount++
		}
	}
	assert.Equal(t, 1, adminCount)
}

func TestBootstrapService_Run_LockHeldSkipsBootstrap(t *testing.T) {
	t.Chdir(t.TempDir())
	kv := newStubKeyValue()
	// Pre-create the lock key so the first service sees it as held.
	_, err := kv.Create("acs.lock.bootstrap.default-accounts", []byte("other-token"))
	require.NoError(t, err)

	svc := newTestBootstrapService(t, kv)
	ctx := context.Background()

	err = svc.Run(ctx)
	require.NoError(t, err)

	// No accounts should have been created because the lock was held.
	accounts, _, err := svc.accountSvc.ListAccounts(ctx, 0, 1000, nil)
	require.NoError(t, err)
	assert.Empty(t, accounts)
}

func TestBootstrapService_ensureDefaultAccount_NoKeyCreatesFile(t *testing.T) {
	t.Chdir(t.TempDir())
	svc := newTestBootstrapService(t, nil)
	ctx := context.Background()

	created, err := svc.ensureDefaultAccount(ctx, defaultAccountSpec{
		role:      models.AccountRoleAdmin,
		configKey: "",
		filename:  "ACS_ACCOUNT_ADMIN_API_KEY.acs",
	})
	require.NoError(t, err)
	assert.True(t, created, "leader should report account created")

	pwd, _ := os.Getwd()
	adminFile := filepath.Join(pwd, "ACS_ACCOUNT_ADMIN_API_KEY.acs")
	data, err := os.ReadFile(adminFile)
	require.NoError(t, err)
	assert.True(t, strings.HasPrefix(string(data), "ak-"))
}

func TestBootstrapService_ensureDefaultAccount_ManagerNoKeyCreatesFile(t *testing.T) {
	t.Chdir(t.TempDir())
	svc := newTestBootstrapService(t, nil)
	ctx := context.Background()

	created, err := svc.ensureDefaultAccount(ctx, defaultAccountSpec{
		role:      models.AccountRoleManager,
		configKey: "",
		filename:  "ACS_ACCOUNT_MANAGER_API_KEY.acs",
	})
	require.NoError(t, err)
	assert.True(t, created, "leader should report account created")

	pwd, _ := os.Getwd()
	managerFile := filepath.Join(pwd, "ACS_ACCOUNT_MANAGER_API_KEY.acs")
	data, err := os.ReadFile(managerFile)
	require.NoError(t, err)
	assert.True(t, strings.HasPrefix(string(data), "ak-"))
}

func TestBootstrapService_validateConfiguredToken_FormatErrors(t *testing.T) {
	svc := newTestBootstrapService(t, nil)
	ctx := context.Background()

	tests := []struct {
		name  string
		token string
	}{
		{"missing separator", "ak-nosecret"},
		{"missing ak prefix", "xx-xxx.yyy"},
		{"empty token", ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := svc.validateConfiguredToken(ctx, tt.token, models.AccountRoleAdmin)
			require.Error(t, err)
		})
	}
}
func TestBootstrapService_validateConfiguredToken_RoleMismatch(t *testing.T) {
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()
	// Create a user account/key and try to validate it as admin.
	user, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "User",
		LoginName:   "user-mismatch",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "User Key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    user.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
	err = svc.validateConfiguredToken(ctx, key.Token, models.AccountRoleAdmin)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "expected admin")
}

func TestBootstrapService_createDefaultAccount_RoleToKeyRoleMapping(t *testing.T) {
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))

	tests := []struct {
		role        models.AccountRole
		expectedKey models.APIKeyRole
	}{
		{models.AccountRoleAdmin, models.APIKeyRoleAdmin},
		{models.AccountRoleManager, models.APIKeyRoleManager},
		{models.AccountRoleUser, models.APIKeyRoleUser},
	}

	for _, tt := range tests {
		t.Run(string(tt.role), func(t *testing.T) {
			account, token, err := svc.createDefaultAccount(ctx, tt.role)
			require.NoError(t, err)
			assert.Equal(t, tt.role, account.Role)
			assert.True(t, strings.HasPrefix(token, "ak-"))

			parts := strings.SplitN(token, ".", 2)
			require.Len(t, parts, 2)
			apiKeyID := parts[0]

			key, err := apiKeySvc.getByID(ctx, apiKeyID)
			require.NoError(t, err)
			assert.Equal(t, tt.expectedKey, key.Role)
		})
	}
}

func TestBootstrapService_writeTokenFile_Permissions(t *testing.T) {
	tmpDir := t.TempDir()
	t.Chdir(tmpDir)
	svc := newTestBootstrapService(t, nil)

	token := "ak-test.secretvalue"
	_, err := svc.writeTokenFile("test-token.acs", token)
	require.NoError(t, err)

	path := filepath.Join(tmpDir, "test-token.acs")
	info, err := os.Stat(path)
	require.NoError(t, err)
	assert.Equal(t, os.FileMode(0600), info.Mode().Perm())

	data, err := os.ReadFile(path)
	require.NoError(t, err)
	assert.Equal(t, token, string(data))
}

func TestBootstrapService_logAccountStats(t *testing.T) {
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()

	_, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Admin",
		LoginName:   "admin-stats",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	_, err = accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Inactive User",
		LoginName:   "inactive-stats",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
	// Should not panic and should complete without error.
	svc.logAccountStats(ctx)
}

func TestBootstrapService_acquireLock_NilKVReturnsError(t *testing.T) {
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, nil, newDiscardLogger(t))
	ctx := context.Background()

	release, err := svc.acquireLock(ctx, "acs.lock.bootstrap.test", "token")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "NATS KV is nil")
	assert.Nil(t, release)
}

func TestBootstrapService_acquireLock_NatsKeyExists(t *testing.T) {
	kv := newStubKeyValue()
	_, err := kv.Create("acs.lock.bootstrap.test", []byte("other-token"))
	require.NoError(t, err)

	svc := newTestBootstrapService(t, kv)
	ctx := context.Background()

	release, err := svc.acquireLock(ctx, "acs.lock.bootstrap.test", "token")
	require.Error(t, err)
	assert.ErrorIs(t, err, ErrBootstrapLockHeld)
	assert.Nil(t, release)
}

func TestBootstrapService_renewLock_TokenMismatchStops(t *testing.T) {
	kv := newStubKeyValue()
	key := "acs.lock.bootstrap.renew"
	// Create the key with a different token value.
	_, err := kv.Create(key, []byte("other-token"))
	require.NoError(t, err)

	svc := newTestBootstrapService(t, kv)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan struct{})
	go svc.renewLock(ctx, key, "our-token", done)

	// Wait briefly to allow at least one renewal attempt.
	time.Sleep(50 * time.Millisecond)
	cancel()

	// renewLock should close done when it detects token mismatch or context cancellation.
	select {
	case <-done:
		// Expected: token mismatch caused early return.
	case <-time.After(2 * time.Second):
		t.Fatal("renewLock did not stop after token mismatch")
	}
}

func TestBootstrapService_validateConfiguredToken_InactiveKey(t *testing.T) {
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	ctx := context.Background()

	admin, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Inactive Admin",
		LoginName:   "inactive-admin",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "Inactive Key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    admin.AccountID,
		CreatorID:  "system",
	})
	require.NoError(t, err)

	// Deactivate the key directly.
	require.NoError(t, db.WithContext(ctx).Model(&models.APIKey{}).Where("api_key_id = ?", key.APIKey.APIKeyID).Update("status", models.APIKeyStatusInactive).Error)

	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
	err = svc.validateConfiguredToken(ctx, key.Token, models.AccountRoleAdmin)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "inactive")
}

func TestBootstrapService_writeTokenFile_Failure(t *testing.T) {
	svc := newTestBootstrapService(t, nil)

	// Use a path that cannot be created to force a write error.
	_, err := svc.writeTokenFile("/nonexistent-dir/test-token.acs", "ak-test.secretvalue")
	require.Error(t, err)
}

func TestBootstrapService_acquireLock_CreateSuccess(t *testing.T) {
	kv := newStubKeyValue()
	svc := newTestBootstrapService(t, kv)
	ctx := context.Background()

	release, err := svc.acquireLock(ctx, "acs.lock.bootstrap.create-success", "token")
	require.NoError(t, err)
	require.NotNil(t, release)

	// Verify the key was created.
	_, err = kv.Get("acs.lock.bootstrap.create-success")
	require.NoError(t, err)

	release()

	// After release the key should be deleted.
	_, err = kv.Get("acs.lock.bootstrap.create-success")
	require.ErrorIs(t, err, nats.ErrKeyNotFound)
}

func TestBootstrapService_acquireLock_CreateOtherError(t *testing.T) {
	kv := newStubKeyValue()
	kv.createErr = errors.New("nats unavailable")

	svc := newTestBootstrapService(t, kv)
	ctx := context.Background()

	release, err := svc.acquireLock(ctx, "acs.lock.bootstrap.create-error", "token")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "nats unavailable")
	assert.Nil(t, release)
}

func TestBootstrapService_renewLock_UpdateErrorContinues(t *testing.T) {
	kv := newStubKeyValue()
	key := "acs.lock.bootstrap.renew-update-error"
	_, err := kv.Create(key, []byte("token"))
	require.NoError(t, err)

	kv.updateErr = errors.New("update failed")

	svc := newTestBootstrapService(t, kv)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	done := make(chan struct{})
	go svc.renewLock(ctx, key, "token", done)

	// Wait briefly to allow at least one renewal attempt with the error.
	time.Sleep(50 * time.Millisecond)
	cancel()

	select {
	case <-done:
		// Expected after context cancellation.
	case <-time.After(2 * time.Second):
		t.Fatal("renewLock did not stop after context cancellation")
	}
}

func TestBootstrapService_hasAccountWithRole_Error(t *testing.T) {
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, newStubKeyValue(), newDiscardLogger(t))
	ctx := context.Background()

	// Close the DB to force an error.
	sqlDB, err := db.DB()
	require.NoError(t, err)
	require.NoError(t, sqlDB.Close())

	_, err = svc.hasAccountWithRole(ctx, models.AccountRoleAdmin)
	require.Error(t, err)
}

func TestBootstrapService_LockKey_HasValidFormat(t *testing.T) {
	// The lock key must not contain ':' because NATS KV rejects such keys.
	assert.NotContains(t, bootstrapLockKey, ":")
	assert.Equal(t, "acs.lock.bootstrap.default-accounts", bootstrapLockKey)
}

func TestBootstrapService_Run_SkipsWhenLockHeld(t *testing.T) {
	t.Chdir(t.TempDir())
	kv := newStubKeyValue()
	svc2 := newTestBootstrapService(t, kv)
	ctx := context.Background()

	// Pre-create the lock key so svc2 sees it as held.
	_, err := kv.Create(bootstrapLockKey, []byte("other-node"))
	require.NoError(t, err)

	// svc2 should detect the lock is held and skip bootstrap without error.
	err = svc2.Run(ctx)
	require.NoError(t, err)

	// No default accounts should have been created by svc2.
	adminExists, err := svc2.hasAccountWithRole(ctx, models.AccountRoleAdmin)
	require.NoError(t, err)
	assert.False(t, adminExists)

	managerExists, err := svc2.hasAccountWithRole(ctx, models.AccountRoleManager)
	require.NoError(t, err)
	assert.False(t, managerExists)
}

func TestBootstrapService_Run_FailsWhenKVNil(t *testing.T) {
	t.Chdir(t.TempDir())
	db, accountSvc, apiKeySvc, _ := newTestBootstrapServices(t)
	svc := NewBootstrapService(db, newTestBootstrapConfig(), accountSvc, apiKeySvc, nil, newDiscardLogger(t))
	ctx := context.Background()

	err := svc.Run(ctx)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "NATS KV is nil")
}
