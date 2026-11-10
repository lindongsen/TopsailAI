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

// label renders one confirmation label as the canonical session identity
// expression, ({provider_session_name}) ({provider_session_id}).
//
// The reported name is the only value the interactive table shows, so naming it
// first lets the operator match the question against the row they selected. The
// provider session identifier follows because it is the provider's own key for
// the session. The opaque cluster resource ID is not printed: it is a routing
// identity, and `info` and `--json` still expose it.
//
// A name never replaces an identifier, because it can be empty, duplicated or
// changed between collections. An absent name and provider identifier fall back
// to the resource ID alone, and the word "session" is omitted there so the
// question never reads "session session-1".
func (t confirmationTarget) label() string {
	if t.ProviderSessionID == "" && t.DisplayName == "" {
		return t.SessionID
	}
	return "session " + sessionIdentityLabel(t.DisplayName, t.ProviderSessionID, t.SessionID)
}

// confirmationTargetFor names one resolved session for a confirmation question.
func confirmationTargetFor(session protocol.Session) confirmationTarget {
	return confirmationTarget{
		DisplayName:       session.DisplayName,
		ProviderSessionID: session.ProviderSessionID,
		SessionID:         session.SessionID,
	}
}
