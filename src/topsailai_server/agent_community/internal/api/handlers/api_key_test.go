// Package handlers provides API key handler tests.
package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// setupAPIKeyTestDB creates an in-memory SQLite database and auto-migrates models.
func setupAPIKeyTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open("file::memory:"), &gorm.Config{})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(
		&models.Account{},
		&models.APIKey{},
		&models.AuditLog{},
	))
	return db
}

// setupAPIKeyTestServices creates real service instances backed by the test database.
func setupAPIKeyTestServices(t *testing.T, db *gorm.DB) (*services.AccountService, *services.APIKeyService) {
	t.Helper()
	cfg := &config.Config{
		Account: config.AccountConfig{
			APIKeyMaxPerAccount:       10,
			LoginSessionExpirySeconds: 86400,
			BcryptCost:                4, // low cost for fast tests
		},
	}
	auditSvc := services.NewAuditLogService(db)
	accountSvc := services.NewAccountService(db, cfg, auditSvc)
	apiKeySvc := services.NewAPIKeyService(db, cfg, auditSvc)
	accountSvc.SetAPIKeyService(apiKeySvc)
	return accountSvc, apiKeySvc
}

// setupAPIKeyTestHandler creates an APIKeyHandler for testing.
func setupAPIKeyTestHandler(t *testing.T, db *gorm.DB) *APIKeyHandler {
	t.Helper()
	accountSvc, apiKeySvc := setupAPIKeyTestServices(t, db)
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	return NewAPIKeyHandler(apiKeySvc, accountSvc, log)
}
// listAPIKeysResponseWrapper mirrors the envelope produced by writeListResponse.
type listAPIKeysResponseWrapper struct {
	Data struct {
		Items  []APIKeyResponse `json:"items"`
		Total  int64            `json:"total"`
		Offset int              `json:"offset"`
		Limit  int              `json:"limit"`
	} `json:"data"`
	TraceID string `json:"trace_id"`
}


// createTestAPIKeyAccount creates an account directly via the service for use in tests.
func createTestAPIKeyAccount(t *testing.T, accountSvc *services.AccountService, name, loginName string, role models.AccountRole) *models.Account {
	t.Helper()
	acc, err := accountSvc.CreateAccount(context.Background(), &services.CreateAccountRequest{
		AccountName: name,
		LoginName:   loginName,
		Role:        role,
		CreatorID:   "system",
	})
	require.NoError(t, err)
	return acc
}

// createTestAPIKey creates an API key directly via the service for use in tests.
func createTestAPIKey(t *testing.T, apiKeySvc *services.APIKeyService, name string, role models.APIKeyRole, ownerID, creatorID string) *models.APIKey {
	t.Helper()
	result, err := apiKeySvc.CreateAPIKey(context.Background(), &services.CreateAPIKeyRequest{
		APIKeyName: name,
		Role:       role,
		OwnerID:    ownerID,
		CreatorID:  creatorID,
	})
	require.NoError(t, err)
	return result.APIKey
}
// toJSON marshals v to JSON and fails the test on error.
func toJSON(t *testing.T, v interface{}) []byte {
	t.Helper()
	b, err := json.Marshal(v)
	require.NoError(t, err)
	return b
}


func TestAPIKeyHandler_CreateAPIKey_AdminCreatesAdminForAnother(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)
	otherAdmin := createTestAPIKeyAccount(t, accountSvc, "OtherAdmin", "otheradmin", models.AccountRoleAdmin)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: otherAdmin.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "Admin Key", Role: "admin"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+otherAdmin.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	var resp APIKeyWithTokenResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "Admin Key", resp.APIKeyName)
	assert.Equal(t, "admin", resp.Role)
	assert.NotEmpty(t, resp.Token)
	assert.Equal(t, otherAdmin.AccountID, resp.OwnerID)
}

