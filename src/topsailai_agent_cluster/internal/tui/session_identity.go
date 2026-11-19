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
func providerIdentityFromInventory(ctx context.Context, api CommandAPI, endpointID, resourceID string) (string, int64, string) {
	providerSessionID, providerPID, _, label := SessionReadIdentity(ctx, api, endpointID, resourceID)
	return providerSessionID, providerPID, label
}

// SessionReadIdentity is the provider identity, generation and operator-facing
// label of one session, read from the committed inventory in one lookup.
//
// It is exported because the standalone surface needs all four facts for one
// catalog read: the label names the session in a message, the generation proves
// which process a selection would reach, and the provider session identifier plus
// process identifier let the provider address the exact row. Reading the inventory
// once for four facts about the same row is the point; four separate lookups would
// be the duplicate work this helper exists to prevent.
//
// An absent row or a failed read returns empty values, which the caller must
// interpret: an empty generation is the unverified case, and an empty provider
// identity means the adapter resolves the target itself.
func SessionReadIdentity(ctx context.Context, api CommandAPI, endpointID, resourceID string) (providerSessionID string, providerPID int64, generation, label string) {
	if api == nil || endpointID == "" || resourceID == "" {
		return "", 0, "", sessionIdentityLabel("", "", resourceID)
	}
	report, err := api.GetInventory(ctx, endpointID)
	if err != nil {
		return "", 0, "", sessionIdentityLabel("", "", resourceID)
	}
	for _, session := range report.Sessions {
		if session.ClusterSessionID == resourceID {
			return session.ProviderSessionID, session.ProviderPID, session.ProviderGeneration, sessionIdentityLabel(session.ProviderDisplayName, session.ProviderSessionID, resourceID)
		}
	}
	return "", 0, "", sessionIdentityLabel("", "", resourceID)
}

// SessionIdentityLabelFromInventory renders the canonical expression of one
// session by looking it up in the committed inventory.
//
// It exists for the messages that carry only the opaque cluster resource ID, such
// as a model-catalog failure. The lookup happens only when such a message is
// about to be rendered, so a successful read gains no extra request.
func SessionIdentityLabelFromInventory(ctx context.Context, api CommandAPI, endpointID, resourceID string) string {
	_, _, _, label := SessionReadIdentity(ctx, api, endpointID, resourceID)
	return label
}
