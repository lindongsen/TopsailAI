package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

// modelSetPayload is the frozen agent.model.set payload.
//
// It carries the provider-private model key after the Endpoint resolved the Cluster
// opaque model profile ID, so no Cluster identity reaches this executable. The shape
// is identical to modelSelectPayload on purpose: both operations name one provider
// model entry, and a second spelling of the same value would be a second thing to
// keep in step.
type modelSetPayload struct {
	ProviderResourceKey string `json:"provider_resource_key"`
}

// Provider error codes for the two refusals agent.model.set can produce.
//
// They are coded rather than plain because the Cluster maps each one to a different
// remedy: an identifier the registry does not contain is a caller mistake, while an
// entry that exists but cannot be launched with is a different choice to make. A
// plain error would arrive as "provider_error" and tell the operator neither.
const (
	modelSetUnknownCode     = "model_not_found"
	modelSetUnavailableCode = "model_unavailable"
)

// decodeModelSetID reads the provider model identifier out of one payload.
//
// The identifier is the provider's own `id`, not its display name, because the
// provider's selection file is keyed by the identifier. `models add "My Model"`
// produces id `my-model` with name `My Model`, so a reader that keyed on the name
// could not name the entry a launch would use.
func decodeModelSetID(payload json.RawMessage) (string, error) {
	var value modelSetPayload
	if err := decodeStrict(payload, &value); err != nil {
		return "", fmt.Errorf("%w: decode agent.model.set payload: %v", errInvalidRequest, err)
	}
	if !strings.HasPrefix(value.ProviderResourceKey, modelProviderKeyPrefix) {
		return "", fmt.Errorf("%w: model profile key is not a provider model key", errInvalidRequest)
	}
	id := strings.TrimPrefix(value.ProviderResourceKey, modelProviderKeyPrefix)
	if id == "" {
		return "", fmt.Errorf("%w: model profile key is empty", errInvalidRequest)
	}
	return id, nil
}

// modelSetArgs builds the provider argv for one environment model selection.
//
// The provider exposes the selection as a first-class command, so the argv invokes it
// directly instead of going through the operator-configured control action catalog. A
// first-class capability must not depend on someone having also written a catalog
// entry.
//
// No --project flag is passed. This operation declares the machine-wide default, which
// is the value a launch uses when no project override applies. A project override is a
// different scope with a different subject, and accepting a folder here would let one
// operation mean two things depending on an optional field.
func modelSetArgs(id string) []string {
	return []string{"models", "set", id, "--json"}
}

// requireSelectableModel refuses a model the provider would not launch with.
//
// The check runs in the same execution path that builds the argv, before the write, so
// a refusal proves nothing was changed. That ordering is load-bearing rather than
// tidy: the provider reports its own refusal on stdout with a non-zero exit, and a
// non-zero exit whose stdout is not a JSON document is classified as an unknown
// effect. Reporting "unknown" for a selection that provably did not happen would send
// the operator to investigate a write that never occurred, and unknown is also the
// value that forbids automatic retry.
//
// The provider's own validation still runs inside `models set`, so this is a preflight
// rather than a replacement. A model that becomes unavailable between the two calls is
// refused by the provider, and that residual case is reported as an unknown effect
// because the provider's refusal text is not machine-readable.
//
// The availability rule is not copied here. It is the same modelAvailability decision
// the registry read uses, so the menu an operator saw and the refusal they receive
// cannot disagree about which entries are usable.
func (p *provider) requireSelectableModel(ctx context.Context, id string) error {
	var entries []modelRegistryEntry
	if err := runJSON(ctx, p.runner, []string{"models", "list", "--json"}, maxModelBytes, &entries); err != nil {
		return err
	}
	for _, entry := range entries {
		if strings.TrimSpace(entry.ID) != id {
			continue
		}
		if available, reason := modelAvailability(modelEntry{Name: entry.Name, Protocol: entry.Protocol, Enabled: entry.Enabled}); !available {
			return codedError{code: modelSetUnavailableCode, message: fmt.Sprintf("model %q cannot be selected: %s", id, reason)}
		}
		return nil
	}
	return codedError{code: modelSetUnknownCode, message: fmt.Sprintf("model %q is not in the provider registry", id)}
}
