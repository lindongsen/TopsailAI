package providercli

import (
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestAgentStartPayloadStrictContract(t *testing.T) {
	tests := []struct {
		name    string
		doc     string
		wantErr string
	}{
		{name: "folder and task", doc: `{"folder":"/work/project","task":"initial task"}`},
		{name: "folder without task", doc: `{"folder":"/work/project"}`},
		{name: "missing folder", doc: `{}`, wantErr: "folder is required"},
		{name: "empty folder", doc: `{"folder":""}`, wantErr: "folder is required"},
		{name: "null folder", doc: `{"folder":null}`, wantErr: "folder is required"},
		{name: "null task", doc: `{"folder":"/work","task":null}`, wantErr: "must not be null"},
		{name: "empty task", doc: `{"folder":"/work","task":""}`, wantErr: "must not be empty"},
		{name: "blank task", doc: `{"folder":"/work","task":"  "}`, wantErr: "nonblank"},
		{name: "unknown field", doc: `{"folder":"/work","extra":true}`, wantErr: "unknown field"},
		{name: "cluster model id", doc: `{"folder":"/work","model_profile_id":"cluster-model"}`, wantErr: "unknown field"},
		{name: "cluster resource id", doc: `{"folder":"/work","resource_id":"cluster-resource"}`, wantErr: "unknown field"},
		{name: "cluster launch profile id", doc: `{"folder":"/work","launch_profile_id":"cluster-profile"}`, wantErr: "unknown field"},
		{name: "oversized task", doc: `{"folder":"/work","task":"` + strings.Repeat("a", protocol.MaxInitialTaskBytes+1) + `"}`, wantErr: "at most"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			payload, err := DecodeAgentStartPayload([]byte(test.doc))
			if test.wantErr == "" {
				if err != nil {
					t.Fatalf("decode: %v", err)
				}
				if payload.Folder == "" {
					t.Fatal("folder was dropped")
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("error = %v, want containing %q", err, test.wantErr)
			}
		})
	}
}

func TestMarshalAgentStartPayloadRoundTrip(t *testing.T) {
	document, err := MarshalAgentStartPayload(AgentStartPayload{Folder: "/work/project", Task: "initial task"})
	if err != nil {
		t.Fatal(err)
	}
	payload, err := DecodeAgentStartPayload(document)
	if err != nil {
		t.Fatal(err)
	}
	if payload.Folder != "/work/project" || payload.Task != "initial task" {
		t.Fatalf("payload = %+v", payload)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(document, &fields); err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"model_profile_id", "resource_id", "launch_profile_id"} {
		if fields[forbidden] != nil {
			t.Fatalf("payload contains Cluster ID field %q", forbidden)
		}
	}
}

func TestRequestValidatesTypedAgentStartPayload(t *testing.T) {
	valid := validRequest(FunctionExecute)
	valid.InvocationID = "invocation-1"
	valid.Target = &Target{ResourceKind: protocol.ResourceLaunchProfile, ProviderResourceKey: "provider-profile", ExpectedGeneration: "revision-1"}
	valid.Operation = &NamedContract{Name: protocol.OperationAgentStart, Version: "v1"}
	valid.Payload = json.RawMessage(`{"folder":"/work/project","task":"initial task"}`)
	if err := valid.Validate(); err != nil {
		t.Fatalf("valid start request rejected: %v", err)
	}

	invalid := valid
	invalid.Payload = json.RawMessage(`{"folder":"/work/project","resource_id":"cluster-id"}`)
	if err := invalid.Validate(); err == nil || !strings.Contains(err.Error(), "unknown field") {
		t.Fatalf("invalid start payload error = %v", err)
	}
}
