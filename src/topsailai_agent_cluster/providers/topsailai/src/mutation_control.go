package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
)

// controlActionsEnvironment names the Provider-local control action catalog file.
//
// The catalog is administrative configuration read once at startup. It is the only
// source of ctl. actions, so the action surface is an operational decision rather
// than a compiled-in list, and a remote payload can never supply a command template
// or an executable path.
const controlActionsEnvironment = "AGENT_CLUSTER_TOPSAILAI_CONTROL_ACTIONS"

// Placeholders a configured command template may use.
//
// A template is a token array, never a shell string: substitution happens per token
// and the result is executed directly, so no shell parses it and no operator text
// can become a command.
const (
	controlSessionPlaceholder = "{session}"
	controlPayloadPlaceholder = "{payload}"
)

// controlAction is one configured provider control action.
type controlAction struct {
	// Name is the action name after the ctl. prefix.
	Name string
	// Command is the provider argv template.
	Command []string
	// PayloadSessionField names a payload field that must carry the provider
	// session key, or is empty when the action does not need the selector.
	PayloadSessionField string
	// PayloadConstants are payload fields this action fixes itself.
	PayloadConstants map[string]string
	// PayloadSchema is the JSON Schema document describing the action payload,
	// or an empty string when the action takes no documented parameters. It is
	// forwarded verbatim into the advertised capability, so the interactive
	// prompt follows the same document the Provider validates against.
	PayloadSchema string
}

// controlCatalog is the Provider-local set of enabled ctl. actions.
//
// An empty catalog advertises no action and refuses every ctl. operation, which is
// the fail-closed default: this executable cannot be talked into running an action
// nobody configured.
type controlCatalog struct {
	actions map[string]controlAction
	order   []string
}

// controlActionFile is the on-disk catalog document shape.
type controlActionFile struct {
	Actions []controlActionEntry `json:"actions"`
}

// controlActionEntry is one configured action before validation.
type controlActionEntry struct {
	Name                string            `json:"name"`
	Command             []string          `json:"command"`
	PayloadSessionField string            `json:"payload_session_field"`
	PayloadConstants    map[string]string `json:"payload_constants"`
	PayloadSchema       json.RawMessage   `json:"payload_schema"`
}

// loadControlCatalog reads the catalog named by the process environment.
//
// A missing variable is not an error: it means no catalog was configured, so the
// ctl. family is disabled. A configured but unreadable or invalid file is an error,
// because silently disabling a configured capability would look like an operator
// choice instead of a broken deployment.
func loadControlCatalog(environment []string) (controlCatalog, error) {
	path := environmentValue(environment, controlActionsEnvironment)
	if path == "" {
		return controlCatalog{}, nil
	}
	document, err := os.ReadFile(path)
	if err != nil {
		return controlCatalog{}, fmt.Errorf("read control action catalog %q: %w", path, err)
	}
	catalog, err := parseControlCatalog(document)
	if err != nil {
		return controlCatalog{}, fmt.Errorf("parse control action catalog %q: %w", path, err)
	}
	return catalog, nil
}

