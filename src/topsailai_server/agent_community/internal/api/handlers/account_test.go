// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/schema"

	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/pkg/logger"
)

// setupAccountTestDB creates an isolated in-memory SQLite database and migrates
// the account and audit log models.
func setupAccountTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := "file:" + t.Name() + "?mode=memory&cache=shared"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{
		NamingStrategy: schema.NamingStrategy{SingularTable: true},
	})
	require.NoError(t, err)

	err = db.AutoMigrate(&models.Account{}, &models.AuditLog{})
	require.NoError(t, err)
	return db
}

// newAccountTestConfig returns a config with a low bcrypt cost for fast tests.
func newAccountTestConfig() *config.Config {
	return &config.Config{
		Account: config.AccountConfig{
			APIKeyMaxPerAccount:       10,
			LoginSessionExpirySeconds: 86400,
			BcryptCost:                4,
		},
	}
}

// setupAccountTestHandler creates an AccountHandler backed by a real service.
func setupAccountTestHandler(t *testing.T, db *gorm.DB) *AccountHandler {
	t.Helper()
	cfg := newAccountTestConfig()
	auditSvc := services.NewAuditLogService(db)
	accountSvc := services.NewAccountService(db, cfg, auditSvc)
	log := logger.New(logger.Config{Output: "stdout", Level: "error"})
	return NewAccountHandler(accountSvc, log)
}

// createTestAccount creates an account through the service for test setup.
func createTestAccount(t *testing.T, svc *services.AccountService, name, loginName string, role models.AccountRole) *models.Account {
	t.Helper()
	acc, err := svc.CreateAccount(nil, &services.CreateAccountRequest{
		AccountName:   name,
		LoginName:     loginName,
		Role:          role,
		LoginPassword: "password",
		CreatorID:     "system",
	})
	require.NoError(t, err)
	return acc
}

// newAccountAuthContext builds an AuthContext for the given account.
func newAccountAuthContext(account *models.Account) middleware.AuthContext {
	return middleware.AuthContext{
		Account:         account,
		IsAuthenticated: true,
	}
}

// TestAccountHandler_CreateAccount_AdminAnyRole verifies an admin can create
// accounts with any role.
func TestAccountHandler_CreateAccount_AdminAnyRole(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)

	admin := &models.Account{
		AccountID: "acc-admin",
		Role:      models.AccountRoleAdmin,
		Status:    models.AccountStatusActive,
	}

	tests := []struct {
		name string
		role string
	}{
		{"user", string(models.AccountRoleUser)},
		{"manager", string(models.AccountRoleManager)},
		{"admin", string(models.AccountRoleAdmin)},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", newAccountAuthContext(admin))
			body := CreateAccountRequest{
				AccountName:   "Test " + tt.name,
				LoginName:     "test-" + tt.name,
				Role:          tt.role,
				LoginPassword: "password",
			}
			jsonBody, _ := json.Marshal(body)
			c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
			c.Request.Header.Set("Content-Type", "application/json")

			handler.CreateAccount(c)

			require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
			var resp AccountResponse
			require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
			assert.Equal(t, tt.role, resp.Role)
		})
	}
}

// TestAccountHandler_CreateAccount_ManagerUserOnly verifies a manager can only
// create user accounts.
func TestAccountHandler_CreateAccount_ManagerUserOnly(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)

	manager := &models.Account{
		AccountID: "acc-manager",
		Role:      models.AccountRoleManager,
		Status:    models.AccountStatusActive,
	}

	tests := []struct {
		name           string
		role           string
		expectedStatus int
	}{
		{"user", string(models.AccountRoleUser), http.StatusCreated},
		{"manager", string(models.AccountRoleManager), http.StatusForbidden},
		{"admin", string(models.AccountRoleAdmin), http.StatusForbidden},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", newAccountAuthContext(manager))
			body := CreateAccountRequest{
				AccountName:   "Manager Creates " + tt.name,
				LoginName:     "manager-creates-" + tt.name,
				Role:          tt.role,
				LoginPassword: "password",
			}
			jsonBody, _ := json.Marshal(body)
			c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
			c.Request.Header.Set("Content-Type", "application/json")

			handler.CreateAccount(c)

			require.Equal(t, tt.expectedStatus, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestAccountHandler_CreateAccount_InvalidJSON verifies malformed JSON returns 400.
func TestAccountHandler_CreateAccount_InvalidJSON(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(&models.Account{
		AccountID: "acc-admin",
		Role:      models.AccountRoleAdmin,
		Status:    models.AccountStatusActive,
	}))
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBufferString("{invalid"))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAccount(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestAccountHandler_CreateAccount_EmptyRoleDefaultsToUser verifies an empty role
// is treated as user.
func TestAccountHandler_CreateAccount_EmptyRoleDefaultsToUser(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(&models.Account{
		AccountID: "acc-admin",
		Role:      models.AccountRoleAdmin,
		Status:    models.AccountStatusActive,
	}))
	body := CreateAccountRequest{
		AccountName:   "Default Role",
		LoginName:     "default-role",
		LoginPassword: "password",
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAccount(c)

	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())
	var resp AccountResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, string(models.AccountRoleUser), resp.Role)
}

