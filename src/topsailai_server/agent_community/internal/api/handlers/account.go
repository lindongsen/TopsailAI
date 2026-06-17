// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/pkg/logger"
)

// AccountHandler handles account-related HTTP requests.
type AccountHandler struct {
	accountSvc *services.AccountService
	log        *logger.Logger
}

// NewAccountHandler creates a new AccountHandler.
func NewAccountHandler(accountSvc *services.AccountService, log *logger.Logger) *AccountHandler {
	return &AccountHandler{
		accountSvc: accountSvc,
		log:        log,
	}
}

// CreateAccountRequest represents the request body for creating an account.
type CreateAccountRequest struct {
	AccountName        string `json:"account_name" binding:"required"`
	AccountDescription string `json:"account_description"`
	Role               string `json:"role"`
	LoginName          string `json:"login_name" binding:"required"`
	LoginPassword      string `json:"login_password"`
	ExternalID         string `json:"external_id"`
	Email              string `json:"email"`
	AuthProvider       string `json:"auth_provider"`
	AvatarURL          string `json:"avatar_url"`
}

// UpdateAccountRequest represents the request body for updating an account.
type UpdateAccountRequest struct {
	AccountName        string `json:"account_name"`
	AccountDescription string `json:"account_description"`
	Role               string `json:"role"`
	Status             string `json:"status"`
	ExternalID         string `json:"external_id"`
	Email              string `json:"email"`
	AuthProvider       string `json:"auth_provider"`
	AvatarURL          string `json:"avatar_url"`
}

// ChangePasswordRequest represents the request body for changing a password.
type ChangePasswordRequest struct {
	NewPassword string `json:"new_password" binding:"required"`
}

// LoginRequest represents the request body for password login.
type LoginRequest struct {
	LoginName string `json:"login_name" binding:"required"`
	Password  string `json:"password" binding:"required"`
}

// AccountResponse represents an account in API responses.
type AccountResponse struct {
	AccountID          string `json:"account_id"`
	AccountName        string `json:"account_name"`
	AccountDescription string `json:"account_description"`
	Role               string `json:"role"`
	Status             string `json:"status"`
	DeleteAtMs         int64  `json:"delete_at_ms"`
	CreatorID          string `json:"creator_id"`
	ExternalID         string `json:"external_id"`
	Email              string `json:"email"`
	AuthProvider       string `json:"auth_provider"`
	AvatarURL          string `json:"avatar_url"`
	LoginName          string `json:"login_name"`
	CreateAtMs         int64  `json:"create_at_ms"`
	UpdateAtMs         int64  `json:"update_at_ms"`
}

// LoginResponse represents the response for a successful login.
type LoginResponse struct {
	AccountID   string `json:"account_id"`
	SessionKey  string `json:"session_key"`
	ExpiresAtMs int64  `json:"expires_at_ms"`
}

// ListAccountsResponse represents the response for listing accounts.
type ListAccountsResponse struct {
	Items  []AccountResponse `json:"items"`
	Total  int64             `json:"total"`
	Offset int               `json:"offset"`
	Limit  int               `json:"limit"`
}

// CreateAccount handles POST /api/v1/accounts.
// Admin can create accounts with any role. Manager can only create user accounts.
func (h *AccountHandler) CreateAccount(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)

	var req CreateAccountRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid create account request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error(), "trace_id": traceID})
		return
	}

	role := models.AccountRole(req.Role)
	if role == "" {
		role = models.AccountRoleUser
	}

	// Manager can only create user accounts.
	if ac.Account.Role == models.AccountRoleManager && role != models.AccountRoleUser {
		c.JSON(http.StatusForbidden, gin.H{"error": "manager can only create user accounts", "trace_id": traceID})
		return
	}

	account, err := h.accountSvc.CreateAccount(c.Request.Context(), &services.CreateAccountRequest{
		AccountName:        req.AccountName,
		AccountDescription: req.AccountDescription,
		Role:               role,
		LoginName:          req.LoginName,
		LoginPassword:      req.LoginPassword,
		ExternalID:         req.ExternalID,
		Email:              req.Email,
		AuthProvider:       req.AuthProvider,
		AvatarURL:          req.AvatarURL,
		CreatorID:          ac.Account.AccountID,
	})
	if err != nil {
		h.log.Error("api", traceID, "failed to create account", "error", err.Error())
		if err == services.ErrDuplicateLoginName {
			c.JSON(http.StatusConflict, gin.H{"error": "login name already exists", "trace_id": traceID})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create account", "trace_id": traceID})
		return
	}

	h.log.Info("api", traceID, "account created", "account_id", account.AccountID)
	c.JSON(http.StatusCreated, toAccountResponse(account))
}

