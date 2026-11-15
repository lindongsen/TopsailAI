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

// requireResumableRecord revalidates that the record exists and is not live.
//
// Resume exists for the case where the process is gone, so a live row is rejected:
// resuming a session that is already running would start a second process for one
// record, which is a different operation from the one the operator asked for.
func (p *provider) requireResumableRecord(ctx context.Context, requested *target) (providerSessionTarget, error) {
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
