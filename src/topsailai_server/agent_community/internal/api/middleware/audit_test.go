package middleware

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/pkg/logger"
)

// mockAuditLogService records every Log call so tests can assert on the
// captured AuditLogRequest.
type mockAuditLogService struct {
	mu    sync.Mutex
	calls []*services.AuditLogRequest
}

func (m *mockAuditLogService) Log(ctx context.Context, req *services.AuditLogRequest) (*models.AuditLog, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.calls = append(m.calls, req)
	return &models.AuditLog{AuditLogID: "al-test"}, nil
}

func (m *mockAuditLogService) Calls() []*services.AuditLogRequest {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]*services.AuditLogRequest, len(m.calls))
	copy(out, m.calls)
	return out
}

func setupAuditRouter(t *testing.T, auditSvc AuditLogService) *gin.Engine {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(logger.New(logger.Config{Output: "stdout", Level: "error"})))
	r.Use(AuditLogger(auditSvc))
	return r
}

func TestAuditLogger_LogsPostAccount(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.POST("/api/v1/accounts", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-001"},
			APIKey:          &models.APIKey{APIKeyID: "ak-001"},
			AuthMethod:      AuthMethodAPIKey,
		})
		c.JSON(http.StatusCreated, gin.H{"account_id": "acc-002"})
	})

	body := `{"account_name":"Alice","login_name":"alice@example.com"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code)
	require.Eventually(t, func() bool {
		return len(mock.Calls()) == 1
	}, time.Second, 10*time.Millisecond)

	call := mock.Calls()[0]
	assert.Equal(t, "acc-001", call.AccountID)
	assert.Equal(t, "ak-001", call.APIKeyID)
	assert.Equal(t, "create_account", call.Action)
	assert.Equal(t, "account", call.ResourceType)
	assert.Equal(t, "", call.ResourceID)
	assert.Equal(t, "Alice", call.ResourceName)
	assert.Contains(t, call.Detail, "status=201")
	assert.NotEmpty(t, call.ClientIP)
}

func TestAuditLogger_LogsPutGroup(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.PUT("/api/v1/groups/:group_id", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-003"},
			AuthMethod:      AuthMethodSession,
		})
		c.JSON(http.StatusOK, gin.H{"group_id": "group-001"})
	})

	body := `{"group_name":"Updated Group"}`
	req := httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-001", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	require.Eventually(t, func() bool {
		return len(mock.Calls()) == 1
	}, time.Second, 10*time.Millisecond)

	call := mock.Calls()[0]
	assert.Equal(t, "update_group", call.Action)
	assert.Equal(t, "group", call.ResourceType)
	assert.Equal(t, "group-001", call.ResourceID)
	assert.Equal(t, "Updated Group", call.ResourceName)
}

func TestAuditLogger_LogsDeleteMessage(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.DELETE("/api/v1/groups/:group_id/messages/:message_id", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-004"},
			AuthMethod:      AuthMethodAPIKey,
		})
		c.JSON(http.StatusOK, gin.H{"message": "deleted"})
	})

	req := httptest.NewRequest(http.MethodDelete, "/api/v1/groups/group-002/messages/msg-001", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	require.Eventually(t, func() bool {
		return len(mock.Calls()) == 1
	}, time.Second, 10*time.Millisecond)

	call := mock.Calls()[0]
	assert.Equal(t, "delete_group_message", call.Action)
	assert.Equal(t, "group_message", call.ResourceType)
	assert.Equal(t, "msg-001", call.ResourceID)
	assert.Equal(t, "", call.ResourceName)
}

func TestAuditLogger_SkipsGet(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.GET("/api/v1/accounts", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-005"},
			AuthMethod:      AuthMethodAPIKey,
		})
		c.JSON(http.StatusOK, gin.H{"items": []any{}})
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/accounts", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	time.Sleep(50 * time.Millisecond)
	assert.Empty(t, mock.Calls())
}

func TestExtractResource_AccountCreate(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts", nil)
	c.Request.URL.Path = "/api/v1/accounts"

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "account", resourceType)
	assert.Equal(t, "", resourceID)
}

func TestExtractResource_APIKeyNested(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodDelete, "/api/v1/accounts/acc-006/api-keys/ak-007", nil)
	c.Params = gin.Params{
		{Key: "account_id", Value: "acc-006"},
		{Key: "api_key_id", Value: "ak-007"},
	}

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "api_key", resourceType)
	assert.Equal(t, "ak-007", resourceID)
}

func TestExtractResource_GroupMember(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-003/members/member-001", nil)
	c.Params = gin.Params{
		{Key: "group_id", Value: "group-003"},
		{Key: "member_id", Value: "member-001"},
	}

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "group_member", resourceType)
	assert.Equal(t, "member-001", resourceID)
}

func TestExtractResourceName_Group(t *testing.T) {
	body := []byte(`{"group_name":"Research Team","group_context":"context"}`)
	name := extractResourceName("group", body)
	assert.Equal(t, "Research Team", name)
}

func TestExtractResourceName_Fallback(t *testing.T) {
	tests := []struct {
		name         string
		resourceType string
		body         []byte
		want         string
	}{
		{
			name:         "name field",
			resourceType: "unknown",
			body:         []byte(`{"name":"Fallback Name"}`),
			want:         "Fallback Name",
		},
		{
			name:         "title field",
			resourceType: "unknown",
			body:         []byte(`{"title":"Fallback Title"}`),
			want:         "Fallback Title",
		},
		{
			name:         "id field",
			resourceType: "unknown",
			body:         []byte(`{"id":"fallback-id"}`),
			want:         "fallback-id",
		},
		{
			name:         "priority name over title",
			resourceType: "unknown",
			body:         []byte(`{"name":"Name","title":"Title"}`),
			want:         "Name",
		},
		{
			name:         "non-string value ignored",
			resourceType: "unknown",
			body:         []byte(`{"name":123}`),
			want:         "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := extractResourceName(tt.resourceType, tt.body)
			assert.Equal(t, tt.want, got)
		})
	}
}

func TestAuditLogger_AnonymousAccount(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.POST("/api/v1/groups", func(c *gin.Context) {
		// No auth context set -> anonymous
		c.JSON(http.StatusCreated, gin.H{"group_id": "group-anon"})
	})

	body := `{"group_name":"Anon Group"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code)
	require.Eventually(t, func() bool {
		return len(mock.Calls()) == 1
	}, time.Second, 10*time.Millisecond)

	call := mock.Calls()[0]
	assert.Equal(t, "", call.AccountID)
	assert.Equal(t, "", call.APIKeyID)
	assert.Equal(t, "create_group", call.Action)
	assert.Equal(t, "group", call.ResourceType)
	assert.Equal(t, "", call.ResourceID)
	assert.Equal(t, "Anon Group", call.ResourceName)
}

