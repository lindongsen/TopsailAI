package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// The closed current-source vocabulary the wire contract declares.
//
// The values are repeated here because this executable is an independent module and
// cannot import the Cluster's protocol package. They are named rather than written as
// bare literals so the four answers stay distinguishable at every call site: a
// workspace default, a project override, a provider-inherited default, and a source
// that was never observed. The last one is not a negative, and collapsing it into one
// of the others would tell the operator the environment uses nothing when the truth
// is that nothing was read.
const (
	modelRegistrySourceWorkspace = "workspace"
	modelRegistrySourceProject   = "project"
	modelRegistrySourceInherited = "inherited"
	modelRegistrySourceUnknown   = "unknown"
)

// modelRegistryEntry is one provider registry record.
//
// ID and Name are different values, and the difference is load-bearing. The provider
// derives the identifier from the display name, so `models add "My Model"` produces
// id `my-model` with name `My Model`. The provider's own selection file stores the
// identifier, and `models current` reports it as `model_id`, so a reader that keys on
// the display name cannot tell which entry a launch would use. Both fields are decoded
// here for that reason; the session catalog decodes only the name because it addresses
// a session rather than the machine.
//
// Enabled is a pointer because the provider omits the field when the entry is enabled
// and writes `false` only when it is disabled. A plain bool would read an absent field
// as disabled and hide every usable model.
type modelRegistryEntry struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Protocol string `json:"protocol"`
	Enabled  *bool  `json:"enabled"`
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
// ProjectOverrides is deliberately absent. The provider's public surface can answer
// "which model does this one folder resolve to" but cannot enumerate the folders that
// carry an override, so filling the field would require reading the provider's private
// selection file. Reporting nothing is honest; reporting a guess would let the operator
// believe a project override does not exist.
type modelRegistryResult struct {
	Entries           []modelRegistryFact `json:"entries"`
	CurrentProviderID string              `json:"current_provider_id,omitempty"`
	CurrentSource     string              `json:"current_source"`
	ObservedAtMS      int64               `json:"observed_at_ms"`
	Truncated         bool                `json:"truncated"`
}

// modelSelection is the provider's answer to `models current --json`.
type modelSelection struct {
	Source  string `json:"source"`
	ModelID string `json:"model_id"`
}

// modelRegistry answers the Endpoint-scoped model read.
//
// It takes no target, because a registry describes the machine rather than one
// session. A caller that supplies one is refused instead of having it ignored: an
// ignored target would let a session-scoped caller believe the answer was about its
// session.
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
	selection := p.modelSelection(ctx)
	result := modelRegistryResult{
		Entries:           make([]modelRegistryFact, 0, len(entries)),
		CurrentProviderID: strings.TrimSpace(selection.ModelID),
		CurrentSource:     modelRegistrySource(selection.Source),
		ObservedAtMS:      p.now().UnixMilli(),
		Truncated:         false,
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

// modelSelection reads the provider's effective selection.
//
// A failed read is reported as an empty selection rather than as an error, and the
// caller then reports the source as unknown. The registry is a menu: taking it away
// because one observation was unavailable would leave the operator with nothing, and
// the honest answer is that the Endpoint did not observe which entry a launch would
// use. This is the same rule the session catalog applies to its own current-model
// observation.
func (p *provider) modelSelection(ctx context.Context) modelSelection {
	var selection modelSelection
	if err := runJSON(ctx, p.runner, []string{"models", "current", "--json"}, maxModelBytes, &selection); err != nil {
		return modelSelection{}
	}
	return selection
}

// modelRegistrySource maps one provider source onto the closed Cluster vocabulary.
//
// An unrecognized value becomes unknown rather than being passed through. The Cluster
// validates the vocabulary, so forwarding a provider value it does not know would fail
// the whole read; mapping it keeps the menu and states honestly that the source was not
// understood.
func modelRegistrySource(source string) string {
	switch strings.TrimSpace(source) {
	case modelRegistrySourceWorkspace:
		return modelRegistrySourceWorkspace
	case modelRegistrySourceProject:
		return modelRegistrySourceProject
	case modelRegistrySourceInherited:
		return modelRegistrySourceInherited
	default:
		return modelRegistrySourceUnknown
	}
}
