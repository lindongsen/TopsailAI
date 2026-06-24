package api

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/discovery"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// fakeDiscovery is a test double for the discovery provider.
type fakeDiscovery struct{}

func (f *fakeDiscovery) Enabled() bool { return true }

func (f *fakeDiscovery) Discover() ([]discovery.ServiceInfo, error) {
	return []discovery.ServiceInfo{}, nil
}

func (f *fakeDiscovery) IsLeader() (bool, error) {
	return true, nil
}

func (f *fakeDiscovery) LeaderInfo() (*discovery.ServiceInfo, error) {
	return &discovery.ServiceInfo{ID: "leader-1", Name: "acs"}, nil
}

func (f *fakeDiscovery) SelfInfo() discovery.ServiceInfo {
	return discovery.ServiceInfo{ID: "self-1", Name: "acs"}
}
// routerTestDBCounter generates unique names for in-memory SQLite databases so
// that parallel and sequential tests do not share the same shared-cache database.
var routerTestDBCounter int64

// setupRouterTestDB creates an in-memory SQLite database and auto-migrates all models.
func setupRouterTestDB(t *testing.T) *gorm.DB {
	dbName := fmt.Sprintf("file:router_test_%d?mode=memory&cache=shared", atomic.AddInt64(&routerTestDBCounter, 1))
	db, err := gorm.Open(sqlite.Open(dbName), &gorm.Config{})
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
func setupRouterTestDependencies(t *testing.T, db *gorm.DB) (*Router, *services.AccountService, *services.APIKeyService) {
	cfg := setupRouterTestConfig()
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})

	accountSvc := services.NewAccountService(db, cfg)
	apiKeySvc := services.NewAPIKeyService(db, cfg)
	accountSvc.SetAPIKeyService(apiKeySvc)

	disc := &fakeDiscovery{}
	router := NewRouter(cfg, db, nil, nil, disc, log)
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

