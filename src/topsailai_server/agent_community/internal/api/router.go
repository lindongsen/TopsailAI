// Package api provides HTTP API routing and server setup for the ACS service.
package api

import (
	"github.com/gin-gonic/gin"

	"github.com/topsailai/agent-community/internal/api/handlers"
	"github.com/topsailai/agent-community/internal/api/middleware"
	"github.com/topsailai/agent-community/internal/config"
	"github.com/topsailai/agent-community/internal/discovery"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/nats"
	"github.com/topsailai/agent-community/internal/services"
	"github.com/topsailai/agent-community/internal/trigger"
	"github.com/topsailai/agent-community/pkg/logger"
	"gorm.io/gorm"
)

// discoveryProvider abstracts the discovery client so the router can be tested
// without a live NATS server. The concrete *discovery.Discovery type satisfies
// this interface.
type discoveryProvider interface {
	Discover() ([]discovery.ServiceInfo, error)
	IsLeader() (bool, error)
	LeaderInfo() (*discovery.ServiceInfo, error)
	SelfInfo() discovery.ServiceInfo
}

// Router holds all API handlers and sets up routes.
type Router struct {
	engine *gin.Engine
}

// NewRouter creates a new Gin router with all routes configured.
func NewRouter(cfg *config.Config, db *gorm.DB, publisher *nats.Publisher, evaluator *trigger.Evaluator, disc discoveryProvider, log *logger.Logger) *Router {
	// Set Gin to release mode in production; use debug mode when log level is debug.
	if cfg.Log.Level == "info" || cfg.Log.Level == "warn" || cfg.Log.Level == "error" {
		gin.SetMode(gin.ReleaseMode)
	} else {
		gin.SetMode(gin.DebugMode)
	}

	engine := gin.New()

	// Global middleware
	engine.Use(middleware.Recovery(log))
	engine.Use(middleware.Logger(log))

	// Initialize services
	auditSvc := services.NewAuditLogService(db)
	accountSvc := services.NewAccountService(db, cfg, auditSvc)
	apiKeySvc := services.NewAPIKeyService(db, cfg, auditSvc)
	accountSvc.SetAPIKeyService(apiKeySvc)

	// Initialize handlers
	groupHandler := handlers.NewGroupHandler(db, publisher, cfg, log)
	memberHandler := handlers.NewGroupMemberHandler(db, publisher, log)
	messageHandler := handlers.NewMessageHandler(db, publisher, evaluator, log)
	healthHandler := handlers.NewHealthHandler(db, disc, log)
	accountHandler := handlers.NewAccountHandler(accountSvc, log)
	apiKeyHandler := handlers.NewAPIKeyHandler(apiKeySvc, accountSvc, log)
	auditLogHandler := handlers.NewAuditLogHandler(auditSvc, log)

	// Authentication middleware
	authMiddleware := middleware.Authentication(apiKeySvc, accountSvc)

	// Health and readiness endpoints (public)
	engine.GET("/healthz", healthHandler.Liveness)
	engine.GET("/readyz", healthHandler.Readiness)
	engine.GET("/health", healthHandler.Health)
	engine.GET("/health/leader", healthHandler.LeaderStatus)

	// Discovery endpoints (public)
	engine.GET("/discovery/services", healthHandler.DiscoveryServices)

	// API v1 routes
	v1 := engine.Group("/api/v1")

	// Public account login endpoint (must not require authentication).
	v1.POST("/accounts/login", accountHandler.Login)

	// Protected routes below require authentication and audit logging.
	v1.Use(authMiddleware)
	v1.Use(middleware.AuditLogger(auditSvc))
	{
		// Account routes
		v1.POST("/accounts", middleware.RequireRole(models.AccountRoleManager), accountHandler.CreateAccount)
		v1.GET("/accounts", middleware.RequireAuthenticated(), accountHandler.ListAccounts)
		v1.GET("/accounts/me", middleware.RequireAuthenticated(), accountHandler.GetMe)
		v1.GET("/accounts/:account_id", middleware.RequireAuthenticated(), accountHandler.GetAccount)
		v1.PUT("/accounts/:account_id", middleware.RequireAuthenticated(), accountHandler.UpdateAccount)
		v1.DELETE("/accounts/:account_id", middleware.RequireRole(models.AccountRoleAdmin), accountHandler.DeleteAccount)
		v1.POST("/accounts/:account_id/password", middleware.RequireAuthenticated(), accountHandler.ChangePassword)
		v1.POST("/accounts/:account_id/session", middleware.RequireRole(models.AccountRoleManager), accountHandler.CreateSession)

		// API key routes nested under accounts
		v1.POST("/accounts/:account_id/api-keys", middleware.RequireAuthenticated(), apiKeyHandler.CreateAPIKey)
		v1.GET("/accounts/:account_id/api-keys", middleware.RequireAuthenticated(), apiKeyHandler.ListAPIKeys)
		v1.DELETE("/accounts/:account_id/api-keys/:api_key_id", middleware.RequireAuthenticated(), apiKeyHandler.DeleteAPIKey)

		// Audit log routes (admin only)
		v1.GET("/audit-logs", middleware.RequireRole(models.AccountRoleAdmin), auditLogHandler.ListAuditLogs)
		v1.GET("/audit-logs/:audit_log_id", middleware.RequireRole(models.AccountRoleAdmin), auditLogHandler.GetAuditLog)

		// Group routes (protected)
		v1.POST("/groups", middleware.RequireAuthenticated(), groupHandler.CreateGroup)
		v1.GET("/groups", middleware.RequireAuthenticated(), groupHandler.ListGroups)
		v1.GET("/groups/:group_id", middleware.RequireAuthenticated(), groupHandler.GetGroup)
		v1.PUT("/groups/:group_id", middleware.RequireAuthenticated(), groupHandler.UpdateGroup)
		v1.DELETE("/groups/:group_id", middleware.RequireAuthenticated(), groupHandler.DeleteGroup)

		// Group member routes (protected)
		v1.POST("/groups/:group_id/members", middleware.RequireAuthenticated(), memberHandler.JoinGroup)
		v1.GET("/groups/:group_id/members", middleware.RequireAuthenticated(), memberHandler.ListGroupMembers)
		v1.PUT("/groups/:group_id/members/:member_id", middleware.RequireAuthenticated(), memberHandler.UpdateMember)
		v1.DELETE("/groups/:group_id/members/:member_id", middleware.RequireAuthenticated(), memberHandler.LeaveGroup)

		// Message routes (protected)
		v1.POST("/groups/:group_id/messages", middleware.RequireAuthenticated(), messageHandler.CreateMessage)
		v1.GET("/groups/:group_id/messages", middleware.RequireAuthenticated(), messageHandler.ListMessages)
		v1.PUT("/groups/:group_id/messages/:message_id", middleware.RequireAuthenticated(), messageHandler.UpdateMessage)
		v1.DELETE("/groups/:group_id/messages/:message_id", middleware.RequireAuthenticated(), messageHandler.DeleteMessage)
		v1.POST("/groups/:group_id/messages/:message_id/trigger", middleware.RequireAuthenticated(), messageHandler.TriggerMessage)
	}

	return &Router{engine: engine}
}

// Engine returns the underlying gin.Engine for testing or direct use.
func (r *Router) Engine() *gin.Engine {
	return r.engine
}
