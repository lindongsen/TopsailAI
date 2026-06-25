// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"
	"time"

	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
)

// Common account service errors.
var (
	ErrAccountNotFound      = errors.New("account not found")
	ErrDuplicateLoginName   = errors.New("login name already exists")
	ErrInvalidRole          = errors.New("invalid account role")
	ErrRoleNotAllowed       = errors.New("caller role cannot create accounts with this role")
	ErrInvalidStatus        = errors.New("invalid account status")
	ErrPasswordNotSet       = errors.New("password login is disabled for this account")
	ErrAccountInactive      = errors.New("account is not active")
	ErrInvalidSession       = errors.New("invalid or expired session")
	ErrSessionFormatInvalid = errors.New("invalid session key format")
)

// AccountRoleWeight maps roles to their hierarchy weight.
// Higher weight means more privileges.
var AccountRoleWeight = map[models.AccountRole]int{
	models.AccountRoleUser:    1,
	models.AccountRoleManager: 2,
	models.AccountRoleAdmin:   3,
}

// ListAccountsFilter holds optional filters for listing accounts.
type ListAccountsFilter struct {
	Role       models.AccountRole
	Status     models.AccountStatus
	ExternalID string
	CallerRole models.AccountRole
	CallerID   string
}

// CreateAccountRequest holds parameters for creating an account.
type CreateAccountRequest struct {
	AccountName        string
	AccountDescription string
	Role               models.AccountRole
	LoginName          string
	LoginPassword      string
	ExternalID         string
	Email              string
	AuthProvider       string
	AvatarURL          string
	CreatorID          string
	CallerRole         models.AccountRole
}

// UpdateAccountRequest holds parameters for updating an account.
type UpdateAccountRequest struct {
	AccountID          string
	AccountName        *string
	AccountDescription *string
	Role               *models.AccountRole
	Status             *models.AccountStatus
	ExternalID         *string
	Email              *string
	AuthProvider       *string
	AvatarURL          *string
	CallerRole         models.AccountRole
}

// AccountService provides account lifecycle operations.
type AccountService struct {
	db        *gorm.DB
	cfg       *config.Config
	apiKeySvc *APIKeyService
}

// NewAccountService creates a new AccountService.
func NewAccountService(db *gorm.DB, cfg *config.Config) *AccountService {
	return &AccountService{
		db:  db,
		cfg: cfg,
	}
}

// SetAPIKeyService injects the API key service for cascade operations.
// It is set separately to avoid a circular dependency during construction.
func (s *AccountService) SetAPIKeyService(apiKeySvc *APIKeyService) {
	s.apiKeySvc = apiKeySvc
}

// DB returns the underlying GORM database handle.
// Exposed for tests that need to manipulate state directly.
func (s *AccountService) DB() *gorm.DB {
	return s.db
}

// CreateAccount creates a new account with optional password hashing.
func (s *AccountService) CreateAccount(ctx context.Context, req *CreateAccountRequest) (*models.Account, error) {
	if req.Role == "" {
		req.Role = models.AccountRoleUser
	}
	if !isValidAccountRole(req.Role) {
		return nil, ErrInvalidRole
	}
	if req.LoginName == "" {
		return nil, fmt.Errorf("login_name is required")
	}

	// Enforce role hierarchy: manager can only create user accounts.
	if req.CallerRole == models.AccountRoleManager && req.Role != models.AccountRoleUser {
		return nil, ErrRoleNotAllowed
	}

	account := &models.Account{
		AccountName:        req.AccountName,
		AccountDescription: req.AccountDescription,
		Role:               req.Role,
		Status:             models.AccountStatusActive,
		CreatorID:          req.CreatorID,
		ExternalID:         req.ExternalID,
		Email:              req.Email,
		AuthProvider:       req.AuthProvider,
		AvatarURL:          req.AvatarURL,
		LoginName:          req.LoginName,
	}

	if req.LoginPassword != "" {
		hash, err := s.hashPassword(req.LoginPassword)
		if err != nil {
			return nil, fmt.Errorf("failed to hash password: %w", err)
		}
		account.LoginPassword = hash
	}

	if err := s.db.WithContext(ctx).Create(account).Error; err != nil {
		if isUniqueViolation(err) {
			return nil, ErrDuplicateLoginName
		}
		return nil, fmt.Errorf("failed to create account: %w", err)
	}

	return account, nil
}

