package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// The current-source vocabulary this provider can actually produce.
//
// The Cluster declares a closed four-value vocabulary, and this executable is an
// independent module that cannot import it, so the values are repeated here. Only two
// of them are reachable from this provider, and that is deliberate rather than an
// omission: the registry is answered by one `models list --json` read, which reports
// the workspace-level selection. A project override is a different read (`--project`),
// so this provider never observes one and must not claim it did. Reporting a source it
// did not read would be a guess dressed as an observation.
const (
	// modelRegistrySourceWorkspace means the list marked one entry as selected, so the
	// machine has a declared default.
	modelRegistrySourceWorkspace = "workspace"
	// modelRegistrySourceUnknown means no entry was marked selected. The operator's
	// rule is that every entry reporting false means nothing is selected, so the model
	// in use is unknown rather than absent-and-therefore-defaulted.
	modelRegistrySourceUnknown = "unknown"
)

// modelRegistryEntry is one provider registry record.
//
// ID and Name are different values, and the difference is load-bearing. The provider
// derives the identifier from the display name, so `models add "My Model"` produces
// id `my-model` with name `My Model`. The provider's own selection file stores the
// identifier, so a reader that keys on the display name cannot tell which entry a
// launch would use. Both fields are decoded here for that reason; the session catalog
// decodes only the name because it addresses a session rather than the machine.
//
// Selected is the provider's own answer to "is this the model in use". It is read from
// the same document as the entries, so the menu and the current marker cannot disagree:
// a second read would be a second source of truth for one fact, and the two reads do
// disagree in practice. Measured on this host, after the selected model was disabled,
// `models list --json` reported every entry as `selected:false` while `models current
// --json` reported `selection_invalid` for the same state. The list is the truthful
// answer, because a disabled model is not what a launch would use.
//
// Enabled is a pointer because the provider omits the field when the entry is enabled
// and writes `false` only when it is disabled. A plain bool would read an absent field
// as disabled and hide every usable model.
type modelRegistryEntry struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Protocol string `json:"protocol"`
	Enabled  *bool  `json:"enabled"`
	Selected bool   `json:"selected"`
}

// modelRegistryFact is one entry as the Cluster contract receives it.
//
// ProviderID travels beside the provider resource key because the Cluster compares it
// against the provider's own selection. The key is the Cluster's addressing identity;
// the identifier is the provider's, and only the provider knows which one it selected.
type modelRegistryFact struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	ProviderID          string `json:"provider_id"`
	DisplayName         string `json:"display_name"`
	Available           bool   `json:"available"`
	UnavailableReason   string `json:"unavailable_reason,omitempty"`
}

// modelRegistryResult is the whole Endpoint-scoped model observation.
//
// ProjectOverrides is deliberately absent. The provider can answer "which model does
// this one folder resolve to" through `models list --project PATH`, but no command
// enumerates the folders that carry an override, so filling the field would require
// reading the provider's private selection file. Reporting nothing is honest; reporting
// a guess would let the operator believe a project override does not exist.
type modelRegistryResult struct {
	Entries           []modelRegistryFact `json:"entries"`
	CurrentProviderID string              `json:"current_provider_id,omitempty"`
	CurrentSource     string              `json:"current_source"`
	ObservedAtMS      int64               `json:"observed_at_ms"`
	Truncated         bool                `json:"truncated"`
}

// modelRegistry answers the Endpoint-scoped model read.
//
// It takes no target, because a registry describes the machine rather than one
// session. A caller that supplies one is refused instead of having it ignored: an
// ignored target would let a session-scoped caller believe the answer was about its
// session.
//
// The whole answer comes from one provider call. The entries and the current marker
// are the same document, so they cannot disagree, and the read costs one provider
// invocation instead of two.
func (p *provider) modelRegistry(ctx context.Context, requested *target, raw json.RawMessage) (modelRegistryResult, error) {
	if requested != nil {
		return modelRegistryResult{}, fmt.Errorf("%w: model.registry does not accept a target", errInvalidRequest)
	}
	var payload struct{}
	if err := decodeStrict(raw, &payload); err != nil {
		return modelRegistryResult{}, fmt.Errorf("%w: model.registry payload: %v", errInvalidRequest, err)
	}
	var entries []modelRegistryEntry
	if err := runJSON(ctx, p.runner, []string{"models", "list", "--json"}, maxModelBytes, &entries); err != nil {
		return modelRegistryResult{}, err
	}
	if entries == nil || len(entries) > maxModelProfiles {
		return modelRegistryResult{}, errorsNew("invalid or oversized model registry")
	}
	result := modelRegistryResult{
		Entries:       make([]modelRegistryFact, 0, len(entries)),
		CurrentSource: modelRegistrySourceUnknown,
		ObservedAtMS:  p.now().UnixMilli(),
		Truncated:     false,
	}
	seen := make(map[string]struct{}, len(entries))
	for _, entry := range entries {
		id := strings.TrimSpace(entry.ID)
		if id == "" {
			return modelRegistryResult{}, errorsNew("model registry entry id is required")
		}
		key := modelProviderKeyPrefix + id
		if len(key) > maxProviderKeyLength {
			return modelRegistryResult{}, errorsNew("model provider resource key exceeds contract limit")
		}
		if _, exists := seen[key]; exists {
			return modelRegistryResult{}, errorsNew("model registry contains duplicate provider resource key")
		}
		seen[key] = struct{}{}
		if entry.Selected {
			// Two selected entries would make "the model in use" have no single
			// answer. Picking one would be a guess, and reporting both would leave
			// the operator unable to tell which one a launch would use, so the
			// inconsistent registry is refused instead of being resolved silently.
			if result.CurrentProviderID != "" {
				return modelRegistryResult{}, errorsNew("model registry marks more than one entry as selected")
			}
			result.CurrentProviderID = id
			result.CurrentSource = modelRegistrySourceWorkspace
		}
		available, reason := modelAvailability(modelEntry{Name: entry.Name, Protocol: entry.Protocol, Enabled: entry.Enabled})
		result.Entries = append(result.Entries, modelRegistryFact{
			ResourceKind:        resourceModelProfile,
			ProviderResourceKey: key,
			ProviderID:          id,
			DisplayName:         modelRegistryDisplayName(entry, id),
			Available:           available,
			UnavailableReason:   reason,
		})
	}
	return result, nil
}

// modelRegistryDisplayName reports the name an operator should read.
//
// The provider requires a name when an entry is added, so an empty one means the
// registry was edited by hand. Falling back to the identifier keeps the entry visible
// instead of failing the whole read: the Cluster contract requires a non-empty display
// name, and taking the menu away because one record is malformed would hide every
// usable model. The identifier is the entry's real identity, so it is a truthful
// label rather than a placeholder.
func modelRegistryDisplayName(entry modelRegistryEntry, id string) string {
	if name := strings.TrimSpace(entry.Name); name != "" {
		return boundedString(name, 256)
	}
	return boundedString(id, 256)
}
