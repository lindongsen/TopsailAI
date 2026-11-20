package providercli

import (
	"encoding/json"
	"fmt"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// DecodeProjectAddPayload decodes one strict project.add payload.
//
// The payload carries the folder the operator asked to register and an optional
// label. It never carries Cluster authority: the Endpoint decides whether the
// folder is inside its configured project root, and the Provider revalidates the
// same decision immediately before it writes its registry.
func DecodeProjectAddPayload(data []byte) (protocol.ProjectAddPayload, error) {
	if !utf8.Valid(data) {
		return protocol.ProjectAddPayload{}, fmt.Errorf("project.add payload must be valid UTF-8")
	}
	var payload protocol.ProjectAddPayload
	if err := decodeStrict(data, &payload); err != nil {
		return protocol.ProjectAddPayload{}, fmt.Errorf("decode project.add payload: %w", err)
	}
	if err := payload.Validate(); err != nil {
		return protocol.ProjectAddPayload{}, err
	}
	return payload, nil
}

// DecodeProjectRemovePayload decodes one strict project.remove payload.
//
// The payload is empty by contract: the target carries the identity, so a payload
// that names a folder would be a second selector for the same decision and could
// disagree with the target.
func DecodeProjectRemovePayload(data []byte) (protocol.ProjectRemovePayload, error) {
	var payload protocol.ProjectRemovePayload
	if err := decodeStrict(data, &payload); err != nil {
		return protocol.ProjectRemovePayload{}, fmt.Errorf("decode project.remove payload: %w", err)
	}
	var fields map[string]json.RawMessage
	if err := decodeStrict(data, &fields); err != nil {
		return protocol.ProjectRemovePayload{}, fmt.Errorf("decode project.remove payload fields: %w", err)
	}
	if len(fields) != 0 {
		return protocol.ProjectRemovePayload{}, fmt.Errorf("project.remove payload must be empty")
	}
	return payload, nil
}
