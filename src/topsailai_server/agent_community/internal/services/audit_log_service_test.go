// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/models"
)

func TestAuditLogService_Log_CreatesRecord(t *testing.T) {
	_, accountSvc, apiKeySvc, auditSvc := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Audited",
		LoginName:   "audited",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "audit-key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    acc.AccountID,
		CreatorID:  acc.AccountID,
	})
	require.NoError(t, err)

	log, err := auditSvc.Log(ctx, &AuditLogRequest{
		AccountID:    acc.AccountID,
		APIKeyID:     key.APIKey.APIKeyID,
		Action:       "create",
		ResourceType: "group",
		ResourceID:   "group-001",
		ResourceName: "Test Group",
		Detail:       "created group",
		ClientIP:     "127.0.0.1",
	})
	require.NoError(t, err)
	assert.NotEmpty(t, log.AuditLogID)
	assert.Equal(t, acc.AccountID, log.AccountID)
	assert.Equal(t, "group", log.ResourceType)
}

func TestAuditLogService_ListAuditLogs_WithFilters(t *testing.T) {
	_, accountSvc, _, auditSvc := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Lister",
		LoginName:   "lister",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	for i := 0; i < 3; i++ {
		_, err := auditSvc.Log(ctx, &AuditLogRequest{
			AccountID:    acc.AccountID,
			Action:       "create",
			ResourceType: "group",
			ResourceID:   "group-001",
			ClientIP:     "127.0.0.1",
		})
		require.NoError(t, err)
	}

	_, err = auditSvc.Log(ctx, &AuditLogRequest{
		AccountID:    acc.AccountID,
		Action:       "delete",
		ResourceType: "api_key",
		ResourceID:   "ak-001",
		ClientIP:     "127.0.0.1",
	})
	require.NoError(t, err)

	logs, total, err := auditSvc.ListAuditLogs(ctx, &AuditLogFilter{
		AccountID:    acc.AccountID,
		ResourceType: "group",
	}, 0, 10)
	require.NoError(t, err)
	assert.Equal(t, int64(3), total)
	assert.Len(t, logs, 3)

	logs, total, err = auditSvc.ListAuditLogs(ctx, &AuditLogFilter{
		Action: "delete",
	}, 0, 10)
	require.NoError(t, err)
	assert.Equal(t, int64(1), total)
	assert.Len(t, logs, 1)
}
