package main

import (
	"context"
	"errors"
	"fmt"
)

// nonLiveAuthorityOperations lists the operations whose authority is a durable
// record rather than a live process.
//
// The list mirrors the frozen enum in protocol/provider-cli/v1/request.schema.json.
// It is repeated here because this executable is an independent module that cannot
// import the Cluster validator, and a test pins the three names so the two copies
// cannot drift silently.
var nonLiveAuthorityOperations = [...]string{
	operationAgentResume,
	operationAgentDriveStop,
	operationWorkspaceClean,
}

// operationNeedsLiveGeneration reports whether an operation must carry a
// generation that proves which live process it addresses.
//
// An unknown operation needs one, so a future operation fails closed instead of
// silently reaching a provider command without target evidence.
func operationNeedsLiveGeneration(operation string) bool {
	for _, candidate := range nonLiveAuthorityOperations {
		if candidate == operation {
			return false
		}
	}
	return true
}

// workspaceAuthority resolves one exact workspace row and its generation.
//
// The read happens once per authority decision, so the row that is validated and
// the row that is addressed cannot disagree. A missing row, a duplicate row and an
// unreadable generation are all rejections: an ambiguous selector must never be
// resolved by picking one candidate.
//
// The read is host-scoped on purpose: it passes --local, so it sees only rows this
// host can confirm. That confines mutation authority to what this Endpoint can
// verify, which matters because this read is the revalidation for row-scoped
// resume, agent.drive.stop, workspace.clean, every ctl.<action> and every default
// mutation. A row recorded on another host is therefore reported as not found, and
// its liveness as unverified; both are refusals rather than admissions.
//
// Cross-host work has one supported path: agent.resume with a session-scoped key,
// which reads the session registry through sessionAuthority and never passes
// --local. Do not widen this read to compensate, because that would extend a
// destructive operation's reach to every row in a shared task directory.
func (p *provider) workspaceAuthority(ctx context.Context, requested *target) (providerSessionTarget, string, error) {
	key, err := validateSessionTarget(requested)
	if err != nil {
		return providerSessionTarget{}, "", err
	}
	var document workspaceResponse
	if err := runJSON(ctx, p.runner, []string{"workspace", "list", "--json", "--local"}, 1<<20, &document); err != nil {
		return providerSessionTarget{}, "", err
	}
	if document.Items == nil {
		return providerSessionTarget{}, "", errors.New("workspace response has no items")
	}
	scoped := sessionScopedKey(key)
	var resolved *providerSessionTarget
	var live *providerSessionTarget
	generation := ""
	liveGeneration := ""
	for _, item := range document.Items {
		matched, matchErr := matchesSessionKey(key, item)
		if matchErr != nil {
			return providerSessionTarget{}, "", matchErr
		}
		if !matched {
			continue
		}
		if resolved != nil && !scoped {
			return providerSessionTarget{}, "", fmt.Errorf("%w: provider resource key matches duplicate workspace rows", errInvalidRequest)
		}
		rowGeneration, generationErr := workspaceGeneration(item.ProcessGeneration)
		if generationErr != nil {
			return providerSessionTarget{}, "", generationErr
		}
		value := providerSessionTarget{SessionID: item.SessionID, ProviderRowKey: item.ProviderRowKey, PID: item.PID, IsTask: item.IsTask}
		if resolved == nil {
			resolved = &value
			generation = rowGeneration
		}
		// A session-scoped target names the session, so the live row is the one
		// the operation must address: a non-live sibling must not hide it.
		if rowGeneration != "" && live == nil {
			live = &value
			liveGeneration = rowGeneration
		}
	}
	if live != nil {
		return *live, liveGeneration, nil
	}
	if resolved == nil {
		return providerSessionTarget{}, "", fmt.Errorf("%w: provider session row was not found", errInvalidRequest)
	}
	return *resolved, generation, nil
}

// requireLiveGeneration revalidates that the requested generation still names the
// live process behind the target.
//
// The comparison is the whole point of the operation-sensitive rule: a mutation
// that addresses a live process must prove which process it reaches, so a stale or
// unverified generation is rejected before any argv exists.
func (p *provider) requireLiveGeneration(ctx context.Context, requested *target) (providerSessionTarget, error) {
	resolved, generation, err := p.workspaceAuthority(ctx, requested)
	if err != nil {
		return providerSessionTarget{}, err
	}
	if generation == "" {
		return providerSessionTarget{}, fmt.Errorf("%w: target liveness is unverified", errInvalidRequest)
	}
	if generation != requested.ExpectedGeneration {
		return providerSessionTarget{}, fmt.Errorf("%w: target generation changed", errInvalidRequest)
	}
	return resolved, nil
}

