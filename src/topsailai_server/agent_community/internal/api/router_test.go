package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// setupRouterTestDB creates an in-memory SQLite database and auto-migrates all models.
func setupRouterTestDB(t *testing.T) *gorm.DB {
	db, err := gorm.Open(sqlite.Open("file::memory:"), &gorm.Config{})
	require.NoError(t, err, "failed to open sqlite database")
	require.NoError(t, db.AutoMigrate(
		&models.Group{},
		&models.GroupMember{},
		&models.GroupMessage{},
		&models.AgentMessageProcessing{},
		&models.Account{},
		&models.APIKey{},
		&models.AuditLog{},
	), "failed to migrate database")
	return db
}

// setupRouterTestConfig returns a minimal config with low bcrypt cost for fast tests.
func setupRouterTestConfig() *config.Config {
	return &config.Config{
		Server: config.ServerConfig{
			Port:         7370,
			ReadTimeout:  30 * time.Second,
			WriteTimeout: 30 * time.Second,
		},
		Database: config.DatabaseConfig{
			Driver: "sqlite",
			Name:   ":memory:",
		},
		Agent: config.AgentConfig{
			AutoTriggerTimeout: 10 * time.Minute,
		},
		AgentWorkPool: config.AgentWorkPoolConfig{
			PerNode:          10,
			PerUser:          5,
			PerGroup:         5,
			StatsLogInterval: 30 * time.Second,
		},
		Account: config.AccountConfig{
			APIKeyMaxPerAccount:       10,
			LoginSessionExpirySeconds: 86400,
			BcryptCost:                4,
		},
		Log: config.LogConfig{
			Output: "stdout",
			Level:  "error",
		},
		Discovery: config.DiscoveryConfig{
			Enabled: false,
		},
	}
}

// setupRouterTestDependencies creates services, handlers, and a router for testing.
// nil publisher/discovery is acceptable because the tested routes do not exercise publish/discovery logic.
func setupRouterTestDependencies(t *testing.T, db *gorm.DB) (*Router, *services.AccountService, *services.APIKeyService) {
	cfg := setupRouterTestConfig()
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})

	auditSvc := services.NewAuditLogService(db)
	accountSvc := services.NewAccountService(db, cfg, auditSvc)
	apiKeySvc := services.NewAPIKeyService(db, cfg, auditSvc)
	accountSvc.SetAPIKeyService(apiKeySvc)

	router := NewRouter(cfg, db, nil, nil, nil, log)
	require.NotNil(t, router, "router should not be nil")

	return router, accountSvc, apiKeySvc
}

// createTestAccountAndAPIKey creates an account and an API key with the given role.
func createTestAccountAndAPIKey(t *testing.T, accountSvc *services.AccountService, apiKeySvc *services.APIKeyService, role models.AccountRole) (*models.Account, string) {
	ctx := t.Context()
	unique := time.Now().UnixNano()
	account, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName:   "Test Account",
		Role:          role,
		LoginName:     fmt.Sprintf("test-%s-%d@example.com", role, unique),
		LoginPassword: "password123",
		CreatorID:     "system",
	})
	require.NoError(t, err, "failed to create account")

	keyRole := models.APIKeyRoleUser
	switch role {
	case models.AccountRoleManager:
		keyRole = models.APIKeyRoleManager
	case models.AccountRoleAdmin:
		keyRole = models.APIKeyRoleAdmin
	}

	result, err := apiKeySvc.CreateAPIKey(ctx, &services.CreateAPIKeyRequest{
		APIKeyName: "test-key",
		Role:       keyRole,
		OwnerID:    account.AccountID,
		CreatorID:  account.AccountID,
	})
	require.NoError(t, err, "failed to create api key")

	return account, result.Token
}

// TestNewRouter_PublicHealthz verifies that GET /healthz is accessible without authentication.
func TestNewRouter_PublicHealthz(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, _, _ := setupRouterTestDependencies(t, db)

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	w := httptest.NewRecorder()
	router.Engine().ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	assert.Contains(t, w.Body.String(), "alive")
}

// TestNewRouter_LoginWithoutAuth verifies that POST /api/v1/accounts/login does not require auth.
func TestNewRouter_LoginWithoutAuth(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, accountSvc, _ := setupRouterTestDependencies(t, db)

	ctx := t.Context()
	account, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName:   "Login User",
		Role:          models.AccountRoleUser,
		LoginName:     "login-user@example.com",
		LoginPassword: "secure-password",
		CreatorID:     "system",
	})
	require.NoError(t, err, "failed to create account")

	body := map[string]string{
		"login_name": "login-user@example.com",
		"password":   "secure-password",
	}
	jsonBody, _ := json.Marshal(body)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts/login", bytes.NewBuffer(jsonBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.Engine().ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	assert.Contains(t, w.Body.String(), account.AccountID)
	assert.Contains(t, w.Body.String(), "session_key")
}

