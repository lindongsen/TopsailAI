package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/schema"
)

// newAuditLogTestDB creates an isolated in-memory SQLite database with audit_logs migrated.
func newAuditLogTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	dsn := "file:" + t.Name() + "?mode=memory&cache=shared"
	db, err := gorm.Open(sqlite.Open(dsn), &gorm.Config{
		NamingStrategy: schema.NamingStrategy{SingularTable: true},
	})
	require.NoError(t, err)
	require.NoError(t, db.AutoMigrate(&models.AuditLog{}))
	return db
}

// seedAuditLogs inserts deterministic audit log records for handler tests.
func seedAuditLogs(t *testing.T, db *gorm.DB, logs []models.AuditLog) {
	t.Helper()
	for i := range logs {
		if logs[i].CreateAtMs == 0 {
			logs[i].CreateAtMs = time.Now().UnixMilli()
		}
		require.NoError(t, db.Create(&logs[i]).Error)
	}
}

// newAuditLogHandlerTestContext returns a Gin test context and recorder.
func newAuditLogHandlerTestContext(t *testing.T, method, path string) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(method, path, nil)
	return c, w
}

func TestAuditLogHandler_List_Success(t *testing.T) {
	db := newAuditLogTestDB(t)
	seedAuditLogs(t, db, []models.AuditLog{
		{AuditLogID: "al-001", AccountID: "acc-a", APIKeyID: "ak-001", Action: "create_account", ResourceType: "account", ResourceID: "acc-a", ResourceName: "Alice", ClientIP: "127.0.0.1", CreateAtMs: 1000},
		{AuditLogID: "al-002", AccountID: "acc-b", APIKeyID: "ak-002", Action: "create_group", ResourceType: "group", ResourceID: "group-001", ResourceName: "Team", ClientIP: "127.0.0.1", CreateAtMs: 2000},
		{AuditLogID: "al-003", AccountID: "acc-a", APIKeyID: "ak-003", Action: "delete_api_key", ResourceType: "api_key", ResourceID: "ak-003", ResourceName: "Key", ClientIP: "127.0.0.1", CreateAtMs: 3000},
	})

	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs")
	h.ListAuditLogs(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp ListAuditLogsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Len(t, resp.Items, 3)
	assert.Equal(t, int64(3), resp.Total)
	assert.Equal(t, 0, resp.Offset)
	assert.Equal(t, 1000, resp.Limit)
}

func TestAuditLogHandler_List_FilterByAccountID(t *testing.T) {
	db := newAuditLogTestDB(t)
	seedAuditLogs(t, db, []models.AuditLog{
		{AuditLogID: "al-001", AccountID: "acc-a", Action: "create_account", ResourceType: "account", ResourceID: "acc-a", ClientIP: "127.0.0.1", CreateAtMs: 1000},
		{AuditLogID: "al-002", AccountID: "acc-b", Action: "create_account", ResourceType: "account", ResourceID: "acc-b", ClientIP: "127.0.0.1", CreateAtMs: 2000},
	})

	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs?account_id=acc-a")
	h.ListAuditLogs(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp ListAuditLogsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Len(t, resp.Items, 1)
	assert.Equal(t, int64(1), resp.Total)
	assert.Equal(t, "acc-a", resp.Items[0].AccountID)
}

func TestAuditLogHandler_List_FilterByAction(t *testing.T) {
	db := newAuditLogTestDB(t)
	seedAuditLogs(t, db, []models.AuditLog{
		{AuditLogID: "al-001", AccountID: "acc-a", Action: "create_account", ResourceType: "account", ResourceID: "acc-a", ClientIP: "127.0.0.1", CreateAtMs: 1000},
		{AuditLogID: "al-002", AccountID: "acc-a", Action: "delete_group", ResourceType: "group", ResourceID: "group-001", ClientIP: "127.0.0.1", CreateAtMs: 2000},
	})

	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs?action=create_account")
	h.ListAuditLogs(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp ListAuditLogsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Len(t, resp.Items, 1)
	assert.Equal(t, "create_account", resp.Items[0].Action)
}

func TestAuditLogHandler_List_TimeRange(t *testing.T) {
	db := newAuditLogTestDB(t)
	seedAuditLogs(t, db, []models.AuditLog{
		{AuditLogID: "al-001", AccountID: "acc-a", Action: "create", ResourceType: "group", ResourceID: "group-001", ClientIP: "127.0.0.1", CreateAtMs: 500},
		{AuditLogID: "al-002", AccountID: "acc-a", Action: "create", ResourceType: "group", ResourceID: "group-002", ClientIP: "127.0.0.1", CreateAtMs: 1500},
		{AuditLogID: "al-003", AccountID: "acc-a", Action: "create", ResourceType: "group", ResourceID: "group-003", ClientIP: "127.0.0.1", CreateAtMs: 2500},
	})

	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs?start_time_ms=1000&end_time_ms=2000")
	h.ListAuditLogs(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp ListAuditLogsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Len(t, resp.Items, 1)
	assert.Equal(t, "group-002", resp.Items[0].ResourceID)
}

func TestAuditLogHandler_List_Pagination(t *testing.T) {
	db := newAuditLogTestDB(t)
	logs := make([]models.AuditLog, 5)
	for i := 0; i < 5; i++ {
		logs[i] = models.AuditLog{
			AuditLogID:   "al-00" + string(rune('1'+i)),
			AccountID:    "acc-a",
			Action:       "create",
			ResourceType: "group",
			ResourceID:   "group-00" + string(rune('1'+i)),
			ClientIP:     "127.0.0.1",
			CreateAtMs:   int64(1000 * (i + 1)),
		}
	}
	seedAuditLogs(t, db, logs)

	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs?offset=1&limit=2")
	h.ListAuditLogs(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp ListAuditLogsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Len(t, resp.Items, 2)
	assert.Equal(t, int64(5), resp.Total)
	assert.Equal(t, 1, resp.Offset)
	assert.Equal(t, 2, resp.Limit)
}

func TestAuditLogHandler_List_Empty(t *testing.T) {
	db := newAuditLogTestDB(t)
	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs")
	h.ListAuditLogs(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp ListAuditLogsResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Empty(t, resp.Items)
	assert.Equal(t, int64(0), resp.Total)
}

func TestAuditLogHandler_Get_Success(t *testing.T) {
	db := newAuditLogTestDB(t)
	seedAuditLogs(t, db, []models.AuditLog{
		{AuditLogID: "al-001", AccountID: "acc-a", Action: "create_account", ResourceType: "account", ResourceID: "acc-a", ResourceName: "Alice", ClientIP: "127.0.0.1", CreateAtMs: 1000},
	})

	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs/al-001")
	c.Params = gin.Params{{Key: "audit_log_id", Value: "al-001"}}
	h.GetAuditLog(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp AuditLogResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "al-001", resp.AuditLogID)
	assert.Equal(t, "acc-a", resp.AccountID)
	assert.Equal(t, "Alice", resp.ResourceName)
}

func TestAuditLogHandler_Get_NotFound(t *testing.T) {
	db := newAuditLogTestDB(t)
	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs/al-missing")
	c.Params = gin.Params{{Key: "audit_log_id", Value: "al-missing"}}
	h.GetAuditLog(c)

	assert.Equal(t, http.StatusNotFound, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Contains(t, body["error"], "audit log not found")
}

func TestAuditLogHandler_Get_InvalidID(t *testing.T) {
	db := newAuditLogTestDB(t)
	auditSvc := services.NewAuditLogService(db)
	h := NewAuditLogHandler(auditSvc, newTestLogger(t))

	c, w := newAuditLogHandlerTestContext(t, http.MethodGet, "/api/v1/audit-logs/")
	c.Params = gin.Params{{Key: "audit_log_id", Value: ""}}
	h.GetAuditLog(c)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Contains(t, body["error"], "audit_log_id is required")
}