// GetAccountByID retrieves an account by its ID.
func (s *AccountService) GetAccountByID(ctx context.Context, accountID string) (*models.Account, error) {
	var account models.Account
	if err := s.db.WithContext(ctx).First(&account, "account_id = ?", accountID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrAccountNotFound
		}
		return nil, fmt.Errorf("failed to get account: %w", err)
	}
	return &account, nil
}

// GetAccountByLoginName retrieves an account by its unique login name.
func (s *AccountService) GetAccountByLoginName(ctx context.Context, loginName string) (*models.Account, error) {
	var account models.Account
	if err := s.db.WithContext(ctx).First(&account, "login_name = ?", loginName).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrAccountNotFound
		}
		return nil, fmt.Errorf("failed to get account by login_name: %w", err)
	}
	return &account, nil
}

// GetAccountByExternalID retrieves an account by external ID.
func (s *AccountService) GetAccountByExternalID(ctx context.Context, externalID string) (*models.Account, error) {
	var account models.Account
	if err := s.db.WithContext(ctx).First(&account, "external_id = ?", externalID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrAccountNotFound
		}
		return nil, fmt.Errorf("failed to get account by external_id: %w", err)
	}
	return &account, nil
}

// ListAccounts returns a paginated list of accounts and the total count.
// Filters are applied in the database query. Visibility restrictions based on
// CallerRole are also applied here so that pagination and total counts are
// consistent with what the caller is allowed to see.
func (s *AccountService) ListAccounts(ctx context.Context, offset, limit int, filter *ListAccountsFilter) ([]models.Account, int64, error) {
	if limit <= 0 {
		limit = 1000
	}

	query := s.db.WithContext(ctx).Model(&models.Account{})

	// Apply caller-provided query filters first.
	if filter != nil {
		if filter.Role != "" {
			query = query.Where("role = ?", filter.Role)
		}
		if filter.Status != "" {
			query = query.Where("status = ?", filter.Status)
		}
		if filter.ExternalID != "" {
			query = query.Where("external_id = ?", filter.ExternalID)
		}
	}

	// Apply visibility restrictions unless this is an internal/admin call.
	if filter != nil && filter.CallerRole != "" {
		switch filter.CallerRole {
		case models.AccountRoleAdmin:
			// Admin can see everything, including deleted accounts, but only when
			// no status filter is supplied. If a status filter is supplied, it was
			// already applied above.
			if filter.Status == "" {
				query = query.Where("status != ?", models.AccountStatusDeleted)
			}
		case models.AccountRoleManager:
			// Manager sees non-deleted user accounts and their own account.
			query = query.Where("status != ? AND (role = ? OR account_id = ?)", models.AccountStatusDeleted, models.AccountRoleUser, filter.CallerID)
		case models.AccountRoleUser:
			// User can list all non-deleted accounts for discovery.
			query = query.Where("status != ?", models.AccountStatusDeleted)
		default:
			query = query.Where("status != ?", models.AccountStatusDeleted)
		}
	} else {
		// Internal/service callers without a caller role should not see deleted accounts
		// unless explicitly requested via the status filter.
		if filter == nil || filter.Status == "" {
			query = query.Where("status != ?", models.AccountStatusDeleted)
		}
	}

	var total int64
	if err := query.Count(&total).Error; err != nil {
		return nil, 0, fmt.Errorf("failed to count accounts: %w", err)
	}

	var accounts []models.Account
	if err := query.Order("create_at_ms desc").Offset(offset).Limit(limit).Find(&accounts).Error; err != nil {
		return nil, 0, fmt.Errorf("failed to list accounts: %w", err)
	}
	return accounts, total, nil
}

