package tui

import (
	"context"
	"fmt"
	"io"
	"strings"
)

// interactiveMessages reads one session's conversation and renders it.
//
// This command is read-only, so unlike history it never replaces the row-number
// namespace and unlike resume it never invalidates it. That is deliberate: an
// operator inspecting a past session usually reads several rows in sequence, and
// clearing the numbers after the first read would force a fresh history render
// between every one of them.
//
// It is also the only conversation surface that addresses live and stopped
// sessions alike. cd requires a live generation and resume requires a proven
// absence, so the two are mutually exclusive; messages addresses persisted
// provider data and therefore needs neither.
func interactiveMessages(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, out, diagnostics io.Writer, color ColorPolicy) error {
	target, maxChars, maxTokens, err := parseMessagesArgs(rest)
	if err != nil {
		return err
	}
	querier, ok := api.(MessagesQuerier)
	if !ok {
		return fmt.Errorf("messages is unavailable: this client cannot read provider conversations")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	endpointID, sessionID, err := messagesTarget(ctx, api, state, target)
	if err != nil {
		return err
	}
	result, err := querier.GetMessages(ctx, endpointID, sessionID, maxChars, maxTokens)
	if err != nil {
		return err
	}
	if result.ErrorCode != "" {
		return fmt.Errorf("messages for session %s on endpoint %q failed: %s", sessionIdentityLabel("", sessionID, ""), endpointID, result.ErrorCode)
	}
	view := BuildMessagesView(endpointID, result, maxChars, maxTokens)
	// The renderer owns both halves of the boundary: it applies trusted styling
	// to its own headers and sanitizes every provider body itself. It therefore
	// needs the trusted writer, because the untrusted one would strip the styling
	// it emits while adding nothing the renderer does not already do.
	return RenderMessages(out, view, color)
}

// messagesTarget resolves the endpoint and provider session a conversation read
// must address.
//
// Session scope names the target already, so an argument is rejected rather than
// silently retargeted. Endpoint scope stays inside the current endpoint. Workspace
// scope resolves a history row number first and then a literal provider session
// ID, and a token matching sessions on several endpoints is rejected with the
// candidate list instead of picking one.
func messagesTarget(ctx context.Context, api InteractiveAPI, state *interactiveState, token string) (string, string, error) {
	if state.Scope.Kind == ScopeSession {
		if token != "" {
			return "", "", fmt.Errorf("messages takes no argument in session scope; use cd .. to read another session")
		}
		_, _, session, err := findSelected(ctx, api, state)
		if err != nil {
			return "", "", err
		}
		if session.ProviderSessionID == "" {
			return "", "", fmt.Errorf("the selected session has no provider session ID, so its conversation cannot be read")
		}
		return state.EndpointID, session.ProviderSessionID, nil
	}
	if token == "" {
		return "", "", fmt.Errorf("usage: messages <history-row-number-or-session-id>")
	}
	// A history row number is resolved against the most recently rendered history
	// table, because that is the only table whose numbers the operator can see
	// while inspecting past sessions.
	if number, numeric := parseRowNumber(token); numeric {
		return messagesHistoryRow(state, number)
	}
	return messagesSessionID(ctx, api, state, token)
}

// messagesHistoryRow resolves one history row number to its endpoint and provider
// session.
//
// A row number is presentation only, so it is accepted solely while the history
// table that produced it is still the rendered one. The row does not need to be
// live, joined or resumable: a conversation read addresses persisted provider
// data, so an unjoined or ambiguous row is still readable. Only the endpoint and
// the provider session ID are required, and both come from the provider's own
// answer rather than from the inventory join.
func messagesHistoryRow(state *interactiveState, number int) (string, string, error) {
	namespace := state.history
	if namespace == nil {
		return "", "", fmt.Errorf("no history table is available for row selection; run history first, or pass a session ID")
	}
	row, ok := namespace.Rows[number]
	if !ok {
		return "", "", fmt.Errorf("row %d is out of range; valid history rows are 1-%d", number, len(namespace.Rows))
	}
	if row.ProviderSessionID == "" {
		return "", "", fmt.Errorf("history row %d has no provider session ID, so its conversation cannot be read", number)
	}
	return namespace.EndpointID, row.ProviderSessionID, nil
}

// messagesSessionID resolves a literal provider session ID.
//
// Endpoint scope confines the search to the current endpoint. Workspace scope
// searches every endpoint, because a stopped session is absent from the inventory
// and therefore cannot be located by a cluster resource ID. A provider session ID
// reported by several endpoints is rejected with the candidate list, because the
// operator asked for one conversation and a silent choice would read the wrong
// machine's session.
func messagesSessionID(ctx context.Context, api InteractiveAPI, state *interactiveState, token string) (string, string, error) {
	if state.Scope.Kind == ScopeEndpoint {
		return state.Scope.EndpointID, token, nil
	}
	loaded, err := loadReports(ctx, api, "")
	if err != nil {
		return "", "", err
	}
	matches := make([]string, 0, 2)
	for _, endpoint := range loaded.endpoints {
		report, ok := loaded.reports[endpoint.EndpointID]
		if !ok {
			continue
		}
		for _, session := range report.Sessions {
			if session.ProviderSessionID == token {
				matches = append(matches, endpoint.EndpointID)
				break
			}
		}
	}
	switch len(matches) {
	case 0:
		// A stopped session is absent from the inventory, so an unmatched token is
		// not an error: the operator may legitimately name a session that no
		// endpoint currently reports. The read is attempted against the sole
		// endpoint when the fleet has exactly one, and otherwise the operator must
		// state which machine to ask.
		if len(loaded.endpoints) == 1 {
			return loaded.endpoints[0].EndpointID, token, nil
		}
		return "", "", fmt.Errorf("session %q is not in the current inventory; pass the endpoint first with cd <endpoint>", token)
	case 1:
		return matches[0], token, nil
	}
	return "", "", fmt.Errorf("session %q is reported by several endpoints (%s); cd into one endpoint first", token, strings.Join(matches, ", "))
}