// requireNonLiveRecord revalidates that the exact durable record still exists.
//
// A non-live operation addresses a record, not a process, so it must not demand a
// generation. It still requires the record to exist and to be unambiguous, because
// a selector that matches nothing or matches twice cannot be executed safely.
func (p *provider) requireNonLiveRecord(ctx context.Context, requested *target) (providerSessionTarget, error) {
	resolved, _, err := p.workspaceAuthority(ctx, requested)
	if err != nil {
		return providerSessionTarget{}, err
	}
	return resolved, nil
}

// sessionAuthority resolves one provider session from the session registry.
//
// Resume addresses a session by handle, and the registry is the only read that
// lists every persisted session. The workspace list is a different view: it
// reports rows this host can see and only rows that still have a workspace
// record, so a session that exists in the registry but has no workspace row is
// absent from it. Reading the workspace list here therefore reported a session
// the provider can resume as not found.
//
// The registry is also the read the history query uses, so a row the operator saw
// in history and a handle the operator typed resolve against one source and mint
// one resource ID.
//
// Liveness is deliberately not decided here. The provider revalidates it twice in
// the resume path and refuses a live target itself, so a cluster-side rejection
// would duplicate that authority and would refuse exactly the sessions resume
// exists for.
func (p *provider) sessionAuthority(ctx context.Context, requested *target) (providerSessionTarget, error) {
	key, err := validateSessionTarget(requested)
	if err != nil {
		return providerSessionTarget{}, err
	}
	var entries []historyEntry
	if err := runJSON(ctx, p.runner, []string{"project", "list_sessions", "--json"}, maxHistoryBytes, &entries); err != nil {
		return providerSessionTarget{}, err
	}
	var resolved *providerSessionTarget
	for _, entry := range entries {
		candidate, keyErr := historySessionKey(entry.SessionID)
		if keyErr != nil {
			return providerSessionTarget{}, keyErr
		}
		if candidate != key {
			continue
		}
		if resolved != nil {
			return providerSessionTarget{}, fmt.Errorf("%w: provider resource key matches duplicate session records", errInvalidRequest)
		}
		value := providerSessionTarget{SessionID: entry.SessionID}
		resolved = &value
	}
	if resolved == nil {
		return providerSessionTarget{}, fmt.Errorf("%w: provider session row was not found", errInvalidRequest)
	}
	return *resolved, nil
}

// requireResumableRecord revalidates that the record resume addresses still exists.
//
// Resume addresses a provider session by handle, so the authority is the provider
// session registry rather than the workspace list. The two reads are not
// interchangeable: the workspace list reports only rows this host can see and only
// rows that still have a workspace record, while a persisted session with no
// workspace row is absent from it even though the provider can resume it. The
// registry is also the read the history query uses, so a row the operator saw in
// history and a handle the operator typed resolve against one source.
//
// A session-scoped key therefore reads the registry and does not decide liveness.
// The provider revalidates liveness twice in the resume path and refuses a live
// target itself, so a cluster-side rejection would duplicate that authority and
// would refuse exactly the sessions resume exists for.
//
// A row-scoped key names one workspace row, which the registry cannot describe, so
// it keeps the workspace read and its live rejection.
func (p *provider) requireResumableRecord(ctx context.Context, requested *target) (providerSessionTarget, error) {
	key, err := validateSessionTarget(requested)
	if err != nil {
		return providerSessionTarget{}, err
	}
	if sessionScopedKey(key) {
		return p.sessionAuthority(ctx, requested)
	}
	resolved, generation, err := p.workspaceAuthority(ctx, requested)
	if err != nil {
		return providerSessionTarget{}, err
	}
	if generation != "" {
		return providerSessionTarget{}, fmt.Errorf("%w: target session is already live", errInvalidRequest)
	}
	return resolved, nil
}

// requireLaunchProfile revalidates the frozen launch profile identity and revision.
//
// A launch profile is not a live process, so its authority is the profile identity
// plus the revision the Endpoint negotiated. A different key or a stale revision is
// rejected, because the profile is what decides which provider command runs.
func (p *provider) requireLaunchProfile(requested *target) error {
	if requested == nil || requested.ResourceKind != resourceLaunchProfile {
		return fmt.Errorf("%w: launch profile target is required", errInvalidRequest)
	}
	if requested.ProviderResourceKey != launchProfileKey {
		return fmt.Errorf("%w: unknown launch profile", errInvalidRequest)
	}
	if requested.ExpectedGeneration != launchProfileRevision {
		return fmt.Errorf("%w: launch profile revision changed", errInvalidRequest)
	}
	return nil
}
