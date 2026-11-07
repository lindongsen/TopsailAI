package tui

import (
	"topsailai_agent_cluster/internal/protocol"
)

// confirmationTarget names the exact session a mutating command will act on.
//
// The provider session identifier is named first because it is the value the list
// shows in SESSION_ID, so the operator can match the confirmation question against
// the row they selected. The opaque cluster resource ID follows in parentheses
// because it is what `status` and `info` accept, so the operator can still copy it.
type confirmationTarget struct {
	ProviderSessionID string
	SessionID         string
}

// label renders one confirmation label. An absent provider identifier falls back
// to the cluster resource ID alone, so the question never names an empty session
// and never repeats the word session.
func (t confirmationTarget) label() string {
	if t.ProviderSessionID == "" {
		return t.SessionID
	}
	label := "session " + t.ProviderSessionID
	if t.SessionID != "" && t.SessionID != t.ProviderSessionID {
		label += " (" + t.SessionID + ")"
	}
	return label
}

// confirmationTargetFor names one resolved session for a confirmation question.
func confirmationTargetFor(session protocol.Session) confirmationTarget {
	return confirmationTarget{
		ProviderSessionID: session.ProviderSessionID,
		SessionID:         session.SessionID,
	}
}

// confirmationTargetForSelection names the pinned selection, for a command that
// has no live session to read, such as resume of a stopped session.
func confirmationTargetForSelection(state *interactiveState) confirmationTarget {
	return confirmationTarget{
		ProviderSessionID: state.Scope.ProviderSessionID,
		SessionID:         state.SessionID,
	}
}
