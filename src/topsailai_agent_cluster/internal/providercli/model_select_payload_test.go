package providercli

import (
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestModelSelectPayloadStrictContract(t *testing.T) {
	tests := []struct {
		name    string
		doc     []byte
		wantErr string
	}{
		{name: "provider key", doc: []byte(`{"provider_resource_key":"provider-model"}`)},
		{name: "missing key", doc: []byte(`{}`), wantErr: "required"},
		{name: "empty key", doc: []byte(`{"provider_resource_key":""}`), wantErr: "required"},
		{name: "null key", doc: []byte(`{"provider_resource_key":null}`), wantErr: "required"},
		{name: "leading whitespace", doc: []byte(`{"provider_resource_key":" provider-model"}`), wantErr: "whitespace"},
		{name: "trailing whitespace", doc: []byte(`{"provider_resource_key":"provider-model "}`), wantErr: "whitespace"},
		{name: "oversized key", doc: []byte(`{"provider_resource_key":"` + strings.Repeat("a", MaxIdentifierBytes+1) + `"}`), wantErr: "exceeds"},
		{name: "invalid UTF-8", doc: []byte{'{', '"', 'p', 'r', 'o', 'v', 'i', 'd', 'e', 'r', '_', 'r', 'e', 's', 'o', 'u', 'r', 'c', 'e', '_', 'k', 'e', 'y', '"', ':', '"', 0xff, '"', '}'}, wantErr: "UTF-8"},
		{name: "unknown field", doc: []byte(`{"provider_resource_key":"provider-model","extra":true}`), wantErr: "unknown field"},
		{name: "cluster model ID", doc: []byte(`{"provider_resource_key":"provider-model","model_profile_id":"cluster-model"}`), wantErr: "unknown field"},
		{name: "cluster resource ID", doc: []byte(`{"provider_resource_key":"provider-model","resource_id":"cluster-resource"}`), wantErr: "unknown field"},
		{name: "cluster session ID", doc: []byte(`{"provider_resource_key":"provider-model","cluster_session_id":"cluster-session"}`), wantErr: "unknown field"},
		{name: "extra document", doc: []byte(`{"provider_resource_key":"provider-model"}{}`), wantErr: "extra JSON document"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			payload, err := DecodeModelSelectPayload(test.doc)
			if test.wantErr == "" {
				if err != nil {
					t.Fatalf("decode: %v", err)
				}
				if payload.ProviderResourceKey != "provider-model" {
					t.Fatalf("provider key = %q", payload.ProviderResourceKey)
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("error = %v, want containing %q", err, test.wantErr)
			}
		})
	}
}

func TestMarshalModelSelectPayloadRoundTrip(t *testing.T) {
	document, err := MarshalModelSelectPayload(ModelSelectPayload{ProviderResourceKey: "provider-model"})
	if err != nil {
		t.Fatal(err)
	}
	payload, err := DecodeModelSelectPayload(document)
	if err != nil {
		t.Fatal(err)
	}
	if payload.ProviderResourceKey != "provider-model" {
		t.Fatalf("payload = %+v", payload)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(document, &fields); err != nil {
		t.Fatal(err)
	}
	if len(fields) != 1 || fields["provider_resource_key"] == nil {
		t.Fatalf("fields = %v", fields)
	}
}

func TestRequestValidatesTypedModelSelectPayload(t *testing.T) {
	valid := validRequest(FunctionExecute)
	valid.InvocationID = "invocation-1"
	valid.Target = &Target{ResourceKind: protocol.ResourceSession, ProviderResourceKey: "provider-session", ExpectedGeneration: "generation-1"}
	valid.Operation = &NamedContract{Name: protocol.OperationAgentModelSelect, Version: "v1"}
	valid.Payload = json.RawMessage(`{"provider_resource_key":"provider-model"}`)
	if err := valid.Validate(); err != nil {
		t.Fatalf("valid model-select request rejected: %v", err)
	}

	invalid := valid
	invalid.Payload = json.RawMessage(`{"provider_resource_key":"provider-model","model_profile_id":"cluster-model"}`)
	if err := invalid.Validate(); err == nil || !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("invalid model-select payload error = %v", err)
	}
}