// parseControlCatalog parses and validates one catalog document.
//
// Every entry is validated here, so a mistake fails at load time instead of at the
// first command. An empty action list is accepted and disables the family, because
// a security default must fail closed.
func parseControlCatalog(document []byte) (controlCatalog, error) {
	var file controlActionFile
	decoder := json.NewDecoder(bytes.NewReader(stripCatalogComments(document)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&file); err != nil {
		return controlCatalog{}, fmt.Errorf("decode catalog: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return controlCatalog{}, errors.New("catalog contains an extra JSON document")
		}
		return controlCatalog{}, fmt.Errorf("decode catalog trailer: %w", err)
	}
	catalog := controlCatalog{actions: make(map[string]controlAction, len(file.Actions))}
	for _, entry := range file.Actions {
		action, err := validateControlAction(entry)
		if err != nil {
			return controlCatalog{}, err
		}
		if _, exists := catalog.actions[action.Name]; exists {
			return controlCatalog{}, fmt.Errorf("duplicate control action %q", action.Name)
		}
		catalog.actions[action.Name] = action
		catalog.order = append(catalog.order, action.Name)
	}
	return catalog, nil
}

// stripCatalogComments removes whole-line '#' comments from a catalog document.
//
// The catalog is operator-facing configuration, so it carries an explanation of
// every rule beside the entries that follow it. Only a line whose first non-space
// character is '#' is removed: a trailing comment is deliberately not supported,
// because deciding whether a '#' sits inside a JSON string would require parsing
// the document, and a wrong guess would silently change a value.
func stripCatalogComments(document []byte) []byte {
	lines := bytes.Split(document, []byte("\n"))
	kept := make([][]byte, 0, len(lines))
	for _, line := range lines {
		if bytes.HasPrefix(bytes.TrimSpace(line), []byte("#")) {
			continue
		}
		kept = append(kept, line)
	}
	return bytes.Join(kept, []byte("\n"))
}

// validateControlAction validates one catalog entry.
func validateControlAction(entry controlActionEntry) (controlAction, error) {
	name := strings.TrimSpace(entry.Name)
	if name == "" {
		return controlAction{}, errors.New("control action name is required")
	}
	if strings.ContainsAny(name, " \t\r\n") {
		return controlAction{}, fmt.Errorf("control action name %q must not contain whitespace", name)
	}
	if len(entry.Command) == 0 {
		return controlAction{}, fmt.Errorf("control action %q requires a command", name)
	}
	if err := validateControlCommand(entry.Command); err != nil {
		return controlAction{}, fmt.Errorf("control action %q: %w", name, err)
	}
	if entry.PayloadSessionField != "" && strings.ContainsAny(entry.PayloadSessionField, " \t\r\n") {
		return controlAction{}, fmt.Errorf("control action %q payload_session_field must not contain whitespace", name)
	}
	schema, err := normalizeControlPayloadSchema(entry.PayloadSchema)
	if err != nil {
		return controlAction{}, fmt.Errorf("control action %q: %w", name, err)
	}
	return controlAction{
		Name:                name,
		Command:             append([]string(nil), entry.Command...),
		PayloadSessionField: entry.PayloadSessionField,
		PayloadConstants:    entry.PayloadConstants,
		PayloadSchema:       schema,
	}, nil
}

// normalizeControlPayloadSchema validates a payload schema and returns it as a
// compact JSON string.
//
// An absent schema is allowed and yields an empty string, so a minimal catalog
// still works and the interactive surface falls back to its generic parameter
// prompt. A present schema must be a JSON object, because the prompt walks named
// fields and a scalar or array document would describe nothing it can ask for.
func normalizeControlPayloadSchema(raw json.RawMessage) (string, error) {
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 || bytes.Equal(trimmed, []byte("null")) {
		return "", nil
	}
	var document map[string]json.RawMessage
	if err := json.Unmarshal(trimmed, &document); err != nil {
		return "", fmt.Errorf("payload_schema must be a JSON object: %w", err)
	}
	if document == nil {
		return "", fmt.Errorf("payload_schema must be a JSON object")
	}
	compact, err := json.Marshal(document)
	if err != nil {
		return "", fmt.Errorf("encode payload_schema: %w", err)
	}
	return string(compact), nil
}

// validateControlCommand rejects a template that cannot be expanded safely.
//
// Each placeholder may appear at most once per token, and an unknown or
// unterminated placeholder is rejected, so a typo cannot silently become a literal
// argument that the provider would read as a selector.
func validateControlCommand(command []string) error {
	for _, token := range command {
		if token == "" {
			return errors.New("command token must not be empty")
		}
		if strings.Count(token, controlSessionPlaceholder) > 1 {
			return fmt.Errorf("command token %q repeats %s", token, controlSessionPlaceholder)
		}
		if strings.Count(token, controlPayloadPlaceholder) > 1 {
			return fmt.Errorf("command token %q repeats %s", token, controlPayloadPlaceholder)
		}
		if err := validateControlPlaceholders(token); err != nil {
			return err
		}
	}
	return nil
}

// validateControlPlaceholders rejects an unknown or unterminated placeholder.
func validateControlPlaceholders(token string) error {
	remainder := token
	for {
		start := strings.Index(remainder, "{")
		if start < 0 {
			return nil
		}
		end := strings.Index(remainder[start:], "}")
		if end < 0 {
			return fmt.Errorf("command token %q has an unterminated placeholder", token)
		}
		placeholder := remainder[start : start+end+1]
		if placeholder != controlSessionPlaceholder && placeholder != controlPayloadPlaceholder {
			return fmt.Errorf("command token %q uses unknown placeholder %q", token, placeholder)
		}
		remainder = remainder[start+end+1:]
	}
}

// contracts returns the advertised control actions in catalog order.
func (c controlCatalog) contracts() []namedContract {
	contracts := make([]namedContract, 0, len(c.order))
	for _, name := range c.order {
		contracts = append(contracts, namedContract{
			Name:          controlOperationPrefix + name,
			Version:       operationVersion,
			TargetKinds:   []string{"session"},
			SafetyClass:   "mutating",
			PayloadSchema: c.actions[name].PayloadSchema,
		})
	}
	return contracts
}

// args builds the provider argv for one ctl. operation.
//
// The action is matched against the catalog before any argv exists, so an action
// nobody configured never reaches the provider even if a caller submits it
// directly instead of going through capability admission.
//
// sessionID is the provider session identifier, not the opaque mapping key: the
// provider CLI addresses a session by its own identifier, and the mapping key is a
// Cluster-side spelling that never leaves the Endpoint.
func (c controlCatalog) args(operation, sessionID string, payload json.RawMessage) ([]string, error) {
	if !strings.HasPrefix(operation, controlOperationPrefix) {
		return nil, fmt.Errorf("%w: provider control operation is required", errInvalidRequest)
	}
	// A control action addresses one session, so a row that reports no session
	// identifier cannot be controlled. Refusing here keeps the unattributed row
	// listable without letting an empty selector reach the provider.
	if strings.TrimSpace(sessionID) == "" {
		return nil, fmt.Errorf("%w: control operation %q requires a session identifier, and this row reports none", errInvalidRequest, operation)
	}
	name := strings.TrimPrefix(operation, controlOperationPrefix)
	action, ok := c.actions[name]
	if !ok {
		return nil, fmt.Errorf("%w: provider control action %q is not configured", errUnsupported, name)
	}
	encoded, err := controlPayload(payload)
	if err != nil {
		return nil, err
	}
	encoded, err = controlConstantPayload(action, encoded)
	if err != nil {
		return nil, err
	}
	encoded, err = controlTargetPayload(action, sessionID, encoded)
	if err != nil {
		return nil, err
	}
	return controlCommand(action, sessionID, encoded)
}

// controlPayload normalizes the operator payload into one JSON object.
//
// The provider forwards the payload verbatim as the action arguments, so a
// non-object payload would either be rejected by the provider or be reinterpreted
// as something the operator did not write.
func controlPayload(payload json.RawMessage) ([]byte, error) {
	if len(payload) == 0 {
		return []byte("{}"), nil
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("%w: control payload must be a JSON object", errInvalidRequest)
	}
	if envelope == nil {
		return nil, fmt.Errorf("%w: control payload must be a JSON object", errInvalidRequest)
	}
	encoded, err := json.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("encode control payload: %w", err)
	}
	return encoded, nil
}

