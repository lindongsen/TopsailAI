package tui

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// modelSetStub adds the endpoint model registry seam and the model-set capability to
// the shared interactive fixture, so the set form can be driven through the real REPL.
//
// It counts registry reads because the two behaviours worth proving are "was the
// registry read to resolve this selector" and "was it read at all": a row number must
// resolve locally, while an identifier must be resolved against a fresh read.
type modelSetStub struct {
	*interactiveStub
	registryCalls int
	endpointsRead []string
	registry      protocol.ModelRegistry
}

// GetCapabilities advertises the registry read and the model-set mutation.
func (s *modelSetStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{
		{Name: protocol.OperationAgentModelRegistry},
		{Name: protocol.OperationAgentModelSet, Version: protocol.ModelSetPayloadVersion},
	}}, nil
}

// GetModelRegistry serves one deterministic registry and records the endpoint.
func (s *modelSetStub) GetModelRegistry(_ context.Context, endpointID string) (protocol.ModelRegistry, error) {
	s.registryCalls++
	s.endpointsRead = append(s.endpointsRead, endpointID)
	return s.registry, nil
}

// modelSetFixture serves three models on the first endpoint: one selected, one plain,
// and one disabled, so a render and a refusal both have a row to distinguish.
func modelSetFixture() *modelSetStub {
	return &modelSetStub{
		interactiveStub: scopeStub(),
		registry: protocol.ModelRegistry{
			Entries: []protocol.ModelRegistryEntry{
				{ModelProfileID: "mp_alpha", ProviderDisplayName: "Alpha", Available: true},
				{ModelProfileID: "mp_beta", ProviderDisplayName: "Beta", Available: true},
				{ModelProfileID: "mp_gamma", ProviderDisplayName: "Gamma", Available: false, UnavailableReason: "disabled"},
			},
			CurrentProfileID: "mp_alpha",
			CurrentSource:    protocol.ModelSourceWorkspace,
			ObservedAtMS:     1794470400000,
		},
	}
}

// modelSetPayloadOf decodes the payload of the single admitted intent.
func modelSetPayloadOf(t *testing.T, stub *modelSetStub) protocol.ModelSetPayload {
	t.Helper()
	if stub.admit != 1 {
		t.Fatalf("admitted=%d, want 1", stub.admit)
	}
	payload, err := protocol.ValidateModelSetPayload(stub.intents[0].Payload)
	if err != nil {
		t.Fatalf("admitted payload is not a valid model set payload: %v", err)
	}
	return payload
}

// TestModelSetResolvesARenderedRowLocally proves a row number addresses the model the
// operator saw, carries the opaque identifier rather than the number, and never
// re-reads the registry to resolve a number.
func TestModelSetResolvesARenderedRowLocally(t *testing.T) {
	stub := modelSetFixture()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nmodel set 2\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.registryCalls != 1 {
		t.Fatalf("registry reads=%d, want 1 (the render only)", stub.registryCalls)
	}
	payload := modelSetPayloadOf(t, stub)
	if payload.ModelProfileID != "mp_beta" {
		t.Fatalf("model_profile_id=%q, want mp_beta", payload.ModelProfileID)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationAgentModelSet {
		t.Fatalf("operation=%q, want %q", intent.Operation, protocol.OperationAgentModelSet)
	}
	if intent.EndpointID != "endpoint-1" {
		t.Fatalf("endpoint=%q, want endpoint-1", intent.EndpointID)
	}
	// The operation addresses the machine, so it must carry no target at all. A
	// target here would make the request address a session that has nothing to do
	// with the change.
	if intent.Target != nil {
		t.Fatalf("model set must be target-less, got target %+v", *intent.Target)
	}
	if !strings.Contains(output, "is now the launch default") {
		t.Fatalf("the change is not reported: %q", output)
	}
}

// TestModelSetResolvesAnIdentifierAgainstAFreshRead proves an identifier is resolved
// against a fresh registry read, because the operator may name a model the current
// table does not show.
func TestModelSetResolvesAnIdentifierAgainstAFreshRead(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel set mp_beta\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.registryCalls != 1 {
		t.Fatalf("registry reads=%d, want 1 (the identifier resolution)", stub.registryCalls)
	}
	if payload := modelSetPayloadOf(t, stub); payload.ModelProfileID != "mp_beta" {
		t.Fatalf("model_profile_id=%q, want mp_beta", payload.ModelProfileID)
	}
}

// TestModelSetRefusesARowWithoutARenderedRegistry proves a row number is never
// guessed: without a table the operator saw, a number has no meaning.
func TestModelSetRefusesARowWithoutARenderedRegistry(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel set 2\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "no model registry has been rendered") {
		t.Fatalf("the refusal does not name the missing table: %q", diagnostics)
	}
}

// TestModelSetRefusesARowOutsideTheRenderedTable proves a number that was not printed
// is refused instead of being retried as an identifier.
func TestModelSetRefusesARowOutsideTheRenderedTable(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nmodel set 9\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "no such row in the rendered registry") {
		t.Fatalf("the refusal does not name the missing row: %q", diagnostics)
	}
}

