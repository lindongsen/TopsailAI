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

// AuditLogHandler handles audit log-related HTTP requests.
type AuditLogHandler struct {
	auditSvc *services.AuditLogService
	log      *logger.Logger
}

// NewAuditLogHandler creates a new AuditLogHandler.
func NewAuditLogHandler(auditSvc *services.AuditLogService, log *logger.Logger) *AuditLogHandler {
	return &AuditLogHandler{
		auditSvc: auditSvc,
		log:      log,
	}
}

// AuditLogResponse represents an audit log in API responses.
type AuditLogResponse struct {
	AuditLogID   string `json:"audit_log_id"`
	AccountID    string `json:"account_id"`
	APIKeyID     string `json:"api_key_id"`
	Action       string `json:"action"`
	ResourceType string `json:"resource_type"`
	ResourceID   string `json:"resource_id"`
	ResourceName string `json:"resource_name"`
	Detail       string `json:"detail"`
	ClientIP     string `json:"client_ip"`
	CreateAtMs   int64  `json:"create_at_ms"`
}

// ListAuditLogsResponse represents the response for listing audit logs.
type ListAuditLogsResponse struct {
	Items  []AuditLogResponse `json:"items"`
	Total  int64              `json:"total"`
	Offset int                `json:"offset"`
	Limit  int                `json:"limit"`
}

// ListAuditLogs handles GET /api/v1/audit-logs.
func (h *AuditLogHandler) ListAuditLogs(c *gin.Context) {
	traceID := middleware.GetTraceID(c)

	offset, _ := strconv.Atoi(c.DefaultQuery("offset", "0"))
	if offset < 0 {
		offset = 0
	}
	limit, _ := strconv.Atoi(c.DefaultQuery("limit", "1000"))
	if limit <= 0 || limit > 1000 {
		limit = 1000
	}

	filter := &services.AuditLogFilter{}
	if accountID := c.Query("account_id"); accountID != "" {
		filter.AccountID = accountID
	}
	if apiKeyID := c.Query("api_key_id"); apiKeyID != "" {
		filter.APIKeyID = apiKeyID
	}
	if action := c.Query("action"); action != "" {
		filter.Action = action
	}
	if resourceType := c.Query("resource_type"); resourceType != "" {
		filter.ResourceType = resourceType
	}
	if resourceID := c.Query("resource_id"); resourceID != "" {
		filter.ResourceID = resourceID
	}
	if start := c.Query("start_time_ms"); start != "" {
		if v, err := strconv.ParseInt(start, 10, 64); err == nil {
			filter.StartTimeMs = v
		}
	}
	if end := c.Query("end_time_ms"); end != "" {
		if v, err := strconv.ParseInt(end, 10, 64); err == nil {
			filter.EndTimeMs = v
		}
	}
	// Support create_at_ms={start}-{end} range filter as documented in API.md.
	if createAtRange := c.Query("create_at_ms"); createAtRange != "" {
		parts := strings.Split(createAtRange, "-")
		if len(parts) == 2 {
			if start, err := strconv.ParseInt(parts[0], 10, 64); err == nil {
				filter.StartTimeMs = start
			}
			if end, err := strconv.ParseInt(parts[1], 10, 64); err == nil {
				filter.EndTimeMs = end
			}
		}
	}
	filter.SortKey = c.DefaultQuery("sort_key", "create_at_ms")
	if orderBy := c.Query("order_by"); orderBy == "asc" || orderBy == "desc" {
		filter.OrderBy = orderBy
	} else {
		filter.OrderBy = "desc"
	}

	logs, total, err := h.auditSvc.ListAuditLogs(c.Request.Context(), filter, offset, limit)
	if err != nil {
		h.log.Error("api", traceID, "failed to list audit logs", "error", err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to list audit logs", "trace_id": traceID})
		return
	}

	items := make([]AuditLogResponse, 0, len(logs))
	for i := range logs {
		items = append(items, toAuditLogResponse(&logs[i]))
	}

	writeListResponse(c, http.StatusOK, items, total, offset, limit, traceID)
}

// GetAuditLog handles GET /api/v1/audit-logs/:audit_log_id.
func (h *AuditLogHandler) GetAuditLog(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	auditLogID := c.Param("audit_log_id")

	if auditLogID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "audit_log_id is required", "trace_id": traceID})
		return
	}

	log, err := h.auditSvc.GetAuditLog(c.Request.Context(), auditLogID)
	if err != nil {
		h.log.Error("api", traceID, "failed to get audit log", "error", err.Error())
		c.JSON(http.StatusNotFound, gin.H{"error": "audit log not found", "trace_id": traceID})
		return
	}

	c.JSON(http.StatusOK, toAuditLogResponse(log))
}

// toAuditLogResponse converts an AuditLog model to API response.
func toAuditLogResponse(l *models.AuditLog) AuditLogResponse {
	return AuditLogResponse{
		AuditLogID:   l.AuditLogID,
		AccountID:    l.AccountID,
		APIKeyID:     l.APIKeyID,
		Action:       l.Action,
		ResourceType: l.ResourceType,
		ResourceID:   l.ResourceID,
		ResourceName: l.ResourceName,
		Detail:       l.Detail,
		ClientIP:     l.ClientIP,
		CreateAtMs:   l.CreateAtMs,
	}
}