// TestNewRouter_PublicEndpoints verifies that all public endpoints are accessible without authentication.
func TestNewRouter_PublicEndpoints(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, accountSvc, _ := setupRouterTestDependencies(t, db)

	// Seed an account for the login endpoint.
	ctx := t.Context()
	_, err := accountSvc.CreateAccount(ctx, &services.CreateAccountRequest{
		AccountName:   "Login User",
		Role:          models.AccountRoleUser,
		LoginName:     "login-user@example.com",
		LoginPassword: "secure-password",
		CreatorID:     "system",
	})
	require.NoError(t, err, "failed to create account")

	publicGETs := []string{
		"/healthz",
		"/readyz",
		"/health",
		"/health/leader",
		"/discovery/services",
	}

	for _, path := range publicGETs {
		t.Run(path, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, path, nil)
			w := httptest.NewRecorder()
			router.Engine().ServeHTTP(w, req)
			assert.NotEqual(t, http.StatusUnauthorized, w.Code, "public endpoint %s returned 401", path)
		})
	}

	t.Run("POST /api/v1/accounts/login", func(t *testing.T) {
		body := map[string]string{
			"login_name":     "login-user@example.com",
			"login_password": "secure-password",
		}
		jsonBody, _ := json.Marshal(body)
		req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts/login", bytes.NewBuffer(jsonBody))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		router.Engine().ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	})
}

// TestNewRouter_ProtectedEndpointsRequireAuth verifies that protected routes reject unauthenticated requests.
func TestNewRouter_ProtectedEndpointsRequireAuth(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, _, _ := setupRouterTestDependencies(t, db)

	protected := []struct {
		method string
		path   string
		body   string
	}{
		{http.MethodGet, "/api/v1/accounts", ""},
		{http.MethodGet, "/api/v1/accounts/me", ""},
		{http.MethodPost, "/api/v1/accounts", `{"account_name":"x","role":"user","login_name":"x@x.com"}`},
		{http.MethodGet, "/api/v1/accounts/acc-1", ""},
		{http.MethodPut, "/api/v1/accounts/acc-1", `{"account_name":"x"}`},
		{http.MethodDelete, "/api/v1/accounts/acc-1", ""},
		{http.MethodPost, "/api/v1/accounts/acc-1/password", `{"new_password":"x"}`},
		{http.MethodPost, "/api/v1/accounts/acc-1/session", ""},
		{http.MethodGet, "/api/v1/accounts/acc-1/api-keys", ""},
		{http.MethodPost, "/api/v1/accounts/acc-1/api-keys", `{"api_key_name":"x","role":"user"}`},
		{http.MethodDelete, "/api/v1/accounts/acc-1/api-keys/ak-1", ""},
		{http.MethodGet, "/api/v1/audit-logs", ""},
		{http.MethodGet, "/api/v1/audit-logs/al-1", ""},
		{http.MethodGet, "/api/v1/groups", ""},
		{http.MethodPost, "/api/v1/groups", `{"group_name":"x"}`},
		{http.MethodGet, "/api/v1/groups/group-1", ""},
		{http.MethodPut, "/api/v1/groups/group-1", `{"group_name":"x"}`},
		{http.MethodDelete, "/api/v1/groups/group-1", ""},
		{http.MethodGet, "/api/v1/groups/group-1/members", ""},
		{http.MethodPost, "/api/v1/groups/group-1/members", `{"member_id":"m1","member_name":"x","member_type":"user"}`},
		{http.MethodPut, "/api/v1/groups/group-1/members/m1", `{"member_name":"x"}`},
		{http.MethodDelete, "/api/v1/groups/group-1/members/m1", ""},
		{http.MethodGet, "/api/v1/groups/group-1/messages", ""},
		{http.MethodPost, "/api/v1/groups/group-1/messages", `{"message_text":"x"}`},
		{http.MethodPut, "/api/v1/groups/group-1/messages/msg-1", `{"message_text":"x"}`},
		{http.MethodDelete, "/api/v1/groups/group-1/messages/msg-1", ""},
		{http.MethodPost, "/api/v1/groups/group-1/messages/msg-1/trigger", ""},
	}

	for _, tc := range protected {
		t.Run(fmt.Sprintf("%s %s", tc.method, tc.path), func(t *testing.T) {
			var body *bytes.Buffer
			if tc.body != "" {
				body = bytes.NewBufferString(tc.body)
			} else {
				body = bytes.NewBuffer(nil)
			}
			req := httptest.NewRequest(tc.method, tc.path, body)
			if tc.body != "" {
				req.Header.Set("Content-Type", "application/json")
			}
			w := httptest.NewRecorder()
			router.Engine().ServeHTTP(w, req)
			assert.Equal(t, http.StatusUnauthorized, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestNewRouter_AccountRoleMiddleware verifies that POST /api/v1/accounts requires manager or admin role.
func TestNewRouter_AccountRoleMiddleware(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, accountSvc, apiKeySvc := setupRouterTestDependencies(t, db)

	_, userToken := createTestAccountAndAPIKey(t, accountSvc, apiKeySvc, models.AccountRoleUser)
	_, managerToken := createTestAccountAndAPIKey(t, accountSvc, apiKeySvc, models.AccountRoleManager)

	body := map[string]string{
		"account_name": "New User",
		"role":         "user",
		"login_name":   "new-user@example.com",
	}
	jsonBody, _ := json.Marshal(body)

	t.Run("user forbidden", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+userToken)
		w := httptest.NewRecorder()
		router.Engine().ServeHTTP(w, req)
		assert.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
	})

	t.Run("manager allowed", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+managerToken)
		w := httptest.NewRecorder()
		router.Engine().ServeHTTP(w, req)
		assert.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	})
}

// TestNewRouter_APIKeyRoleMiddleware verifies that API key routes require authentication and ownership.
func TestNewRouter_APIKeyRoleMiddleware(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, accountSvc, apiKeySvc := setupRouterTestDependencies(t, db)

	user, userToken := createTestAccountAndAPIKey(t, accountSvc, apiKeySvc, models.AccountRoleUser)

	t.Run("unauthenticated rejected", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/v1/accounts/%s/api-keys", user.AccountID), nil)
		w := httptest.NewRecorder()
		router.Engine().ServeHTTP(w, req)
		assert.Equal(t, http.StatusUnauthorized, w.Code)
	})

	t.Run("owner can list api keys", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, fmt.Sprintf("/api/v1/accounts/%s/api-keys", user.AccountID), nil)
		req.Header.Set("Authorization", "Bearer "+userToken)
		w := httptest.NewRecorder()
		router.Engine().ServeHTTP(w, req)
		assert.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	})
}

