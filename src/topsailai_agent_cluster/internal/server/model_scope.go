package server

import (
	"context"
	"net/http"

	"topsailai_agent_cluster/internal/security"
)

// operationModelCatalogList names the model-catalog read surface, so an
// authorization failure names the exact operation the caller tried to reach.
const operationModelCatalogList = "agent.model.list"

// authorizeModelCatalogRead decides whether the authenticated caller may read the
// model profiles a session can select, and writes the rejection itself when it may
// not.
//
// A model profile carries a display name and an availability verdict. That is
// metadata rather than session output, so the required scope is view rather than
// read_output: an operator who may see the fleet may see which profiles exist, but
// reading a session's actual output still needs the separate read_output scope.
// Selecting a profile is a different operation with a different scope, because it
// changes live agent behaviour.
//
// The check runs before the transport is consulted, so an unauthorized caller
// cannot infer Endpoint reachability or Server capability from a status code or a
// response time.
func (h *Handler) authorizeModelCatalogRead(w http.ResponseWriter, r *http.Request) bool {
	if err := authorizeModelCatalogReadContext(r.Context()); err != nil {
		h.writeError(w, http.StatusForbidden, "permission_denied", err.Error())
		return false
	}
	return true
}

// authorizeModelCatalogReadContext is the context-only form of the check. The
// handler form delegates to it, so the rule has exactly one implementation.
func authorizeModelCatalogReadContext(ctx context.Context) error {
	return security.AuthorizeOperation(security.AuthenticatedScopes(ctx), operationModelCatalogList, security.ScopeView, true)
}
