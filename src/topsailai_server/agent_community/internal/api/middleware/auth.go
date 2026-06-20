// Package middleware provides HTTP middleware for the ACS API.
package middleware

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"

	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/internal/services"
)

// AuthMethod indicates how the request was authenticated.
type AuthMethod string

const (
	// AuthMethodAPIKey means the request was authenticated with an API key.
	AuthMethodAPIKey AuthMethod = "api_key"
	// AuthMethodSession means the request was authenticated with a session key.
	AuthMethodSession AuthMethod = "session"
	// AuthMethodPassword means the request was authenticated with login name/password.
	AuthMethodPassword AuthMethod = "password"
	// AuthMethodNone means the request was not authenticated.
	AuthMethodNone AuthMethod = "none"
)

// authContextKey is the Gin context key for AuthContext.
const authContextKey = "auth_context"

// clientIPContextKey is the Gin context key for the resolved client IP.
const clientIPContextKey = "client_ip"

// AuthContext carries authentication and authorization information for a request.
type AuthContext struct {
	Account         *models.Account
	APIKey          *models.APIKey
	AuthMethod      AuthMethod
	IsAuthenticated bool
}

// Authentication returns a Gin middleware that authenticates requests using
// login name/password, session key, or an Authorization Bearer token (API key),
// in that priority order.
func Authentication(apiKeySvc *services.APIKeyService, accountSvc *services.AccountService) gin.HandlerFunc {
	return func(c *gin.Context) {
		ctx := c.Request.Context()

		// Resolve and store client IP early so downstream middleware can use it.
		c.Set(clientIPContextKey, c.ClientIP())

		// Priority 1: login name/password headers.
		loginName := c.GetHeader("X-Login-Name")
		loginPassword := c.GetHeader("X-Login-Password")
		if loginName != "" && loginPassword != "" {
			account, err := accountSvc.ValidateLoginPassword(ctx, loginName, loginPassword)
			if err == nil {
				c.Set(authContextKey, AuthContext{
					Account:         account,
					AuthMethod:      AuthMethodPassword,
					IsAuthenticated: true,
				})
				c.Next()
				return
			}
		}

		// Priority 2: session key: X-Session-Key: {account_id}-{secret}
		sessionKey := c.GetHeader("X-Session-Key")
		if sessionKey != "" {
			account, err := accountSvc.ValidateLoginSession(ctx, sessionKey)
			if err == nil {
				c.Set(authContextKey, AuthContext{
					Account:         account,
					AuthMethod:      AuthMethodSession,
					IsAuthenticated: true,
				})
				c.Next()
				return
			}
		}

		// Priority 3: API key: Authorization: Bearer {api_key_id}.{secret}
		authHeader := c.GetHeader("Authorization")
		if strings.HasPrefix(authHeader, "Bearer ") {
			token := strings.TrimPrefix(authHeader, "Bearer ")
			token = strings.TrimSpace(token)
			if token != "" {
				key, owner, err := apiKeySvc.VerifyAPIKey(ctx, token)
				if err == nil {
					c.Set(authContextKey, AuthContext{
						Account:         owner,
						APIKey:          key,
						AuthMethod:      AuthMethodAPIKey,
						IsAuthenticated: true,
					})
					c.Next()
					return
				}
			}
		}

		// No valid credentials found; set anonymous context and continue.
		c.Set(authContextKey, AuthContext{
			AuthMethod:      AuthMethodNone,
			IsAuthenticated: false,
		})
		c.Next()
	}
}

// GetAuthContext extracts the AuthContext from a Gin context.
func GetAuthContext(c *gin.Context) (AuthContext, bool) {
	val, exists := c.Get(authContextKey)
	if !exists {
		return AuthContext{AuthMethod: AuthMethodNone, IsAuthenticated: false}, false
	}
	if ac, ok := val.(AuthContext); ok {
		return ac, true
	}
	return AuthContext{AuthMethod: AuthMethodNone, IsAuthenticated: false}, false
}

// GetClientIP extracts the resolved client IP from a Gin context.
func GetClientIP(c *gin.Context) (string, bool) {
	val, exists := c.Get(clientIPContextKey)
	if !exists {
		return "", false
	}
	if ip, ok := val.(string); ok {
		return ip, true
	}
	return "", false
}

