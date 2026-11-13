package topsailai

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// modelProviderKeyPrefix namespaces a model profile inside the shared resource
// mapping table.
//
// The mapping table is keyed by (adapter_id, provider_key) and holds every
// Endpoint resource this adapter owns, including session keys. A model profile
// therefore cannot use a bare provider name as its key: a model whose name
// happened to equal a session key would resolve to that session's mapping and
// select the wrong thing. The prefix keeps the two namespaces disjoint, so a
// profile identifier can never resolve to a session and vice versa.
const modelProviderKeyPrefix = "model:"

// errModelProfileUnknown marks a profile identifier this Endpoint never minted, or
// one that resolves to a resource of another kind.
var errModelProfileUnknown = errors.New("unknown model profile")

// modelProviderName resolves one opaque profile identifier to the provider's own
// selection key.
//
// The provider selects a model by name, not by its registry id, so the name is
// what the mapping stores. An identifier this Endpoint never minted is rejected
// here, before any provider call, so an unknown identifier can never reach the
// provider as a guess.
func (a *Adapter) modelProviderName(ctx context.Context, profileID string) (string, error) {
	if a.mapper == nil {
		return "", errors.New("durable resource mapper is required")
	}
	mapping, err := a.mapper.LookupResourceID(ctx, profileID)
	if err != nil {
		return "", fmt.Errorf("%w: %v", errModelProfileUnknown, err)
	}
	if !strings.HasPrefix(mapping.ProviderKey, modelProviderKeyPrefix) {
		return "", errModelProfileUnknown
	}
	name := strings.TrimPrefix(mapping.ProviderKey, modelProviderKeyPrefix)
	if name == "" {
		return "", errModelProfileUnknown
	}
	return name, nil
}

// modelSelectArgs builds the provider argv for one model selection.
//
// The provider exposes model selection as a registered instruction, so the
// adapter invokes that instruction directly instead of going through the
// operator-configured control action catalog. A standard operation must not
// depend on an operator having configured a catalog entry: the catalog exists for
// provider-private actions, and a first-class capability that only worked when
// someone had also written a catalog entry would be a capability the Endpoint
// silently does not have.
func modelSelectArgs(providerKey, modelName string) ([]string, error) {
	return callInstructionArgs(providerKey, "agent.models", []string{modelName})
}

// callInstructionArgs builds the provider argv for one registered instruction.
//
// Every instruction this adapter invokes goes through the same provider surface,
// so the argv shape is built in one place. A second copy would let the two call
// sites drift in flag order or in the payload envelope, and the drift would only
// appear as a provider parse failure at runtime.
func callInstructionArgs(providerKey, instruction string, args []string) ([]string, error) {
	payload, err := json.Marshal(map[string]any{
		"instruction": instruction,
		"args":        args,
	})
	if err != nil {
		return nil, err
	}
	return []string{"runtime", "control", "call_instruction", "-s", providerKey, "-a", string(payload), "--json"}, nil
}

// selectModel performs one model selection for a session.
//
// It returns the provider argv so the shared Execute tail performs the invocation
// and decodes the provider's own outcome document. Reusing that tail keeps the
// effect-certainty rules identical to every other operation: a rejected or
// unconfirmed provider answer is never flattened into a definite failure.
//
// The returned code distinguishes a malformed payload from an unknown profile.
// Reporting both as an unknown profile would send the operator looking for a
// missing profile when the request itself was wrong.
func (a *Adapter) selectModel(ctx context.Context, intent protocol.ImmutableIntent, providerKey string) ([]string, string, error) {
	request, err := protocol.ValidateModelSelectPayload(intent.Payload)
	if err != nil {
		return nil, "invalid_payload", err
	}
	modelName, err := a.modelProviderName(ctx, request.ModelProfileID)
	if err != nil {
		return nil, protocol.ModelSelectUnknownProfile, err
	}
	args, err := modelSelectArgs(providerKey, modelName)
	if err != nil {
		return nil, "invalid_payload", err
	}
	return args, "", nil
}
