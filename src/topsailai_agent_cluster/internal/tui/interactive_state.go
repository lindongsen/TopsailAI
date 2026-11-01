package tui

import "fmt"

// interactiveSelection stores the identity pinned by an explicit use command.
type interactiveSelection struct {
	EndpointID    string
	SessionID     string
	Generation    string
	Invalidated   bool
	InvalidReason string
}

// invalidate marks a selection permanently unusable until use selects it again.
func (s *interactiveSelection) invalidate(reason string) {
	if s.Invalidated {
		return
	}
	s.Invalidated = true
	s.InvalidReason = reason
}

// reset replaces the pinned selection after a successful explicit use command.
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
		return fmt.Errorf("no session selected; use <endpoint> <session>")
	}
	if s.Invalidated {
		return fmt.Errorf("selected session invalidated; use the session again")
	}
	return nil
}
