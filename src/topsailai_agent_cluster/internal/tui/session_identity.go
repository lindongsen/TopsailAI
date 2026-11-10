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

// SessionIdentityLabelFromInventory renders the canonical expression of one
// session by looking it up in the committed inventory.
//
// It exists for the messages that carry only the opaque cluster resource ID, such
// as a model-catalog failure. The lookup happens only when such a message is
// about to be rendered, so a successful read gains no extra request.
//
// A lookup failure or an absent row degrades to the resource ID rather than
// suppressing the message, because a diagnostic that cannot be printed is worse
// than one that names the session less precisely.
func SessionIdentityLabelFromInventory(ctx context.Context, api CommandAPI, endpointID, resourceID string) string {
	if api == nil || endpointID == "" || resourceID == "" {
		return sessionIdentityLabel("", "", resourceID)
	}
	report, err := api.GetInventory(ctx, endpointID)
	if err != nil {
		return sessionIdentityLabel("", "", resourceID)
	}
	for _, session := range report.Sessions {
		if session.SessionID == resourceID {
			return sessionIdentityLabel(session.DisplayName, session.ProviderSessionID, resourceID)
		}
	}
	return sessionIdentityLabel("", "", resourceID)
}
