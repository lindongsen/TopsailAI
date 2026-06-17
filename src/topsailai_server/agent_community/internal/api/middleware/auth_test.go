// Package middleware provides HTTP middleware for the ACS API.
package middleware

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/schema"
)

// newTestDB creates an in-memory SQLite database for middleware tests.
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
func newTestServices(t *testing.T) (*services.AccountService, *services.APIKeyService) {
	t.Helper()
	db := newTestDB(t)
	cfg := &config.Config{
		Account: config.AccountConfig{
			APIKeyMaxPerAccount:       10,
			LoginSessionExpirySeconds: 86400,
			BcryptCost:                4,
		},
	}
	auditSvc := services.NewAuditLogService(db)
	accountSvc := services.NewAccountService(db, cfg, auditSvc)
	apiKeySvc := services.NewAPIKeyService(db, cfg, auditSvc)
	accountSvc.SetAPIKeyService(apiKeySvc)
	return accountSvc, apiKeySvc
}

func setupTestRouter(accountSvc *services.AccountService, apiKeySvc *services.APIKeyService) *gin.Engine {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	log := logger.New(logger.Config{Level: "error", Output: "stdout"})
	r.Use(Logger(log))
	r.Use(Authentication(apiKeySvc, accountSvc))
	r.GET("/protected", RequireAuthenticated(), func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	r.GET("/admin", RequireRole(models.AccountRoleAdmin), func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	r.GET("/apikey-admin", RequireAPIKeyRole(models.APIKeyRoleAdmin), func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	return r
}

func TestAuthentication_ValidAPIKey(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "API User",
		LoginName:   "apiuser",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &services.CreateAPIKeyRequest{
		APIKeyName: "test-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    acc.AccountID,
		CreatorID:  acc.AccountID,
	})
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/protected", nil)
	req.Header.Set("Authorization", "Bearer "+key.Token)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestAuthentication_ValidSessionKey(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName:   "Session User",
		LoginName:     "sessionuser",
		LoginPassword: "secret",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/protected", nil)
	req.Header.Set("X-Session-Key", sessionKey)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
}

func TestAuthentication_MissingCredentials(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/protected", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestAuthentication_InvalidToken(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/protected", nil)
	req.Header.Set("Authorization", "Bearer invalid-token")
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusUnauthorized, w.Code)
}

func TestRequireRole_AdminOnly(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)
	ctx := context.Background()

	admin, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "Admin",
		LoginName:   "adminuser",
		Role:        models.AccountRoleAdmin,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	user, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "User",
		LoginName:   "normaluser",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	adminKey, err := apiKeySvc.CreateAPIKey(ctx, &services.CreateAPIKeyRequest{
		APIKeyName: "admin-key",
		Role:       models.APIKeyRoleAdmin,
		OwnerID:    admin.AccountID,
		CreatorID:  admin.AccountID,
	})
	require.NoError(t, err)

	userKey, err := apiKeySvc.CreateAPIKey(ctx, &services.CreateAPIKeyRequest{
		APIKeyName: "user-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    user.AccountID,
		CreatorID:  user.AccountID,
	})
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/admin", nil)
	req.Header.Set("Authorization", "Bearer "+adminKey.Token)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusOK, w.Code)

	w = httptest.NewRecorder()
	req, _ = http.NewRequest("GET", "/admin", nil)
	req.Header.Set("Authorization", "Bearer "+userKey.Token)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusForbidden, w.Code)
}

func TestRequireAPIKeyRole_RequiresAPIKeyAuth(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName:   "Session Admin",
		LoginName:     "sessionadmin",
		LoginPassword: "secret",
		Role:          models.AccountRoleAdmin,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/apikey-admin", nil)
	req.Header.Set("X-Session-Key", sessionKey)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusUnauthorized, w.Code)
}
