package main

import (
	"encoding/json"
	"fmt"
	"strings"
)

// mutationInvocation carries everything one argv mapping needs.
//
// It is a value, not a request: the authority decision has already happened, so the
// mapping cannot re-read a target and cannot disagree with the row that was
// validated.
type mutationInvocation struct {
	// Operation is the standard operation name being mapped.
	Operation string
	// Generation is the provider generation the target was validated against.
	Generation string
	// Resolved is the exact workspace row the authority check accepted.
	Resolved providerSessionTarget
	// Payload is the typed operation payload from the request.
	Payload json.RawMessage
}

// agentStartPayload is the frozen agent.start payload.
//
// The launch-profile identity and revision stay in the common request target, so
// this document carries only provider-neutral launch input.
type agentStartPayload struct {
	Folder string `json:"folder"`
	Task   string `json:"task"`
}

// modelSelectPayload is the frozen agent.model.select payload.
//
// It carries the provider-private model key after the Endpoint resolved the Cluster
// opaque model profile ID, so no Cluster identity reaches this executable.
type modelSelectPayload struct {
	ProviderResourceKey string `json:"provider_resource_key"`
}

// runtimeMessagePayload is the provider-neutral message payload.
//
// Both spellings are accepted because the Cluster contract has carried both, and a
// message that arrives under either name must reach the provider unchanged.
type runtimeMessagePayload struct {
	Text    string `json:"text"`
	Message string `json:"message"`
}

// mutationArgs maps one validated operation onto its fixed provider argv.
//
// Every branch returns an argv array, never a command string, so no shell parses
// the result and no operator-supplied text can become a command. The argv shapes
// match the Cluster adapter exactly, because two spellings of one provider
// invocation would be two behaviours to keep in step.
func mutationArgs(invocation mutationInvocation) ([]string, error) {
	// A row may report no session identifier, but no provider operation can act
	// on one: every argv below passes the identifier as the provider's session
	// selector, and an empty selector would either be rejected by the provider or,
	// worse, be read as "no filter" and address a different session. Refusing here
	// keeps the unattributed row listable without making it operable.
	if invocation.Operation != operationAgentStart && strings.TrimSpace(invocation.Resolved.SessionID) == "" {
		return nil, fmt.Errorf("%w: operation %q requires a session identifier, and this row reports none", errInvalidRequest, invocation.Operation)
	}
	switch invocation.Operation {
	case operationMessageSend:
		message, err := runtimeMessage(invocation.Payload)
		if err != nil {
			return nil, err
		}
		// The provider parser classifies a separate argv element, so a message that
		// is one dash-leading token would be consumed as an option. The assignment
		// form keeps the value attached to its flag without adding a shell.
		return []string{"runtime", "send", "-s", invocation.Resolved.SessionID, "-m=" + message, "--json"}, nil
	case operationContextInject:
		message, err := runtimeMessage(invocation.Payload)
		if err != nil {
			return nil, err
		}
		return []string{"runtime", "btw", "-s", invocation.Resolved.SessionID, "-m=" + message, "--json"}, nil
	case operationAgentStop:
		if invocation.Generation == "" {
			return nil, fmt.Errorf("%w: generation is required for stop", errInvalidRequest)
		}
		return []string{"workspace", "kill", invocation.Resolved.SessionID, "-g", invocation.Generation, "--json"}, nil
	case operationAgentDriveStart:
		// The provider selects the unique live row for the session and rejects an
		// ambiguous target itself. No PID is passed: a cluster generation is not a
		// provider PID, and inventing one would address a different process.
		return []string{"workspace", "driver", "start", "-s", invocation.Resolved.SessionID, "--json"}, nil
	case operationAgentDriveStop:
		return []string{"workspace", "driver", "stop", "-s", invocation.Resolved.SessionID, "--json"}, nil
	case operationAgentResume:
		return []string{"workspace", "resume", "-s", invocation.Resolved.SessionID, "--background", "--json"}, nil
	case operationWorkspaceClean:
		if invocation.Resolved.SessionID == "" || invocation.Resolved.PID <= 0 {
			return nil, fmt.Errorf("%w: workspace clean requires an exact session ID and PID", errInvalidRequest)
		}
		return []string{"workspace", "clean", "-s", invocation.Resolved.SessionID, "-p", fmt.Sprint(invocation.Resolved.PID), "--yes", "--json"}, nil
	case operationAgentStart:
		return agentStartArgs(invocation.Payload)
	case operationAgentModelSelect:
		return modelSelectArgs(invocation.Resolved.SessionID, invocation.Payload)
	case operationExecutionInterrupt:
		return interruptArgs(invocation.Resolved.SessionID, invocation.Payload)
	default:
		return nil, fmt.Errorf("%w: provider operation %q is not implemented", errUnsupported, invocation.Operation)
	}
}