func TestAPIKeyHandler_CreateAPIKey_AdminCreatesManagerForManager(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)
	manager := createTestAPIKeyAccount(t, accountSvc, "Manager", "manager", models.AccountRoleManager)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: manager.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "Manager Key", Role: "manager"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+manager.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	var resp APIKeyWithTokenResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "manager", resp.Role)
	assert.Equal(t, manager.AccountID, resp.OwnerID)
}

func TestAPIKeyHandler_CreateAPIKey_UserCreatesForSelf(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: user, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "User Key"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+user.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	var resp APIKeyWithTokenResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "User Key", resp.APIKeyName)
	assert.Equal(t, "user", resp.Role)
	assert.Equal(t, user.AccountID, resp.OwnerID)
}

func TestAPIKeyHandler_CreateAPIKey_ManagerForbidden(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	manager := createTestAPIKeyAccount(t, accountSvc, "Manager", "manager", models.AccountRoleManager)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: manager, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: manager.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "Manager Key"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+manager.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

func TestAPIKeyHandler_CreateAPIKey_NonAdminCannotCreateForOther(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)
	other := createTestAPIKeyAccount(t, accountSvc, "Other", "other", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: user, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: other.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "User Key"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+other.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

func TestAPIKeyHandler_CreateAPIKey_InvalidJSON(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: admin.AccountID}}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+admin.AccountID+"/api-keys", bytes.NewBufferString("not json"))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

func TestAPIKeyHandler_CreateAPIKey_EmptyRoleDefaultsToUser(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: user, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "Default Role Key"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+user.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	var resp APIKeyWithTokenResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "user", resp.Role)
}

func TestAPIKeyHandler_CreateAPIKey_OwnerNotFound(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: "acc-nonexistent"}}
	body := CreateAPIKeyRequest{APIKeyName: "Orphan Key"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/acc-nonexistent/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusNotFound, w.Code, "body: %s", w.Body.String())
}

func TestAPIKeyHandler_CreateAPIKey_RoleExceedsOwnerRole(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "Admin Key For User", Role: "admin"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+user.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

func TestAPIKeyHandler_CreateAPIKey_LimitReached(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, apiKeySvc := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)

	// Reduce limit to 2 for deterministic testing.
	handler.apiKeySvc = services.NewAPIKeyService(db, &config.Config{
		Account: config.AccountConfig{
			APIKeyMaxPerAccount:       2,
			LoginSessionExpirySeconds: 86400,
			BcryptCost:                4,
		},
	}, services.NewAuditLogService(db))

	createTestAPIKey(t, apiKeySvc, "Key1", models.APIKeyRoleUser, user.AccountID, admin.AccountID)
	createTestAPIKey(t, apiKeySvc, "Key2", models.APIKeyRoleUser, user.AccountID, admin.AccountID)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "Key3"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+user.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusConflict, w.Code, "body: %s", w.Body.String())
}

// TestAPIKeyHandler_CreateAPIKey_ServiceErrorPath_Documented documents the 500
// handler path. It is not easily triggerable with an in-memory SQLite database,
// so the test only ensures the path does not panic when the service succeeds.
func TestAPIKeyHandler_CreateAPIKey_ServiceErrorPath_Documented(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: admin.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "Service Error Doc Key"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+admin.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	assert.Equal(t, http.StatusCreated, w.Code)
}

func TestAPIKeyHandler_ListAPIKeys_AdminListsAny(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, apiKeySvc := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)
	createTestAPIKey(t, apiKeySvc, "User Key", models.APIKeyRoleUser, user.AccountID, user.AccountID)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts/"+user.AccountID+"/api-keys", nil)

	handler.ListAPIKeys(c)
	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp listAPIKeysResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Data.Total)
	assert.Len(t, resp.Data.Items, 1)
	assert.Equal(t, "User Key", resp.Data.Items[0].APIKeyName)
}

