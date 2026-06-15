// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/discovery"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/gorm"
)

// HealthHandler handles health and readiness check requests.
type HealthHandler struct {
	db        *gorm.DB
	discovery *discovery.Discovery
	log       *logger.Logger
}

// NewHealthHandler creates a new HealthHandler.
func NewHealthHandler(db *gorm.DB, disc *discovery.Discovery, log *logger.Logger) *HealthHandler {
	return &HealthHandler{
		db:        db,
		discovery: disc,
		log:       log,
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

// DiscoveryServicesResponse represents the list of discovered services.
type DiscoveryServicesResponse struct {
	Services []discovery.ServiceInfo `json:"services"`
	Count    int                     `json:"count"`
}

// LeaderStatusResponse represents the leader status of this instance.
type LeaderStatusResponse struct {
	IsLeader   bool                   `json:"is_leader"`
	Self       discovery.ServiceInfo  `json:"self"`
	Leader     *discovery.ServiceInfo `json:"leader,omitempty"`
	Timestamp  int64                  `json:"timestamp"`
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

// DiscoveryServices handles GET /discovery/services.
// Returns all currently registered services from NATS KV.
func (h *HealthHandler) DiscoveryServices(c *gin.Context) {
	traceID := middleware.GetTraceID(c)

	if h.discovery == nil {
		h.log.Warn("api", traceID, "discovery not initialized")
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error": "service discovery not available",
		})
		return
	}

	services, err := h.discovery.Discover()
	if err != nil {
		h.log.Error("api", traceID, "failed to discover services", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "failed to discover services",
		})
		return
	}

	h.log.Debug("api", traceID, "discovery services listed", "count", len(services))
	c.JSON(http.StatusOK, DiscoveryServicesResponse{
		Services: services,
		Count:    len(services),
	})
}

// LeaderStatus handles GET /health/leader.
// Returns whether this instance is the current Service-Leader.
func (h *HealthHandler) LeaderStatus(c *gin.Context) {
	traceID := middleware.GetTraceID(c)

	if h.discovery == nil {
		h.log.Warn("api", traceID, "discovery not initialized")
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error": "service discovery not available",
		})
		return
	}

	isLeader, err := h.discovery.IsLeader()
	if err != nil {
		h.log.Error("api", traceID, "failed to check leader status", "error", err)
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "failed to check leader status",
		})
		return
	}

	leaderInfo, err := h.discovery.LeaderInfo()
	if err != nil {
		h.log.Error("api", traceID, "failed to get leader info", "error", err)
		// Non-fatal: still return is_leader and self info
		leaderInfo = nil
	}

	h.log.Debug("api", traceID, "leader status checked", "is_leader", isLeader)
	c.JSON(http.StatusOK, LeaderStatusResponse{
		IsLeader:  isLeader,
		Self:      h.discovery.SelfInfo(),
		Leader:    leaderInfo,
		Timestamp: time.Now().UnixMilli(),
	})
}
