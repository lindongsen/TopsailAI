// Package services provides business logic for ACS resources.
package services

import (
	"context"
	"testing"
	"time"

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

func TestAuditLogService_Log_ValidationErrors(t *testing.T) {
	_, _, _, auditSvc := newTestServices(t)
	ctx := context.Background()

	base := &AuditLogRequest{
		Action:       "create",
		ResourceType: "group",
		ResourceID:   "group-001",
	}

	cases := []struct {
		name    string
		mutate  func(r *AuditLogRequest)
		wantErr string
	}{
		{
			name: "missing action",
			mutate: func(r *AuditLogRequest) {
				r.Action = ""
			},
			wantErr: "action is required",
		},
		{
			name: "missing resource_type",
			mutate: func(r *AuditLogRequest) {
				r.ResourceType = ""
			},
			wantErr: "resource_type is required",
		},
		{
			name: "missing resource_id",
			mutate: func(r *AuditLogRequest) {
				r.ResourceID = ""
			},
			wantErr: "resource_id is required",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := *base
			tc.mutate(&req)
			_, err := auditSvc.Log(ctx, &req)
			require.Error(t, err)
			assert.Contains(t, err.Error(), tc.wantErr)
		})
	}
}

func TestAuditLogService_Log_DatabaseError(t *testing.T) {
	db, _, _, auditSvc := newTestServices(t)
	ctx := context.Background()

	require.NoError(t, db.Exec("DROP TABLE audit_logs").Error)

	_, err := auditSvc.Log(ctx, &AuditLogRequest{
		Action:       "create",
		ResourceType: "group",
		ResourceID:   "group-001",
	})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to create audit log")
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

func TestAuditLogService_ListAuditLogs_NilFilter(t *testing.T) {
	_, accountSvc, _, auditSvc := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "NilFilter",
		LoginName:   "nilfilter",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	for i := 0; i < 5; i++ {
		_, err := auditSvc.Log(ctx, &AuditLogRequest{
			AccountID:    acc.AccountID,
			Action:       "create",
			ResourceType: "group",
			ResourceID:   "group-001",
		})
		require.NoError(t, err)
	}

	// CreateAccount no longer writes an account.create audit log (handled by middleware),
	// so total is exactly 5.
	logs, total, err := auditSvc.ListAuditLogs(ctx, nil, 0, 100)
	require.NoError(t, err)
	assert.Equal(t, int64(5), total)
	assert.Len(t, logs, 5)
}

func TestAuditLogService_ListAuditLogs_IndividualFilters(t *testing.T) {
	_, accountSvc, apiKeySvc, auditSvc := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Individual",
		LoginName:   "individual",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	key, err := apiKeySvc.CreateAPIKey(ctx, &CreateAPIKeyRequest{
		APIKeyName: "key",
		Role:       models.APIKeyRoleUser,
		OwnerID:    acc.AccountID,
		CreatorID:  acc.AccountID,
	})
	require.NoError(t, err)

	_, err = auditSvc.Log(ctx, &AuditLogRequest{
		AccountID:    acc.AccountID,
		APIKeyID:     key.APIKey.APIKeyID,
		Action:       "create",
		ResourceType: "group",
		ResourceID:   "group-001",
		ResourceName: "First",
	})
	require.NoError(t, err)

	_, err = auditSvc.Log(ctx, &AuditLogRequest{
		AccountID:    "acc-other",
		APIKeyID:     "ak-other",
		Action:       "delete",
		ResourceType: "api_key",
		ResourceID:   "ak-002",
		ResourceName: "Second",
	})
	require.NoError(t, err)

	cases := []struct {
		name   string
		filter *AuditLogFilter
		want   int64
	}{
		{
			name:   "account_id",
			filter: &AuditLogFilter{AccountID: acc.AccountID},
			// api_key.create + group create
			want: 1,
		},
		{
			name:   "api_key_id",
			filter: &AuditLogFilter{APIKeyID: key.APIKey.APIKeyID},
			// api_key.create + group create
			want: 1,
		},
		{
			name:   "action",
			filter: &AuditLogFilter{Action: "delete"},
			want:   1,
		},
		{
			name:   "resource_type",
			filter: &AuditLogFilter{ResourceType: "group"},
			want:   1,
		},
		{
			name:   "resource_id",
			filter: &AuditLogFilter{ResourceID: "ak-002"},
			want:   1,
		},
		{
			name:   "time_range",
			filter: &AuditLogFilter{StartTimeMs: 0, EndTimeMs: time.Now().UnixMilli() + 3600000},
			// api_key.create + 2 explicit logs
			want: 2,
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, total, err := auditSvc.ListAuditLogs(ctx, tc.filter, 0, 100)
			require.NoError(t, err)
			assert.Equal(t, tc.want, total)
		})
	}
}

