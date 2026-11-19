package tui

import (
	"context"
	"fmt"
	"io"

	"topsailai_agent_cluster/internal/protocol"
)

// resumeEntryPrefix names the step that follows a completed resume in every
// diagnostic it writes, so the operator can tell which step degraded.
const resumeEntryPrefix = "resume completed"

// enterResumedSession moves the REPL into the session a completed resume started,
// so the operator does not have to type cd afterwards.
//
// The step is a convenience layered on the durable receipt, never a second
// authority. The resume already succeeded, so every failure here is a diagnostic
// and the scope is left unchanged; reporting a failure would deny an admission
// that happened.
//
// The forced collection is mandatory and runs first, because resume submits no
// generation: it addresses a session whose process is gone, so the generation
// only exists once a collection proves a process holds the session. Entering
// earlier would bind an empty generation, which the Endpoint rejects with
// generation_required. This is the same ordering the post-start tail uses, and for
// the same reason.
func enterResumedSession(parent context.Context, api InteractiveAPI, state *interactiveState, selection resumeSelection, result map[string]any, trustedOut io.Writer, options InteractiveOptions) error {
	// A receipt that proves the effect was not applied means no runtime was
	// started, so there is no session to enter. The predicate is the same one the
	// post-start refresh and the automatic tail use, so "provably did not take
	// effect" keeps one definition.
	if ReceiptForStatus(result).EffectCertainty == protocol.EffectNotApplied {
		return nil
	}
	// A client without the forced-collection seam keeps its previous behaviour
	// silently. It cannot mint the generation the entry needs, and a diagnostic
	// would turn a working resume into a noisy one on every such client.
	refresher, forced := api.(InventoryRefresher)
	if !forced {
		return nil
	}
	ctx, cancel := context.WithTimeout(parent, refreshCommandTimeout)
	defer cancel()
	report, err := refresher.RefreshInventory(ctx, selection.EndpointID)
	if err != nil {
		return writeAutomaticDiagnostic(trustedOut, resumeEntryPrefix, "automatic collection failed: "+sanitizeTerminal([]byte(err.Error())))
	}
	// Only the endpoint record is needed here, because the committed document is
	// the one the collection just returned. Reading the stored document again
	// would be a second read of the same fact.
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return writeAutomaticDiagnostic(trustedOut, resumeEntryPrefix, "automatic collection failed: "+sanitizeTerminal([]byte(err.Error())))
	}
	endpoint, found := endpointByID(reportLoad{endpoints: endpoints}, selection.EndpointID)
	if !found {
		return writeAutomaticDiagnostic(trustedOut, resumeEntryPrefix, fmt.Sprintf("automatic entry skipped: endpoint %q was not found", sanitizeInlineText(selection.EndpointID)))
	}
	session, err := resumedSession(report, selection)
	if err != nil {
		return writeAutomaticDiagnostic(trustedOut, resumeEntryPrefix, "automatic entry skipped: "+sanitizeTerminal([]byte(err.Error())))
	}
	if session.ProviderGeneration == "" {
		// enterValidatedSession already refuses an unverified session, so this
		// guard is not the safety boundary; it exists because that refusal names
		// resume as the remedy, which is the command the operator just ran. Naming
		// the next collection instead is the only advice that can change the
		// outcome, and a tail bound to an empty generation would be refused by the
		// Endpoint anyway.
		return writeAutomaticDiagnostic(trustedOut, resumeEntryPrefix, "automatic entry skipped: the resumed session has no verified generation; run list after the next collection")
	}
	if _, err := enterValidatedSession(state, endpoint, report, session); err != nil {
		return writeAutomaticDiagnostic(trustedOut, resumeEntryPrefix, "automatic entry skipped: "+sanitizeTerminal([]byte(err.Error())))
	}
	return autoFollowOnSessionEntry(parent, api, state, trustedOut, options, resumeEntryPrefix)
}

// resumedSession locates the session a completed resume started inside the
// committed document.
//
// The cluster resource ID is preferred because it is the identity the resume
// addressed, so a match is the same resource rather than a lookalike. The provider
// session identifier is the fallback for the handle form, which names a session
// the Endpoint had not discovered when the command was submitted; that form has no
// resource ID at all.
//
// A provider session identifier matching several rows is refused instead of
// resolved to the first row. Entering the wrong session is worse than entering
// none, and the ambiguity is real: one provider session can own several
// independently selectable rows.
func resumedSession(report protocol.InventoryReport, selection resumeSelection) (protocol.Session, error) {
	if selection.ResourceID != "" {
		for _, session := range report.Sessions {
			if session.ClusterSessionID == selection.ResourceID {
				return session, nil
			}
		}
		return protocol.Session{}, fmt.Errorf("session %s is not visible yet; run list after the next collection", sanitizeInlineText(selection.ResourceID))
	}
	if selection.ProviderSessionID == "" {
		return protocol.Session{}, fmt.Errorf("the resume target carries no identity, so the resumed session cannot be located")
	}
	matches := sessionsByProviderID(report.Sessions, selection.ProviderSessionID)
	switch len(matches) {
	case 1:
		return matches[0], nil
	case 0:
		return protocol.Session{}, fmt.Errorf("session %s is not visible yet; run list after the next collection", sanitizeInlineText(selection.ProviderSessionID))
	default:
		return protocol.Session{}, fmt.Errorf("session %s matches several rows, so the resumed session cannot be identified; run list and cd the row", sanitizeInlineText(selection.ProviderSessionID))
	}
}