// ListAccounts handles GET /api/v1/accounts.
// Admin sees all accounts. Manager sees user accounts only. User sees self.
func (h *AccountHandler) ListAccounts(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)

	offset, _ := strconv.Atoi(c.DefaultQuery("offset", "0"))
	if offset < 0 {
		offset = 0
	}
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "1000"))
	if limit <= 0 || limit > 1000 {
		limit = 1000
	}

	accounts, total, err := h.accountSvc.ListAccounts(c.Request.Context(), offset, limit)
	if err != nil {
		h.log.Error("api", traceID, "failed to list accounts", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list accounts", "trace_id": traceID})
		return
	}

	items := make([]AccountResponse, 0, len(accounts))
	for i := range accounts {
		if !h.canViewAccount(ac, &accounts[i]) {
			continue
		}
		items = append(items, toAccountResponse(&accounts[i]))
	}

	c.JSON(http.StatusOK, ListAccountsResponse{
		Items:  items,
		Total:  total,
		Offset: offset,
		Limit:  limit,
	})
}

// GetAccount handles GET /api/v1/accounts/:account_id.
func (h *AccountHandler) GetAccount(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)
	accountID := c.Param("account_id")

	account, err := h.accountSvc.GetAccountByID(c.Request.Context(), accountID)
	if err != nil {
		if err == services.ErrAccountNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "account not found", "trace_id": traceID})
			return
		}
		h.log.Error("api", traceID, "failed to get account", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to get account", "trace_id": traceID})
		return
	}

	if !h.canViewAccount(ac, account) {
		c.JSON(http.StatusForbidden, gin.H{"error": "access denied", "trace_id": traceID})
		return
	}

	c.JSON(http.StatusOK, toAccountResponse(account))
}

// UpdateAccount handles PUT /api/v1/accounts/:account_id.
func (h *AccountHandler) UpdateAccount(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)
	accountID := c.Param("account_id")

	if ac.Account.Role != models.AccountRoleAdmin && ac.Account.AccountID != accountID {
		c.JSON(http.StatusForbidden, gin.H{"error": "access denied", "trace_id": traceID})
		return
	}

	var req UpdateAccountRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid update account request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error(), "trace_id": traceID})
		return
	}

	updateReq := &services.UpdateAccountRequest{
		AccountID:  accountID,
		CallerRole: ac.Account.Role,
	}
	if req.AccountName != "" {
		updateReq.AccountName = &req.AccountName
	}
	if req.AccountDescription != "" {
		updateReq.AccountDescription = &req.AccountDescription
	}
	if req.Role != "" {
		role := models.AccountRole(req.Role)
		updateReq.Role = &role
	}
	if req.Status != "" {
		status := models.AccountStatus(req.Status)
		updateReq.Status = &status
	}
	if req.ExternalID != "" {
		updateReq.ExternalID = &req.ExternalID
	}
	if req.Email != "" {
		updateReq.Email = &req.Email
	}
	if req.AuthProvider != "" {
		updateReq.AuthProvider = &req.AuthProvider
	}
	if req.AvatarURL != "" {
		updateReq.AvatarURL = &req.AvatarURL
	}

	account, err := h.accountSvc.UpdateAccount(c.Request.Context(), updateReq)
	if err != nil {
		h.log.Error("api", traceID, "failed to update account", "error", err.Error())
		if err == services.ErrAccountNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "account not found", "trace_id": traceID})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to update account", "trace_id": traceID})
		return
	}

	h.log.Info("api", traceID, "account updated", "account_id", accountID)
	c.JSON(http.StatusOK, toAccountResponse(account))
}

// DeleteAccount handles DELETE /api/v1/accounts/:account_id.
func (h *AccountHandler) DeleteAccount(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)
	accountID := c.Param("account_id")

	if ac.Account.Role != models.AccountRoleAdmin && ac.Account.AccountID != accountID {
		c.JSON(http.StatusForbidden, gin.H{"error": "access denied", "trace_id": traceID})
		return
	}

	if err := h.accountSvc.SoftDeleteAccount(c.Request.Context(), accountID); err != nil {
		h.log.Error("api", traceID, "failed to delete account", "error", err.Error())
		if err == services.ErrAccountNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "account not found", "trace_id": traceID})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete account", "trace_id": traceID})
		return
	}

	h.log.Info("api", traceID, "account deleted", "account_id", accountID)
	c.JSON(http.StatusOK, gin.H{"message": "account deleted", "trace_id": traceID})
}