// TestModelSetRefusesAnUnavailableModelBeforeConfirming proves the registry's own
// availability answer is reused, so the operator is not asked to confirm a change the
// provider would then refuse.
func TestModelSetRefusesAnUnavailableModelBeforeConfirming(t *testing.T) {
	stub := modelSetFixture()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nmodel set 3\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "is unavailable (disabled)") {
		t.Fatalf("the refusal does not repeat the registry reason: %q", diagnostics)
	}
	if strings.Contains(output, "Confirm") {
		t.Fatalf("an unavailable model must not reach a confirmation: %q", output)
	}
}

// TestModelSetRefusesAnUnknownIdentifier proves an identifier the registry does not
// contain is refused, so a typo cannot become a provider-side guess.
func TestModelSetRefusesAnUnknownIdentifier(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel set mp_nope\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "is not in the current registry") {
		t.Fatalf("the refusal does not name the unknown identifier: %q", diagnostics)
	}
}

// TestModelSetRefusesAnAmbiguousDisplayName proves a display name shared by several
// entries is refused rather than resolved to the first, because selecting the first
// would apply a model the operator did not choose.
func TestModelSetRefusesAnAmbiguousDisplayName(t *testing.T) {
	stub := modelSetFixture()
	stub.registry.Entries = append(stub.registry.Entries, protocol.ModelRegistryEntry{
		ModelProfileID: "mp_beta_two", ProviderDisplayName: "Beta", Available: true,
	})
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel set Beta\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "is ambiguous") {
		t.Fatalf("the refusal does not name the ambiguity: %q", diagnostics)
	}
	if !strings.Contains(diagnostics, "mp_beta") || !strings.Contains(diagnostics, "mp_beta_two") {
		t.Fatalf("the refusal does not name the colliding identifiers: %q", diagnostics)
	}
}

// TestModelSetPromptsForAnEndpointInWorkspaceScope proves workspace scope asks which
// machine to change, because a launch default belongs to one machine.
func TestModelSetPromptsForAnEndpointInWorkspaceScope(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "model set mp_beta\n1\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.endpointsRead) != 1 || stub.endpointsRead[0] != "endpoint-1" {
		t.Fatalf("read endpoints=%v, want [endpoint-1]", stub.endpointsRead)
	}
	if intent := stub.intents[0]; intent.EndpointID != "endpoint-1" {
		t.Fatalf("endpoint=%q, want endpoint-1", intent.EndpointID)
	}
}

// TestModelSetCancelledPromptChangesNothing proves cancelling the endpoint prompt
// performs no read and admits nothing, because cancelling is a decision rather than a
// failure.
func TestModelSetCancelledPromptChangesNothing(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "model set mp_beta\n\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.registryCalls != 0 {
		t.Fatalf("registry reads=%d, want 0", stub.registryCalls)
	}
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
}

// TestModelSetRefusedInSessionScope proves the set form is refused where "model
// <number>" already applies a profile to the session, so two similar spellings cannot
// do different things with the same number.
func TestModelSetRefusedInSessionScope(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nmodel set 2\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "available outside session scope") {
		t.Fatalf("the refusal does not name the scope restriction: %q", diagnostics)
	}
	if !strings.Contains(diagnostics, "model <profile>") {
		t.Fatalf("the refusal does not name the correct form: %q", diagnostics)
	}
}

// TestModelSetDropsTheRegistryNamespaceAfterAChange proves the numbers rendered before
// a successful change are dropped, because the table no longer describes the machine.
func TestModelSetDropsTheRegistryNamespaceAfterAChange(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nmodel set 2\ny\nmodel set 2\nexit\n", ColorPolicy{})
	if stub.admit != 1 {
		t.Fatalf("admitted=%d, want 1", stub.admit)
	}
	if !strings.Contains(diagnostics, "no model registry has been rendered") {
		t.Fatalf("the stale namespace survived the change: %q", diagnostics)
	}
}

// TestModelSetRejectsAnOption proves an option is refused before any read, because the
// interactive surface never accepts a flag.
func TestModelSetRejectsAnOption(t *testing.T) {
	stub := modelSetFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel set 2 --json\nexit\n", ColorPolicy{})
	if stub.registryCalls != 0 || stub.admit != 0 {
		t.Fatalf("registry reads=%d admitted=%d, want 0 and 0", stub.registryCalls, stub.admit)
	}
	if !strings.Contains(diagnostics, "available only in non-interactive mode") {
		t.Fatalf("the refusal does not name the option restriction: %q", diagnostics)
	}
}

// TestModelSetPayloadCarriesOnlyTheIdentifier pins the wire shape, so a provider name
// or index can never be added to the payload without this test failing.
func TestModelSetPayloadCarriesOnlyTheIdentifier(t *testing.T) {
	payload, err := ModelSetPayload("mp_beta")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		t.Fatalf("payload is not JSON: %v", err)
	}
	if len(decoded) != 1 {
		t.Fatalf("payload carries %d keys, want exactly 1: %s", len(decoded), payload)
	}
	if decoded["model_profile_id"] != "mp_beta" {
		t.Fatalf("payload does not carry the identifier: %s", payload)
	}
}
