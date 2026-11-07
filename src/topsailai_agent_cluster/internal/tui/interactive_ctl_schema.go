package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"

	"topsailai_agent_cluster/internal/protocol"
)

// ctlField is one operator-facing parameter of a control action.
//
// The field list comes from the payload schema the Endpoint advertises, so the
// prompt asks for the parameters that action actually documents instead of a
// generic key=value line. The client never invents a field: an action whose
// schema is empty keeps the generic prompt.
type ctlField struct {
	// Name is the payload key.
	Name string
	// Type is the documented JSON type, used to decide how an answer is encoded.
	Type string
	// Required reports whether the action rejects an omitted value.
	Required bool
	// Enum lists the accepted values, so the prompt can refuse anything else
	// before the command is submitted.
	Enum []string
	// Default is the documented default, echoed so the operator can see what an
	// empty answer means.
	Default json.RawMessage
}

// ctlSchemaDocument is the subset of JSON Schema the prompt understands.
type ctlSchemaDocument struct {
	Properties map[string]ctlSchemaProperty `json:"properties"`
	Required   []string                     `json:"required"`
}

// ctlSchemaProperty is one documented property.
type ctlSchemaProperty struct {
	Type    string          `json:"type"`
	Enum    []string        `json:"enum"`
	Default json.RawMessage `json:"default"`
}

// ctlActionSchema returns the advertised payload schema of one action.
//
// The schema is read from the Endpoint's own capability descriptor, so the prompt
// follows the Endpoint rather than a client-side table and a newly documented
// action needs no client change. An action without a schema returns an empty
// string, which keeps the generic parameter prompt in force.
func ctlActionSchema(descriptor protocol.CapabilityDescriptor, action string) string {
	for _, capability := range descriptor.Capabilities {
		if capability.Name == ctlOperationPrefix+action {
			return capability.PayloadSchema
		}
	}
	return ""
}

// ctlSchemaFields parses a payload schema into the ordered fields to prompt for.
//
// Fields are sorted by name because a JSON object does not preserve member order
// once decoded, and a prompt whose order changes between runs would be confusing.
// A schema with no properties yields no fields, so the caller falls back to the
// generic prompt instead of asking nothing and sending an empty object for an
// action that does take arguments.
func ctlSchemaFields(schema string) ([]ctlField, error) {
	if strings.TrimSpace(schema) == "" {
		return nil, nil
	}
	var document ctlSchemaDocument
	if err := json.Unmarshal([]byte(schema), &document); err != nil {
		return nil, fmt.Errorf("payload schema is not a JSON object: %w", err)
	}
	if len(document.Properties) == 0 {
		return nil, nil
	}
	required := make(map[string]bool, len(document.Required))
	for _, name := range document.Required {
		required[name] = true
	}
	names := make([]string, 0, len(document.Properties))
	for name := range document.Properties {
		names = append(names, name)
	}
	sort.Strings(names)
	fields := make([]ctlField, 0, len(names))
	for _, name := range names {
		property := document.Properties[name]
		fields = append(fields, ctlField{
			Name:     name,
			Type:     property.Type,
			Required: required[name],
			Enum:     property.Enum,
			Default:  property.Default,
		})
	}
	return fields, nil
}

// ctlFieldPrompt renders one field description for the operator.
//
// The description states the type, whether the value is required, the accepted
// values and the documented default, so the operator can answer without reading
// the provider documentation. The trailing hint differs for a required field,
// because an empty answer there is an error rather than a skip. A structured
// field states the shape it expects, because an operator cannot guess that an
// array is written as space-separated words.
func ctlFieldPrompt(field ctlField) string {
	parts := []string{field.Name}
	if field.Type != "" {
		parts = append(parts, field.Type)
	}
	if field.Required {
		parts = append(parts, "required")
	} else {
		parts = append(parts, "optional")
	}
	if len(field.Enum) > 0 {
		parts = append(parts, "one of: "+strings.Join(field.Enum, ", "))
	}
	if len(field.Default) > 0 {
		parts = append(parts, "default: "+string(field.Default))
	}
	if shape := ctlFieldShape(field); shape != "" {
		parts = append(parts, shape)
	}
	hint := "; empty skips"
	if field.Required {
		hint = "; empty is rejected"
	}
	return strings.Join(parts, " · ") + hint
}

