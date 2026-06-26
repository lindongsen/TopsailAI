// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
)

// ErrBootstrapLockHeld indicates another node is already running bootstrap.
var ErrBootstrapLockHeld = errors.New("bootstrap lock held by another node")

// bootstrapLockKey is the NATS KV key used to coordinate default account
// creation across ACS nodes. It uses the same dotted format as
// internal/lock/distributed_lock.go and must not contain ':'.
const bootstrapLockKey = "acs.lock.bootstrap.default-accounts"

// BootstrapService handles default admin/manager account creation on startup.
type BootstrapService struct {
	db         *gorm.DB
	cfg        *config.Config
	accountSvc *AccountService
	apiKeySvc  *APIKeyService
	kv         nats.KeyValue
	log        *logger.Logger
}

// NewBootstrapService creates a new BootstrapService.
func NewBootstrapService(
	db *gorm.DB,
	cfg *config.Config,
	accountSvc *AccountService,
	apiKeySvc *APIKeyService,
	kv nats.KeyValue,
	log *logger.Logger,
) *BootstrapService {
	return &BootstrapService{
		db:         db,
		cfg:        cfg,
		accountSvc: accountSvc,
		apiKeySvc:  apiKeySvc,
		kv:         kv,
		log:        log,
	}
}

// Run executes the startup bootstrap logic.
// It acquires a distributed lock, validates or creates default accounts, and logs statistics.
func (s *BootstrapService) Run(ctx context.Context) error {
	lockToken := uuid.New().String()

	release, err := s.acquireLock(ctx, bootstrapLockKey, lockToken)
	if err != nil {
		if errors.Is(err, ErrBootstrapLockHeld) {
			s.log.Warn("bootstrap", "", "bootstrap lock held by another node, skipping default account creation")
			return nil
		}
		return fmt.Errorf("failed to acquire bootstrap lock: %w", err)
	}
	defer release()

	if _, err := s.ensureDefaultAccount(ctx, defaultAccountSpec{
		role:      models.AccountRoleAdmin,
		configKey: s.cfg.Account.AdminAPIKey,
		filename:  "ACS_ACCOUNT_ADMIN_API_KEY.acs",
	}); err != nil {
		return err
	}

	if _, err := s.ensureDefaultAccount(ctx, defaultAccountSpec{
		role:      models.AccountRoleManager,
		configKey: s.cfg.Account.ManagerAPIKey,
		filename:  "ACS_ACCOUNT_MANAGER_API_KEY.acs",
	}); err != nil {
		return err
	}

	s.logAccountStats(ctx)
	return nil
}

// defaultAccountSpec describes a default account to validate or create.
type defaultAccountSpec struct {
	role      models.AccountRole
	configKey string
	filename  string
}

// ensureDefaultAccount validates a configured token or creates a default
// account and writes its plaintext API key to a file in the working directory.
// When the default account already exists, the node that did not create it in
// this bootstrap run must not regenerate API keys or write token files, because
// doing so would invalidate the keys created by another node in a multi-node
// deployment.
func (s *BootstrapService) ensureDefaultAccount(ctx context.Context, spec defaultAccountSpec) (bool, error) {
	roleName := string(spec.role)

	if spec.configKey != "" {
		if err := s.validateConfiguredToken(ctx, spec.configKey, spec.role); err != nil {
			s.log.Error("bootstrap", "", fmt.Sprintf("configured %s api key is invalid", roleName), "error", err.Error())
			return false, fmt.Errorf("configured %s api key mismatch: %w", roleName, err)
		}
		s.log.Info("bootstrap", "", fmt.Sprintf("configured %s api key validated", roleName))
		return false, nil
	}

	exists, err := s.hasAccountWithRole(ctx, spec.role)
	if err != nil {
		return false, err
	}
	if exists {
		account, err := s.findDefaultAccount(ctx, spec.role)
		if err != nil {
			return false, fmt.Errorf("failed to locate default %s account: %w", roleName, err)
		}
		pwd, err := os.Getwd()
		if err != nil {
			return false, fmt.Errorf("failed to get working directory: %w", err)
		}
		path := filepath.Join(pwd, spec.filename)
		if _, err := os.Stat(path); os.IsNotExist(err) {
			s.log.Warn("bootstrap", "", fmt.Sprintf("default %s account exists but local token file is missing; skipping regeneration to avoid invalidating keys created by another node", roleName),
				"account_id", account.AccountID,
				"file", spec.filename,
			)
		} else {
			s.log.Info("bootstrap", "", fmt.Sprintf("default %s account already exists, skipping key generation", roleName),
				"account_id", account.AccountID,
				"file", spec.filename,
			)
		}
		return false, nil
	}

	account, token, err := s.createDefaultAccount(ctx, spec.role)
	if err != nil {
		return false, err
	}

	path, err := s.writeTokenFile(spec.filename, token)
	if err != nil {
		return false, fmt.Errorf("failed to write %s api key file: %w", roleName, err)
	}

	s.log.Info("bootstrap", "", fmt.Sprintf("created default %s account", roleName),
		"account_id", account.AccountID,
		"file", spec.filename,
		"path", path,
	)
	return true, nil
}