// TestAccountHandler_CreateAccount_DuplicateLoginName verifies duplicate login
// names return 409 Conflict.
func TestAccountHandler_CreateAccount_DuplicateLoginName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)

	admin := &models.Account{
		AccountID: "acc-admin",
		Role:      models.AccountRoleAdmin,
		Status:    models.AccountStatusActive,
	}

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(admin))
	body := CreateAccountRequest{
		AccountName:   "First",
		LoginName:     "duplicate",
		LoginPassword: "password",
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	handler.CreateAccount(c)
	require.Equal(t, http.StatusCreated, w.Code, "body: %s", w.Body.String())

	w = httptest.NewRecorder()
	c, _ = gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(admin))
	body = CreateAccountRequest{
		AccountName:   "Second",
		LoginName:     "duplicate",
		LoginPassword: "password",
	}
	jsonBody, _ = json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	handler.CreateAccount(c)

	require.Equal(t, http.StatusConflict, w.Code, "body: %s", w.Body.String())
}

// TestAccountHandler_CreateAccount_ServiceError verifies an invalid role that
// reaches the service returns 500.
func TestAccountHandler_CreateAccount_ServiceError(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(&models.Account{
		AccountID: "acc-admin",
		Role:      models.AccountRoleAdmin,
		Status:    models.AccountStatusActive,
	}))
	body := CreateAccountRequest{
		AccountName:   "Invalid Role",
		LoginName:     "invalid-role",
		Role:          "superuser",
		LoginPassword: "password",
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.CreateAccount(c)

	require.Equal(t, http.StatusInternalServerError, w.Code, "body: %s", w.Body.String())
}

// TestAccountHandler_ListAccounts_RoleFiltering verifies admin sees all,
// manager sees users and self, and user sees self.
func TestAccountHandler_ListAccounts_RoleFiltering(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	admin := createTestAccount(t, accountSvc, "Admin", "admin-list", models.AccountRoleAdmin)
	manager := createTestAccount(t, accountSvc, "Manager", "manager-list", models.AccountRoleManager)
	user := createTestAccount(t, accountSvc, "User", "user-list", models.AccountRoleUser)

	tests := []struct {
		name          string
		caller        *models.Account
		expectedIDs   []string
		expectedTotal int64
	}{
		{
			name:          "admin sees all",
			caller:        admin,
			expectedIDs:   []string{admin.AccountID, manager.AccountID, user.AccountID},
			expectedTotal: 3,
		},
		{
			name:          "manager sees users and self",
			caller:        manager,
			expectedIDs:   []string{manager.AccountID, user.AccountID},
			expectedTotal: 3,
		},
		{
			name:          "user sees self",
			caller:        user,
			expectedIDs:   []string{user.AccountID},
			expectedTotal: 3,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", newAccountAuthContext(tt.caller))
			c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts", nil)

			handler.ListAccounts(c)

			require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
			var resp ListAccountsResponse
			require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
			assert.Equal(t, tt.expectedTotal, resp.Total)
			assert.Len(t, resp.Items, len(tt.expectedIDs))

			ids := make(map[string]bool)
			for _, item := range resp.Items {
				ids[item.AccountID] = true
			}
			for _, expectedID := range tt.expectedIDs {
				assert.True(t, ids[expectedID], "expected %s in items", expectedID)
			}
		})
	}
}

