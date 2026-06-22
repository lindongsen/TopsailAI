// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"fmt"

	"gorm.io/gorm"

	"github.com/topsailai/agent-community/internal/models"
)

// clientIPKey is the context key used to carry the HTTP client IP through
// request context so that business services can include it in audit logs.
type clientIPKey struct{}

// ContextWithClientIP returns a new context with the client IP attached.
func ContextWithClientIP(ctx context.Context, ip string) context.Context {
	return context.WithValue(ctx, clientIPKey{}, ip)
}

// ClientIPFromContext returns the client IP stored in the context, if any.
func ClientIPFromContext(ctx context.Context) (string, bool) {
	ip, ok := ctx.Value(clientIPKey{}).(string)
	return ip, ok
}

// AuditLogRequest holds parameters for writing an audit log record.
type AuditLogRequest struct {
	AccountID    string
	APIKeyID     string
	Action       string
	ResourceType string
	ResourceID   string
	ResourceName string
	Detail       string
	ClientIP     string
}

// AuditLogFilter holds optional filters for listing audit logs.
type AuditLogFilter struct {
	AccountID    string
	APIKeyID     string
	Action       string
	ResourceType string
	ResourceID   string
	StartTimeMs  int64
	EndTimeMs    int64
	SortKey      string
	OrderBy      string
}

// AuditLogService writes and queries audit log records.
type AuditLogService struct {
	db *gorm.DB
}

// NewAuditLogService creates a new AuditLogService.
func NewAuditLogService(db *gorm.DB) *AuditLogService {
	return &AuditLogService{db: db}
}

// Log writes an audit log record.
func (s *AuditLogService) Log(ctx context.Context, req *AuditLogRequest) (*models.AuditLog, error) {
	if req.Action == "" {
		return nil, fmt.Errorf("action is required")
	}
	if req.ResourceType == "" {
		return nil, fmt.Errorf("resource_type is required")
	}
	if req.ResourceID == "" {
		return nil, fmt.Errorf("resource_id is required")
	}

	log := &models.AuditLog{
		AccountID:    req.AccountID,
		APIKeyID:     req.APIKeyID,
		Action:       req.Action,
		ResourceType: req.ResourceType,
		ResourceID:   req.ResourceID,
		ResourceName: req.ResourceName,
		Detail:       req.Detail,
		ClientIP:     req.ClientIP,
	}

	if err := s.db.WithContext(ctx).Create(log).Error; err != nil {
		return nil, fmt.Errorf("failed to create audit log: %w", err)
	}

	// Also print the lifecycle event to stdout for operational visibility.
	fmt.Printf("[AUDIT] %s %s/%s account=%s api_key=%s detail=%s\n",
		log.Action, log.ResourceType, log.ResourceID, log.AccountID, log.APIKeyID, log.Detail)

	return log, nil
}

// ListAuditLogs returns a paginated list of audit logs with optional filters.
func (s *AuditLogService) ListAuditLogs(ctx context.Context, filter *AuditLogFilter, offset, limit int) ([]models.AuditLog, int64, error) {
	if limit <= 0 {
		limit = 1000
	}

	query := s.db.WithContext(ctx).Model(&models.AuditLog{})
	if filter != nil {
		if filter.AccountID != "" {
			query = query.Where("account_id = ?", filter.AccountID)
		}
		if filter.APIKeyID != "" {
			query = query.Where("api_key_id = ?", filter.APIKeyID)
		}
		if filter.Action != "" {
			query = query.Where("action = ?", filter.Action)
		}
		if filter.ResourceType != "" {
			query = query.Where("resource_type = ?", filter.ResourceType)
		}
		if filter.ResourceID != "" {
			query = query.Where("resource_id = ?", filter.ResourceID)
		}
		if filter.StartTimeMs > 0 {
			query = query.Where("create_at_ms >= ?", filter.StartTimeMs)
		}
		if filter.EndTimeMs > 0 {
			query = query.Where("create_at_ms <= ?", filter.EndTimeMs)
		}
	}

	var total int64
	if err := query.Count(&total).Error; err != nil {
		return nil, 0, fmt.Errorf("failed to count audit logs: %w", err)
	}

	orderClause := "create_at_ms desc"
	if filter != nil && filter.SortKey != "" {
		order := "desc"
		if filter.OrderBy == "asc" {
			order = "asc"
		}
		orderClause = fmt.Sprintf("%s %s", filter.SortKey, order)
	}

	var logs []models.AuditLog
	if err := query.Order(orderClause).Offset(offset).Limit(limit).Find(&logs).Error; err != nil {
		return nil, 0, fmt.Errorf("failed to list audit logs: %w", err)
	}
	return logs, total, nil
}

// GetAuditLog retrieves a single audit log by ID.
func (s *AuditLogService) GetAuditLog(ctx context.Context, auditLogID string) (*models.AuditLog, error) {
	var log models.AuditLog
	if err := s.db.WithContext(ctx).First(&log, "audit_log_id = ?", auditLogID).Error; err != nil {
		return nil, fmt.Errorf("failed to get audit log: %w", err)
	}
	return &log, nil
}
