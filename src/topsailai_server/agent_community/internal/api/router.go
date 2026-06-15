// Package api provides HTTP API routing and server setup for the ACS service.
package api

import (
	"github.com/gin-gonic/gin"
	"github.com/topsailai/agent-community/internal/api/handlers"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/discovery"
	"github.com/topsailai/agent-community/internal/nats"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/gorm"
)

// Router holds all API handlers and sets up routes.
type Router struct {
	engine *gin.Engine
}

// NewRouter creates a new Gin router with all routes configured.
func NewRouter(cfg *config.Config, db *gorm.DB, publisher *nats.Publisher, evaluator *trigger.Evaluator, disc *discovery.Discovery, log *logger.Logger) *Router {
	// Set Gin to release mode in production
	if cfg.Log.Level == "info" || cfg.Log.Level == "warn" || cfg.Log.Level == "error" {
		gin.SetMode(gin.ReleaseMode)
	}

	engine := gin.New()

	// Global middleware
	engine.Use(middleware.Recovery(log))
	engine.Use(middleware.Logger(log))

	// Initialize handlers
	groupHandler := handlers.NewGroupHandler(db, publisher, log)
	memberHandler := handlers.NewGroupMemberHandler(db, publisher, log)
	messageHandler := handlers.NewMessageHandler(db, publisher, evaluator, log)
	healthHandler := handlers.NewHealthHandler(db, disc, log)

	// Health and readiness endpoints
	engine.GET("/healthz", healthHandler.Liveness)
	engine.GET("/readyz", healthHandler.Readiness)
	engine.GET("/health", healthHandler.Health)
	engine.GET("/health/leader", healthHandler.LeaderStatus)

	// Discovery endpoints
	engine.GET("/discovery/services", healthHandler.DiscoveryServices)

	// API v1 routes
	v1 := engine.Group("/api/v1")
	{
		// Group routes
		v1.POST("/groups", groupHandler.CreateGroup)
		v1.GET("/groups", groupHandler.ListGroups)
		v1.GET("/groups/:group_id", groupHandler.GetGroup)
		v1.PUT("/groups/:group_id", groupHandler.UpdateGroup)
		v1.DELETE("/groups/:group_id", groupHandler.DeleteGroup)

		// Group member routes
		v1.POST("/groups/:group_id/members", memberHandler.JoinGroup)
		v1.GET("/groups/:group_id/members", memberHandler.ListGroupMembers)
		v1.PUT("/groups/:group_id/members/:member_id", memberHandler.UpdateMember)
		v1.DELETE("/groups/:group_id/members/:member_id", memberHandler.LeaveGroup)

		// Message routes
		v1.POST("/groups/:group_id/messages", messageHandler.CreateMessage)
		v1.GET("/groups/:group_id/messages", messageHandler.ListMessages)
		v1.PUT("/groups/:group_id/messages/:message_id", messageHandler.UpdateMessage)
		v1.DELETE("/groups/:group_id/messages/:message_id", messageHandler.DeleteMessage)
		v1.POST("/groups/:group_id/messages/:message_id/trigger", messageHandler.TriggerMessage)
	}

	return &Router{engine: engine}
}

// Engine returns the underlying gin.Engine for testing or direct use.
func (r *Router) Engine() *gin.Engine {
	return r.engine
}
