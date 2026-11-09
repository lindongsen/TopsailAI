package server

import (
	"context"
	"net/http"

	"topsailai_agent_cluster/internal/security"
)

// operationHistoryList names the history read surface, so an authorization
// failure names the exact operation the caller tried to reach.
const operationHistoryList = "history.list"

// authorizeHistoryRead decides whether the authenticated caller may read provider
// session history, and writes the rejection itself when it may not.
//
// A history row carries the provider session name, the recorded task text and the
// project workspace. That is metadata rather than session output, so the required
// scope is view rather than read_output: an operator who may see the fleet may
// see which past sessions exist, but reading a session's actual output still
// needs the separate read_output scope.
//
// The check runs before the transport is consulted, so an unauthorized caller
// cannot infer Endpoint reachability or Server capability from a status code or a
// response time.
func (h *Handler) authorizeHistoryRead(w http.ResponseWriter, r *http.Request) bool {
	if err := authorizeHistoryReadContext(r.Context()); err != nil {
		h.writeError(w, http.StatusForbidden, "permission_denied", err.Error())
		return false
	}
	return true
}

// authorizeHistoryReadContext is the context-only form of the check. The handler
// form delegates to it, so the rule has exactly one implementation.
func authorizeHistoryReadContext(ctx context.Context) error {
	return security.AuthorizeOperation(security.AuthenticatedScopes(ctx), operationHistoryList, security.ScopeView, true)
}
