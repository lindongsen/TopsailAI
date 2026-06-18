// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
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


// BootstrapService handles default admin/manager account creation on startup.
type BootstrapService struct {
	db         *gorm.DB
	cfg        *config.Config
	accountSvc *AccountService
	apiKeySvc  *APIKeyService
	auditSvc   *AuditLogService
	kv         nats.KeyValue
	log        *logger.Logger

	// inMemoryLock is used as a fallback when NATS KV is unavailable.
	inMemoryLock *sync.Mutex
}

// NewBootstrapService creates a new BootstrapService.
func NewBootstrapService(
	db *gorm.DB,
	cfg *config.Config,
	accountSvc *AccountService,
	apiKeySvc *APIKeyService,
	auditSvc *AuditLogService,
	kv nats.KeyValue,
	log *logger.Logger,
) *BootstrapService {
	return &BootstrapService{
		db:           db,
		cfg:          cfg,
		accountSvc:   accountSvc,
		apiKeySvc:    apiKeySvc,
		auditSvc:     auditSvc,
		kv:           kv,
		log:          log,
		inMemoryLock: &sync.Mutex{},
	}
}

// Run executes the startup bootstrap logic.
// It acquires a distributed lock, validates or creates default accounts, and logs statistics.
func (s *BootstrapService) Run(ctx context.Context) error {
	lockKey := "acs:lock:bootstrap:default-accounts"
	lockToken := uuid.New().String()

	release, err := s.acquireLock(ctx, lockKey, lockToken)
	if err != nil {
		if errors.Is(err, ErrBootstrapLockHeld) {
			s.log.Warn("bootstrap", "", "bootstrap lock held by another node, skipping default account creation")
			return nil
		}
		return fmt.Errorf("failed to acquire bootstrap lock: %w", err)
	}
	defer release()

	if err := s.ensureAdminAccount(ctx); err != nil {
		return err
	}

	if err := s.ensureManagerAccount(ctx); err != nil {
		return err
	}

	s.logAccountStats(ctx)
	return nil
}

// ensureAdminAccount validates or creates the default admin account.
func (s *BootstrapService) ensureAdminAccount(ctx context.Context) error {
	adminKey := s.cfg.Account.AdminAPIKey

	if adminKey != "" {
		// Validate the configured token.
		if err := s.validateConfiguredToken(ctx, adminKey, models.AccountRoleAdmin); err != nil {
			s.log.Error("bootstrap", "", "configured admin api key is invalid", "error", err.Error())
			return fmt.Errorf("configured admin api key mismatch: %w", err)
		}
		s.log.Info("bootstrap", "", "configured admin api key validated")
		return nil
	}

	// No configured key: create a default admin account if none exists.
	exists, err := s.hasAccountWithRole(ctx, models.AccountRoleAdmin)
	if err != nil {
		return err
	}
	if exists {
		s.log.Info("bootstrap", "", "admin account already exists, skipping default creation")
		return nil
	}

	account, token, err := s.createDefaultAccount(ctx, models.AccountRoleAdmin)
	if err != nil {
		return err
	}

	if err := s.writeTokenFile("ACS_ACCOUNT_ADMIN_API_KEY.acs", token); err != nil {
		return fmt.Errorf("failed to write admin api key file: %w", err)
	}

	s.log.Info("bootstrap", "", "created default admin account",
		"account_id", account.AccountID,
		"file", "ACS_ACCOUNT_ADMIN_API_KEY.acs",
	)
	return nil
}

// ensureManagerAccount validates or creates the default manager account.
func (s *BootstrapService) ensureManagerAccount(ctx context.Context) error {
	managerKey := s.cfg.Account.ManagerAPIKey

	if managerKey != "" {
		if err := s.validateConfiguredToken(ctx, managerKey, models.AccountRoleManager); err != nil {
			s.log.Error("bootstrap", "", "configured manager api key is invalid", "error", err.Error())
			return fmt.Errorf("configured manager api key mismatch: %w", err)
		}
		s.log.Info("bootstrap", "", "configured manager api key validated")
		return nil
	}

	exists, err := s.hasAccountWithRole(ctx, models.AccountRoleManager)
	if err != nil {
		return err
	}
	if exists {
		s.log.Info("bootstrap", "", "manager account already exists, skipping default creation")
		return nil
	}

	account, token, err := s.createDefaultAccount(ctx, models.AccountRoleManager)
	if err != nil {
		return err
	}

	if err := s.writeTokenFile("ACS_ACCOUNT_MANAGER_API_KEY.acs", token); err != nil {
		return fmt.Errorf("failed to write manager api key file: %w", err)
	}

	s.log.Info("bootstrap", "", "created default manager account",
		"account_id", account.AccountID,
		"file", "ACS_ACCOUNT_MANAGER_API_KEY.acs",
	)
	return nil
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

// writeTokenFile writes the plaintext token to a file in the working directory.
func (s *BootstrapService) writeTokenFile(filename, token string) error {
	pwd, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("failed to get working directory: %w", err)
	}
	path := filepath.Join(pwd, filename)

	// Restrict permissions to owner read/write only.
	if err := os.WriteFile(path, []byte(token), 0600); err != nil {
		return fmt.Errorf("failed to write token file: %w", err)
	}
	return nil
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

// acquireLock attempts to acquire a distributed lock using NATS KV, falling
// back to an in-memory lock when NATS KV is unavailable.
func (s *BootstrapService) acquireLock(ctx context.Context, key, token string) (func(), error) {
	if s.kv != nil {
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
		// NATS KV error but not because key exists; fall back to in-memory.
		s.log.Warn("bootstrap", "", "failed to acquire distributed lock, falling back to in-memory lock", "error", err.Error())
	}

	// In-memory fallback.
	s.inMemoryLock.Lock()
	return func() {
		s.inMemoryLock.Unlock()
	}, nil
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
