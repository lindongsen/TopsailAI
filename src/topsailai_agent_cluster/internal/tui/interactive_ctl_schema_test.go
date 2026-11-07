package tui

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// ctlSchemaCapability builds one advertised control capability carrying a
// payload schema, so a test can prove the prompt follows the descriptor.
func ctlSchemaCapability(action, schema string) protocol.Capability {
	return protocol.Capability{
		Name:               ctlOperationPrefix + action,
		Version:            "v1",
		TargetKinds:        []string{"session"},
		PayloadSchema:      schema,
		SafetyClass:        "mutating",
		RequiredPermission: "control",
	}
}

func TestCtlActionSchemaFollowsTheDescriptor(t *testing.T) {
	descriptor := protocol.CapabilityDescriptor{Capabilities: []protocol.Capability{
		ctlSchemaCapability("pause", `{"type":"object","properties":{"reason":{"type":"string"}}}`),
		ctlSchemaCapability("heartbeat", ""),
	}}
	if got := ctlActionSchema(descriptor, "pause"); !strings.Contains(got, `"reason"`) {
		t.Fatalf("pause schema = %q, want it to carry reason", got)
	}
	if got := ctlActionSchema(descriptor, "heartbeat"); got != "" {
		t.Fatalf("heartbeat schema = %q, want empty", got)
	}
	if got := ctlActionSchema(descriptor, "absent"); got != "" {
		t.Fatalf("absent schema = %q, want empty", got)
	}
}

func TestCtlSchemaFieldsParsesPropertiesInStableOrder(t *testing.T) {
	fields, err := ctlSchemaFields(`{"type":"object","properties":{
		"timeout_seconds":{"type":"number"},
		"reason":{"type":"string"},
		"default":{"type":"string","enum":["continue","interrupt"],"default":"continue"}
	},"required":["reason"]}`)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(fields) != 3 {
		t.Fatalf("fields = %d, want 3", len(fields))
	}
	// Sorted by name, because a decoded JSON object does not preserve member order
	// and a prompt whose order changes between runs would be confusing.
	want := []string{"default", "reason", "timeout_seconds"}
	for index, name := range want {
		if fields[index].Name != name {
			t.Fatalf("field %d = %q, want %q", index, fields[index].Name, name)
		}
	}
	if !fields[1].Required {
		t.Fatal("reason is not marked required")
	}
	if fields[0].Required {
		t.Fatal("default is marked required")
	}
	if len(fields[0].Enum) != 2 {
		t.Fatalf("default enum = %v, want two values", fields[0].Enum)
	}
	if string(fields[0].Default) != `"continue"` {
		t.Fatalf("default default = %s, want continue", fields[0].Default)
	}
}

func TestCtlSchemaFieldsEmptySchemaYieldsNoFields(t *testing.T) {
	// An action without a schema must fall back to the generic prompt instead of
	// asking nothing and sending an empty object for an action that takes arguments.
	for _, schema := range []string{"", "   ", `{"type":"object"}`, `{"type":"object","properties":{}}`} {
		fields, err := ctlSchemaFields(schema)
		if err != nil {
			t.Fatalf("schema %q: %v", schema, err)
		}
		if len(fields) != 0 {
			t.Fatalf("schema %q yielded %d fields, want 0", schema, len(fields))
		}
	}
}

func TestCtlSchemaFieldsRejectsBrokenSchema(t *testing.T) {
	if _, err := ctlSchemaFields(`{"properties":`); err == nil {
		t.Fatal("a broken schema was accepted")
	}
}

func TestCtlFieldPromptStatesTypeRequirementEnumAndDefault(t *testing.T) {
	prompt := ctlFieldPrompt(ctlField{
		Name:     "default",
		Type:     "string",
		Required: true,
		Enum:     []string{"continue", "interrupt"},
		Default:  json.RawMessage(`"continue"`),
	})
	for _, want := range []string{"default", "string", "required", "continue, interrupt", `default: "continue"`, "empty is rejected"} {
		if !strings.Contains(prompt, want) {
			t.Fatalf("prompt = %q, want it to contain %q", prompt, want)
		}
	}
	optional := ctlFieldPrompt(ctlField{Name: "reason", Type: "string"})
	if !strings.Contains(optional, "optional") || !strings.Contains(optional, "empty skips") {
		t.Fatalf("optional prompt = %q, want it to say the field is skippable", optional)
	}
}

