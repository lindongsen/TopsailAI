// Package middleware provides HTTP middleware for the ACS API.
package middleware

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/topsailai/agent-community/pkg/logger"
)

// Recovery returns a Gin middleware that recovers from panics and returns 500.
func Recovery(log *logger.Logger) gin.HandlerFunc {
	return gin.CustomRecovery(func(c *gin.Context, recovered interface{}) {
		traceID := GetTraceID(c)
		if traceID == "" {
			traceID = "unknown"
		}

		log.Error("api", traceID, "panic recovered",
			"error", recovered,
			"method", c.Request.Method,
			"path", c.Request.URL.Path,
		)

		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
			"error":    "internal server error",
			"trace_id": traceID,
		})
	})
}
