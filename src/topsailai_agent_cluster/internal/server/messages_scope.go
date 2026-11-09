package server

import (
	"context"
	"net/http"

	"topsailai_agent_cluster/internal/security"
)

// operationMessagesRead names the conversation read surface, so an authorization
// failure names the exact operation the caller tried to reach.
const operationMessagesRead = "session.read_messages"

// authorizeMessagesRead decides whether the authenticated caller may read a
// session's conversation, and writes the rejection itself when it may not.
//
// A conversation carries prompts, model answers and tool arguments, so it is the
// same sensitivity class as session output. The required scope is therefore
// read_output rather than view: an operator who may list the fleet and read
// history metadata must not thereby read what was actually said. History uses
// view because a history row is metadata only; messages must not inherit that
// weaker scope merely because both surfaces address a past session.
//
// The check runs before the transport is consulted, so an unauthorized caller
// cannot infer Endpoint reachability or Server capability from a status code or a
// response time.
func (h *Handler) authorizeMessagesRead(w http.ResponseWriter, r *http.Request) bool {
	if err := authorizeMessagesReadContext(r.Context()); err != nil {
		h.writeError(w, http.StatusForbidden, "permission_denied", err.Error())
		return false
	}
	return true
}

// authorizeMessagesReadContext is the context-only form of the check. The handler
// form delegates to it, so the rule has exactly one implementation.
func authorizeMessagesReadContext(ctx context.Context) error {
	return security.AuthorizeOperation(security.AuthenticatedScopes(ctx), operationMessagesRead, security.ScopeReadOutput, true)
}
