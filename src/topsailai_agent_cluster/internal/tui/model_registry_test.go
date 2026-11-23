package tui

import (
	"encoding/json"
	"os"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/config"
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
// configuration advertises the operation at the capability version, not at the
// payload schema version.
//
// The two versions are different facts and the configuration is a second source
// of truth for the capability one. The Endpoint intersects the configured entry
// with the Provider's descriptor by name and version, so a config that names the
// payload version drops the capability exactly as if the Provider did not
// implement it: no log, no startup error, and every request refused as
// unsupported. The sibling agent.model.select entry is the reference, because it
// declares the capability version while its payload version is also "1".
//
// The document is parsed rather than substring-matched, so a reformatted line
// cannot satisfy the assertion and a second entry cannot hide a wrong one.
func TestEndpointConfigDeclaresTheModelSetCapability(t *testing.T) {
	content, err := os.ReadFile("../../conf/node.endpoint.conf.example")
	if err != nil {
		t.Fatalf("read endpoint config example: %v", err)
	}
	declared := templateCapabilities(t, string(content))

	capability, ok := declared[protocol.OperationAgentModelSet]
	if !ok {
		t.Fatalf("the shipped ADAPTERS example does not declare %q, so a node built from this template refuses it", protocol.OperationAgentModelSet)
	}
	if capability.Version != capabilityVersionV1 {
		t.Fatalf("%s is declared at version %q, want %q: the configured version is intersected with the Provider descriptor, so the payload schema version %q drops the capability silently",
			protocol.OperationAgentModelSet, capability.Version, capabilityVersionV1, protocol.ModelSetPayloadVersion)
	}
	// The payload version is a separate fact and must stay what the protocol
	// sends, so a future edit cannot "fix" this test by changing the payload.
	if protocol.ModelSetPayloadVersion == capabilityVersionV1 {
		t.Fatalf("ModelSetPayloadVersion is %q, the same as the capability version, so this test can no longer tell the two facts apart", protocol.ModelSetPayloadVersion)
	}
}

// capabilityVersionV1 is the capability version every standard operation in the
// shipped template declares. It is a literal because the template is a document
// an operator edits, and the protocol package deliberately defines no constant
// for it: the version is part of the wire contract, not a value the code derives.
const capabilityVersionV1 = "v1"

// templateCapabilities parses the ADAPTERS assignment of the shipped template
// and returns its capabilities keyed by name.
//
// It reads the assignment the way the shell does, so a multi-line document is
// parsed as one value instead of being truncated at its first line. The prefix
// and terminator match the shipped file, which keeps ADAPTERS single-quoted
// because the shell strips unquoted newlines.
func templateCapabilities(t *testing.T, content string) map[string]protocol.Capability {
	t.Helper()
	const prefix = "ADAPTERS='"
	start := strings.Index(content, prefix)
	if start < 0 {
		t.Fatalf("the shipped template has no ADAPTERS assignment")
	}
	start += len(prefix)
	end := strings.Index(content[start:], "'\n")
	if end < 0 {
		t.Fatalf("the shipped ADAPTERS assignment is not terminated by a closing quote")
	}
	adapters, err := config.ParseAdapters(content[start : start+end])
	if err != nil {
		t.Fatalf("the shipped ADAPTERS assignment does not parse: %v", err)
	}
	if len(adapters) != 1 {
		t.Fatalf("the shipped ADAPTERS declares %d adapters, want 1", len(adapters))
	}
	if adapters[0].Capabilities == nil {
		t.Fatalf("the shipped ADAPTERS declares no capabilities, so a node built from this template advertises none")
	}
	declared := make(map[string]protocol.Capability, len(adapters[0].Capabilities.Capabilities))
	for _, capability := range adapters[0].Capabilities.Capabilities {
		declared[capability.Name] = capability
	}
	return declared
}
