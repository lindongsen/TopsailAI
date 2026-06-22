// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"

	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/pkg/logger"
)

// APIKeyHandler handles API key-related HTTP requests.
type APIKeyHandler struct {
	apiKeySvc  *services.APIKeyService
	accountSvc *services.AccountService
	log        *logger.Logger
}

// NewAPIKeyHandler creates a new APIKeyHandler.
func NewAPIKeyHandler(apiKeySvc *services.APIKeyService, accountSvc *services.AccountService, log *logger.Logger) *APIKeyHandler {
	return &APIKeyHandler{
		apiKeySvc:  apiKeySvc,
		accountSvc: accountSvc,
		log:        log,
	}
}

// CreateAPIKeyRequest represents the request body for creating an API key.
type CreateAPIKeyRequest struct {
	APIKeyName string `json:"api_key_name" binding:"required"`
	Role       string `json:"role"`
}

// APIKeyResponse represents an API key in API responses.
type APIKeyResponse struct {
	APIKeyID   string `json:"api_key_id"`
	APIKeyName string `json:"api_key_name"`
	Role       string `json:"role"`
	Status     string `json:"status"`
	CreatorID  string `json:"creator_id"`
	OwnerID    string `json:"owner_id"`
	CreateAtMs int64  `json:"create_at_ms"`
	UpdateAtMs int64  `json:"update_at_ms"`
}

// APIKeyWithTokenResponse includes the plaintext token once after creation.
type APIKeyWithTokenResponse struct {
	APIKeyResponse
	Token string `json:"token"`
}

// ListAPIKeysResponse represents the response for listing API keys.
type ListAPIKeysResponse struct {
	Items  []APIKeyResponse `json:"items"`
	Total  int64            `json:"total"`
	Offset int              `json:"offset"`
	Limit  int              `json:"limit"`
}

// CreateAPIKey handles POST /api/v1/accounts/:account_id/api-keys.
func (h *APIKeyHandler) CreateAPIKey(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)
	ownerID := c.Param("account_id")

	// Manager accounts cannot create API keys.
	if ac.Account.Role == models.AccountRoleManager {
		c.JSON(http.StatusForbidden, gin.H{"error": "manager cannot create api keys", "trace_id": traceID})
		return
	}

	// Non-admin users can only create keys for themselves.
	if ac.Account.Role != models.AccountRoleAdmin && ac.Account.AccountID != ownerID {
		c.JSON(http.StatusForbidden, gin.H{"error": "access denied", "trace_id": traceID})
		return
	}

	var req CreateAPIKeyRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		h.log.Warn("api", traceID, "invalid create api key request", "error", err.Error())
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error(), "trace_id": traceID})
		return
	}

	role := models.APIKeyRole(req.Role)
	if role == "" {
		role = models.APIKeyRoleUser
	}

	result, err := h.apiKeySvc.CreateAPIKey(c.Request.Context(), &services.CreateAPIKeyRequest{
		APIKeyName: req.APIKeyName,
		Role:       role,
		OwnerID:    ownerID,
		CreatorID:  ac.Account.AccountID,
	})
	if err != nil {
		h.log.Error("api", traceID, "failed to create api key", "error", err.Error())
		switch err {
		case services.ErrAccountNotFound:
			c.JSON(http.StatusNotFound, gin.H{"error": "owner account not found", "trace_id": traceID})
		case services.ErrManagerCannotCreate:
			c.JSON(http.StatusForbidden, gin.H{"error": "manager cannot create api keys", "trace_id": traceID})
		case services.ErrAPIKeyRoleTooHigh:
			c.JSON(http.StatusForbidden, gin.H{"error": "api key role cannot exceed owner role", "trace_id": traceID})
		case services.ErrAPIKeyLimitReached:
			c.JSON(http.StatusConflict, gin.H{"error": "api key limit reached", "trace_id": traceID})
		default:
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to create api key", "trace_id": traceID})
		}
		return
	}

	h.log.Info("api", traceID, "api key created", "api_key_id", result.APIKey.APIKeyID, "owner_id", ownerID)
	writeDataResponse(c, http.StatusCreated, APIKeyWithTokenResponse{
		APIKeyResponse: toAPIKeyResponse(result.APIKey),
		Token:          result.Token,
	}, traceID)
}

// ListAPIKeys handles GET /api/v1/accounts/:account_id/api-keys.
func (h *APIKeyHandler) ListAPIKeys(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)
	ownerID := c.Param("account_id")

	if ac.Account.Role != models.AccountRoleAdmin && ac.Account.AccountID != ownerID {
		c.JSON(http.StatusForbidden, gin.H{"error": "access denied", "trace_id": traceID})
		return
	}

	offset, _ := strconv.Atoi(c.DefaultQuery("offset", "0"))
	if offset < 0 {
		offset = 0
	}
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "1000"))
	if limit <= 0 || limit > 1000 {
		limit = 1000
	}

	keys, total, err := h.apiKeySvc.ListAPIKeysByOwner(c.Request.Context(), ownerID, offset, limit)
	if err != nil {
		h.log.Error("api", traceID, "failed to list api keys", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list api keys", "trace_id": traceID})
		return
	}

	items := make([]APIKeyResponse, 0, len(keys))
	for i := range keys {
		items = append(items, toAPIKeyResponse(&keys[i]))
	}

	writeListResponse(c, http.StatusOK, items, total, offset, limit, traceID)
}

// DeleteAPIKey handles DELETE /api/v1/accounts/:account_id/api-keys/:api_key_id.
func (h *APIKeyHandler) DeleteAPIKey(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	ac, _ := middleware.GetAuthContext(c)
	ownerID := c.Param("account_id")
	apiKeyID := c.Param("api_key_id")

	if ac.Account.Role != models.AccountRoleAdmin && ac.Account.AccountID != ownerID {
		c.JSON(http.StatusForbidden, gin.H{"error": "access denied", "trace_id": traceID})
		return
	}

	if err := h.apiKeySvc.DeleteAPIKey(c.Request.Context(), apiKeyID); err != nil {
		h.log.Error("api", traceID, "failed to delete api key", "error", err.Error())
		if err == services.ErrAPIKeyNotFound {
			c.JSON(http.StatusNotFound, gin.H{"error": "api key not found", "trace_id": traceID})
			return
		}
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to delete api key", "trace_id": traceID})
		return
	}

	h.log.Info("api", traceID, "api key deleted", "api_key_id", apiKeyID)
	writeDataResponse(c, http.StatusOK, gin.H{"message": "api key deleted"}, traceID)
}

// toAPIKeyResponse converts an APIKey model to API response.
func toAPIKeyResponse(k *models.APIKey) APIKeyResponse {
	return APIKeyResponse{
		APIKeyID:   k.APIKeyID,
		APIKeyName: k.APIKeyName,
		Role:       string(k.Role),
		Status:     string(k.Status),
		CreatorID:  k.CreatorID,
		OwnerID:    k.OwnerID,
		CreateAtMs: k.CreateAtMs,
		UpdateAtMs: k.UpdateAtMs,
	}
}
