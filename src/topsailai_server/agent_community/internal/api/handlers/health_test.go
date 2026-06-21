package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/discovery"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// mockDiscovery is a test double for the discoveryProvider interface.
type mockDiscovery struct {
	enabled       bool
	services      []discovery.ServiceInfo
	discoverErr   error
	isLeader      bool
	isLeaderErr   error
	leaderInfo    *discovery.ServiceInfo
	leaderInfoErr error
	self          discovery.ServiceInfo
}

func (m *mockDiscovery) Enabled() bool { return m.enabled }

func (m *mockDiscovery) Discover() ([]discovery.ServiceInfo, error) {
	return m.services, m.discoverErr
}

func (m *mockDiscovery) IsLeader() (bool, error) {
	return m.isLeader, m.isLeaderErr
}

func (m *mockDiscovery) LeaderInfo() (*discovery.ServiceInfo, error) {
	if m.leaderInfoErr != nil {
		return nil, m.leaderInfoErr
	}
	return m.leaderInfo, nil
}

func (m *mockDiscovery) SelfInfo() discovery.ServiceInfo {
	return m.self
}
// newTestLogger creates a logger that writes to a temporary file for test assertions.
func newTestLogger(t *testing.T) *logger.Logger {
	t.Helper()
	tmpFile, err := os.CreateTemp("", "health-test-*.log")
	require.NoError(t, err)
	t.Cleanup(func() { _ = os.Remove(tmpFile.Name()) })
	_ = tmpFile.Close()

	return logger.New(logger.Config{
		Output:   "file",
		Level:    "debug",
		FilePath: tmpFile.Name(),
	})
}

// newHealthyDB returns an in-memory SQLite DB that responds to Ping.
func newHealthyDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open("file::memory:?cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	return db
}

// newUnhealthyDB returns a *gorm.DB whose underlying connection is closed so Ping fails.
func newUnhealthyDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open("file::memory:?cache=shared"), &gorm.Config{})
	require.NoError(t, err)
	sqlDB, err := db.DB()
	require.NoError(t, err)
	require.NoError(t, sqlDB.Close())
	return db
}

// newGinContext creates a Gin test context and recorder with a GET request.
func newGinContext(t *testing.T) (*gin.Context, *httptest.ResponseRecorder) {
	t.Helper()
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)
	c.Request = httptest.NewRequest(http.MethodGet, "/", nil)
	return c, w
}

func TestHealthHandler_Liveness(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(nil, nil, newTestLogger(t))

	h.Liveness(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "alive", body["status"])
}

func TestHealthHandler_Readiness_Healthy(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(newHealthyDB(t), nil, newTestLogger(t))

	h.Readiness(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp ReadinessResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "ready", resp.Status)
	assert.Equal(t, "healthy", resp.Checks["database"])
	assert.Greater(t, resp.Timestamp, int64(0))
}

func TestHealthHandler_Readiness_DBError(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(newUnhealthyDB(t), nil, newTestLogger(t))

	h.Readiness(c)

	assert.Equal(t, http.StatusServiceUnavailable, w.Code)
	var resp ReadinessResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "not_ready", resp.Status)
	assert.Contains(t, resp.Checks["database"], "unhealthy")
}

func TestHealthHandler_Readiness_NilDB(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(nil, nil, newTestLogger(t))

	h.Readiness(c)

	assert.Equal(t, http.StatusServiceUnavailable, w.Code)
	var resp ReadinessResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "not_ready", resp.Status)
	assert.Contains(t, resp.Checks["database"], "not initialized")
}

func TestHealthHandler_Health_Healthy(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(newHealthyDB(t), nil, newTestLogger(t))

	h.Health(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp HealthResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "healthy", resp.Status)
	assert.Equal(t, "1.0.0", resp.Version)
	assert.Equal(t, "healthy", resp.Checks["database"])
	assert.Greater(t, resp.Timestamp, int64(0))
}

func TestHealthHandler_Health_DBError(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(newUnhealthyDB(t), nil, newTestLogger(t))

	h.Health(c)

	assert.Equal(t, http.StatusServiceUnavailable, w.Code)
	var resp HealthResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "unhealthy", resp.Status)
	assert.Contains(t, resp.Checks["database"], "unhealthy")
}

func TestHealthHandler_Health_NilDB(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(nil, nil, newTestLogger(t))

	h.Health(c)

	assert.Equal(t, http.StatusServiceUnavailable, w.Code)
	var resp HealthResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "unhealthy", resp.Status)
	assert.Contains(t, resp.Checks["database"], "not initialized")
}

