// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"

	"golang.org/x/crypto/bcrypt"
	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
)

// Common API key service errors.
var (
	ErrAPIKeyNotFound      = errors.New("api key not found")
	ErrAPIKeyInvalidToken  = errors.New("invalid api key token")
	ErrAPIKeyInactive      = errors.New("api key is inactive")
	ErrAPIKeyLimitReached  = errors.New("api key limit reached for account")
	ErrAPIKeyRoleTooHigh   = errors.New("api key role cannot exceed owner role")
	ErrManagerCannotCreate = errors.New("manager accounts cannot create api keys")
)

// CreateAPIKeyRequest holds parameters for creating an API key.
type CreateAPIKeyRequest struct {
	APIKeyName string
	Role       models.APIKeyRole
	OwnerID    string
	CreatorID  string
}

// APIKeyWithToken returns the created key together with its plaintext token.
type APIKeyWithToken struct {
	APIKey *models.APIKey
	Token  string
}

// APIKeyService provides API key lifecycle operations.
type APIKeyService struct {
	db  *gorm.DB
	cfg *config.Config
}

// NewAPIKeyService creates a new APIKeyService.
func NewAPIKeyService(db *gorm.DB, cfg *config.Config) *APIKeyService {
	return &APIKeyService{
		db:  db,
		cfg: cfg,
	}
}

// CreateAPIKey creates a new API key for an account.
func (s *APIKeyService) CreateAPIKey(ctx context.Context, req *CreateAPIKeyRequest) (*APIKeyWithToken, error) {
	if req.OwnerID == "" {
		return nil, fmt.Errorf("owner_id is required")
	}

	owner, err := s.getOwner(ctx, req.OwnerID)
	if err != nil {
		return nil, err
	}

	// Note: manager accounts cannot create API keys themselves; that check is
	// enforced at the handler level by inspecting the authenticated caller.
	// Admin users are allowed to create API keys for manager accounts as long
	// as the key role does not exceed the owner role.

	if req.Role == "" {
		req.Role = models.APIKeyRoleUser
	}
	if !isValidAPIKeyRole(req.Role) {
		return nil, fmt.Errorf("invalid api key role")
	}

	// API key role must not exceed owner role.
	if !s.roleLE(req.Role, owner.Role) {
		return nil, ErrAPIKeyRoleTooHigh
	}

	maxKeys := s.cfg.Account.APIKeyMaxPerAccount
	if maxKeys <= 0 {
		maxKeys = 10
	}
	count, err := s.countByOwner(ctx, req.OwnerID)
	if err != nil {
		return nil, err
	}
	if int(count) >= maxKeys {
		return nil, ErrAPIKeyLimitReached
	}

	secret, err := generateAPISecret()
	if err != nil {
		return nil, err
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(secret), s.bcryptCost())
	if err != nil {
		return nil, fmt.Errorf("failed to hash api key secret: %w", err)
	}

	key := &models.APIKey{
		APIKeyName: req.APIKeyName,
		APIKeyHash: string(hash),
		Role:       req.Role,
		Status:     models.APIKeyStatusActive,
		CreatorID:  req.CreatorID,
		OwnerID:    req.OwnerID,
	}

	if err := s.db.WithContext(ctx).Create(key).Error; err != nil {
		return nil, fmt.Errorf("failed to create api key: %w", err)
	}

	token := key.APIKeyID + "." + secret

	return &APIKeyWithToken{APIKey: key, Token: token}, nil
}

// VerifyAPIKey validates a Bearer token and returns the key and owner account.
func (s *APIKeyService) VerifyAPIKey(ctx context.Context, token string) (*models.APIKey, *models.Account, error) {
	parts := strings.SplitN(token, ".", 2)
	if len(parts) != 2 {
		return nil, nil, ErrAPIKeyInvalidToken
	}
	apiKeyID := parts[0]
	secret := parts[1]

	if !strings.HasPrefix(apiKeyID, "ak-") {
		return nil, nil, ErrAPIKeyInvalidToken
	}

	var key models.APIKey
	if err := s.db.WithContext(ctx).First(&key, "api_key_id = ?", apiKeyID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, nil, ErrAPIKeyNotFound
		}
		return nil, nil, fmt.Errorf("failed to find api key: %w", err)
	}

	if !key.IsActive() {
		return nil, nil, ErrAPIKeyInactive
	}

	if err := bcrypt.CompareHashAndPassword([]byte(key.APIKeyHash), []byte(secret)); err != nil {
		return nil, nil, ErrAPIKeyInvalidToken
	}

	owner, err := s.getOwner(ctx, key.OwnerID)
	if err != nil {
		return nil, nil, err
	}
	if !owner.IsActive() {
		return nil, nil, fmt.Errorf("owner account is not active")
	}

	return &key, owner, nil
}

