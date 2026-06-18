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

func TestAuthentication_Priority_APIKeyOverSession(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	log := logger.New(logger.Config{Level: "error", Output: "stdout"})
	r.Use(Logger(log))
	r.Use(Authentication(apiKeySvc, accountSvc))
	r.GET("/whoami", func(c *gin.Context) {
		ac, _ := GetAuthContext(c)
		require.NotNil(t, ac.Account)
		c.JSON(http.StatusOK, gin.H{"account_id": ac.Account.AccountID, "auth_method": string(ac.AuthMethod)})
	})
	ctx := context.Background()

	apiAccount, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "API Priority",
		LoginName:   "apipriority",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	sessionAccount, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName:   "Session Priority",
		LoginName:     "sessionpriority",
		LoginPassword: "secret",
		Role:          models.AccountRoleAdmin,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	apiKey, err := apiKeySvc.CreateAPIKey(ctx, &services.CreateAPIKeyRequest{
		APIKeyName: "priority-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    apiAccount.AccountID,
		CreatorID:  apiAccount.AccountID,
	})
	require.NoError(t, err)

	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, sessionAccount.AccountID)
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/whoami", nil)
	req.Header.Set("Authorization", "Bearer "+apiKey.Token)
	req.Header.Set("X-Session-Key", sessionKey)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Body.String(), apiAccount.AccountID)
	assert.Contains(t, w.Body.String(), "api_key")
}

func TestRequireAuthenticated_InactiveAccount(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName:   "Inactive User",
		LoginName:     "inactiveuser",
		LoginPassword: "secret",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	_, err = accountSvc.UpdateAccount(ctx, &services.UpdateAccountRequest{
		AccountID: acc.AccountID,
		Status:    ptrStatus(models.AccountStatusInactive),
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)

	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/protected", nil)
	req.Header.Set("X-Session-Key", sessionKey)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusForbidden, w.Code)
	assert.Contains(t, w.Body.String(), "account is not active")
}

func TestRequireRole_ManagerCanAccessUserRoute(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	log := logger.New(logger.Config{Level: "error", Output: "stdout"})
	r.Use(Logger(log))
	r.Use(Authentication(apiKeySvc, accountSvc))
	r.GET("/user", RequireRole(models.AccountRoleUser), func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	ctx := context.Background()

	manager, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "Manager",
		LoginName:   "manageruser",
		Role:        models.AccountRoleManager,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	managerKey, err := apiKeySvc.CreateAPIKey(ctx, &services.CreateAPIKeyRequest{
		APIKeyName: "manager-key",
		Role:       models.APIKeyRoleManager,
		OwnerID:    manager.AccountID,
		CreatorID:  manager.AccountID,
	})
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/user", nil)
	req.Header.Set("Authorization", "Bearer "+managerKey.Token)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusOK, w.Code)
}

func TestRequireRole_UnknownRole(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName:   "Unknown Role",
		LoginName:     "unknownrole",
		LoginPassword: "secret",
		Role:          models.AccountRoleUser,
		CreatorID:     "system",
	})
	require.NoError(t, err)

	// Bypass service validation to set an unknown role directly in the DB.
	err = accountSvc.(*services.AccountService).DB().WithContext(ctx).
		Model(&models.Account{}).
		Where("account_id = ?", acc.AccountID).
		Update("role", "").Error
	require.NoError(t, err)

	sessionKey, _, err := accountSvc.CreateLoginSession(ctx, acc.AccountID)
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/protected", nil)
	req.Header.Set("X-Session-Key", sessionKey)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusForbidden, w.Code)
}

func TestRequireAPIKeyRole_InsufficientRole(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	r := setupTestRouter(accountSvc, apiKeySvc)
	ctx := context.Background()

	user, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "User",
		LoginName:   "userlowrole",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
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
	req, _ := http.NewRequest("GET", "/apikey-admin", nil)
	req.Header.Set("Authorization", "Bearer "+userKey.Token)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusForbidden, w.Code)
	assert.Contains(t, w.Body.String(), "insufficient api key role")
}