// TestAccountHandler_ListAccounts_PaginationClamping verifies negative offset
// and out-of-range limit are clamped.
func TestAccountHandler_ListAccounts_PaginationClamping(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	for i := 0; i < 3; i++ {
		createTestAccount(t, accountSvc, "User", "pagination-"+string(rune('a'+i)), models.AccountRoleUser)
	}

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(&models.Account{
		AccountID: "acc-admin",
		Role:      models.AccountRoleAdmin,
		Status:    models.AccountStatusActive,
	}))
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts?offset=-1&limit=0", nil)

	handler.ListAccounts(c)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp ListAccountsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, 0, resp.Offset)
	assert.Equal(t, 1000, resp.Limit)
	assert.Equal(t, int64(3), resp.Total)
}

// TestAccountHandler_GetAccount_AccessControl verifies role-based access for
// retrieving accounts.
func TestAccountHandler_GetAccount_AccessControl(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	admin := createTestAccount(t, accountSvc, "Admin", "admin-get", models.AccountRoleAdmin)
	manager := createTestAccount(t, accountSvc, "Manager", "manager-get", models.AccountRoleManager)
	otherManager := createTestAccount(t, accountSvc, "OtherManager", "other-manager-get", models.AccountRoleManager)
	user := createTestAccount(t, accountSvc, "User", "user-get", models.AccountRoleUser)

	tests := []struct {
		name           string
		caller         *models.Account
		targetID       string
		expectedStatus int
	}{
		{"admin gets admin", admin, admin.AccountID, http.StatusOK},
		{"admin gets manager", admin, manager.AccountID, http.StatusOK},
		{"admin gets user", admin, user.AccountID, http.StatusOK},
		{"manager gets user", manager, user.AccountID, http.StatusOK},
		{"manager gets self", manager, manager.AccountID, http.StatusOK},
		{"manager gets other manager", manager, otherManager.AccountID, http.StatusForbidden},
		{"user gets self", user, user.AccountID, http.StatusOK},
		{"user gets other user", user, createTestAccount(t, accountSvc, "Other", "other-get", models.AccountRoleUser).AccountID, http.StatusForbidden},
		{"not found", admin, "acc-nonexistent", http.StatusNotFound},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", newAccountAuthContext(tt.caller))
			c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts/"+tt.targetID, nil)
			c.Params = gin.Params{{Key: "account_id", Value: tt.targetID}}

			handler.GetAccount(c)

			require.Equal(t, tt.expectedStatus, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestAccountHandler_UpdateAccount_AdminCanUpdateAny verifies an admin can
// update any account including role and status.
func TestAccountHandler_UpdateAccount_AdminCanUpdateAny(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	admin := createTestAccount(t, accountSvc, "Admin", "admin-update", models.AccountRoleAdmin)
	user := createTestAccount(t, accountSvc, "User", "user-update", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(admin))
	newRole := string(models.AccountRoleManager)
	newStatus := string(models.AccountStatusInactive)
	body := UpdateAccountRequest{
		AccountName: "Updated Name",
		Role:        newRole,
		Status:      newStatus,
	}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/accounts/"+user.AccountID, bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}

	handler.UpdateAccount(c)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp AccountResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "Updated Name", resp.AccountName)
	assert.Equal(t, newRole, resp.Role)
	assert.Equal(t, newStatus, resp.Status)
}

// TestAccountHandler_UpdateAccount_UserSelfCanUpdateName verifies a user can
// update their own name but cannot promote themselves.
func TestAccountHandler_UpdateAccount_UserSelfCanUpdateName(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	user := createTestAccount(t, accountSvc, "User", "user-self-update", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(user))
	body := UpdateAccountRequest{AccountName: "Updated Name"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/accounts/"+user.AccountID, bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}

	handler.UpdateAccount(c)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp AccountResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "Updated Name", resp.AccountName)
	assert.Equal(t, string(models.AccountRoleUser), resp.Role)
	assert.Equal(t, string(models.AccountStatusActive), resp.Status)
}

// TestAccountHandler_UpdateAccount_UserSelfCannotPromote verifies a user cannot
// promote themselves to a higher role.
func TestAccountHandler_UpdateAccount_UserSelfCannotPromote(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	user := createTestAccount(t, accountSvc, "User", "user-self-promote", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(user))
	body := UpdateAccountRequest{Role: string(models.AccountRoleAdmin)}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/accounts/"+user.AccountID, bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}

	handler.UpdateAccount(c)

	require.Equal(t, http.StatusInternalServerError, w.Code, "body: %s", w.Body.String())
}

// TestAccountHandler_UpdateAccount_UserOtherForbidden verifies a user cannot
// update another account.
func TestAccountHandler_UpdateAccount_UserOtherForbidden(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	user := createTestAccount(t, accountSvc, "User", "user-update-other", models.AccountRoleUser)
	other := createTestAccount(t, accountSvc, "Other", "other-update", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(user))
	body := UpdateAccountRequest{AccountName: "Hacked"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/accounts/"+other.AccountID, bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "account_id", Value: other.AccountID}}

	handler.UpdateAccount(c)

	require.Equal(t, http.StatusForbidden, w.Code, "body: %s", w.Body.String())
}

// TestAccountHandler_UpdateAccount_InvalidJSON verifies malformed JSON returns 400.
func TestAccountHandler_UpdateAccount_InvalidJSON(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc
	user := createTestAccount(t, accountSvc, "User", "user-update-json", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(user))
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/accounts/"+user.AccountID, bytes.NewBufferString("{invalid"))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}

	handler.UpdateAccount(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestAccountHandler_UpdateAccount_NotFound verifies updating a missing account
// returns 404.
func TestAccountHandler_UpdateAccount_NotFound(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(&models.Account{
		AccountID: "acc-admin",
		Role:      models.AccountRoleAdmin,
		Status:    models.AccountStatusActive,
	}))
	body := UpdateAccountRequest{AccountName: "Updated"}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/accounts/acc-nonexistent", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "account_id", Value: "acc-nonexistent"}}

	handler.UpdateAccount(c)

	require.Equal(t, http.StatusNotFound, w.Code, "body: %s", w.Body.String())
}

// TestAccountHandler_DeleteAccount_AccessControl verifies admin can delete any
// account and user can delete self.
func TestAccountHandler_DeleteAccount_AccessControl(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	admin := createTestAccount(t, accountSvc, "Admin", "admin-delete", models.AccountRoleAdmin)
	user := createTestAccount(t, accountSvc, "User", "user-delete", models.AccountRoleUser)
	other := createTestAccount(t, accountSvc, "Other", "other-delete", models.AccountRoleUser)

	tests := []struct {
		name           string
		caller         *models.Account
		targetID       string
		expectedStatus int
	}{
		{"admin deletes user", admin, user.AccountID, http.StatusOK},
		{"user deletes self", other, other.AccountID, http.StatusOK},
		{"user deletes other", user, other.AccountID, http.StatusForbidden},
		{"not found", admin, "acc-nonexistent", http.StatusNotFound},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", newAccountAuthContext(tt.caller))
			c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/accounts/"+tt.targetID, nil)
			c.Params = gin.Params{{Key: "account_id", Value: tt.targetID}}

			handler.DeleteAccount(c)

			require.Equal(t, tt.expectedStatus, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestAccountHandler_ChangePassword_AccessControl verifies admin can change any
// password and user can only change own password.
func TestAccountHandler_ChangePassword_AccessControl(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	admin := createTestAccount(t, accountSvc, "Admin", "admin-password", models.AccountRoleAdmin)
	user := createTestAccount(t, accountSvc, "User", "user-password", models.AccountRoleUser)
	other := createTestAccount(t, accountSvc, "Other", "other-password", models.AccountRoleUser)

	tests := []struct {
		name           string
		caller         *models.Account
		targetID       string
		expectedStatus int
	}{
		{"admin changes user", admin, user.AccountID, http.StatusOK},
		{"user changes self", user, user.AccountID, http.StatusOK},
		{"user changes other", user, other.AccountID, http.StatusForbidden},
		{"not found", admin, "acc-nonexistent", http.StatusNotFound},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", newAccountAuthContext(tt.caller))
			body := ChangePasswordRequest{NewPassword: "newpassword"}
			jsonBody, _ := json.Marshal(body)
			c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+tt.targetID+"/password", bytes.NewBuffer(jsonBody))
			c.Request.Header.Set("Content-Type", "application/json")
			c.Params = gin.Params{{Key: "account_id", Value: tt.targetID}}

			handler.ChangePassword(c)

			require.Equal(t, tt.expectedStatus, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestAccountHandler_ChangePassword_EmptyPassword verifies empty password
// returns 400.
func TestAccountHandler_ChangePassword_EmptyPassword(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc
	user := createTestAccount(t, accountSvc, "User", "user-empty-password", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(user))
	body := ChangePasswordRequest{NewPassword: ""}
	jsonBody, _ := json.Marshal(body)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+user.AccountID+"/password", bytes.NewBuffer(jsonBody))
	c.Request.Header.Set("Content-Type", "application/json")
	c.Params = gin.Params{{Key: "account_id", Value: user.AccountID}}

	handler.ChangePassword(c)

	require.Equal(t, http.StatusBadRequest, w.Code, "body: %s", w.Body.String())
}

// TestAccountHandler_Login verifies password login behavior.
func TestAccountHandler_Login(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	createTestAccount(t, accountSvc, "User", "login-user", models.AccountRoleUser)

	// Account without password.
	_, err := accountSvc.CreateAccount(nil, &services.CreateAccountRequest{
		AccountName: "No Password",
		LoginName:   "no-password",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	tests := []struct {
		name           string
		body           LoginRequest
		expectedStatus int
	}{
		{
			name:           "valid credentials",
			body:           LoginRequest{LoginName: "login-user", Password: "password"},
			expectedStatus: http.StatusOK,
		},
		{
			name:           "wrong password",
			body:           LoginRequest{LoginName: "login-user", Password: "wrong"},
			expectedStatus: http.StatusUnauthorized,
		},
		{
			name:           "unknown login name",
			body:           LoginRequest{LoginName: "unknown", Password: "password"},
			expectedStatus: http.StatusUnauthorized,
		},
		{
			name:           "password not set",
			body:           LoginRequest{LoginName: "no-password", Password: "any"},
			expectedStatus: http.StatusUnauthorized,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			jsonBody, _ := json.Marshal(tt.body)
			c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/login", bytes.NewBuffer(jsonBody))
			c.Request.Header.Set("Content-Type", "application/json")

			handler.Login(c)

			require.Equal(t, tt.expectedStatus, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestAccountHandler_Login_InvalidJSON verifies malformed login JSON returns 400.
func TestAccountHandler_Login_InvalidJSON(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/login", bytes.NewBufferString("{invalid"))
	c.Request.Header.Set("Content-Type", "application/json")

	handler.Login(c)

	require.Equal(t, http.StatusBadRequest, w.Code)
}

// TestAccountHandler_CreateSession_AccessControl verifies role-based access for
// creating login sessions.
func TestAccountHandler_CreateSession_AccessControl(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	admin := createTestAccount(t, accountSvc, "Admin", "admin-session", models.AccountRoleAdmin)
	manager := createTestAccount(t, accountSvc, "Manager", "manager-session", models.AccountRoleManager)
	user := createTestAccount(t, accountSvc, "User", "user-session", models.AccountRoleUser)
	other := createTestAccount(t, accountSvc, "Other", "other-session", models.AccountRoleUser)

	tests := []struct {
		name           string
		caller         *models.Account
		targetID       string
		expectedStatus int
	}{
		{"admin creates for manager", admin, manager.AccountID, http.StatusOK},
		{"admin creates for user", admin, user.AccountID, http.StatusOK},
		{"manager creates for user", manager, user.AccountID, http.StatusOK},
		{"manager creates for admin", manager, admin.AccountID, http.StatusForbidden},
		{"manager creates for manager", manager, manager.AccountID, http.StatusForbidden},
		{"user creates for self", user, user.AccountID, http.StatusOK},
		{"user creates for other", user, other.AccountID, http.StatusForbidden},
		{"not found", admin, "acc-nonexistent", http.StatusNotFound},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			c, _ := gin.CreateTestContext(w)
			c.Set("auth_context", newAccountAuthContext(tt.caller))
			c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+tt.targetID+"/session", nil)
			c.Params = gin.Params{{Key: "account_id", Value: tt.targetID}}

			handler.CreateSession(c)

			require.Equal(t, tt.expectedStatus, w.Code, "body: %s", w.Body.String())
		})
	}
}

// TestAccountHandler_CreateSession_InactiveAccount verifies creating a session
// for an inactive account returns 500.
func TestAccountHandler_CreateSession_InactiveAccount(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc

	admin := createTestAccount(t, accountSvc, "Admin", "admin-session-inactive", models.AccountRoleAdmin)
	inactive := createTestAccount(t, accountSvc, "Inactive", "inactive-session", models.AccountRoleUser)
	inactiveStatus := models.AccountStatusInactive
	_, err := accountSvc.UpdateAccount(nil, &services.UpdateAccountRequest{
		AccountID:  inactive.AccountID,
		Status:     &inactiveStatus,
		CallerRole: models.AccountRoleAdmin,
	})
	require.NoError(t, err)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(admin))
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/"+inactive.AccountID+"/session", nil)
	c.Params = gin.Params{{Key: "account_id", Value: inactive.AccountID}}

	handler.CreateSession(c)

	require.Equal(t, http.StatusInternalServerError, w.Code, "body: %s", w.Body.String())
}

// TestAccountHandler_GetMe verifies GetMe returns the authenticated account.
func TestAccountHandler_GetMe(t *testing.T) {
	gin.SetMode(gin.TestMode)
	db := setupAccountTestDB(t)
	handler := setupAccountTestHandler(t, db)
	accountSvc := handler.accountSvc
	user := createTestAccount(t, accountSvc, "User", "user-me", models.AccountRoleUser)

	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Set("auth_context", newAccountAuthContext(user))
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts/me", nil)

	handler.GetMe(c)

	require.Equal(t, http.StatusOK, w.Code, "body: %s", w.Body.String())
	var resp AccountResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, user.AccountID, resp.AccountID)
	assert.Equal(t, user.AccountName, resp.AccountName)
}

// TestCanViewAccount verifies all role combinations for account visibility.
func TestCanViewAccount(t *testing.T) {
	handler := &AccountHandler{}

	admin := &models.Account{AccountID: "acc-admin", Role: models.AccountRoleAdmin}
	manager := &models.Account{AccountID: "acc-manager", Role: models.AccountRoleManager}
	user := &models.Account{AccountID: "acc-user", Role: models.AccountRoleUser}

	tests := []struct {
		name     string
		caller   *models.Account
		target   *models.Account
		expected bool
	}{
		{"admin views admin", admin, admin, true},
		{"admin views manager", admin, manager, true},
		{"admin views user", admin, user, true},
		{"manager views user", manager, user, true},
		{"manager views manager (self)", manager, manager, true},
		{"manager views other manager", manager, &models.Account{AccountID: "acc-manager-2", Role: models.AccountRoleManager}, false},
		{"user views self", user, user, true},
		{"user views other user", user, &models.Account{AccountID: "acc-other", Role: models.AccountRoleUser}, false},
		{"user views admin", user, admin, false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			ac := middleware.AuthContext{Account: tt.caller}
			assert.Equal(t, tt.expected, handler.canViewAccount(ac, tt.target))
		})
	}
}

// TestToAccountResponse verifies the response mapping includes all fields.
func TestToAccountResponse(t *testing.T) {
	account := &models.Account{
		AccountID:          "acc-123",
		AccountName:        "Test Account",
		AccountDescription: "A test account",
		Role:               models.AccountRoleUser,
		Status:             models.AccountStatusActive,
		DeleteAtMs:         0,
		CreatorID:          "system",
		ExternalID:         "ext-123",
		Email:              "test@example.com",
		AuthProvider:       "oidc",
		AvatarURL:          "http://example.com/avatar.png",
		LoginName:          "test",
		CreateAtMs:         1000,
		UpdateAtMs:         2000,
	}

	resp := toAccountResponse(account)
	assert.Equal(t, account.AccountID, resp.AccountID)
	assert.Equal(t, account.AccountName, resp.AccountName)
	assert.Equal(t, account.AccountDescription, resp.AccountDescription)
	assert.Equal(t, string(account.Role), resp.Role)
	assert.Equal(t, string(account.Status), resp.Status)
	assert.Equal(t, account.DeleteAtMs, resp.DeleteAtMs)
	assert.Equal(t, account.CreatorID, resp.CreatorID)
	assert.Equal(t, account.ExternalID, resp.ExternalID)
	assert.Equal(t, account.Email, resp.Email)
	assert.Equal(t, account.AuthProvider, resp.AuthProvider)
	assert.Equal(t, account.AvatarURL, resp.AvatarURL)
	assert.Equal(t, account.LoginName, resp.LoginName)
	assert.Equal(t, account.CreateAtMs, resp.CreateAtMs)
	assert.Equal(t, account.UpdateAtMs, resp.UpdateAtMs)
}

// TestParseAccountRole verifies role parsing normalizes casing.
func TestParseAccountRole(t *testing.T) {
	assert.Equal(t, models.AccountRoleAdmin, parseAccountRole("ADMIN"))
	assert.Equal(t, models.AccountRoleManager, parseAccountRole("Manager"))
	assert.Equal(t, models.AccountRoleUser, parseAccountRole("user"))
	assert.Equal(t, models.AccountRole("unknown"), parseAccountRole("unknown"))
}
