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
	"time"

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

// responseRecorder wraps gin.ResponseWriter to capture the response body for
// audit log resource ID extraction without altering the client response.
type responseRecorder struct {
	gin.ResponseWriter
	body *bytes.Buffer
}

func newResponseRecorder(w gin.ResponseWriter) *responseRecorder {
	return &responseRecorder{ResponseWriter: w, body: &bytes.Buffer{}}
}

func (r *responseRecorder) Write(b []byte) (int, error) {
	r.body.Write(b)
	return r.ResponseWriter.Write(b)
}

func (r *responseRecorder) WriteString(s string) (int, error) {
	r.body.WriteString(s)
	return r.ResponseWriter.WriteString(s)
}

// AuditLogger returns a Gin middleware that writes audit log records for
// lifecycle actions (POST, PUT, PATCH, DELETE) after the handler completes.
func AuditLogger(auditSvc AuditLogService) gin.HandlerFunc {
	return func(c *gin.Context) {
		// Capture request body for resource name extraction.
		var bodyBytes []byte
		if c.Request.Body != nil && c.Request.Body != http.NoBody {
			bodyBytes, _ = io.ReadAll(c.Request.Body)
			c.Request.Body = io.NopCloser(bytes.NewBuffer(bodyBytes))
		}

		// Wrap the response writer so we can inspect successful create responses.
		recorder := newResponseRecorder(c.Writer)
		c.Writer = recorder

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

		// For successful create responses, try to extract the generated resource ID
		// from the response envelope so audit logs reference the real object.
		if isCreateMethod(method) && isSuccessStatus(recorder.Status()) {
			if extractedID := extractCreatedResourceID(resourceType, recorder.body.Bytes()); extractedID != "" {
				resourceID = extractedID
			}
		}

		action := buildAction(method, resourceType, c)
		detail := fmt.Sprintf("status=%d trace_id=%s", recorder.Status(), GetTraceID(c))
		resourceName := extractResourceName(resourceType, bodyBytes)

		// Write audit log asynchronously to avoid delaying the response.
		// Use a detached context so the write is not cancelled when the HTTP
		// request completes.
		clientIP := c.ClientIP()
		ctx, cancel := context.WithTimeout(context.WithoutCancel(c.Request.Context()), 5*time.Second)
		go func() {
			defer cancel()
			_, _ = auditSvc.Log(ctx, &services.AuditLogRequest{
				AccountID:    accountID,
				APIKeyID:     apiKeyID,
				Action:       action,
				ResourceType: resourceType,
				ResourceID:   resourceID,
				ResourceName: resourceName,
				Detail:       detail,
				ClientIP:     clientIP,
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

// isCreateMethod returns true for POST requests.
func isCreateMethod(method string) bool {
	return method == http.MethodPost
}

// isSuccessStatus returns true for 2xx status codes.
func isSuccessStatus(status int) bool {
	return status >= 200 && status < 300
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

// buildAction returns a stable action name for the request.
// Special cases are handled for login, password change, and session creation.
func buildAction(method, resourceType string, c *gin.Context) string {
	path := c.Request.URL.Path

	if strings.HasSuffix(path, "/password") && method == http.MethodPost {
		return "change_password"
	}
	if strings.HasSuffix(path, "/session") && method == http.MethodPost {
		return "create_session"
	}
	if strings.HasSuffix(path, "/login") && method == http.MethodPost {
		return "login"
	}

	verb := methodVerb(method)
	return fmt.Sprintf("%s_%s", verb, resourceType)
}

// methodVerb maps an HTTP method to a stable action verb.
func methodVerb(method string) string {
	switch method {
	case http.MethodPost:
		return "create"
	case http.MethodPut, http.MethodPatch:
		return "update"
	case http.MethodDelete:
		return "delete"
	default:
		return strings.ToLower(method)
	}
}

// extractCreatedResourceID parses a successful create response envelope and
// returns the generated resource ID for the given resource type.
func extractCreatedResourceID(resourceType string, body []byte) string {
	if len(body) == 0 {
		return ""
	}

	var envelope struct {
		Data map[string]interface{} `json:"data"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		return ""
	}
	if envelope.Data == nil {
		return ""
	}

	idField := ""
	switch resourceType {
	case "account":
		idField = "account_id"
	case "api_key":
		idField = "api_key_id"
	case "group":
		idField = "group_id"
	case "group_member":
		idField = "member_id"
	case "group_message":
		idField = "message_id"
	case "audit_log":
		idField = "audit_log_id"
	}
	if idField == "" {
		return ""
	}

	if v, ok := envelope.Data[idField]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
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
