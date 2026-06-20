package middleware

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRecovery_RecoversFromStringPanic(t *testing.T) {
	log, logPath := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Recovery(log))
	r.GET("/panic", func(c *gin.Context) {
		panic("something went wrong")
	})

	req := httptest.NewRequest(http.MethodGet, "/panic", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusInternalServerError, w.Code)

	var body map[string]any
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "internal server error", body["error"])
	assert.NotEmpty(t, body["trace_id"])

	lines := readLogFile(t, logPath)
	require.Len(t, lines, 1)
	entry := lines[0]
	assert.Equal(t, "api", entry["module"])
	assert.Equal(t, "panic recovered", entry["message"])
	assert.Contains(t, entry["error"], "something went wrong")
	assert.Equal(t, "GET", entry["method"])
	assert.Equal(t, "/panic", entry["path"])
}

func TestRecovery_RecoversFromErrorPanic(t *testing.T) {
	log, logPath := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Recovery(log))
	r.GET("/panic", func(c *gin.Context) {
		panic(errors.New("db error"))
	})

	req := httptest.NewRequest(http.MethodGet, "/panic", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusInternalServerError, w.Code)

	var body map[string]any
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "internal server error", body["error"])
	assert.NotEmpty(t, body["trace_id"])

	lines := readLogFile(t, logPath)
	require.Len(t, lines, 1)
	assert.Contains(t, lines[0]["error"], "db error")
}

func TestRecovery_RecoversFromArbitraryPanic(t *testing.T) {
	log, _ := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Recovery(log))
	r.GET("/panic", func(c *gin.Context) {
		panic(42)
	})

	req := httptest.NewRequest(http.MethodGet, "/panic", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusInternalServerError, w.Code)

	var body map[string]any
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "internal server error", body["error"])
	assert.NotEmpty(t, body["trace_id"])
}

func TestRecovery_AbortsAfterPanic(t *testing.T) {
	log, _ := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Recovery(log))
	r.GET("/panic", func(c *gin.Context) {
		panic("abort")
	}, func(c *gin.Context) {
		c.Set("after_panic", true)
		c.Status(http.StatusOK)
	})

	req := httptest.NewRequest(http.MethodGet, "/panic", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusInternalServerError, w.Code)
}

func TestRecovery_PreservesTraceID(t *testing.T) {
	log, _ := newTestLogger(t)
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.Use(Logger(log), Recovery(log))
	r.GET("/panic", func(c *gin.Context) {
		panic("with trace")
	})

	req := httptest.NewRequest(http.MethodGet, "/panic", nil)
	req.Header.Set(TraceIDHeader, "trace-abc-123")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	require.Equal(t, http.StatusInternalServerError, w.Code)

	var body map[string]any
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
	assert.Equal(t, "trace-abc-123", body["trace_id"])
}