func TestAuditLogger_LogsPatch(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.PATCH("/api/v1/accounts/:account_id", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-008"},
		})
		c.JSON(http.StatusOK, gin.H{})
	})

	body := `{"account_name":"Patched"}`
	req := httptest.NewRequest(http.MethodPatch, "/api/v1/accounts/acc-008", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	require.Eventually(t, func() bool {
		return len(mock.Calls()) == 1
	}, time.Second, 10*time.Millisecond)

	call := mock.Calls()[0]
	assert.Equal(t, "update_account", call.Action)
	assert.Equal(t, "acc-008", call.ResourceID)
	assert.Equal(t, "Patched", call.ResourceName)
}

func TestAuditLogger_InvalidJSONBody(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.POST("/api/v1/groups", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-009"},
		})
		c.JSON(http.StatusCreated, gin.H{"group_id": "group-bad"})
	})

	body := `not valid json`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/groups", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code)
	require.Eventually(t, func() bool {
		return len(mock.Calls()) == 1
	}, time.Second, 10*time.Millisecond)

	call := mock.Calls()[0]
	assert.Equal(t, "", call.ResourceName)
}

func TestAuditLogger_UnknownResourceType(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.POST("/api/v1/unknown", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-010"},
		})
		c.JSON(http.StatusCreated, gin.H{})
	})

	req := httptest.NewRequest(http.MethodPost, "/api/v1/unknown", strings.NewReader(`{"name":"x"}`))
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code)
	time.Sleep(50 * time.Millisecond)
	assert.Empty(t, mock.Calls())
}

func TestExtractResourceName_GroupMessage(t *testing.T) {
	body := []byte(`{"message_text":"hello world"}`)
	name := extractResourceName("group_message", body)
	assert.Equal(t, "hello world", name)
}

func TestExtractResourceName_APIKey(t *testing.T) {
	body := []byte(`{"api_key_name":"CLI Key"}`)
	name := extractResourceName("api_key", body)
	assert.Equal(t, "CLI Key", name)
}