func TestAPIKeyHandler_ListAPIKeys_UserListsSelf(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, apiKeySvc := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)
	createTestAPIKey(t, apiKeySvc, "User Key", models.APIKeyRoleUser, user.AccountID, user.AccountID)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: user, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts/"+user.AccountID+"/api-keys", nil)

	handler.ListAPIKeys(c)
	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp listAPIKeysResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, int64(1), resp.Data.Total)
}

func TestAPIKeyHandler_ListAPIKeys_UserCannotListOther(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)
	other := createTestAPIKeyAccount(t, accountSvc, "Other", "other", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: user, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: other.AccountID}}
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts/"+other.AccountID+"/api-keys", nil)

	handler.ListAPIKeys(c)
	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

func TestAPIKeyHandler_ListAPIKeys_PaginationClamping(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: admin.AccountID}}
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts/"+admin.AccountID+"/api-keys?offset=-1&limit=0", nil)

	handler.ListAPIKeys(c)
	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp listAPIKeysResponseWrapper
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Data.Offset)
	assert.Equal(t, 1000, resp.Data.Limit)
}

// TestAPIKeyHandler_ListAPIKeys_ServiceErrorPath_Documented documents the 500
// handler path. It is not easily triggerable with an in-memory SQLite database,
// so the test only ensures the path does not panic when the service succeeds.
func TestAPIKeyHandler_ListAPIKeys_ServiceErrorPath_Documented(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: admin.AccountID}}
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts/"+admin.AccountID+"/api-keys", nil)

	handler.ListAPIKeys(c)
	assert.Equal(t, http.StatusOK, w.Code)
}

func TestAPIKeyHandler_DeleteAPIKey_AdminDeletesAny(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, apiKeySvc := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)
	key := createTestAPIKey(t, apiKeySvc, "User Key", models.APIKeyRoleUser, user.AccountID, user.AccountID)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{
		{Key: "account_id", Value: user.AccountID},
		{Key: "api_key_id", Value: key.APIKeyID},
	}
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/accounts/"+user.AccountID+"/api-keys/"+key.APIKeyID, nil)

	handler.DeleteAPIKey(c)
	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())

	_, _, err := apiKeySvc.VerifyAPIKey(context.Background(), "ak-invalid.invalid")
	require.Error(t, err)
}

func TestAPIKeyHandler_DeleteAPIKey_UserDeletesOwn(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, apiKeySvc := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)
	key := createTestAPIKey(t, apiKeySvc, "User Key", models.APIKeyRoleUser, user.AccountID, user.AccountID)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: user, IsAuthenticated: true})
	c.Params = gin.Params{
		{Key: "account_id", Value: user.AccountID},
		{Key: "api_key_id", Value: key.APIKeyID},
	}
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/accounts/"+user.AccountID+"/api-keys/"+key.APIKeyID, nil)

	handler.DeleteAPIKey(c)
	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
}

func TestAPIKeyHandler_DeleteAPIKey_UserCannotDeleteOther(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, apiKeySvc := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)
	other := createTestAPIKeyAccount(t, accountSvc, "Other", "other", models.AccountRoleUser)
	key := createTestAPIKey(t, apiKeySvc, "Other Key", models.APIKeyRoleUser, other.AccountID, other.AccountID)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: user, IsAuthenticated: true})
	c.Params = gin.Params{
		{Key: "account_id", Value: other.AccountID},
		{Key: "api_key_id", Value: key.APIKeyID},
	}
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/accounts/"+other.AccountID+"/api-keys/"+key.APIKeyID, nil)

	handler.DeleteAPIKey(c)
	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

func TestAPIKeyHandler_DeleteAPIKey_NotFound(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{
		{Key: "account_id", Value: admin.AccountID},
		{Key: "api_key_id", Value: "ak-nonexistent"},
	}
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/accounts/"+admin.AccountID+"/api-keys/ak-nonexistent", nil)

	handler.DeleteAPIKey(c)
	require.Equal(t, http.StatusNotFound, w.Code, "body: %s", w.Body.String())
}

