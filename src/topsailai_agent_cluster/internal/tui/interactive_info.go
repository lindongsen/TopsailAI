package tui

import (
	"context"
	"fmt"
	"io"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// interactiveInfo renders the detail of exactly one session.
//
// It is read-only: it never changes the selected session, the list row numbers,
// or any provider state. A bare ASCII row number selects the session from the
// most recently rendered list, so the operator never has to type a provider
// session identifier. In session scope the current session is the default; in
// workspace and endpoint scope an explicit target is required because neither
// scope has a selected session.
func interactiveInfo(parent context.Context, api InteractiveAPI, state *interactiveState, rest string, out io.Writer) error {
	if state.Invalidated {
		return state.requireUsable()
	}
	token := strings.TrimSpace(rest)
	endpointID, resourceID, err := resolveInfoTarget(state, token)
	if err != nil {
		return err
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	loaded, err := loadReports(ctx, api, endpointID)
	if err != nil {
		return err
	}
	endpoint, session, err := locateInfoSession(loaded, endpointID, resourceID)
	if err != nil {
		return numericTokenHint(token, err)
	}
	return RenderSessionInfo(out, endpoint, session)
}

// locateInfoSession finds the one session named by resourceID.
//
// An empty endpointID means workspace scope, where a literal identifier may live
// on any endpoint, so every loaded report is searched. An ambiguous match is an
// error rather than an arbitrary pick, because silently choosing one endpoint
// would show the operator a different session than the identifier names.
func locateInfoSession(loaded reportLoad, endpointID, resourceID string) (protocol.Endpoint, protocol.Session, error) {
	if endpointID != "" {
		endpoint, _, session, err := findSessionInEndpoint(loaded, endpointID, resourceID)
		return endpoint, session, err
	}
	var (
		foundEndpoint protocol.Endpoint
		foundSession  protocol.Session
		matches       int
	)
	for _, endpoint := range loaded.endpoints {
		_, _, session, err := findSessionInEndpoint(loaded, endpoint.EndpointID, resourceID)
		if err != nil {
			continue
		}
		if matches == 0 {
			foundEndpoint, foundSession = endpoint, session
		}
		matches++
	}
	if matches == 0 {
		return protocol.Endpoint{}, protocol.Session{}, fmt.Errorf("session %q was not found on any endpoint; run list to select a session by row number", resourceID)
	}
	if matches > 1 {
		return protocol.Endpoint{}, protocol.Session{}, fmt.Errorf("session %q matches %d endpoints; run cd <hostname>/<endpoint-id> first and use info there", resourceID, matches)
	}
	return foundEndpoint, foundSession, nil
}

// resolveInfoTarget maps the operator token to one endpoint and session.
//
// A resolved list row supplies both identities, so a row number works in every
// scope. An unresolved token is treated as a session identifier: workspace scope
// searches every endpoint, while endpoint and session scope stay inside the
// current endpoint so a token cannot silently address another machine.
//
// A row number is resolved through the read-only resolver, because info only reads
// persisted report data. An unverified session row therefore renders its real detail
// instead of being refused, which is the same reasoning messagesListRow already
// applies to a conversation read. An endpoint placeholder row still cannot be read
// here, because info is a session command, but the refusal names the command that
// does read that row instead of reporting that the row identifies nothing.
func resolveInfoTarget(state *interactiveState, token string) (string, string, error) {
	if token == "" {
		if state.Scope.Kind != ScopeSession {
			return "", "", fmt.Errorf("info requires a session in %s scope; use info <number> for a session row or info <session-id>", state.Scope.Kind)
		}
		if state.Scope.ClusterSessionID == "" {
			return "", "", fmt.Errorf("no session selected; use cd <number> to select a session row, or cd <hostname>/<endpoint-id>/<session>")
		}
		return state.Scope.EndpointID, state.Scope.ClusterSessionID, nil
	}
	if state.Scope.Kind == ScopeWorkspace {
		row, resolved, err := resolveReadSessionToken(state, token)
		if err != nil {
			return "", "", err
		}
		if resolved {
			return infoRowTarget(row)
		}
		return "", token, nil
	}
	endpointID := state.Scope.EndpointID
	if endpointID == "" {
		return "", "", fmt.Errorf("no endpoint selected; use cd <number> to enter an endpoint row, or cd <hostname>/<endpoint-id>")
	}
	row, resolved, err := resolveReadSessionTokenInEndpoint(state, token, endpointID)
	if err != nil {
		return "", "", err
	}
	if resolved {
		return infoRowTarget(row)
	}
	return endpointID, token, nil
}

// infoRowTarget converts one resolved list row into the endpoint and session that
// info reads.
//
// A row with no session identity is an endpoint placeholder row, which info cannot
// render because it has no session detail. The refusal names the endpoint and the
// command that reads it, so the operator is not left with a visible row and no
// remedy.
func infoRowTarget(row SessionRow) (string, string, error) {
	if row.ClusterSessionID == "" {
		return "", "", fmt.Errorf("row %d is endpoint %q, not a session; use show %s for endpoint detail", row.No, row.EndpointID, row.EndpointID)
	}
	return row.EndpointID, row.ClusterSessionID, nil
}

// RenderSessionInfo writes one session's detail.
//
// Every provider-supplied value is sanitized before it reaches the terminal,
// because session metadata is untrusted report data. The project workspace is
// printed as descriptive context only; it never selects a route, capability, or
// permission.
//
// The drive fields come from driveDetailLines, the same source drive status uses,
// so the two surfaces cannot drift. They are appended after the session fields
// because a controller belongs to the session rather than being part of its
// identity, and an absent observation is reported as not_reported instead of being
// omitted: an operator reading info must not conclude that no controller exists.
func RenderSessionInfo(w io.Writer, endpoint protocol.Endpoint, session protocol.Session) error {
	lines := []detailLine{
		{"session_id", session.ClusterSessionID},
		{"provider_session_id", session.ProviderSessionID},
		{"provider_pid", providerPIDLabel(session.ProviderPID)},
		{"display_name", session.ProviderDisplayName},
		{"project_workspace", session.ProviderProjectWorkspace},
		{"agent_id", session.ProviderAgentID},
		{"generation", session.ProviderGeneration},
		{"adapter_id", session.AdapterID},
		{"state", session.State},
		{"state_reason", session.StateReason},
		{"collection_status", session.CollectionStatus},
		{"stale", fmt.Sprint(session.Stale)},
		{"unknown", fmt.Sprint(session.Unknown)},
		{"observed_at_ms", fmt.Sprint(session.ObservedAtMS)},
		{"endpoint_id", endpoint.EndpointID},
		{"endpoint_connection_state", endpoint.ConnectionState},
	}
	lines = append(lines, driveDetailLines(session.Drive)...)
	for _, line := range lines {
		if _, err := fmt.Fprintf(w, "%s: %s\n", line.label, escapeCell(line.value)); err != nil {
			return err
		}
	}
	return nil
}

// providerPIDLabel renders the provider-reported session PID.
//
// A provider that reports no PID decodes to zero, and printing "0" would read as
// a real process identity that happens to be unusable. The label is therefore
// empty, matching every other unreported field in this detail view, so an absent
// value is visibly absent instead of being mistaken for a process identity. The
// value is display evidence only: it is never a routing identity, never a
// generation, and never a signal authority, so an operator must not copy it into
// a command that expects a cluster generation.
func providerPIDLabel(pid int64) string {
	if pid <= 0 {
		return ""
	}
	return fmt.Sprint(pid)
}