// validateConfiguredToken checks that the provided plaintext token matches an
// active API key with the expected role.
func (s *BootstrapService) validateConfiguredToken(ctx context.Context, token string, expectedRole models.AccountRole) error {
	parts := strings.SplitN(token, ".", 2)
	if len(parts) != 2 {
		return fmt.Errorf("token format must be {api_key_id}.{secret}")
	}
	apiKeyID := parts[0]
	if !strings.HasPrefix(apiKeyID, "ak-") {
		return fmt.Errorf("api_key_id must start with ak-")
	}

	key, owner, err := s.apiKeySvc.VerifyAPIKey(ctx, token)
	if err != nil {
		return fmt.Errorf("token verification failed: %w", err)
	}
	if owner.Role != expectedRole {
		return fmt.Errorf("token owner role is %s, expected %s", owner.Role, expectedRole)
	}
	if !key.IsActive() {
		return fmt.Errorf("api key is not active")
	}
	return nil
}

// hasAccountWithRole reports whether any active account with the given role exists.
func (s *BootstrapService) hasAccountWithRole(ctx context.Context, role models.AccountRole) (bool, error) {
	var count int64
	if err := s.db.WithContext(ctx).Model(&models.Account{}).
		Where("role = ? AND status = ?", role, models.AccountStatusActive).
		Count(&count).Error; err != nil {
		return false, fmt.Errorf("failed to count %s accounts: %w", role, err)
	}
	return count > 0, nil
}

// findDefaultAccount returns the system-created default account for the given role.
// If no system-created account exists, it falls back to any active account with the role.
func (s *BootstrapService) findDefaultAccount(ctx context.Context, role models.AccountRole) (*models.Account, error) {
	var account models.Account
	if err := s.db.WithContext(ctx).
		Where("role = ? AND status = ? AND creator_id = ?", role, models.AccountStatusActive, "system").
		Order("create_at_ms asc").
		First(&account).Error; err == nil {
		return &account, nil
	} else if !errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, fmt.Errorf("failed to query default %s account: %w", role, err)
	}

	if err := s.db.WithContext(ctx).
		Where("role = ? AND status = ?", role, models.AccountStatusActive).
		Order("create_at_ms asc").
		First(&account).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, fmt.Errorf("no active %s account found", role)
		}
		return nil, fmt.Errorf("failed to query %s account: %w", role, err)
	}
	return &account, nil
}

// createDefaultAccount creates a system account with the given role and an API key.
func (s *BootstrapService) createDefaultAccount(ctx context.Context, role models.AccountRole) (*models.Account, string, error) {
	loginName := fmt.Sprintf("system-%s", role)
	accountName := fmt.Sprintf("System %s", strings.Title(string(role)))

	account, err := s.accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName:        accountName,
		AccountDescription: fmt.Sprintf("Default %s account created by system", role),
		Role:               role,
		LoginName:          loginName,
		CreatorID:          "system",
	})
	if err != nil {
		return nil, "", fmt.Errorf("failed to create default %s account: %w", role, err)
	}

	keyRole := models.APIKeyRoleUser
	if role == models.AccountRoleAdmin {
		keyRole = models.APIKeyRoleAdmin
	} else if role == models.AccountRoleManager {
		keyRole = models.APIKeyRoleManager
	}

	result, err := s.apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: fmt.Sprintf("Default %s Key", strings.Title(string(role))),
		Role:       keyRole,
		OwnerID:    account.AccountID,
		CreatorID:  "system",
	})
	if err != nil {
		return nil, "", fmt.Errorf("failed to create default %s api key: %w", role, err)
	}

	return account, result.Token, nil
}