// agentStartArgs builds the provider argv for one launch.
func agentStartArgs(payload json.RawMessage) ([]string, error) {
	var value agentStartPayload
	if err := decodeStrict(payload, &value); err != nil {
		return nil, fmt.Errorf("%w: decode agent.start payload: %v", errInvalidRequest, err)
	}
	if strings.TrimSpace(value.Folder) == "" {
		return nil, fmt.Errorf("%w: agent.start folder is required", errInvalidRequest)
	}
	args := []string{"workspace", "agent", value.Folder, "--background", "--json", "--non-interactive"}
	if value.Task != "" {
		args = append(args, "--task="+value.Task)
	}
	return args, nil
}

// modelSelectArgs builds the provider argv for one model selection.
//
// The provider exposes model selection as a registered instruction, so the argv
// invokes that instruction directly instead of going through the operator-configured
// control action catalog. A first-class capability must not depend on someone having
// also written a catalog entry.
//
// sessionID is the provider session identifier, not the opaque mapping key: the
// provider CLI addresses a session by its own identifier, and the mapping key is a
// Cluster-side spelling that never leaves the Endpoint.
func modelSelectArgs(sessionID string, payload json.RawMessage) ([]string, error) {
	var value modelSelectPayload
	if err := decodeStrict(payload, &value); err != nil {
		return nil, fmt.Errorf("%w: decode agent.model.select payload: %v", errInvalidRequest, err)
	}
	if !strings.HasPrefix(value.ProviderResourceKey, modelProviderKeyPrefix) {
		return nil, fmt.Errorf("%w: model profile key is not a provider model key", errInvalidRequest)
	}
	name := strings.TrimPrefix(value.ProviderResourceKey, modelProviderKeyPrefix)
	if name == "" {
		return nil, fmt.Errorf("%w: model profile key is empty", errInvalidRequest)
	}
	return modelInstructionArgs(sessionID, "agent.models", []string{name})
}

// runtimeMessage extracts the message text from one provider-neutral payload.
func runtimeMessage(payload json.RawMessage) (string, error) {
	var value runtimeMessagePayload
	if err := decodeJSONDocument(payload, &value, false); err != nil {
		return "", fmt.Errorf("%w: decode runtime payload: %v", errInvalidRequest, err)
	}
	if value.Text != "" {
		return value.Text, nil
	}
	if value.Message != "" {
		return value.Message, nil
	}
	return "", fmt.Errorf("%w: runtime payload requires text or message", errInvalidRequest)
}

// interruptPayload is the frozen execution.interrupt payload.
//
// The action names the provider instruction to invoke and the message is the
// optional text a soft interrupt carries. Both fields are provider-neutral: the
// Cluster contract defines the action vocabulary, so this executable maps a
// standard action onto a provider instruction rather than inventing one.
type interruptPayload struct {
	Action  string `json:"action"`
	Message string `json:"message"`
}

// interruptArgs builds the provider argv for one turn interruption.
//
// The provider exposes interruption as a registered control instruction, so the
// argv invokes that instruction directly instead of going through the
// operator-configured control action catalog. A first-class capability must not
// depend on someone having also written a catalog entry, which is the same reason
// model selection does not consult the catalog.
//
// The action is validated against the closed Cluster vocabulary before any argv
// exists, so an unknown action fails closed instead of reaching the provider as an
// arbitrary instruction name. The message is only accepted for a soft interrupt,
// because a hard interrupt has no text to carry and silently dropping one would
// report a delivery the operator did not ask for.
//
// sessionID is the provider session identifier, not the opaque mapping key: the
// provider CLI addresses a session by its own identifier, and the mapping key is a
// Cluster-side spelling that never leaves the Endpoint.
func interruptArgs(sessionID string, payload json.RawMessage) ([]string, error) {
	var value interruptPayload
	if err := decodeStrict(payload, &value); err != nil {
		return nil, fmt.Errorf("%w: decode execution.interrupt payload: %v", errInvalidRequest, err)
	}
	switch value.Action {
	case interruptActionSoft:
		// A soft interrupt carries an optional message. An empty message has
		// nothing to deliver, so it produces the empty document rather than a
		// message field with no text.
		document := []byte("{}")
		if value.Message != "" {
			encoded, err := json.Marshal(map[string]string{"message": value.Message})
			if err != nil {
				return nil, fmt.Errorf("encode soft interrupt payload: %w", err)
			}
			document = encoded
		}
		return []string{"runtime", "control", interruptActionSoft, "-s", sessionID, "-a", string(document), "--json"}, nil
	case interruptActionHard:
		if value.Message != "" {
			return nil, fmt.Errorf("%w: hard_interrupt does not accept a message", errInvalidRequest)
		}
		return []string{"runtime", "control", interruptActionHard, "-s", sessionID, "-a", "{}", "--json"}, nil
	default:
		return nil, fmt.Errorf("%w: interrupt action %q is not supported", errInvalidRequest, value.Action)
	}
}
