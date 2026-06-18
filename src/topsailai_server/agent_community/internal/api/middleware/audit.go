// Package middleware provides HTTP middleware for the ACS API.
package middleware

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
)

// AuditLogService is the minimal interface required by the audit middleware.
// It mirrors the Log method of *services.AuditLogService so that tests can
// inject mocks without importing the full services package.
type AuditLogService interface {
	Log(ctx context.Context, req *services.AuditLogRequest) (*models.AuditLog, error)
}

// AuditLogger returns a Gin middleware that writes audit log records for
// lifecycle actions (POST, PUT, DELETE) after the handler completes.
func AuditLogger(auditSvc AuditLogService) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Capture request body for resource name extraction.
		var bodyBytes []byte
		if c.Request.Body != nil && c.Request.Body != http.NoBody {
			bodyBytes, _ = io.ReadAll(c.Request.Body)
			c.Request.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))
		}

		// Process the request.
		c.Next()

		method := c.Request.Method
		if !isAuditMethod(method) {
			return
		}

		resourceType, resourceID := extractResource(c)
		if resourceType == "" {
			return
		}

		ac, _ := GetAuthContext(c)
		accountID := ""
		apiKeyID := ""
		if ac.IsAuthenticated && ac.Account != nil {
			accountID = ac.Account.AccountID
		}
		if ac.APIKey != nil {
			apiKeyID = ac.APIKey.APIKeyID
		}

		action := fmt.Sprintf("%s %s", strings.ToLower(method), resourceType)
		detail := fmt.Sprintf("status=%d trace_id=%s", c.Writer.Status(), GetTraceID(c))

		resourceName := extractResourceName(resourceType, bodyBytes)

		// Write audit log asynchronously to avoid delaying the response.
		go func() {
			_, _ = auditSvc.Log(c.Request.Context(), &services.AuditLogRequest{
				AccountID:    accountID,
				APIKeyID:     apiKeyID,
				Action:       action,
				ResourceType: resourceType,
				ResourceID:   resourceID,
				ResourceName: resourceName,
				Detail:       detail,
				ClientIP:     c.ClientIP(),
			})
		}()
	}
}

// isAuditMethod returns true for HTTP methods that represent lifecycle actions.
func isAuditMethod(method string) bool {
	switch method {
	case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
		return true
	default:
		return false
	}
}

// extractResource derives resource type and ID from the request path and params.
func extractResource(c *gin.Context) (string, string) {
	path := c.Request.URL.Path

	// API key routes: /api/v1/accounts/:account_id/api-keys/:api_key_id
	if strings.Contains(path, "/api-keys/") {
		return "api_key", c.Param("api_key_id")
	}
	if strings.Contains(path, "/api-keys") && c.Request.Method == http.MethodPost {
		return "api_key", c.Param("account_id")
	}

	// Message routes: /api/v1/groups/:group_id/messages/:message_id
	if strings.Contains(path, "/messages/") {
		return "group_message", c.Param("message_id")
	}
	if strings.Contains(path, "/messages") && c.Request.Method == http.MethodPost {
		return "group_message", ""
	}

	// Group member routes: /api/v1/groups/:group_id/members/:member_id
	if strings.Contains(path, "/members/") {
		return "group_member", c.Param("member_id")
	}
	if strings.Contains(path, "/members") && c.Request.Method == http.MethodPost {
		return "group_member", ""
	}

	// Account routes: /api/v1/accounts/:account_id
	if strings.Contains(path, "/accounts/") {
		return "account", c.Param("account_id")
	}
	if strings.Contains(path, "/accounts") && c.Request.Method == http.MethodPost {
		return "account", ""
	}

	// Audit log routes: /api/v1/audit-logs/:audit_log_id
	if strings.Contains(path, "/audit-logs/") {
		return "audit_log", c.Param("audit_log_id")
	}

	// Group routes: /api/v1/groups/:group_id
	if strings.Contains(path, "/groups/") {
		return "group", c.Param("group_id")
	}
	if strings.Contains(path, "/groups") && c.Request.Method == http.MethodPost {
		return "group", ""
	}

	return "", ""
}

// extractResourceName tries to read a friendly name from the request body.
func extractResourceName(resourceType string, body []byte) string {
	if len(body) == 0 {
		return ""
	}

	var payload map[string]interface{}
	if err := json.Unmarshal(body, &payload); err != nil {
		return ""
	}

	nameFields := []string{}
	switch resourceType {
	case "account":
		nameFields = []string{"account_name", "name"}
	case "api_key":
		nameFields = []string{"api_key_name", "name"}
	case "group":
		nameFields = []string{"group_name", "name"}
	case "group_member":
		nameFields = []string{"member_name", "name"}
	case "group_message":
		nameFields = []string{"message_text", "text"}
	default:
		nameFields = []string{"name", "title", "id"}
	}

	for _, field := range nameFields {
		if v, ok := payload[field]; ok {
			if s, ok := v.(string); ok {
				return s
			}
		}
	}
	return ""
}