// writeTokenFile writes the plaintext token to a file in the working directory
// and returns the absolute path. It verifies the file exists and is readable.
func (s *BootstrapService) writeTokenFile(filename, token string) (string, error) {
	pwd, err := os.Getwd()
	if err != nil {
		return "", fmt.Errorf("failed to get working directory: %w", err)
	}
	path := filepath.Join(pwd, filename)

	// Restrict permissions to owner read/write only.
	if err := os.WriteFile(path, []byte(token), 0600); err != nil {
		return "", fmt.Errorf("failed to write token file %s: %w", path, err)
	}

	// Verify the file was written and is readable.
	written, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("failed to read back token file %s: %w", path, err)
	}
	if string(written) != token {
		return "", fmt.Errorf("token file %s content mismatch", path)
	}

	return path, nil
}

// logAccountStats logs counts of admin, manager, total, and status breakdown.
func (s *BootstrapService) logAccountStats(ctx context.Context) {
	var total int64
	if err := s.db.WithContext(ctx).Model(&models.Account{}).Count(&total).Error; err != nil {
		s.log.Error("bootstrap", "", "failed to count total accounts", "error", err.Error())
		return
	}
	var adminCount, managerCount int64
	if err := s.db.WithContext(ctx).Model(&models.Account{}).
		Where("role = ? AND status = ?", models.AccountRoleAdmin, models.AccountStatusActive).
		Count(&adminCount).Error; err != nil {
		s.log.Error("bootstrap", "", "failed to count admin accounts", "error", err.Error())
	}
	if err := s.db.WithContext(ctx).Model(&models.Account{}).
		Where("role = ? AND status = ?", models.AccountRoleManager, models.AccountStatusActive).
		Count(&managerCount).Error; err != nil {
		s.log.Error("bootstrap", "", "failed to count manager accounts", "error", err.Error())
	}

	statusCounts := make(map[string]int64)
	rows, err := s.db.WithContext(ctx).Model(&models.Account{}).
		Select("status, count(*) as cnt").Group("status").Rows()
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var status string
			var cnt int64
			if err := rows.Scan(&status, &cnt); err == nil {
				statusCounts[status] = cnt
			}
		}
	}

	s.log.Info("bootstrap", "", "account statistics",
		"total", total,
		"admin_active", adminCount,
		"manager_active", managerCount,
		"status_breakdown", statusCounts,
	)
}

// acquireLock attempts to acquire a distributed lock using NATS KV.
// It returns a release function on success, ErrBootstrapLockHeld if another
// node already holds the lock, or an error if the lock could not be acquired.
// There is no in-memory fallback: bootstrap requires a working distributed
// lock to prevent duplicate default accounts across ACS nodes.
func (s *BootstrapService) acquireLock(ctx context.Context, key, token string) (func(), error) {
	if s.kv == nil {
		return nil, fmt.Errorf("NATS KV is nil; distributed lock required for bootstrap")
	}

	_, err := s.kv.Create(key, []byte(token))
	if err == nil {
		// Start a background renewal goroutine.
		renewCtx, cancel := context.WithCancel(context.Background())
		done := make(chan struct{})
		go s.renewLock(renewCtx, key, token, done)

		return func() {
			cancel()
			<-done
			_ = s.kv.Delete(key)
		}, nil
	}
	if errors.Is(err, nats.ErrKeyExists) {
		// Another node holds the lock; signal the caller to skip bootstrap.
		return nil, ErrBootstrapLockHeld
	}

	// Any other NATS KV error is propagated; do not fall back to an unsafe
	// in-memory lock because cross-node coordination is required.
	return nil, fmt.Errorf("failed to create bootstrap lock key %q: %w", key, err)
}

// renewLock periodically renews the NATS KV lock until the context is cancelled.
func (s *BootstrapService) renewLock(ctx context.Context, key, token string, done chan<- struct{}) {
	defer close(done)
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			if s.kv == nil {
				return
			}
			entry, err := s.kv.Get(key)
			if err != nil {
				s.log.Warn("bootstrap", "", "failed to get lock entry for renewal", "error", err.Error())
				continue
			}
			if string(entry.Value()) != token {
				s.log.Warn("bootstrap", "", "bootstrap lock token mismatch, stopping renewal")
				return
			}
			if _, err := s.kv.Update(key, []byte(token), entry.Revision()); err != nil {
				s.log.Warn("bootstrap", "", "failed to renew bootstrap lock", "error", err.Error())
			}
		}
	}
}
