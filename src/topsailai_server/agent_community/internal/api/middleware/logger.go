// Package middleware provides HTTP middleware for the ACS API.
package middleware

import (
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/topsailai/agent-community/pkg/logger"
)

const (
	// TraceIDHeader is the HTTP header for trace ID.
	TraceIDHeader = "X-Trace-ID"
	// TraceIDContextKey is the Gin context key for trace ID.
	TraceIDContextKey = "trace_id"
	// LoggerContextKey is the Gin context key for the logger instance.
	LoggerContextKey = "logger"
)

// Logger returns a Gin middleware that injects trace_id and logs requests.
func Logger(log *logger.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()

		// Extract or generate trace_id
		traceID := c.GetHeader(TraceIDHeader)
		if traceID == "" {
			traceID = uuid.New().String()
		}

		// Set trace_id in context
		c.Set(TraceIDContextKey, traceID)
		c.Header(TraceIDHeader, traceID)

		// Create a logger with trace_id for this request
		requestLogger := log.WithAttrs("api", traceID)
		c.Set(LoggerContextKey, requestLogger)

		// Process request
		c.Next()

		// Log after request completes
		duration := time.Since(start)
		status := c.Writer.Status()
		method := c.Request.Method
		path := c.Request.URL.Path
		clientIP := c.ClientIP()
		userAgent := c.Request.UserAgent()

		log.Info("api", traceID, "request completed",
			"method", method,
			"path", path,
			"status", status,
			"duration_ms", duration.Milliseconds(),
			"client_ip", clientIP,
			"user_agent", userAgent,
			"errors", c.Errors.String(),
		)
	}
}

// GetTraceID extracts trace_id from Gin context.
func GetTraceID(c *gin.Context) string {
	traceID, exists := c.Get(TraceIDContextKey)
	if !exists {
		return ""
	}
	if id, ok := traceID.(string); ok {
		return id
	}
	return ""
}

// GetLogger extracts the logger from Gin context.
func GetLogger(c *gin.Context) *logger.Logger {
	log, exists := c.Get(LoggerContextKey)
	if !exists {
		return nil
	}
	if l, ok := log.(*logger.Logger); ok {
		return l
	}
	return nil
}
