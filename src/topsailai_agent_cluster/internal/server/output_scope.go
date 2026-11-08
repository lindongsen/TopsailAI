package server

import (
	"context"
	"net/http"

	"topsailai_agent_cluster/internal/security"
)

// Output read operations. They are named like the other standard operations so
// an authorization failure names the exact surface the caller tried to reach.
const (
	operationOutputSnapshot = "output.snapshot"
	operationOutputFollow   = "output.follow"
)

// authorizeOutputRead decides whether the authenticated caller may read session
// output, and writes the rejection itself when it may not.
//
// Session output carries prompts, model answers, tool arguments and command
// output, so it is the most sensitive payload the cluster serves. Reading it
// therefore requires the read_output scope rather than merely a valid
// credential. Both output routes call this one helper, so a future output route
// cannot be added without the check.
//
// The check runs before the transport is consulted and before the handler
// inspects whether a transport or streaming capability is configured. An
// unauthorized caller must not be able to infer Endpoint reachability or Server
// capability from a status code or a response time.
//
// An unrestricted scope set holds every permission, which models the
// single-credential deployment where the one provisioned credential is the
// administrator. A configured set restricts the credential to exactly the listed
// scopes, so a narrowed credential is refused here.
func (h *Handler) authorizeOutputRead(w http.ResponseWriter, r *http.Request, operation string) bool {
	if err := authorizeOutputReadContext(r.Context(), operation); err != nil {
		h.writeError(w, http.StatusForbidden, "permission_denied", err.Error())
		return false
	}
	return true
}

// authorizeOutputReadContext is the context-only form of the check. The handler
// form delegates to it, so the rule has exactly one implementation and a caller
// that resolves authorization before writing a response cannot drift from it.
func authorizeOutputReadContext(ctx context.Context, operation string) error {
	return security.AuthorizeOperation(security.AuthenticatedScopes(ctx), operation, security.ScopeReadOutput, true)
}