// ListAPIKeysByOwner returns API keys belonging to an owner.
func (s *APIKeyService) ListAPIKeysByOwner(ctx context.Context, ownerID string, offset, limit int) ([]models.APIKey, int64, error) {
	if limit <= 0 {
		limit = 1000
	}
	var total int64
	if err := s.db.WithContext(ctx).Model(&models.APIKey{}).Where("owner_id = ?", ownerID).Count(&total).Error; err != nil {
		return nil, 0, fmt.Errorf("failed to count api keys: %w", err)
	}

	var keys []models.APIKey
	if err := s.db.WithContext(ctx).Where("owner_id = ?", ownerID).Order("create_at_ms desc").Offset(offset).Limit(limit).Find(&keys).Error; err != nil {
		return nil, 0, fmt.Errorf("failed to list api keys: %w", err)
	}
	return keys, total, nil
}

// DeleteAPIKey hard-deletes an API key by ID.
func (s *APIKeyService) DeleteAPIKey(ctx context.Context, apiKeyID string) error {
	if _, err := s.getByID(ctx, apiKeyID); err != nil {
		return err
	}

	if err := s.db.WithContext(ctx).Delete(&models.APIKey{}, "api_key_id = ?", apiKeyID).Error; err != nil {
		return fmt.Errorf("failed to delete api key: %w", err)
	}

	return nil
}

// DeleteAPIKeysByOwner hard-deletes all API keys for an owner.
func (s *APIKeyService) DeleteAPIKeysByOwner(ctx context.Context, ownerID string) error {
	if err := s.db.WithContext(ctx).Where("owner_id = ?", ownerID).Delete(&models.APIKey{}).Error; err != nil {
		return fmt.Errorf("failed to delete api keys by owner: %w", err)
	}
	return nil
}

// getByID retrieves an API key by ID.
func (s *APIKeyService) getByID(ctx context.Context, apiKeyID string) (*models.APIKey, error) {
	var key models.APIKey
	if err := s.db.WithContext(ctx).First(&key, "api_key_id = ?", apiKeyID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrAPIKeyNotFound
		}
		return nil, fmt.Errorf("failed to get api key: %w", err)
	}
	return &key, nil
}

// getOwner retrieves the owner account.
func (s *APIKeyService) getOwner(ctx context.Context, ownerID string) (*models.Account, error) {
	var owner models.Account
	if err := s.db.WithContext(ctx).First(&owner, "account_id = ?", ownerID).Error; err != nil {
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, ErrAccountNotFound
		}
		return nil, fmt.Errorf("failed to find owner account: %w", err)
	}
	return &owner, nil
}

// countByOwner returns the number of API keys for an owner.
func (s *APIKeyService) countByOwner(ctx context.Context, ownerID string) (int64, error) {
	var count int64
	if err := s.db.WithContext(ctx).Model(&models.APIKey{}).Where("owner_id = ?", ownerID).Count(&count).Error; err != nil {
		return 0, fmt.Errorf("failed to count api keys: %w", err)
	}
	return count, nil
}

// roleLE reports whether keyRole is less than or equal to ownerRole.
func (s *APIKeyService) roleLE(keyRole models.APIKeyRole, ownerRole models.AccountRole) bool {
	keyWeight := 0
	ownerWeight := 0
	switch keyRole {
	case models.APIKeyRoleUser:
		keyWeight = 1
	case models.APIKeyRoleManager:
		keyWeight = 2
	case models.APIKeyRoleAdmin:
		keyWeight = 3
	}
	switch ownerRole {
	case models.AccountRoleUser:
		ownerWeight = 1
	case models.AccountRoleManager:
		ownerWeight = 2
	case models.AccountRoleAdmin:
		ownerWeight = 3
	}
	return keyWeight <= ownerWeight
}

// bcryptCost returns the configured bcrypt cost.
func (s *APIKeyService) bcryptCost() int {
	cost := s.cfg.Account.BcryptCost
	if cost <= 0 {
		cost = bcrypt.DefaultCost
	}
	return cost
}

// generateAPISecret generates a URL-safe random secret.
func generateAPISecret() (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("failed to generate api secret: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}

// isValidAPIKeyRole reports whether role is a known API key role.
func isValidAPIKeyRole(role models.APIKeyRole) bool {
	switch role {
	case models.APIKeyRoleAdmin, models.APIKeyRoleManager, models.APIKeyRoleUser:
		return true
	}
	return false
}