// RequireAuthenticated returns a middleware that rejects unauthenticated requests.
func RequireAuthenticated() gin.HandlerFunc {
	return func(c *gin.Context) {
		ac, _ := GetAuthContext(c)
		if !ac.IsAuthenticated || ac.Account == nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error":    "authentication required",
				"trace_id": GetTraceID(c),
			})
			return
		}
		if !ac.Account.IsActive() {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":    "account is not active",
				"trace_id": GetTraceID(c),
			})
			return
		}
		c.Next()
	}
}

// RequireRole returns a middleware that requires the authenticated account to
// have at least the specified role.
func RequireRole(minRole models.AccountRole) gin.HandlerFunc {
	return func(c *gin.Context) {
		ac, _ := GetAuthContext(c)
		if !ac.IsAuthenticated || ac.Account == nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error":    "authentication required",
				"trace_id": GetTraceID(c),
			})
			return
		}
		if !ac.Account.IsActive() {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":    "account is not active",
				"trace_id": GetTraceID(c),
			})
			return
		}
		if !accountRoleGE(ac.Account.Role, minRole) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":    "insufficient account role",
				"trace_id": GetTraceID(c),
			})
			return
		}
		c.Next()
	}
}

// RequireAPIKeyRole returns a middleware that requires authentication via an API
// key with at least the specified role. Session-based authentication is not
// accepted by this middleware.
func RequireAPIKeyRole(minRole models.APIKeyRole) gin.HandlerFunc {
	return func(c *gin.Context) {
		ac, _ := GetAuthContext(c)
		if !ac.IsAuthenticated || ac.APIKey == nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error":    "api key authentication required",
				"trace_id": GetTraceID(c),
			})
			return
		}
		if !ac.Account.IsActive() {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":    "account is not active",
				"trace_id": GetTraceID(c),
			})
			return
		}
		if !apiKeyRoleGE(ac.APIKey.Role, minRole) {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":    "insufficient api key role",
				"trace_id": GetTraceID(c),
			})
			return
		}
		c.Next()
	}
}

// RequireOwnerOrAdmin returns a middleware that allows access only when the
// authenticated account is the resource owner or has the admin role.
func RequireOwnerOrAdmin(resourceOwnerID string) gin.HandlerFunc {
	return func(c *gin.Context) {
		ac, _ := GetAuthContext(c)
		if !ac.IsAuthenticated || ac.Account == nil {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"error":    "authentication required",
				"trace_id": GetTraceID(c),
			})
			return
		}
		if !ac.Account.IsActive() {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
				"error":    "account is not active",
				"trace_id": GetTraceID(c),
			})
			return
		}
		if ac.Account.Role == models.AccountRoleAdmin || ac.Account.AccountID == resourceOwnerID {
			c.Next()
			return
		}
		c.AbortWithStatusJSON(http.StatusForbidden, gin.H{
			"error":    "access denied",
			"trace_id": GetTraceID(c),
		})
	}
}

// accountRoleGE returns true if role a is greater than or equal to role b.
func accountRoleGE(a, b models.AccountRole) bool {
	return roleWeight(a) >= roleWeight(b)
}

// roleWeight maps account roles to numeric weights.
func roleWeight(r models.AccountRole) int {
	switch r {
	case models.AccountRoleAdmin:
		return 3
	case models.AccountRoleManager:
		return 2
	case models.AccountRoleUser:
		return 1
	default:
		return 0
	}
}

// apiKeyRoleGE returns true if API key role a is greater than or equal to b.
func apiKeyRoleGE(a, b models.APIKeyRole) bool {
	return apiKeyRoleWeight(a) >= apiKeyRoleWeight(b)
}

// apiKeyRoleWeight maps API key roles to numeric weights.
func apiKeyRoleWeight(r models.APIKeyRole) int {
	switch r {
	case models.APIKeyRoleAdmin:
		return 3
	case models.APIKeyRoleManager:
		return 2
	case models.APIKeyRoleUser:
		return 1
	default:
		return 0
	}
}
