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
// because an empty answer there is an error rather than a skip.
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
	hint := "; empty skips"
	if field.Required {
		hint = "; empty is rejected"
	}
	return strings.Join(parts, " · ") + hint
}

// ctlFieldValue encodes one answer for a field.
//
// An enumerated field accepts only a documented value and is always sent as a
// string, so a value such as continue is never reinterpreted as a boolean. A
// string field is sent verbatim. Any other field keeps the guided typing rules, so
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
	if field.Type == "string" {
		return json.Marshal(trimmed)
	}
	return ctlParameterValue(trimmed)
}

// promptCtlSchemaParameters asks for each documented field of one action.
//
// The operator answers one field at a time, so the interactive surface never asks
// for a JSON document. An empty answer omits an optional field, which lets the
// provider apply its own default, and is rejected for a required field so a
// missing value fails before submission instead of at the provider.
func promptCtlSchemaParameters(parent context.Context, action string, fields []ctlField, lines <-chan lineReadResult, out io.Writer) (json.RawMessage, error) {
	payload := make(map[string]json.RawMessage, len(fields))
	for _, field := range fields {
		if _, err := fmt.Fprintln(out, ctlFieldPrompt(field)); err != nil {
			return nil, err
		}
		markRecoverablePromptFailure(parent)
		answer, err := readStartAnswer(parent, lines, "ctl."+field.Name+"> ")
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