func TestCtlFieldValueRejectsValueOutsideEnum(t *testing.T) {
	field := ctlField{Name: "default", Type: "string", Enum: []string{"continue", "interrupt"}}
	if _, err := ctlFieldValue(field, "abort"); err == nil {
		t.Fatal("a value outside the enum was accepted")
	}
	value, err := ctlFieldValue(field, "interrupt")
	if err != nil {
		t.Fatalf("enum value: %v", err)
	}
	if string(value) != `"interrupt"` {
		t.Fatalf("value = %s, want the string interrupt", value)
	}
}

func TestCtlFieldValueKeepsStringFieldsAsStrings(t *testing.T) {
	// A string field must not be reinterpreted as a number or a boolean, so a
	// literal such as 300 stays a string when the schema says string.
	value, err := ctlFieldValue(ctlField{Name: "reason", Type: "string"}, "300")
	if err != nil {
		t.Fatalf("string field: %v", err)
	}
	if string(value) != `"300"` {
		t.Fatalf("value = %s, want the string 300", value)
	}
}

func TestCtlFieldValueKeepsNumericFieldsAsNumbers(t *testing.T) {
	value, err := ctlFieldValue(ctlField{Name: "timeout_seconds", Type: "number"}, "300")
	if err != nil {
		t.Fatalf("number field: %v", err)
	}
	if string(value) != `300` {
		t.Fatalf("value = %s, want the number 300", value)
	}
}

func TestPromptCtlSchemaParametersAsksEachField(t *testing.T) {
	fields := []ctlField{
		{Name: "reason", Type: "string"},
		{Name: "timeout_seconds", Type: "number"},
	}
	var out bytes.Buffer
	payload, err := promptCtlSchemaParameters(context.Background(), "pause", fields, ctlLines("maintenance", "300"), &out)
	if err != nil {
		t.Fatalf("prompt: %v", err)
	}
	if !sameJSONObject(payload, `{"reason":"maintenance","timeout_seconds":300}`) {
		t.Fatalf("payload = %s, want reason and timeout_seconds", payload)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "reason") || !strings.Contains(rendered, "timeout_seconds") {
		t.Fatalf("prompt output = %q, want both field names", rendered)
	}
}

func TestPromptCtlSchemaParametersSkipsOptionalFieldOnEmptyAnswer(t *testing.T) {
	fields := []ctlField{{Name: "reason", Type: "string"}}
	var out bytes.Buffer
	payload, err := promptCtlSchemaParameters(context.Background(), "pause", fields, ctlLines(""), &out)
	if err != nil {
		t.Fatalf("prompt: %v", err)
	}
	if string(payload) != `{}` {
		t.Fatalf("payload = %s, want the empty object so the provider default applies", payload)
	}
}

func TestPromptCtlSchemaParametersRejectsEmptyRequiredField(t *testing.T) {
	fields := []ctlField{{Name: "session_id", Type: "string", Required: true}}
	var out bytes.Buffer
	_, err := promptCtlSchemaParameters(context.Background(), "get_session_messages", fields, ctlLines(""), &out)
	if err == nil {
		t.Fatal("an empty required field was accepted")
	}
	if !strings.Contains(err.Error(), "session_id is required") {
		t.Fatalf("error = %v, want it to name the required field", err)
	}
}

func TestPromptCtlActionParametersUsesSchemaWhenAdvertised(t *testing.T) {
	stub := ctlStub(ctlSchemaCapability("pause", `{"type":"object","properties":{"reason":{"type":"string"}}}`))
	var out bytes.Buffer
	payload, err := promptCtlActionParameters(context.Background(), stub, ctlState(), "pause", ctlLines("maintenance"), &out)
	if err != nil {
		t.Fatalf("prompt: %v", err)
	}
	if !sameJSONObject(payload, `{"reason":"maintenance"}`) {
		t.Fatalf("payload = %s, want reason", payload)
	}
	if !strings.Contains(out.String(), "reason") {
		t.Fatalf("prompt output = %q, want the field name", out.String())
	}
}

func TestPromptCtlActionParametersFallsBackToGenericPrompt(t *testing.T) {
	// An Endpoint that advertises no schema must keep the generic key=value
	// prompt, so an older Endpoint still works and the surface never regresses to
	// asking for JSON.
	stub := ctlStub(ctlSchemaCapability("pause", ""))
	var out bytes.Buffer
	payload, err := promptCtlActionParameters(context.Background(), stub, ctlState(), "pause", ctlLines("reason=maintenance"), &out)
	if err != nil {
		t.Fatalf("prompt: %v", err)
	}
	if !sameJSONObject(payload, `{"reason":"maintenance"}`) {
		t.Fatalf("payload = %s, want reason", payload)
	}
	if !strings.Contains(out.String(), "key=value") {
		t.Fatalf("prompt output = %q, want the generic key=value prompt", out.String())
	}
}