// ChangePassword handles POST /api/v1/accounts/:account_id/password.
func (h *AccountHandler) ChangePassword(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)
	accountID := c.Param("account_id")

	if ac.Account.Role != models.AccountRoleAdmin && ac.Account.AccountID != accountID {
		c.JSON(http.StatusForbidden, gin.H{"error": "access denied", "trace_id": traceID})
		return
	}

	var req ChangePasswordRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid change password request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error(), "trace_id": traceID})
		return
	}

	if err := h.accountSvc.ChangePassword(c.Request.Context(), accountID, req.NewPassword); err != nil {
		h.log.Error("api", traceID, "failed to change password", "error", err.Error())
		if err == services.ErrAccountNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "account not found", "trace_id": traceID})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to change password", "trace_id": traceID})
		return
	}

	h.log.Info("api", traceID, "password changed", "account_id", accountID)
	c.JSON(http.StatusOK, gin.H{"message": "password changed", "trace_id": traceID})
}

// Login handles POST /api/v1/accounts/login.
func (h *AccountHandler) Login(c *gin.Context) {
	traceID := middleware.GetTraceID(c)

	var req LoginRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid login request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error(), "trace_id": traceID})
		return
	}

	account, sessionKey, expiry, err := h.accountSvc.LoginByPassword(c.Request.Context(), req.LoginName, req.Password)
	if err != nil {
		h.log.Warn("api", traceID, "login failed", "error", err.Error())
		if err == services.ErrAccountNotFound || err == services.ErrPasswordNotSet {
			c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid credentials", "trace_id": traceID})
			return
		}
		c.JSON(http.StatusUnauthorized, gin.H{"error": "invalid credentials", "trace_id": traceID})
		return
	}

	h.log.Info("api", traceID, "login succeeded", "account_id", account.AccountID)
	c.JSON(http.StatusOK, LoginResponse{
		AccountID:   account.AccountID,
		SessionKey:  sessionKey,
		ExpiresAtMs: expiry,
	})
}

// CreateSession handles POST /api/v1/accounts/:account_id/session.
// Manager can only create sessions for user accounts.
func (h *AccountHandler) CreateSession(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)
	accountID := c.Param("account_id")

	account, err := h.accountSvc.GetAccountByID(c.Request.Context(), accountID)
	if err != nil {
		if err == services.ErrAccountNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "account not found", "trace_id": traceID})
			return
		}
		h.log.Error("api", traceID, "failed to get account for session", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create session", "trace_id": traceID})
		return
	}

	if ac.Account.Role == models.AccountRoleManager && account.Role != models.AccountRoleUser {
		c.JSON(http.StatusForbidden, gin.H{"error": "manager can only create sessions for user accounts", "trace_id": traceID})
		return
	}
	if ac.Account.Role != models.AccountRoleAdmin && ac.Account.AccountID != accountID {
		c.JSON(http.StatusForbidden, gin.H{"error": "access denied", "trace_id": traceID})
		return
	}

	sessionKey, expiry, err := h.accountSvc.CreateLoginSession(c.Request.Context(), accountID)
	if err != nil {
		h.log.Error("api", traceID, "failed to create session", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create session", "trace_id": traceID})
		return
	}

	h.log.Info("api", traceID, "session created", "account_id", accountID)
	c.JSON(http.StatusOK, LoginResponse{
		AccountID:   accountID,
		SessionKey:  sessionKey,
		ExpiresAtMs: expiry,
	})
}

// GetMe handles GET /api/v1/accounts/me.
func (h *AccountHandler) GetMe(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)

	account, err := h.accountSvc.GetAccountByID(c.Request.Context(), ac.Account.AccountID)
	if err != nil {
		h.log.Error("api", traceID, "failed to get current account", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to get account", "trace_id": traceID})
		return
	}

	c.JSON(http.StatusOK, toAccountResponse(account))
}

// canViewAccount checks whether the caller can view the target account.
func (h *AccountHandler) canViewAccount(ac middleware.AuthContext, account *models.Account) bool {
	if ac.Account.Role == models.AccountRoleAdmin {
		return true
	}
	if ac.Account.AccountID == account.AccountID {
		return true
	}
	if ac.Account.Role == models.AccountRoleManager && account.Role == models.AccountRoleUser {
		return true
	}
	return false
}

// toAccountResponse converts an Account model to API response.
func toAccountResponse(a *models.Account) AccountResponse {
	return AccountResponse{
		AccountID:          a.AccountID,
		AccountName:        a.AccountName,
		AccountDescription: a.AccountDescription,
		Role:               string(a.Role),
		Status:             string(a.Status),
		DeleteAtMs:         a.DeleteAtMs,
		CreatorID:          a.CreatorID,
		ExternalID:         a.ExternalID,
		Email:              a.Email,
		AuthProvider:       a.AuthProvider,
		AvatarURL:          a.AvatarURL,
		LoginName:          a.LoginName,
		CreateAtMs:         a.CreateAtMs,
		UpdateAtMs:         a.UpdateAtMs,
	}
}

// parseAccountRole parses a role string and returns the model role.
func parseAccountRole(role string) models.AccountRole {
	return models.AccountRole(strings.ToLower(role))
}