// controlConstantPayload merges the payload fields an action fixes itself.
//
// A supplied value that disagrees with the constant is rejected rather than
// overwritten: the catalog is the authorization surface, so a caller must not reach
// a different instruction through an entry that advertises one.
func controlConstantPayload(action controlAction, payload []byte) ([]byte, error) {
	if len(action.PayloadConstants) == 0 {
		return payload, nil
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("%w: control payload must be a JSON object", errInvalidRequest)
	}
	if envelope == nil {
		envelope = make(map[string]json.RawMessage, len(action.PayloadConstants))
	}
	for field, constant := range action.PayloadConstants {
		if supplied, ok := envelope[field]; ok {
			var value string
			if err := json.Unmarshal(supplied, &value); err != nil {
				return nil, fmt.Errorf("%w: %s must be a string", errInvalidRequest, field)
			}
			if value != constant {
				return nil, fmt.Errorf("%w: %s %q does not match the %q this action fixes", errInvalidRequest, field, value, constant)
			}
		}
		encodedConstant, err := json.Marshal(constant)
		if err != nil {
			return nil, fmt.Errorf("encode %s: %w", field, err)
		}
		envelope[field] = encodedConstant
	}
	encoded, err := json.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("encode control payload: %w", err)
	}
	return encoded, nil
}

// controlTargetPayload injects the target-derived selector an action needs.
//
// A supplied value that disagrees with the revalidated target is rejected instead
// of being overwritten, because silently replacing it would read a different
// session than the operator named, and silently honouring it would bypass the
// target the Provider just revalidated.
func controlTargetPayload(action controlAction, sessionID string, payload []byte) ([]byte, error) {
	if action.PayloadSessionField == "" {
		return payload, nil
	}
	if sessionID == "" {
		return nil, fmt.Errorf("%w: %s requires a resolved provider session", errInvalidRequest, action.Name)
	}
	var envelope map[string]json.RawMessage
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return nil, fmt.Errorf("%w: control payload must be a JSON object", errInvalidRequest)
	}
	if envelope == nil {
		envelope = make(map[string]json.RawMessage, 1)
	}
	if supplied, ok := envelope[action.PayloadSessionField]; ok {
		var value string
		if err := json.Unmarshal(supplied, &value); err != nil {
			return nil, fmt.Errorf("%w: %s must be a string", errInvalidRequest, action.PayloadSessionField)
		}
		if value != sessionID {
			return nil, fmt.Errorf("%w: %s does not match the selected session", errInvalidRequest, action.PayloadSessionField)
		}
	}
	encodedKey, err := json.Marshal(sessionID)
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

// controlCommand expands the configured argv template.
//
// Substitution is per token, so a placeholder never splits into several arguments
// and an operator-supplied payload never becomes a token boundary.
func controlCommand(action controlAction, sessionID string, payload []byte) ([]string, error) {
	args := make([]string, 0, len(action.Command))
	for _, token := range action.Command {
		expanded := token
		if strings.Contains(expanded, controlSessionPlaceholder) {
			if sessionID == "" {
				return nil, fmt.Errorf("%w: %s requires a resolved provider session", errInvalidRequest, action.Name)
			}
			expanded = strings.ReplaceAll(expanded, controlSessionPlaceholder, sessionID)
		}
		if strings.Contains(expanded, controlPayloadPlaceholder) {
			expanded = strings.ReplaceAll(expanded, controlPayloadPlaceholder, string(payload))
		}
		args = append(args, expanded)
	}
	return args, nil
}
