package middleware

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/topsailai/agent-community/pkg/logger"
)

// newTestLogger creates a logger that writes to a temporary file so tests can
// capture and inspect its output without depending on os.Stdout.
func newTestLogger(t *testing.T) (*logger.Logger, string) {
	t.Helper()
	tmpDir := t.TempDir()
	logPath := filepath.Join(tmpDir, "test.log")
	log := logger.New(logger.Config{
		Output:   "file",
		FilePath: logPath,
		Level:    "info",
	})
	return log, logPath
}

// readLogFile reads all log lines written to the temporary log file.
func readLogFile(t *testing.T, logPath string) []map[string]any {
	t.Helper()
	data, err := os.ReadFile(logPath)
	require.NoError(t, err)

	var lines []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		var entry map[string]any
		require.NoError(t, json.Unmarshal([]byte(line), &entry))
		lines = append(lines, entry)
	}
	return lines
}

func TestLogger_LogsRequest(t *testing.T) {
	log, logPath := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(log))
	r.GET("/api/v1/healthz", func(c *gin.Context) {
		c.Status(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	lines := readLogFile(t, logPath)
	require.Len(t, lines, 1)

	entry := lines[0]
	assert.Equal(t, "api", entry["module"])
	assert.Equal(t, "GET", entry["method"])
	assert.Equal(t, "/api/v1/healthz", entry["path"])
	assert.Equal(t, float64(http.StatusOK), entry["status"])
	assert.NotEmpty(t, entry["trace_id"])
	assert.GreaterOrEqual(t, entry["duration_ms"], float64(0))
}

func TestLogger_UsesIncomingTraceID(t *testing.T) {
	log, logPath := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(log))
	r.GET("/api/v1/healthz", func(c *gin.Context) {
		assert.Equal(t, "abc-123", GetTraceID(c))
		c.Status(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/healthz", nil)
	req.Header.Set(TraceIDHeader, "abc-123")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	lines := readLogFile(t, logPath)
	require.Len(t, lines, 1)
	assert.Equal(t, "abc-123", lines[0]["trace_id"])
	assert.Equal(t, "abc-123", w.Header().Get(TraceIDHeader))
}

func TestLogger_GeneratesTraceID(t *testing.T) {
	log, logPath := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(log))
	r.GET("/api/v1/healthz", func(c *gin.Context) {
		traceID := GetTraceID(c)
		assert.NotEmpty(t, traceID)
		_, err := uuid.Parse(traceID)
		assert.NoError(t, err)
		c.Status(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/healthz", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	lines := readLogFile(t, logPath)
	require.Len(t, lines, 1)

	traceID, ok := lines[0]["trace_id"].(string)
	require.True(t, ok)
	assert.NotEmpty(t, traceID)
	_, err := uuid.Parse(traceID)
	assert.NoError(t, err)
	assert.Equal(t, traceID, w.Header().Get(TraceIDHeader))
}

func TestLogger_CallsNextHandler(t *testing.T) {
	log, _ := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(log))
	r.GET("/test", func(c *gin.Context) {
		c.Set("passed", true)
		c.Status(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/test", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
}

func TestLogger_CapturesErrorStatus(t *testing.T) {
	log, logPath := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(log))
	r.GET("/error", func(c *gin.Context) {
		c.Status(http.StatusInternalServerError)
	})

	req := httptest.NewRequest(http.MethodGet, "/error", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusInternalServerError, w.Code)
	lines := readLogFile(t, logPath)
	require.Len(t, lines, 1)
	assert.Equal(t, float64(http.StatusInternalServerError), lines[0]["status"])
}

func TestLogger_CapturesClientIP(t *testing.T) {
	log, logPath := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(log))
	r.GET("/ip", func(c *gin.Context) {
		c.Status(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/ip", nil)
	req.Header.Set("X-Forwarded-For", "192.168.1.10")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
	lines := readLogFile(t, logPath)
	require.Len(t, lines, 1)
	assert.Equal(t, "192.168.1.10", lines[0]["client_ip"])
}

func TestLogger_SetsRequestLoggerInContext(t *testing.T) {
	log, _ := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(log))
	r.GET("/logger", func(c *gin.Context) {
		requestLogger := GetLogger(c)
		assert.NotNil(t, requestLogger)
		c.Status(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/logger", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
}

func TestGetTraceID_Missing(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	assert.Empty(t, GetTraceID(c))
}

func TestGetTraceID_NonString(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Set(TraceIDContextKey, 123)
	assert.Empty(t, GetTraceID(c))
}

func TestGetLogger_Missing(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	assert.Nil(t, GetLogger(c))
}

func TestGetLogger_WrongType(t *testing.T) {
	gin.SetMode(gin.TestMode)
	c, _ := gin.CreateTestContext(httptest.NewRecorder())
	c.Set(LoggerContextKey, "not-a-logger")
	assert.Nil(t, GetLogger(c))
}