// UpdateAccount updates account fields with caller role checks.
func (s *AccountService) UpdateAccount(ctx context.Context, req *UpdateAccountRequest) (*models.Account, error) {
	account, err := s.GetAccountByID(ctx, req.AccountID)
	if err != nil {
		return nil, err
	}

	callerWeight := AccountRoleWeight[req.CallerRole]
	if callerWeight == 0 {
		return nil, fmt.Errorf("invalid caller role")
	}

	// Caller cannot modify an account with a higher role.
	if AccountRoleWeight[account.Role] > callerWeight {
		return nil, fmt.Errorf("insufficient privileges to modify this account")
	}

	if req.AccountName != nil {
		account.AccountName = *req.AccountName
	}
	if req.AccountDescription != nil {
		account.AccountDescription = *req.AccountDescription
	}
	if req.ExternalID != nil {
		account.ExternalID = *req.ExternalID
	}
	if req.Email != nil {
		account.Email = *req.Email
	}
	if req.AuthProvider != nil {
		account.AuthProvider = *req.AuthProvider
	}
	if req.AvatarURL != nil {
		account.AvatarURL = *req.AvatarURL
	}
	if req.Status != nil {
		if !isValidAccountStatus(*req.Status) {
			return nil, ErrInvalidStatus
		}
		account.Status = *req.Status
	}
	if req.Role != nil {
		if !isValidAccountRole(*req.Role) {
			return nil, ErrInvalidRole
		}
		// Target role cannot exceed caller role.
		if AccountRoleWeight[*req.Role] > callerWeight {
			return nil, fmt.Errorf("cannot assign role higher than caller role")
		}
		account.Role = *req.Role
	}

	if err := s.db.WithContext(ctx).Save(account).Error; err != nil {
		return nil, fmt.Errorf("failed to update account: %w", err)
	}

	return account, nil
}

// SoftDeleteAccount marks an account as deleted and hard-deletes its API keys.
func (s *AccountService) SoftDeleteAccount(ctx context.Context, accountID string) error {
	account, err := s.GetAccountByID(ctx, accountID)
	if err != nil {
		return err
	}

	now := time.Now().UnixMilli()
	account.Status = models.AccountStatusDeleted
	account.DeleteAtMs = now

	if err := s.db.WithContext(ctx).Save(account).Error; err != nil {
		return fmt.Errorf("failed to soft-delete account: %w", err)
	}

	if s.apiKeySvc != nil {
		if err := s.apiKeySvc.DeleteAPIKeysByOwner(ctx, accountID); err != nil {
			return fmt.Errorf("failed to cascade delete api keys: %w", err)
		}
	}

	return nil
}

// ChangePassword updates the login password for an account and invalidates
// any existing login session so that active sessions cannot outlive a password change.
func (s *AccountService) ChangePassword(ctx context.Context, accountID, newPassword string) error {
	if newPassword == "" {
		return fmt.Errorf("password cannot be empty")
	}
	account, err := s.GetAccountByID(ctx, accountID)
	if err != nil {
		return err
	}

	hash, err := s.hashPassword(newPassword)
	if err != nil {
		return fmt.Errorf("failed to hash password: %w", err)
	}

	account.LoginPassword = hash
	account.LoginSessionKey = ""
	account.LoginSessionExpiredTime = 0
	if err := s.db.WithContext(ctx).Save(account).Error; err != nil {
		return fmt.Errorf("failed to change password: %w", err)
	}

	return nil
}

// CreateLoginSession generates a new session key for an account.
// The returned sessionKey is the plaintext value to return to the client.
func (s *AccountService) CreateLoginSession(ctx context.Context, accountID string) (string, int64, error) {
	account, err := s.GetAccountByID(ctx, accountID)
	if err != nil {
		return "", 0, err
	}
	if !account.IsActive() {
		return "", 0, fmt.Errorf("account is not active")
	}

	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", 0, fmt.Errorf("failed to generate session key: %w", err)
	}
	secret := base64.RawURLEncoding.EncodeToString(raw)
	sessionKey := accountID + "-" + secret

	hash, err := s.hashPassword(secret)
	if err != nil {
		return "", 0, fmt.Errorf("failed to hash session key: %w", err)
	}

	expiry := time.Now().Add(time.Duration(s.cfg.Account.LoginSessionExpirySeconds) * time.Second).UnixMilli()
	account.LoginSessionKey = hash
	account.LoginSessionExpiredTime = expiry

	if err := s.db.WithContext(ctx).Save(account).Error; err != nil {
		return "", 0, fmt.Errorf("failed to save session: %w", err)
	}

	return sessionKey, expiry, nil
}

