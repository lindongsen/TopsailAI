package topsailai

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// providerControlAction is one reviewed provider control action.
//
// The provider exposes a live handler registry, but Describe runs once per
// command, so querying the registry there would spawn a provider subprocess on
// every command. The reviewed list is therefore declared here and a test asserts
// it still matches the live registry, so drift is caught instead of silently
// advertising an action the provider no longer serves.
type providerControlAction struct {
	// Name is the provider action name, appended to the ctl. operation prefix.
	Name string
	// Permission is the operator scope required to invoke the action.
	Permission string
}

// providerControlActions is the reviewed set of provider control actions.
//
// Actions that return conversation content require read_output rather than
// control: an operator allowed to interrupt a session is not thereby allowed to
// read its messages.
var providerControlActions = []providerControlAction{
	{Name: "call_instruction", Permission: security.ScopeControl},
	{Name: "clear_interrupt", Permission: security.ScopeControl},
	{Name: "clear_pause", Permission: security.ScopeControl},
	{Name: "get_runtime_messages", Permission: security.ScopeReadOutput},
	{Name: "get_session_messages", Permission: security.ScopeReadOutput},
	{Name: "hard_interrupt", Permission: security.ScopeControl},
	{Name: "heartbeat", Permission: security.ScopeControl},
	{Name: "llm_control", Permission: security.ScopeControl},
	{Name: "pause", Permission: security.ScopeControl},
	{Name: "soft_interrupt", Permission: security.ScopeControl},
}

// errControlActionUnreviewed reports that a ctl. operation names an action the
// adapter does not serve. It is a definite failure: nothing was sent.
var errControlActionUnreviewed = errors.New("provider control action is not reviewed")

// controlActionCapabilities returns one capability per enabled control action.
//
// A nil set means no control action file was configured, so the reviewed default
// set stays in force and an existing deployment keeps working unchanged. A non-nil
// set is authoritative: an action it omits is not advertised, and because the
// Endpoint rejects an operation absent from the advertised capabilities, omitting
// an action also makes it unreachable. An empty set therefore disables the whole
// ctl. family, which is the fail-closed default once an operator configures it.
func controlActionCapabilities(set *ControlActionSet) []protocol.Capability {
	if set == nil {
		capabilities := make([]protocol.Capability, 0, len(providerControlActions))
		for _, action := range providerControlActions {
			capabilities = append(capabilities, protocol.Capability{
				Name:               security.ProviderControlPrefix + action.Name,
				Version:            "v1",
				TargetKinds:        []string{"session"},
				SafetyClass:        "mutating",
				RequiredPermission: action.Permission,
			})
		}
		return capabilities
	}
	actions := set.Actions()
	capabilities := make([]protocol.Capability, 0, len(actions))
	for _, action := range actions {
		capabilities = append(capabilities, protocol.Capability{
			Name:               security.ProviderControlPrefix + action.Name,
			Version:            "v1",
			TargetKinds:        []string{"session"},
			PayloadSchema:      action.PayloadSchema,
			SafetyClass:        "mutating",
			RequiredPermission: action.Permission,
		})
	}
	return capabilities
}

// controlActionPermission returns the reviewed permission for an action.
func controlActionPermission(name string) (string, bool) {
	for _, action := range providerControlActions {
		if action.Name == name {
			return action.Permission, true
		}
	}
	return "", false
}

// controlActionPayload validates the operator payload of one ctl. operation.
//
// The payload must be a JSON object, because the provider forwards it verbatim as
// the action arguments. A non-object payload would either be rejected by the
// provider or, worse, be reinterpreted as something the operator did not write.
func controlActionPayload(payload []byte) ([]byte, error) {
	if len(payload) == 0 {
		return []byte("{}"), nil
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("control payload must be a JSON object: %w", err)
	}
	if envelope == nil {
		return nil, errors.New("control payload must be a JSON object")
	}
	encoded, err := json.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("encode control payload: %w", err)
	}
	return encoded, nil
}

// controlActionArgs builds the provider argv for one ctl. operation.
//
// The action is matched against the enabled set before any argv is built, so an
// action the operator disabled never reaches the provider even if a caller submits
// it directly instead of going through capability admission. A nil set keeps the
// reviewed default set in force, matching controlActionCapabilities.
func controlActionArgs(set *ControlActionSet, operation, providerKey string, payload []byte) ([]string, error) {
	if !strings.HasPrefix(operation, security.ProviderControlPrefix) {
		return nil, errControlActionUnreviewed
	}
	action := strings.TrimPrefix(operation, security.ProviderControlPrefix)
	if !controlActionEnabled(set, action) {
		return nil, fmt.Errorf("%w: %q", errControlActionUnreviewed, action)
	}
	args, err := controlActionPayload(payload)
	if err != nil {
		return nil, err
	}
	args, err = controlActionTargetPayload(action, providerKey, args)
	if err != nil {
		return nil, err
	}
	return []string{"runtime", "control", action, "-s", providerKey, "-a", string(args), "--json"}, nil
}

// controlActionTargetPayload injects the target-derived selector an action needs.
//
// get_session_messages requires a provider session_id, and the Endpoint already
// holds it: the resource mapping stores the provider session_id as the provider
// key, which is the same value every -s selector uses. Deriving it from the
// revalidated target therefore needs no provider change and no operator input.
//
// A supplied value that disagrees with the target is rejected instead of being
// overwritten, because silently replacing it would read a different session than
// the operator named, and silently honouring it would bypass the target the
// Endpoint just revalidated.
func controlActionTargetPayload(action, providerKey string, payload []byte) ([]byte, error) {
	if action != "get_session_messages" {
		return payload, nil
	}
	if providerKey == "" {
		return nil, errors.New("get_session_messages requires a resolved provider session")
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("control payload must be a JSON object: %w", err)
	}
	if envelope == nil {
		envelope = make(map[string]json.RawMessage, 1)
	}
	if supplied, ok := envelope["session_id"]; ok {
		var value string
		if err := json.Unmarshal(supplied, &value); err != nil {
			return nil, fmt.Errorf("session_id must be a string: %w", err)
		}
		if value != providerKey {
			return nil, fmt.Errorf("session_id %q does not match the selected session", value)
		}
	}
	encodedKey, err := json.Marshal(providerKey)
	if err != nil {
		return nil, fmt.Errorf("encode session_id: %w", err)
	}
	envelope["session_id"] = encodedKey
	encoded, err := json.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("encode control payload: %w", err)
	}
	return encoded, nil
}

// controlActionEnabled reports whether an action may be invoked.
//
// A nil set means no control action file was configured, so the reviewed default
// set applies. A non-nil set is authoritative and an omitted action is disabled.
func controlActionEnabled(set *ControlActionSet, name string) bool {
	if set == nil {
		_, ok := controlActionPermission(name)
		return ok
	}
	_, ok := set.Get(name)
	return ok
}
