package providercli

import (
	"encoding/json"
	"fmt"
	"strings"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// AgentStartPayload is the closed Provider CLI v1 input for agent.start.
type AgentStartPayload struct {
	Folder string `json:"folder"`
	Task   string `json:"task,omitempty"`
}

// DecodeAgentStartPayload decodes and validates exactly one typed agent.start payload.
func DecodeAgentStartPayload(data []byte) (AgentStartPayload, error) {
	if !utf8.Valid(data) {
		return AgentStartPayload{}, fmt.Errorf("agent.start payload must be valid UTF-8")
	}
	var fields map[string]json.RawMessage
	if err := decodeStrict(data, &fields); err != nil {
		return AgentStartPayload{}, fmt.Errorf("decode agent.start payload fields: %w", err)
	}
	if task, present := fields["task"]; present {
		if string(task) == "null" {
			return AgentStartPayload{}, fmt.Errorf("agent.start task must not be null")
		}
		var value string
		if err := json.Unmarshal(task, &value); err != nil {
			return AgentStartPayload{}, fmt.Errorf("decode agent.start task: %w", err)
		}
		if value == "" {
			return AgentStartPayload{}, fmt.Errorf("agent.start task must not be empty")
		}
	}
	var payload AgentStartPayload
	if err := decodeStrict(data, &payload); err != nil {
		return AgentStartPayload{}, fmt.Errorf("decode agent.start payload: %w", err)
	}
	if err := payload.Validate(); err != nil {
		return AgentStartPayload{}, err
	}
	return payload, nil
}

// Validate rejects launch input that cannot be safely passed as literal Provider arguments.
func (p AgentStartPayload) Validate() error {
	if p.Folder == "" {
		return fmt.Errorf("agent.start folder is required")
	}
	if err := protocol.ValidateFolder(p.Folder); err != nil {
		return fmt.Errorf("invalid agent.start folder: %w", err)
	}
	if p.Task == "" {
		return nil
	}
	if !utf8.ValidString(p.Task) || strings.ContainsRune(p.Task, 0) || strings.TrimSpace(p.Task) == "" || len(p.Task) > protocol.MaxInitialTaskBytes {
		return fmt.Errorf("agent.start task must be nonblank UTF-8 without NUL and at most %d bytes", protocol.MaxInitialTaskBytes)
	}
	return nil
}

// MarshalAgentStartPayload validates and encodes one typed payload.
func MarshalAgentStartPayload(payload AgentStartPayload) (json.RawMessage, error) {
	if err := payload.Validate(); err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encode agent.start payload: %w", err)
	}
	return json.RawMessage(encoded), nil
}
