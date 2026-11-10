package tui

import (
	"context"
	"fmt"
	"io"

	"topsailai_agent_cluster/internal/protocol"
)

// SessionInfo is the machine-readable result of the standalone info command.
//
// It carries the endpoint that owns the session plus the standard session
// record, so a caller never has to infer ownership from a display label.
type SessionInfo struct {
	EndpointID string           `json:"endpoint_id"`
	Session    protocol.Session `json:"session"`
}

// Info renders the detail of exactly one session selected by identifier.
//
// The standalone surface has no rendered list, so a row number is meaningless
// here and only a real identifier is accepted. A token that names an endpoint is
// rejected instead of silently rendering something else, because info is a
// session command and an endpoint has no session detail to show.
func (r CommandRunner) Info(ctx context.Context, out io.Writer, id string, jsonMode bool) error {
	endpoints, err := r.API.ListEndpoints(ctx)
	if err != nil {
		return err
	}
	reports := make(map[string]protocol.InventoryReport, len(endpoints))
	for _, endpoint := range endpoints {
		report, fetchErr := r.API.GetInventory(ctx, endpoint.EndpointID)
		if fetchErr == nil {
			reports[endpoint.EndpointID] = report
		}
	}
	endpoint, session, err := findInfoSession(id, endpoints, reports)
	if err != nil {
		return err
	}
	if jsonMode {
		return RenderJSON(out, SessionInfo{EndpointID: endpoint.EndpointID, Session: session})
	}
	return RenderSessionInfo(out, endpoint, session)
}

// findInfoSession resolves one identifier to exactly one session.
//
// A cluster resource ID keeps precedence over a provider session ID, matching
// the interactive resolver: the resource ID is the routing identity, so it must
// win when the two namespaces collide. Several matches are an error rather than
// an arbitrary pick, because silently choosing one endpoint would show a
// different session than the identifier names.
func findInfoSession(id string, endpoints []protocol.Endpoint, reports map[string]protocol.InventoryReport) (protocol.Endpoint, protocol.Session, error) {
	for _, endpoint := range endpoints {
		if endpoint.EndpointID == id {
			return protocol.Endpoint{}, protocol.Session{}, fmt.Errorf("%q is an endpoint, not a session; use show %s for endpoint detail", id, id)
		}
	}
	if endpoint, session, matches := matchInfoSession(id, endpoints, reports, true); matches > 0 {
		if matches > 1 {
			return protocol.Endpoint{}, protocol.Session{}, fmt.Errorf("session %q matches %d endpoints; use show <endpoint-id> to inspect one endpoint first", id, matches)
		}
		return endpoint, session, nil
	}
	if endpoint, session, matches := matchInfoSession(id, endpoints, reports, false); matches > 0 {
		if matches > 1 {
			return protocol.Endpoint{}, protocol.Session{}, fmt.Errorf("provider session %q matches %d endpoints; use show <endpoint-id> to inspect one endpoint first", id, matches)
		}
		return endpoint, session, nil
	}
	return protocol.Endpoint{}, protocol.Session{}, fmt.Errorf("session %q was not found on any endpoint", id)
}

// matchInfoSession counts matches in one identifier namespace and returns the
// first one. byResourceID selects the cluster resource ID namespace; otherwise
// the provider session ID namespace is searched.
func matchInfoSession(id string, endpoints []protocol.Endpoint, reports map[string]protocol.InventoryReport, byResourceID bool) (protocol.Endpoint, protocol.Session, int) {
	var (
		foundEndpoint protocol.Endpoint
		foundSession  protocol.Session
		matches       int
	)
	for _, endpoint := range endpoints {
		report, ok := reports[endpoint.EndpointID]
		if !ok {
			continue
		}
		for _, session := range report.Sessions {
			matched := session.ClusterSessionID == id
			if !byResourceID {
				matched = session.ProviderSessionID != "" && session.ProviderSessionID == id
			}
			if !matched {
				continue
			}
			if matches == 0 {
				foundEndpoint, foundSession = endpoint, session
			}
			matches++
		}
	}
	return foundEndpoint, foundSession, matches
}
