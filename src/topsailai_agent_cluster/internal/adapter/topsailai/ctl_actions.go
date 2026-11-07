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

// controlActionCapabilities returns one capability per reviewed control action.
func controlActionCapabilities() []protocol.Capability {
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
// The action is matched against the reviewed list before any argv is built, so an
// unreviewed action never reaches the provider even if a caller submits it
// directly instead of going through capability admission.
func controlActionArgs(operation, providerKey string, payload []byte) ([]string, error) {
	if !strings.HasPrefix(operation, security.ProviderControlPrefix) {
		return nil, errControlActionUnreviewed
	}
	action := strings.TrimPrefix(operation, security.ProviderControlPrefix)
	if _, ok := controlActionPermission(action); !ok {
		return nil, fmt.Errorf("%w: %q", errControlActionUnreviewed, action)
	}
	args, err := controlActionPayload(payload)
	if err != nil {
		return nil, err
	}
	return []string{"runtime", "control", action, "-s", providerKey, "-a", string(args), "--json"}, nil
}