// ctlFieldShape describes how a structured field is written on one line.
//
// The interactive surface reads one line per field, so a list and a map both need
// a compact spelling. An empty string means the field is a scalar and needs no
// explanation.
func ctlFieldShape(field ctlField) string {
	switch field.Type {
	case "array":
		return `space-separated, quote an item to keep spaces`
	case "object":
		return `key=value pairs, space-separated`
	}
	return ""
}

// ctlFieldValue encodes one answer for a field.
//
// An enumerated field accepts only a documented value and is always sent as a
// string, so a value such as continue is never reinterpreted as a boolean. A
// string field is sent verbatim. An array and an object are encoded as real JSON
// structures, because the provider validates their type and would reject a string
// that merely looks like a list. Any other field keeps the guided typing rules, so
// a numeric field accepts 300 as a number.
func ctlFieldValue(field ctlField, answer string) (json.RawMessage, error) {
	trimmed := strings.TrimSpace(answer)
	if len(field.Enum) > 0 {
		for _, allowed := range field.Enum {
			if trimmed == allowed {
				return json.Marshal(allowed)
			}
		}
		return nil, fmt.Errorf("%q is not one of %s", trimmed, strings.Join(field.Enum, ", "))
	}
	switch field.Type {
	case "string":
		return json.Marshal(trimmed)
	case "array":
		return ctlArrayValue(trimmed)
	case "object":
		return ctlObjectValue(trimmed)
	}
	return ctlParameterValue(trimmed)
}

// ctlArrayValue encodes a space-separated answer as a JSON array of strings.
//
// A double-quoted item keeps its spaces, so an argument that contains a space is
// still expressible on one line. An unquoted item is taken literally, which means
// an operator never has to escape anything for the common case.
func ctlArrayValue(answer string) (json.RawMessage, error) {
	items, err := ctlSplitQuoted(answer)
	if err != nil {
		return nil, err
	}
	encoded, err := json.Marshal(items)
	if err != nil {
		return nil, fmt.Errorf("encode array value: %w", err)
	}
	return encoded, nil
}

// ctlSplitQuoted splits an answer on whitespace, honouring double quotes.
//
// A quoted run keeps its inner spaces and loses the quotes. An unterminated quote
// is rejected rather than silently swallowing the rest of the line, because the
// operator would otherwise submit a value they did not intend.
func ctlSplitQuoted(answer string) ([]string, error) {
	items := make([]string, 0, 4)
	var current strings.Builder
	inQuotes := false
	started := false
	for _, character := range answer {
		switch {
		case character == '"':
			inQuotes = !inQuotes
			started = true
		case character == ' ' || character == '\t':
			if inQuotes {
				current.WriteRune(character)
				continue
			}
			if started {
				items = append(items, current.String())
				current.Reset()
				started = false
			}
		default:
			current.WriteRune(character)
			started = true
		}
	}
	if inQuotes {
		return nil, fmt.Errorf("unterminated quote in %q", answer)
	}
	if started {
		items = append(items, current.String())
	}
	return items, nil
}

// ctlObjectValue encodes space-separated key=value pairs as a JSON object.
//
// Values are strings, matching the provider's own interactive wizard, so a value
// that looks numeric is not silently retyped. A pair without '=' is rejected
// instead of being guessed, and a repeated key is rejected because the later value
// would otherwise overwrite the earlier one without telling the operator.
func ctlObjectValue(answer string) (json.RawMessage, error) {
	pairs, err := ctlSplitQuoted(answer)
	if err != nil {
		return nil, err
	}
	object := make(map[string]string, len(pairs))
	for _, pair := range pairs {
		key, value, found := strings.Cut(pair, "=")
		key = strings.TrimSpace(key)
		if !found || key == "" {
			return nil, fmt.Errorf("%q must be key=value", pair)
		}
		if _, exists := object[key]; exists {
			return nil, fmt.Errorf("%q is given more than once", key)
		}
		object[key] = value
	}
	encoded, err := json.Marshal(object)
	if err != nil {
		return nil, fmt.Errorf("encode object value: %w", err)
	}
	return encoded, nil
}

