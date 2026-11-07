package topsailai

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// errControlActionUnreviewed reports that a ctl. operation names an action the
// Endpoint does not serve. It is a definite failure: nothing was sent.
var errControlActionUnreviewed = errors.New("provider control action is not configured")

// controlActionCapabilities returns one capability per enabled control action.
//
// The catalog is the only source of actions. A nil set means no control action
// file was configured, so no action is advertised and every ctl. operation is
// refused: the Endpoint cannot serve an action it was never told about. That is
// the fail-closed default, and it keeps the action surface a configuration
// decision instead of a compiled-in list.
func controlActionCapabilities(set *ControlActionSet) []protocol.Capability {
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
// The action is matched against the configured catalog before any argv is built,
// so an action the operator did not configure never reaches the provider even if a
// caller submits it directly instead of going through capability admission. The
// argv comes from the catalog's command template, so the provider invocation is a
// configuration decision rather than a compiled-in switch.
func controlActionArgs(set *ControlActionSet, operation, providerKey string, payload []byte) ([]string, error) {
	if !strings.HasPrefix(operation, security.ProviderControlPrefix) {
		return nil, errControlActionUnreviewed
	}
	name := strings.TrimPrefix(operation, security.ProviderControlPrefix)
	action, ok := set.Get(name)
	if !ok {
		return nil, fmt.Errorf("%w: %q", errControlActionUnreviewed, name)
	}
	encoded, err := controlActionPayload(payload)
	if err != nil {
		return nil, err
	}
	encoded, err = controlActionTargetPayload(action, providerKey, encoded)
	if err != nil {
		return nil, err
	}
	return controlActionCommand(action, providerKey, encoded)
}

// controlActionTargetPayload injects the target-derived selector an action needs.
//
// An action whose payload carries the provider session key declares the field in
// the catalog, so the Endpoint fills it from the revalidated target instead of
// asking the operator. A supplied value that disagrees with the target is rejected
// instead of being overwritten, because silently replacing it would read a
// different session than the operator named, and silently honouring it would
// bypass the target the Endpoint just revalidated.
func controlActionTargetPayload(action ControlAction, providerKey string, payload []byte) ([]byte, error) {
	if action.PayloadSessionField == "" {
		return payload, nil
	}
	if providerKey == "" {
		return nil, fmt.Errorf("%s requires a resolved provider session", action.Name)
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("control payload must be a JSON object: %w", err)
	}
	if envelope == nil {
		envelope = make(map[string]json.RawMessage, 1)
	}
	if supplied, ok := envelope[action.PayloadSessionField]; ok {
		var value string
		if err := json.Unmarshal(supplied, &value); err != nil {
			return nil, fmt.Errorf("%s must be a string: %w", action.PayloadSessionField, err)
		}
		if value != providerKey {
			return nil, fmt.Errorf("%s %q does not match the selected session", action.PayloadSessionField, value)
		}
	}
	encodedKey, err := json.Marshal(providerKey)
	if err != nil {
		return nil, fmt.Errorf("encode %s: %w", action.PayloadSessionField, err)
	}
	envelope[action.PayloadSessionField] = encodedKey
	encoded, err := json.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("encode control payload: %w", err)
	}
	return encoded, nil
}

// controlActionCommand expands the configured argv template.
//
// Substitution is per token, so a placeholder never splits into several arguments
// and an operator-supplied payload never becomes a token boundary. A template
// without a {session} placeholder is allowed, because an action may address the
// provider without a session selector.
func controlActionCommand(action ControlAction, providerKey string, payload []byte) ([]string, error) {
	args := make([]string, 0, len(action.Command))
	for _, token := range action.Command {
		expanded := token
		if strings.Contains(expanded, controlSessionPlaceholder) {
			if providerKey == "" {
				return nil, fmt.Errorf("%s requires a resolved provider session", action.Name)
			}
			expanded = strings.ReplaceAll(expanded, controlSessionPlaceholder, providerKey)
		}
		if strings.Contains(expanded, controlPayloadPlaceholder) {
			expanded = strings.ReplaceAll(expanded, controlPayloadPlaceholder, string(payload))
		}
		args = append(args, expanded)
	}
	return args, nil
}