func TestAuditLogService_ListAuditLogs_CombinedFilters(t *testing.T) {
	_, accountSvc, _, auditSvc := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Combined",
		LoginName:   "combined",
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
		})
		require.NoError(t, err)
	}

	_, err = auditSvc.Log(ctx, &AuditLogRequest{
		AccountID:    acc.AccountID,
		Action:       "create",
		ResourceType: "api_key",
		ResourceID:   "ak-001",
	})
	require.NoError(t, err)

	_, err = auditSvc.Log(ctx, &AuditLogRequest{
		AccountID:    "acc-other",
		Action:       "create",
		ResourceType: "group",
		ResourceID:   "group-002",
	})
	require.NoError(t, err)

	logs, total, err := auditSvc.ListAuditLogs(ctx, &AuditLogFilter{
		AccountID:    acc.AccountID,
		Action:       "create",
		ResourceType: "group",
		ResourceID:   "group-001",
	}, 0, 100)
	require.NoError(t, err)
	assert.Equal(t, int64(3), total)
	assert.Len(t, logs, 3)
}

func TestAuditLogService_ListAuditLogs_PaginationAndErrors(t *testing.T) {
	db, accountSvc, _, auditSvc := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Pagination",
		LoginName:   "pagination",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	for i := 0; i < 5; i++ {
		_, err := auditSvc.Log(ctx, &AuditLogRequest{
			AccountID:    acc.AccountID,
			Action:       "create",
			ResourceType: "group",
			ResourceID:   "group-001",
		})
		require.NoError(t, err)
	}

	// CreateAccount no longer writes an account.create audit log (handled by middleware),
	// so baseline total is exactly 5.
	t.Run("limit defaults to 1000", func(t *testing.T) {
		logs, total, err := auditSvc.ListAuditLogs(ctx, nil, 0, 0)
		require.NoError(t, err)
		assert.Equal(t, int64(5), total)
		assert.Len(t, logs, 5)
	})

	t.Run("offset and limit", func(t *testing.T) {
		logs, total, err := auditSvc.ListAuditLogs(ctx, nil, 2, 2)
		require.NoError(t, err)
		assert.Equal(t, int64(5), total)
		assert.Len(t, logs, 2)
	})

	t.Run("offset beyond total", func(t *testing.T) {
		logs, total, err := auditSvc.ListAuditLogs(ctx, nil, 100, 10)
		require.NoError(t, err)
		assert.Equal(t, int64(5), total)
		assert.Empty(t, logs)
	})

	t.Run("count query error", func(t *testing.T) {
		// Close the database to force a query error.
		sqlDB, err := db.DB()
		require.NoError(t, err)
		require.NoError(t, sqlDB.Close())

		_, _, err = auditSvc.ListAuditLogs(ctx, nil, 0, 10)
		assert.Error(t, err)
	})
}

func TestAuditLogService_GetAuditLog_SuccessAndNotFound(t *testing.T) {
	_, accountSvc, _, auditSvc := newTestServices(t)
	ctx := context.Background()

	acc, err := accountSvc.CreateAccount(ctx, &CreateAccountRequest{
		AccountName: "Getter",
		LoginName:   "getter",
		Role:        models.AccountRoleUser,
		CreatorID:   "system",
	})
	require.NoError(t, err)

	log, err := auditSvc.Log(ctx, &AuditLogRequest{
		AccountID:    acc.AccountID,
		Action:       "create",
		ResourceType: "group",
		ResourceID:   "group-001",
	})
	require.NoError(t, err)

	found, err := auditSvc.GetAuditLog(ctx, log.AuditLogID)
	require.NoError(t, err)
	assert.Equal(t, log.AuditLogID, found.AuditLogID)
	assert.Equal(t, "group", found.ResourceType)

	_, err = auditSvc.GetAuditLog(ctx, "al-nonexistent")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to get audit log")
}