// promptCtlSchemaParameters asks for each documented field of one action.
//
// The operator answers one field at a time, so the interactive surface never asks
// for a JSON document. An empty answer omits an optional field, which lets the
// provider apply its own default, and is rejected for a required field so a
// missing value fails before submission instead of at the provider.
//
// An enumerated field is rendered as a numbered menu instead of a free-text
// prompt, because the accepted values are a closed set and the provider rejects
// anything else. Offering the values as a menu means the operator cannot type an
// unsupported value at all, which is the point of advertising the enum.
func promptCtlSchemaParameters(parent context.Context, action string, fields []ctlField, lines <-chan lineReadResult, out io.Writer) (json.RawMessage, error) {
	payload := make(map[string]json.RawMessage, len(fields))
	for _, field := range fields {
		if _, err := fmt.Fprintln(out, ctlFieldPrompt(field)); err != nil {
			return nil, err
		}
		answer, err := promptCtlFieldAnswer(parent, field, lines, out)
		if err != nil {
			return nil, err
		}
		if strings.TrimSpace(answer) == "" {
			if field.Required {
				return nil, fmt.Errorf("%s is required for %s", field.Name, sanitizeInlineText(action))
			}
			continue
		}
		value, err := ctlFieldValue(field, answer)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", field.Name, err)
		}
		payload[field.Name] = value
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("encode control parameters: %w", err)
	}
	return encoded, nil
}

// promptCtlFieldAnswer reads one field answer, rendering a menu for an enum.
//
// An enumerated field lists its accepted values with numbers, so the operator
// selects one instead of typing it. A number selects that entry and the literal
// value is also accepted, because an operator who already knows the value should
// not have to count menu rows. An empty answer still means "skip" or "rejected",
// so the caller keeps deciding that.
func promptCtlFieldAnswer(parent context.Context, field ctlField, lines <-chan lineReadResult, out io.Writer) (string, error) {
	if len(field.Enum) == 0 {
		markRecoverablePromptFailure(parent)
		return readStartAnswer(parent, lines, "ctl."+field.Name+"> ")
	}
	for index, allowed := range field.Enum {
		if _, err := fmt.Fprintf(out, "  %d. %s\n", index+1, sanitizeInlineText(allowed)); err != nil {
			return "", err
		}
	}
	markRecoverablePromptFailure(parent)
	answer, err := readStartAnswer(parent, lines, "ctl."+field.Name+"> ")
	if err != nil {
		return "", err
	}
	trimmed := strings.TrimSpace(answer)
	if trimmed == "" {
		return "", nil
	}
	for index, allowed := range field.Enum {
		if trimmed == fmt.Sprintf("%d", index+1) {
			return allowed, nil
		}
	}
	return trimmed, nil
}

// promptCtlActionParameters collects the parameters of one action.
//
// A documented schema drives a per-field prompt. An action without a schema keeps
// the generic key=value prompt, so an Endpoint that advertises no schema still
// works and the interactive surface never regresses to asking for JSON.
func promptCtlActionParameters(parent context.Context, api InteractiveAPI, state *interactiveState, action string, lines <-chan lineReadResult, out io.Writer) (json.RawMessage, error) {
	ctx, cancel := commandContext(parent)
	defer cancel()
	descriptor, err := api.GetCapabilities(ctx, state.EndpointID)
	if err != nil {
		return nil, fmt.Errorf("capability query failed for endpoint %q: %w", state.EndpointID, err)
	}
	fields, err := ctlSchemaFields(ctlActionSchema(descriptor, action))
	if err != nil {
		return nil, fmt.Errorf("control action %q: %w", sanitizeInlineText(action), err)
	}
	if len(fields) == 0 {
		return promptCtlParameters(parent, action, lines, out)
	}
	return promptCtlSchemaParameters(parent, action, fields, lines, out)
}