func TestRequireOwnerOrAdmin_Owner(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	log := logger.New(logger.Config{Level: "error", Output: "stdout"})
	r.Use(Logger(log))
	r.Use(Authentication(apiKeySvc, accountSvc))
	r.GET("/owner/:owner_id", func(c *gin.Context) {
		ownerID := c.Param("owner_id")
		RequireOwnerOrAdmin(ownerID)(c)
	}, func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	ctx := context.Background()

	owner, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "Owner",
		LoginName:   "owneruser",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	ownerKey, err := apiKeySvc.CreateAPIKey(ctx, &services.CreateAPIKeyRequest{
		APIKeyName: "owner-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    owner.AccountID,
		CreatorID:  owner.AccountID,
	})
	require.NoError(t, err)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/owner/"+owner.AccountID, nil)
	req.Header.Set("Authorization", "Bearer "+ownerKey.Token)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusOK, w.Code)
}

func TestRequireOwnerOrAdmin_Admin(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	log := logger.New(logger.Config{Level: "error", Output: "stdout"})
	r.Use(Logger(log))
	r.Use(Authentication(apiKeySvc, accountSvc))
	r.GET("/owner/:owner_id", func(c *gin.Context) {
		ownerID := c.Param("owner_id")
		RequireOwnerOrAdmin(ownerID)(c)
	}, func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	ctx := context.Background()

	admin, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "Admin",
		LoginName:   "adminowner",
		Role:        models.AccountRoleAdmin,
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

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/owner/some-other-owner", nil)
	req.Header.Set("Authorization", "Bearer "+adminKey.Token)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusOK, w.Code)
}

func TestRequireOwnerOrAdmin_Denied(t *testing.T) {
	accountSvc, apiKeySvc := newTestServices(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	log := logger.New(logger.Config{Level: "error", Output: "stdout"})
	r.Use(Logger(log))
	r.Use(Authentication(apiKeySvc, accountSvc))
	r.GET("/owner/:owner_id", func(c *gin.Context) {
		ownerID := c.Param("owner_id")
		RequireOwnerOrAdmin(ownerID)(c)
	}, func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"ok": true})
	})
	ctx := context.Background()

	user, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "User",
		LoginName:   "userdenied",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	other, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "Other",
		LoginName:   "otheruser",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
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
	req, _ := http.NewRequest("GET", "/owner/"+other.AccountID, nil)
	req.Header.Set("Authorization", "Bearer "+userKey.Token)
	r.ServeHTTP(w, req)
	assert.Equal(t, http.StatusForbidden, w.Code)
	assert.Contains(t, w.Body.String(), "access denied")
}

func TestGetAuthContext_Missing(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())

	ac, ok := GetAuthContext(c)
	assert.False(t, ok)
	assert.Equal(t, AuthMethodNone, ac.AuthMethod)
	assert.False(t, ac.IsAuthenticated)
}

func TestRoleGE_Unknown(t *testing.T) {
	assert.False(t, accountRoleGE(models.AccountRole("unknown"), models.AccountRoleUser))
	assert.False(t, accountRoleGE(models.AccountRole("unknown"), models.AccountRole("")))
	assert.True(t, accountRoleGE(models.AccountRoleAdmin, models.AccountRole("unknown")))

	assert.False(t, apiKeyRoleGE(models.APIKeyRole("unknown"), models.APIKeyRoleUser))
	assert.False(t, apiKeyRoleGE(models.APIKeyRole("unknown"), models.APIKeyRole("")))
	assert.True(t, apiKeyRoleGE(models.APIKeyRoleAdmin, models.APIKeyRole("unknown")))
}

func ptrStatus(s models.AccountStatus) *models.AccountStatus {
	return &s
}