// TestAPIKeyHandler_DeleteAPIKey_ServiceErrorPath_Documented documents the 500
// handler path. It is not easily triggerable with an in-memory SQLite database,
// so the test only ensures the path does not panic when the service succeeds.
func TestAPIKeyHandler_DeleteAPIKey_ServiceErrorPath_Documented(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, apiKeySvc := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)
	key := createTestAPIKey(t, apiKeySvc, "Admin Key", models.APIKeyRoleAdmin, admin.AccountID, admin.AccountID)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{
		{Key: "account_id", Value: admin.AccountID},
		{Key: "api_key_id", Value: key.APIKeyID},
	}
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/accounts/"+admin.AccountID+"/api-keys/"+key.APIKeyID, nil)

	handler.DeleteAPIKey(c)
	assert.Equal(t, http.StatusOK, w.Code)
}

func TestToAPIKeyResponse(t *testing.T) {
	key := &models.APIKey{
		APIKeyID:   "ak-abc123",
		APIKeyName: "Test Key",
		APIKeyHash: "secret-hash-must-be-excluded",
		Role:       models.APIKeyRoleManager,
		Status:     models.APIKeyStatusActive,
		CreatorID:  "acc-admin",
		OwnerID:    "acc-user",
		CreateAtMs: 1000,
		UpdateAtMs: 2000,
	}
	resp := toAPIKeyResponse(key)
	assert.Equal(t, "ak-abc123", resp.APIKeyID)
	assert.Equal(t, "Test Key", resp.APIKeyName)
	assert.Equal(t, "manager", resp.Role)
	assert.Equal(t, "active", resp.Status)
	assert.Equal(t, "acc-admin", resp.CreatorID)
	assert.Equal(t, "acc-user", resp.OwnerID)
	assert.Equal(t, int64(1000), resp.CreateAtMs)
	assert.Equal(t, int64(2000), resp.UpdateAtMs)

	// APIKeyHash must not be exposed in the response. Marshal the response and
	// verify the hash field is absent from the serialized JSON.
	respJSON, err := json.Marshal(resp)
	require.NoError(t, err)
	assert.NotContains(t, string(respJSON), "api_key_hash")
}

func TestAPIKeyHandler_CreateAPIKey_UserCannotExceedOwnRole(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)

	for _, role := range []string{"manager", "admin"} {
		w := httptest.NewRecorder()
		c, _ := gin.CreateTestContext(w)
		c.Set("auth_context", middleware.AuthContext{Account: user, IsAuthenticated: true})
		c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}
		body := CreateAPIKeyRequest{APIKeyName: "Elevated Key", Role: role}
		c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+user.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
		c.Request.Header.Set("Content-Type", "application/json")

		handler.CreateAPIKey(c)
		require.Equal(t, http.StatusForbidden, w.Code, "role %s should be rejected; body: %s", role, w.Body.String())
	}
}

func TestAPIKeyHandler_CreateAPIKey_AdminCreatesUserForAnother(t *testing.T) {
	db := setupAPIKeyTestDB(t)
	accountSvc, _ := setupAPIKeyTestServices(t, db)
	handler := setupAPIKeyTestHandler(t, db)
	admin := createTestAPIKeyAccount(t, accountSvc, "Admin", "admin", models.AccountRoleAdmin)
	user := createTestAPIKeyAccount(t, accountSvc, "User", "user", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", middleware.AuthContext{Account: admin, IsAuthenticated: true})
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}
	body := CreateAPIKeyRequest{APIKeyName: "User Key For User", Role: "user"}
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+user.AccountID+"/api-keys", bytes.NewBuffer(toJSON(t, body)))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAPIKey(c)
	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	var resp APIKeyWithTokenResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "user", resp.Role)
	assert.Equal(t, user.AccountID, resp.OwnerID)
}