func TestExtractResourceName_GroupMember(t *testing.T) {
	body := []byte(`{"member_name":"Alice"}`)
	name := extractResourceName("group_member", body)
	assert.Equal(t, "Alice", name)
}

func TestExtractResourceName_Account(t *testing.T) {
	body := []byte(`{"account_name":"Bob"}`)
	name := extractResourceName("account", body)
	assert.Equal(t, "Bob", name)
}

func TestExtractResourceName_EmptyBody(t *testing.T) {
	name := extractResourceName("group", []byte{})
	assert.Equal(t, "", name)
}

func TestExtractResourceName_InvalidJSON(t *testing.T) {
	name := extractResourceName("group", []byte(`{invalid`))
	assert.Equal(t, "", name)
}

func TestExtractResource_APIKeyCreate(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/accounts/acc-011/api-keys", nil)
	c.Params = gin.Params{{Key: "account_id", Value: "acc-011"}}

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "api_key", resourceType)
	assert.Equal(t, "acc-011", resourceID)
}

func TestExtractResource_GroupCreate(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups", nil)

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "group", resourceType)
	assert.Equal(t, "", resourceID)
}

func TestExtractResource_GroupMemberCreate(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-004/members", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-004"}}

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "group_member", resourceType)
	assert.Equal(t, "", resourceID)
}

func TestExtractResource_MessageCreate(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPost, "/api/v1/groups/group-005/messages", nil)
	c.Params = gin.Params{{Key: "group_id", Value: "group-005"}}

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "group_message", resourceType)
	assert.Equal(t, "", resourceID)
}

func TestExtractResource_MessageNested(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodPut, "/api/v1/groups/group-006/messages/msg-002", nil)
	c.Params = gin.Params{
		{Key: "group_id", Value: "group-006"},
		{Key: "message_id", Value: "msg-002"},
	}

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "group_message", resourceType)
	assert.Equal(t, "msg-002", resourceID)
}

func TestExtractResource_AuditLogNested(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/audit-logs/al-001", nil)
	c.Params = gin.Params{{Key: "audit_log_id", Value: "al-001"}}

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "audit_log", resourceType)
	assert.Equal(t, "al-001", resourceID)
}

func TestExtractResource_AccountNested(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Request = httptest.NewRequest(http.MethodGet, "/api/v1/accounts/acc-012", nil)
	c.Params = gin.Params{{Key: "account_id", Value: "acc-012"}}

	resourceType, resourceID := extractResource(c)
	assert.Equal(t, "account", resourceType)
	assert.Equal(t, "acc-012", resourceID)
}

func TestAuditLogger_BodyRewoundForHandler(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.POST("/api/v1/accounts", func(c *gin.Context) {
		body, err := io.ReadAll(c.Request.Body)
		require.NoError(t, err)
		var payload map[string]any
		require.NoError(t, json.Unmarshal(body, &payload))
		assert.Equal(t, "Alice", payload["account_name"])
		c.JSON(http.StatusCreated, gin.H{})
	})

	body := `{"account_name":"Alice"}`
	req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code)
}

func TestAuditLogger_DetailContainsTraceID(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.POST("/api/v1/accounts", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-013"},
		})
		c.JSON(http.StatusCreated, gin.H{})
	})

	req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts", strings.NewReader(`{"account_name":"Trace"}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Trace-ID", "trace-abc")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusCreated, w.Code)
	require.Eventually(t, func() bool {
		return len(mock.Calls()) == 1
	}, time.Second, 10*time.Millisecond)

	call := mock.Calls()[0]
	assert.Contains(t, call.Detail, "trace_id=trace-abc")
}

func TestAuditLogger_MultipleRequests(t *testing.T) {
	mock := &mockAuditLogService{}
	r := setupAuditRouter(t, mock)
	r.POST("/api/v1/accounts", func(c *gin.Context) {
		c.Set(authContextKey, AuthContext{
			IsAuthenticated: true,
			Account:         &models.Account{AccountID: "acc-014"},
		})
		c.JSON(http.StatusCreated, gin.H{})
	})

	for i := 0; i < 3; i++ {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/accounts", strings.NewReader(`{"account_name":"Multi"}`))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		require.Equal(t, http.StatusCreated, w.Code)
		// Wait for the async audit goroutine to finish before reusing the router
		// with a new request, avoiding races on shared gin request internals.
		require.Eventually(t, func() bool {
			return len(mock.Calls()) == i+1
		}, time.Second, 10*time.Millisecond)
	}

	require.Equal(t, 3, len(mock.Calls()))
}
