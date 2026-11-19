package tui

import "context"

// sessionIdentityLabel renders the canonical operator-facing expression of one
// resolved session: ({provider_session_name}) ({provider_session_id}).
//
// The reported name is provider text, so it is sanitized before it reaches a
// trusted styled line. The opaque cluster resource ID is deliberately not
// printed: it is a routing identity, and `info` and `--json` still expose it, so
// prose does not have to carry it.
//
// A value that was not reported is omitted rather than printed empty, so a
// session with no name never renders "() (provider-id)", and a session with
// neither value falls back to the resource ID alone instead of naming nothing.
func sessionIdentityLabel(name, providerSessionID, resourceID string) string {
	cleanName := sanitizeInlineText(name)
	cleanProvider := sanitizeInlineText(providerSessionID)
	switch {
	case cleanName != "" && cleanProvider != "":
		return "(" + cleanName + ") (" + cleanProvider + ")"
	case cleanProvider != "":
		return "(" + cleanProvider + ")"
	case cleanName != "":
		return "(" + cleanName + ")"
	}
	return sanitizeInlineText(resourceID)
}

// providerIdentityFromInventory returns the provider's own identity for one
// session together with the canonical operator-facing label, from one inventory
// read.
//
// It delegates to SessionReadIdentity so the inventory lookup exists once. A
// second copy would let the two callers disagree about which row they read, and
// the disagreement would appear as a message naming one session while the read
// addressed another.
func providerIdentityFromInventory(ctx context.Context, api CommandAPI, endpointID, resourceID string) (string, string) {
	identity := SessionReadIdentity(ctx, api, endpointID, resourceID)
	return identity.ProviderTarget, identity.Label
}

// SessionReadIdentityResult is every fact one committed inventory row supplies
// to session-addressed reads and commands. ProviderTarget is opaque to the CLI.
type SessionReadIdentityResult struct {
	ProviderSessionID string
	ProviderPID       int64
	ProviderTarget    string
	Generation        string
	Label             string
}

// SessionReadIdentity reads one session row once and returns its complete read identity.
func SessionReadIdentity(ctx context.Context, api CommandAPI, endpointID, resourceID string) SessionReadIdentityResult {
	fallback := SessionReadIdentityResult{Label: sessionIdentityLabel("", "", resourceID)}
	if api == nil || endpointID == "" || resourceID == "" {
		return fallback
	}
	report, err := api.GetInventory(ctx, endpointID)
	if err != nil {
		return fallback
	}
	for _, session := range report.Sessions {
		if session.ClusterSessionID == resourceID {
			return SessionReadIdentityResult{
				ProviderSessionID: session.ProviderSessionID,
				ProviderPID:       session.ProviderPID,
				ProviderTarget:    session.ProviderTarget,
				Generation:        session.ProviderGeneration,
				Label:             sessionIdentityLabel(session.ProviderDisplayName, session.ProviderSessionID, resourceID),
			}
		}
	}
	return fallback
}

// SessionIdentityLabelFromInventory renders the canonical expression of one
// session by looking it up in the committed inventory.
//
// It exists for the messages that carry only the opaque cluster resource ID, such
// as a model-catalog failure. The lookup happens only when such a message is
// about to be rendered, so a successful read gains no extra request.
func SessionIdentityLabelFromInventory(ctx context.Context, api CommandAPI, endpointID, resourceID string) string {
	return SessionReadIdentity(ctx, api, endpointID, resourceID).Label
}