// ValidateLoginSession validates a plaintext session key and returns the account.
// The session key format is {account_id}-{secret}. Because account_id itself
// contains a hyphen (e.g. acc-xxx), we reconstruct account_id from the first
// two hyphen-separated segments and treat the remainder as the secret.
func (s *AccountService) ValidateLoginSession(ctx context.Context, sessionKey string) (*models.Account, error) {
	parts := strings.Split(sessionKey, "-")
	if len(parts) < 3 {
		return nil, ErrSessionFormatInvalid
	}
	accountID := parts[0] + "-" + parts[1]
	secret := strings.Join(parts[2:], "-")

	account, err := s.GetAccountByID(ctx, accountID)
	if err != nil {
		return nil, err
	}
	if !account.IsActive() {
		return nil, ErrInvalidSession
	}
	if account.LoginSessionKey == "" {
		return nil, ErrInvalidSession
	}
	if time.Now().UnixMilli() > account.LoginSessionExpiredTime {
		return nil, ErrInvalidSession
	}
	if err := bcrypt.CompareHashAndPassword([]byte(account.LoginSessionKey), []byte(secret)); err != nil {
		return nil, ErrInvalidSession
	}
	return account, nil
}

// EnsureLoginSession returns a valid plaintext login session key for the account.
// If the account has no session or the existing session has expired, a new session
// is generated, persisted, and returned. The caller receives the plaintext key
// suitable for forwarding to agent environments.
func (s *AccountService) EnsureLoginSession(ctx context.Context, accountID string) (string, int64, error) {
	account, err := s.GetAccountByID(ctx, accountID)
	if err != nil {
		return "", 0, err
	}
	if !account.IsActive() {
		return "", 0, fmt.Errorf("account is not active")
	}

	// Because we only store a bcrypt hash of the session key, the plaintext key
	// is not recoverable. Always create a fresh session so the caller has a
	// usable plaintext key.
	return s.CreateLoginSession(ctx, accountID)
}

// LoginByPassword validates login credentials and creates a session.
func (s *AccountService) LoginByPassword(ctx context.Context, loginName, password string) (*models.Account, string, int64, error) {
	var account models.Account
	if err := s.db.WithContext(ctx).First(&account, "login_name = ?", loginName).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, "", 0, ErrAccountNotFound
		}
		return nil, "", 0, fmt.Errorf("failed to find account: %w", err)
	}
	if !account.IsActive() {
		return nil, "", 0, ErrAccountInactive
	}
	if account.LoginPassword == "" {
		return nil, "", 0, ErrPasswordNotSet
	}
	if err := bcrypt.CompareHashAndPassword([]byte(account.LoginPassword), []byte(password)); err != nil {
		return nil, "", 0, fmt.Errorf("invalid password")
	}

	sessionKey, expiry, err := s.CreateLoginSession(ctx, account.AccountID)
	if err != nil {
		return nil, "", 0, err
	}

	return &account, sessionKey, expiry, nil
}

// ValidateLoginPassword validates login credentials without creating a session.
// It is intended for stateless middleware authentication where a session should
// not be generated automatically.
func (s *AccountService) ValidateLoginPassword(ctx context.Context, loginName, password string) (*models.Account, error) {
	var account models.Account
	if err := s.db.WithContext(ctx).First(&account, "login_name = ?", loginName).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrAccountNotFound
		}
		return nil, fmt.Errorf("failed to find account: %w", err)
	}
	if !account.IsActive() {
		return nil, fmt.Errorf("account is not active")
	}
	if account.LoginPassword == "" {
		return nil, ErrPasswordNotSet
	}
	if err := bcrypt.CompareHashAndPassword([]byte(account.LoginPassword), []byte(password)); err != nil {
		return nil, fmt.Errorf("invalid password")
	}
	return &account, nil
}

// hashPassword hashes a password using bcrypt with configured cost.
func (s *AccountService) hashPassword(password string) (string, error) {
	cost := s.cfg.Account.BcryptCost
	if cost <= 0 {
		cost = bcrypt.DefaultCost
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), cost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

// isValidAccountRole reports whether role is a known account role.
func isValidAccountRole(role models.AccountRole) bool {
	switch role {
	case models.AccountRoleAdmin, models.AccountRoleManager, models.AccountRoleUser:
		return true
	}
	return false
}

// isValidAccountStatus reports whether status is a known account status.
func isValidAccountStatus(status models.AccountStatus) bool {
	switch status {
	case models.AccountStatusActive, models.AccountStatusInactive, models.AccountStatusDeleted:
		return true
	}
	return false
}

// isUniqueViolation checks whether an error is a unique constraint violation.
func isUniqueViolation(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "unique") || strings.Contains(msg, "duplicate")
}
