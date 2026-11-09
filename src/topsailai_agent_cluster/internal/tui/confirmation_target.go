package tui

import (
	"topsailai_agent_cluster/internal/protocol"
)

// confirmationTarget names the exact session a mutating command will act on.
//
// The reported session name is named first because it is the only value the
// operator can see in the interactive table, which hides the SESSION_ID column.
// The provider session identifier follows because it is the provider's own name
// for the session, and the opaque cluster resource ID follows in parentheses
// because it is what `status` and `info` accept, so the operator can still copy
// it. A name never replaces an identifier: it can be empty, duplicated or changed
// between collections, so the question must stay answerable without it.
type confirmationTarget struct {
	DisplayName       string
	ProviderSessionID string
	SessionID         string
}

// label renders one confirmation label. An absent name and provider identifier
// fall back to the cluster resource ID alone, so the question never names an empty
// session and never repeats the word session.
func (t confirmationTarget) label() string {
	if t.ProviderSessionID == "" && t.DisplayName == "" {
		return t.SessionID
	}
	label := "session"
	if t.DisplayName != "" {
		label += ` "` + t.DisplayName + `"`
	}
	if t.ProviderSessionID != "" {
		label += " " + t.ProviderSessionID
	}
	if t.SessionID != "" && t.SessionID != t.ProviderSessionID {
		label += " (" + t.SessionID + ")"
	}
	return label
}

// confirmationTargetFor names one resolved session for a confirmation question.
func confirmationTargetFor(session protocol.Session) confirmationTarget {
	return confirmationTarget{
		DisplayName:       session.DisplayName,
		ProviderSessionID: session.ProviderSessionID,
		SessionID:         session.SessionID,
	}
}