// TestNewRouter_ProtectedRequiresAuth verifies that GET /api/v1/accounts/me returns 401 without auth.
func TestNewRouter_ProtectedRequiresAuth(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, _, _ := setupRouterTestDependencies(t, db)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/accounts/me", nil)
	w := httptest.NewRecorder()
	router.Engine().ServeHTTP(w, req)

	require.Equal(t, http.StatusUnauthorized, w.Code, "body: %s", w.Body.String())
}

// TestNewRouter_AdminRouteDeniedToUser verifies that a user API key cannot delete accounts.
func TestNewRouter_AdminRouteDeniedToUser(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, accountSvc, apiKeySvc := setupRouterTestDependencies(t, db)

	_, userToken := createTestAccountAndAPIKey(t, accountSvc, apiKeySvc, models.AccountRoleUser)

	// Create a target account to delete.
	ctx := t.Context()
	target, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName: "Target Account",
		Role:        models.AccountRoleUser,
		LoginName:   "target@example.com",
		CreatorID:   "system",
	})
	require.NoError(t, err, "failed to create target account")

	req := httptest.NewRequest(http.MethodDelete, fmt.Sprintf("/api/v1/accounts/%s", target.AccountID), nil)
	req.Header.Set("Authorization", "Bearer "+userToken)
	w := httptest.NewRecorder()
	router.Engine().ServeHTTP(w, req)

	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

// TestNewRouter_ManagerCanCreateAccount verifies that a manager API key can create user accounts.
func TestNewRouter_ManagerCanCreateAccount(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, accountSvc, apiKeySvc := setupRouterTestDependencies(t, db)

	_, managerToken := createTestAccountAndAPIKey(t, accountSvc, apiKeySvc, models.AccountRoleManager)

	body := map[string]string{
		"account_name": "New User",
		"role":         "user",
		"login_name":   "new-user@example.com",
	}
	jsonBody, _ := json.Marshal(body)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+managerToken)
	w := httptest.NewRecorder()
	router.Engine().ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	assert.Contains(t, w.Body.String(), "new-user@example.com")
}

// TestNewRouter_EngineNotNil verifies that Engine() returns a non-nil gin engine.
func TestNewRouter_EngineNotNil(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, _, _ := setupRouterTestDependencies(t, db)

	assert.NotNil(t, router.Engine())
}

// TestNewRouter_RouteTable verifies that the expected routes are registered.
func TestNewRouter_RouteTable(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, _, _ := setupRouterTestDependencies(t, db)

	expectedRoutes := map[string]bool{
		"GET /healthz":                                  false,
		"GET /readyz":                                   false,
		"GET /health":                                   false,
		"GET /health/leader":                            false,
		"GET /discovery/services":                       false,
		"POST /api/v1/accounts/login":                   false,
		"GET /api/v1/accounts/me":                       false,
		"GET /api/v1/accounts":                          false,
		"POST /api/v1/accounts":                         false,
		"GET /api/v1/accounts/:account_id":              false,
		"PUT /api/v1/accounts/:account_id":              false,
		"DELETE /api/v1/accounts/:account_id":           false,
		"POST /api/v1/accounts/:account_id/password":    false,
		"POST /api/v1/accounts/:account_id/session":     false,
		"GET /api/v1/accounts/:account_id/api-keys":     false,
		"POST /api/v1/accounts/:account_id/api-keys":    false,
		"DELETE /api/v1/accounts/:account_id/api-keys/:api_key_id": false,
		"GET /api/v1/audit-logs":                        false,
		"GET /api/v1/audit-logs/:audit_log_id":          false,
		"GET /api/v1/groups":                            false,
		"POST /api/v1/groups":                           false,
		"GET /api/v1/groups/:group_id":                  false,
		"PUT /api/v1/groups/:group_id":                  false,
		"DELETE /api/v1/groups/:group_id":               false,
		"GET /api/v1/groups/:group_id/members":          false,
		"POST /api/v1/groups/:group_id/members":         false,
		"PUT /api/v1/groups/:group_id/members/:member_id":    false,
		"DELETE /api/v1/groups/:group_id/members/:member_id": false,
		"GET /api/v1/groups/:group_id/messages":         false,
		"POST /api/v1/groups/:group_id/messages":        false,
		"PUT /api/v1/groups/:group_id/messages/:message_id":    false,
		"DELETE /api/v1/groups/:group_id/messages/:message_id": false,
		"POST /api/v1/groups/:group_id/messages/:message_id/trigger": false,
	}

	registered := make(map[string]bool)
	routes := router.Engine().Routes()
	for _, route := range routes {
		key := route.Method + " " + route.Path
		registered[key] = true
		if _, ok := expectedRoutes[key]; ok {
			expectedRoutes[key] = true
		}
	}

	missing := []string{}
	for route, found := range expectedRoutes {
		if !found {
			missing = append(missing, route)
		}
	}
	assert.Empty(t, missing, "expected routes not registered; registered routes: %v", registered)
}
