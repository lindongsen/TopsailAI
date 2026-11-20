package providercli

import (
	"encoding/json"
	"fmt"
	"unicode/utf8"
)

// ModelSetPayload is the closed Provider CLI v1 input for agent.model.set.
//
// It carries the provider-private model key after the Endpoint resolved the Cluster
// opaque model profile ID, so no Cluster identity reaches the provider executable.
// The shape is deliberately identical to ModelSelectPayload: both operations name one
// provider model entry, and a second spelling of the same value would be a second
// thing to keep in step.
type ModelSetPayload struct {
	ProviderResourceKey string `json:"provider_resource_key"`
}

// DecodeModelSetPayload decodes and validates exactly one typed model-set payload.
func DecodeModelSetPayload(data []byte) (ModelSetPayload, error) {
	if !utf8.Valid(data) {
		return ModelSetPayload{}, fmt.Errorf("agent.model.set payload must be valid UTF-8")
	}
	var payload ModelSetPayload
	if err := decodeStrict(data, &payload); err != nil {
		return ModelSetPayload{}, fmt.Errorf("decode agent.model.set payload: %w", err)
	}
	if err := payload.Validate(); err != nil {
		return ModelSetPayload{}, err
	}
	return payload, nil
}

// Validate rejects a missing or malformed Provider-private model key.
func (p ModelSetPayload) Validate() error {
	return validateProviderResourceKey("model provider_resource_key", p.ProviderResourceKey, true)
}

// MarshalModelSetPayload validates and encodes one typed payload.
func MarshalModelSetPayload(payload ModelSetPayload) (json.RawMessage, error) {
	if err := payload.Validate(); err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encode agent.model.set payload: %w", err)
	}
	return json.RawMessage(encoded), nil
}