func TestHealthHandler_DiscoveryServices_Success(t *testing.T) {
	c, w := newGinContext(t)
	mock := &mockDiscovery{
		enabled: true,
		services: []discovery.ServiceInfo{
			{ID: "svc-1", Name: "acs", Address: "http://10.0.0.1:7370"},
			{ID: "svc-2", Name: "acs", Address: "http://10.0.0.2:7370"},
		},
	}
	h := NewHealthHandler(nil, mock, newTestLogger(t))

	h.DiscoveryServices(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp DiscoveryServicesResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Len(t, resp.Services, 2)
	assert.Equal(t, 2, resp.Count)
	assert.Equal(t, "svc-1", resp.Services[0].ID)
}

func TestHealthHandler_DiscoveryServices_Error(t *testing.T) {
	c, w := newGinContext(t)
	mock := &mockDiscovery{enabled: true, discoverErr: errors.New("nats unavailable")}
	h := NewHealthHandler(nil, mock, newTestLogger(t))

	h.DiscoveryServices(c)

	assert.Equal(t, http.StatusInternalServerError, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Contains(t, body["error"], "failed to discover services")
}

func TestHealthHandler_DiscoveryServices_Disabled(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(nil, NewDisabledDiscovery(), newTestLogger(t))

	h.DiscoveryServices(c)

	assert.Equal(t, http.StatusServiceUnavailable, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "service discovery not available", body["error"])
}

func TestHealthHandler_DiscoveryServices_Nil(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(nil, nil, newTestLogger(t))

	h.DiscoveryServices(c)

	assert.Equal(t, http.StatusServiceUnavailable, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "service discovery not available", body["error"])
}

func TestHealthHandler_LeaderStatus_Success(t *testing.T) {
	c, w := newGinContext(t)
	mock := &mockDiscovery{
		enabled:  true,
		isLeader: false,
		leaderInfo: &discovery.ServiceInfo{
			ID: "leader-1", Name: "acs", Address: "http://10.0.0.3:7370",
		},
		self: discovery.ServiceInfo{
			ID: "self-1", Name: "acs", Address: "http://10.0.0.1:7370",
		},
	}
	h := NewHealthHandler(nil, mock, newTestLogger(t))

	h.LeaderStatus(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp LeaderStatusResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.False(t, resp.IsLeader)
	assert.Equal(t, "self-1", resp.Self.ID)
	assert.Equal(t, "leader-1", resp.Leader.ID)
	assert.Greater(t, resp.Timestamp, int64(0))
}

func TestHealthHandler_LeaderStatus_IsLeaderError(t *testing.T) {
	c, w := newGinContext(t)
	mock := &mockDiscovery{enabled: true, isLeaderErr: errors.New("leader check failed")}
	h := NewHealthHandler(nil, mock, newTestLogger(t))

	h.LeaderStatus(c)

	assert.Equal(t, http.StatusInternalServerError, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Contains(t, body["error"], "failed to check leader status")
}

func TestHealthHandler_LeaderStatus_LeaderInfoError(t *testing.T) {
	c, w := newGinContext(t)
	mock := &mockDiscovery{
		enabled:       true,
		isLeader:      true,
		leaderInfoErr: errors.New("leader info missing"),
		self:          discovery.ServiceInfo{ID: "self-1", Name: "acs"},
	}
	h := NewHealthHandler(nil, mock, newTestLogger(t))

	h.LeaderStatus(c)

	assert.Equal(t, http.StatusOK, w.Code)
	var resp LeaderStatusResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.True(t, resp.IsLeader)
	assert.Equal(t, "self-1", resp.Self.ID)
	assert.Nil(t, resp.Leader)
}

func TestHealthHandler_LeaderStatus_Disabled(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(nil, NewDisabledDiscovery(), newTestLogger(t))

	h.LeaderStatus(c)

	assert.Equal(t, http.StatusServiceUnavailable, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "service discovery not available", body["error"])
}

func TestHealthHandler_LeaderStatus_NilDiscovery(t *testing.T) {
	c, w := newGinContext(t)
	h := NewHealthHandler(nil, nil, newTestLogger(t))

	h.LeaderStatus(c)

	assert.Equal(t, http.StatusServiceUnavailable, w.Code)
	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "service discovery not available", body["error"])
}

func TestDisabledDiscovery_ReportsDisabled(t *testing.T) {
	d := NewDisabledDiscovery()
	assert.False(t, d.Enabled())

	_, err := d.Discover()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "disabled")

	_, err = d.IsLeader()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "disabled")

	_, err = d.LeaderInfo()
	assert.Error(t, err)
	assert.Contains(t, err.Error(), "disabled")

	assert.Equal(t, discovery.ServiceInfo{}, d.SelfInfo())
}
