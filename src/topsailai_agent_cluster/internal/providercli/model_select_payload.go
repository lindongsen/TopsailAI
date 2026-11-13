package providercli

import (
	"encoding/json"
	"fmt"
	"unicode/utf8"
)

// ModelSelectPayload is the closed Provider CLI v1 input for agent.model.select.
type ModelSelectPayload struct {
	ProviderResourceKey string `json:"provider_resource_key"`
}

// DecodeModelSelectPayload decodes and validates exactly one typed model-select payload.
func DecodeModelSelectPayload(data []byte) (ModelSelectPayload, error) {
	if !utf8.Valid(data) {
		return ModelSelectPayload{}, fmt.Errorf("agent.model.select payload must be valid UTF-8")
	}
	var payload ModelSelectPayload
	if err := decodeStrict(data, &payload); err != nil {
		return ModelSelectPayload{}, fmt.Errorf("decode agent.model.select payload: %w", err)
	}
	if err := payload.Validate(); err != nil {
		return ModelSelectPayload{}, err
	}
	return payload, nil
}

// Validate rejects a missing or malformed Provider-private model key.
func (p ModelSelectPayload) Validate() error {
	if err := validateIdentifier("model provider_resource_key", p.ProviderResourceKey, true); err != nil {
		return err
	}
	return nil
}

// MarshalModelSelectPayload validates and encodes one typed payload.
func MarshalModelSelectPayload(payload ModelSelectPayload) (json.RawMessage, error) {
	if err := payload.Validate(); err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encode agent.model.select payload: %w", err)
	}
	return json.RawMessage(encoded), nil
}