// TestNewRouter_GroupRoutesRequireAuth verifies that group routes require authentication.
func TestNewRouter_GroupRoutesRequireAuth(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, _, _ := setupRouterTestDependencies(t, db)

	groupRoutes := []struct {
		method string
		path   string
		body   string
	}{
		{http.MethodGet, "/api/v1/groups", ""},
		{http.MethodPost, "/api/v1/groups", `{"group_name":"x"}`},
		{http.MethodGet, "/api/v1/groups/group-1", ""},
		{http.MethodPut, "/api/v1/groups/group-1", `{"group_name":"x"}`},
		{http.MethodDelete, "/api/v1/groups/group-1", ""},
		{http.MethodGet, "/api/v1/groups/group-1/members", ""},
		{http.MethodPost, "/api/v1/groups/group-1/members", `{"member_id":"m1","member_name":"x","member_type":"user"}`},
		{http.MethodGet, "/api/v1/groups/group-1/messages", ""},
		{http.MethodPost, "/api/v1/groups/group-1/messages", `{"message_text":"x"}`},
	}

	for _, tc := range groupRoutes {
		t.Run(fmt.Sprintf("%s %s", tc.method, tc.path), func(t *testing.T) {
			var body *bytes.Buffer
			if tc.body != "" {
				body = bytes.NewBufferString(tc.body)
			} else {
				body = bytes.NewBuffer(nil)
			}
			req := httptest.NewRequest(tc.method, tc.path, body)
			if tc.body != "" {
				req.Header.Set("Content-Type", "application/json")
			}
			w := httptest.NewRecorder()
			router.Engine().ServeHTTP(w, req)
			assert.Equal(t, http.StatusUnauthorized, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestNewRouter_AuditMiddlewareApplied verifies that protected endpoints invoke audit middleware without panic.
func TestNewRouter_AuditMiddlewareApplied(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, accountSvc, apiKeySvc := setupRouterTestDependencies(t, db)

	_, adminToken := createTestAccountAndAPIKey(t, accountSvc, apiKeySvc, models.AccountRoleAdmin)

	body := map[string]string{
		"account_name": "Audited User",
		"role":         "user",
		"login_name":   "audited@example.com",
	}
	jsonBody, _ := json.Marshal(body)

	req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+adminToken)
	w := httptest.NewRecorder()

	assert.NotPanics(t, func() {
		router.Engine().ServeHTTP(w, req)
	})

	assert.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	// Allow async audit log write to complete.
	time.Sleep(100 * time.Millisecond)

	var count int64
	err := db.Model(&models.AuditLog{}).Count(&count).Error
	require.NoError(t, err)
	assert.GreaterOrEqual(t, count, int64(1), "expected at least one audit log record")
}

// TestNewRouter_GinModeRelease verifies that Gin runs in release mode for info/warn/error log levels.
func TestNewRouter_GinModeRelease(t *testing.T) {
	originalMode := gin.Mode()
	defer gin.SetMode(originalMode)

	for _, level := range []string{"info", "warn", "error"} {
		t.Run(level, func(t *testing.T) {
			gin.SetMode(gin.TestMode)
			cfg := setupRouterTestConfig()
			cfg.Log.Level = level
			log := logger.New(logger.Config{Output: "stdout", Level: level})
			db := setupRouterTestDB(t)

			router := NewRouter(cfg, db, nil, nil, &fakeDiscovery{}, log)
			require.NotNil(t, router)

			assert.Equal(t, gin.ReleaseMode, gin.Mode())
		})
	}
}

// TestNewRouter_GinModeDebug verifies that Gin does not run in release mode for debug log level.
func TestNewRouter_GinModeDebug(t *testing.T) {
	originalMode := gin.Mode()
	defer gin.SetMode(originalMode)

	gin.SetMode(gin.ReleaseMode)
	cfg := setupRouterTestConfig()
	cfg.Log.Level = "debug"
	log := logger.New(logger.Config{Output: "stdout", Level: "debug"})
	db := setupRouterTestDB(t)

	router := NewRouter(cfg, db, nil, nil, &fakeDiscovery{}, log)
	require.NotNil(t, router)

	assert.NotEqual(t, gin.ReleaseMode, gin.Mode())
}

// TestNewRouter_EngineReturnsRouter verifies that Engine() returns a non-nil engine with routes registered.
func TestNewRouter_EngineReturnsRouter(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupRouterTestDB(t)
	router, _, _ := setupRouterTestDependencies(t, db)

	engine := router.Engine()
	require.NotNil(t, engine)
	assert.Greater(t, len(engine.Routes()), 0, "expected routes to be registered")
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
		"login_name":     "login-user@example.com",
		"login_password": "secure-password",
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
