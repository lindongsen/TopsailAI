package tui

import (
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// ScopeKind identifies the interactive navigation scope.
type ScopeKind int

const (
	ScopeWorkspace ScopeKind = iota
	ScopeEndpoint
	ScopeSession
)

// String returns the stable name of the scope.
func (k ScopeKind) String() string {
	switch k {
	case ScopeWorkspace:
		return "workspace"
	case ScopeEndpoint:
		return "endpoint"
	case ScopeSession:
		return "session"
	default:
		return "unknown"
	}
}

// ScopeState stores the current interactive navigation location.
type ScopeState struct {
	Kind              ScopeKind
	EndpointID        string
	Hostname          string
	SessionID         string
	ProviderSessionID string
	SessionName       string
	Generation        string
}

// interactiveSelection stores the identity pinned by an explicit navigation command.
type interactiveSelection struct {
	EndpointID    string
	SessionID     string
	Generation    string
	Invalidated   bool
	InvalidReason string
	Rows          map[int]SessionRow
}

// invalidate marks a selection permanently unusable until a session is selected again.
func (s *interactiveSelection) invalidate(reason string) {
	if s.Invalidated {
		return
	}
	s.Invalidated = true
	s.InvalidReason = reason
}

// reset replaces the pinned selection after a successful explicit navigation command.
func (s *interactiveSelection) reset(endpointID, sessionID, generation string) {
	s.EndpointID = endpointID
	s.SessionID = sessionID
	s.Generation = generation
	s.Invalidated = false
	s.InvalidReason = ""
}

// requireUsable rejects no-selection and sticky-invalidated states.
func (s interactiveSelection) requireUsable() error {
	if s.EndpointID == "" || s.SessionID == "" {
		return fmt.Errorf("no session selected; use cd <endpoint>/<session>")
	}
	if s.Invalidated {
		return fmt.Errorf("selected session invalidated; use the session again")
	}
	return nil
}

func (s *interactiveState) setRows(rows []SessionRow) {
	s.Rows = make(map[int]SessionRow, len(rows))
	for _, row := range rows {
		s.Rows[row.No] = row
	}
}

// enterWorkspace resets navigation and selection to the workspace scope.
func (s *interactiveState) enterWorkspace() {
	*s = interactiveState{}
}

// enterEndpoint keeps endpoint context while clearing session identity and stale row mappings.
func (s *interactiveState) enterEndpoint(endpoint protocol.Endpoint) {
	s.interactiveSelection = interactiveSelection{EndpointID: endpoint.EndpointID}
	s.Rows = nil
	s.Scope = ScopeState{Kind: ScopeEndpoint, EndpointID: endpoint.EndpointID, Hostname: endpoint.Hostname}
}

// enterSession pins a validated session and records its endpoint hostname.
func (s *interactiveState) enterSession(endpoint protocol.Endpoint, sessionID, generation string) {
	s.enterSessionDetails(endpoint, sessionID, "", "", generation)
}

// enterSessionDetails pins a session and its user-facing identity in the prompt.
func (s *interactiveState) enterSessionDetails(endpoint protocol.Endpoint, sessionID, providerSessionID, sessionName, generation string) {
	s.reset(endpoint.EndpointID, sessionID, generation)
	s.Scope = ScopeState{
		Kind:              ScopeSession,
		EndpointID:        endpoint.EndpointID,
		Hostname:          endpoint.Hostname,
		SessionID:         sessionID,
		ProviderSessionID: providerSessionID,
		SessionName:       sessionName,
		Generation:        generation,
	}
}
