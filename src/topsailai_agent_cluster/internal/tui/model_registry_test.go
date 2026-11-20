package tui

import (
	"encoding/json"
	"os"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestModelSetPayloadCarriesOnlyTheOpaqueProfileID pins the payload shape.
//
// The payload is the only place a caller could smuggle provider vocabulary onto
// the wire, so a second field appearing here would be a contract change rather
// than a convenience.
func TestModelSetPayloadCarriesOnlyTheOpaqueProfileID(t *testing.T) {
	payload, err := ModelSetPayload("res_profile")
	if err != nil {
		t.Fatalf("payload: %v", err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(decoded) != 1 || decoded["model_profile_id"] != "res_profile" {
		t.Fatalf("payload = %s, want only model_profile_id", payload)
	}
}

// TestModelSetPayloadRejectsAnEmptyProfile proves an empty identifier is refused
// before submission, so the operator learns about the mistake locally instead of
// reading an Endpoint rejection that names a provider.
func TestModelSetPayloadRejectsAnEmptyProfile(t *testing.T) {
	if _, err := ModelSetPayload("   "); err == nil {
		t.Fatal("an empty model profile was accepted")
	}
}

// TestEndpointConfigDeclaresTheModelSetCapability proves the shipped Endpoint
// configuration advertises the operation with the version the protocol defines.
//
// The configuration is a second source of truth for the version string, and a
// mismatch makes the operation unreachable: the Endpoint validates an intent
// against the advertised version, so a config that names "v1" while the protocol
// sends "1" refuses every request as unsupported.
func TestEndpointConfigDeclaresTheModelSetCapability(t *testing.T) {
	content, err := os.ReadFile("../../conf/node.endpoint.conf.example")
	if err != nil {
		t.Fatalf("read endpoint config example: %v", err)
	}
	want := `"name": "` + protocol.OperationAgentModelSet + `", "version": "` + protocol.ModelSetPayloadVersion + `"`
	if !strings.Contains(string(content), want) {
		t.Fatalf("endpoint config does not declare %s at version %s", protocol.OperationAgentModelSet, protocol.ModelSetPayloadVersion)
	}
}
