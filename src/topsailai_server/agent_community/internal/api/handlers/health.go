// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/gorm"
)

// HealthHandler handles health and readiness check requests.
type HealthHandler struct {
	db  *gorm.DB
	log *logger.Logger
}

// NewHealthHandler creates a new HealthHandler.
func NewHealthHandler(db *gorm.DB, log *logger.Logger) *HealthHandler {
	return &HealthHandler{
		db:  db,
		log: log,
	}
}

// HealthResponse represents the health check response.
type HealthResponse struct {
	Status    string            `json:"status"`
	Version   string            `json:"version"`
	Timestamp int64             `json:"timestamp"`
	Checks    map[string]string `json:"checks"`
}

// ReadinessResponse represents the readiness check response.
type ReadinessResponse struct {
	Status    string            `json:"status"`
	Timestamp int64             `json:"timestamp"`
	Checks    map[string]string `json:"checks"`
}

// Liveness handles GET /healthz (liveness probe).
func (h *HealthHandler) Liveness(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	h.log.Debug("api", traceID, "liveness check")

	c.JSON(http.StatusOK, gin.H{
		"status": "alive",
	})
}

// Readiness handles GET /readyz (readiness probe).
func (h *HealthHandler) Readiness(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	checks := make(map[string]string)

	// Check database connectivity
	if h.db != nil {
		sqlDB, err := h.db.DB()
		if err != nil {
			checks["database"] = "unhealthy: " + err.Error()
		} else {
			if err := sqlDB.Ping(); err != nil {
				checks["database"] = "unhealthy: " + err.Error()
			} else {
				checks["database"] = "healthy"
			}
		}
	} else {
		checks["database"] = "unhealthy: not initialized"
	}

	// Determine overall status
	status := "ready"
	for _, check := range checks {
		if check != "healthy" {
			status = "not_ready"
			break
		}
	}

	code := http.StatusOK
	if status != "ready" {
		code = http.StatusServiceUnavailable
	}

	h.log.Debug("api", traceID, "readiness check", "status", status)
	c.JSON(code, ReadinessResponse{
		Status:    status,
		Timestamp: time.Now().UnixMilli(),
		Checks:    checks,
	})
}

// Health handles GET /health (comprehensive health check).
func (h *HealthHandler) Health(c *gin.Context) {
	traceID := middleware.GetTraceID(c)
	checks := make(map[string]string)

	// Check database
	if h.db != nil {
		sqlDB, err := h.db.DB()
		if err != nil {
			checks["database"] = "unhealthy: " + err.Error()
		} else {
			if err := sqlDB.Ping(); err != nil {
				checks["database"] = "unhealthy: " + err.Error()
			} else {
				checks["database"] = "healthy"
			}
		}
	} else {
		checks["database"] = "unhealthy: not initialized"
	}

	// Determine overall status
	status := "healthy"
	for _, check := range checks {
		if check != "healthy" {
			status = "unhealthy"
			break
		}
	}

	code := http.StatusOK
	if status != "healthy" {
		code = http.StatusServiceUnavailable
	}

	h.log.Debug("api", traceID, "health check", "status", status)
	c.JSON(code, HealthResponse{
		Status:    status,
		Version:   "1.0.0",
		Timestamp: time.Now().UnixMilli(),
		Checks:    checks,
	})
}
