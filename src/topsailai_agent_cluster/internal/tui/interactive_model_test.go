package tui

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// modelNamespace builds a rendered catalog namespace for one session.
//
// The rows are the ones a real render would have produced, so a selector test
// exercises the same map the interactive surface keeps between commands.
func modelNamespace(sessionID string, rows ...ModelCatalogViewRow) *modelCatalogNamespace {
	namespace := &modelCatalogNamespace{
		EndpointID: "endpoint-1",
		SessionID:  sessionID,
		Rows:       make(map[int]ModelCatalogViewRow, len(rows)),
	}
	for _, row := range rows {
		namespace.Rows[row.No] = row
	}
	return namespace
}

// TestModelSelectUnmatchedNumberIsNotRetriedAsAnID proves a number that is not in
// the rendered catalog is refused instead of being reinterpreted as a profile ID.
//
// Falling through to an ID lookup would submit a profile the operator never saw,
// which is the one outcome a numbered menu must never produce.
func TestModelSelectUnmatchedNumberIsNotRetriedAsAnID(t *testing.T) {
	namespace := modelNamespace("res_1", ModelCatalogViewRow{No: 1, ModelProfileID: "mp-1", DisplayName: "claude"})

	_, err := resolveModelProfileSelector(namespace, "res_1", "7")
	if err == nil {
		t.Fatal("expected an unmatched row number to be rejected")
	}
	if !strings.Contains(err.Error(), "run model again") {
		t.Fatalf("expected the recovery hint, got %q", err.Error())
	}
	if strings.Contains(err.Error(), "mp-") {
		t.Fatalf("an unmatched number must not be retried as a profile ID, got %q", err.Error())
	}
}

// TestModelSelectRejectsACatalogFromAnotherSession proves a catalog rendered for
// one session cannot select a profile for a different session.
//
// The row numbers describe the session that was read, so applying them elsewhere
// would address a profile the operator never saw for that target.
func TestModelSelectRejectsACatalogFromAnotherSession(t *testing.T) {
	namespace := modelNamespace("res_1", ModelCatalogViewRow{No: 1, ModelProfileID: "mp-1"})

	_, err := resolveModelProfileSelector(namespace, "res_2", "1")
	if err == nil {
		t.Fatal("expected a catalog from another session to be rejected")
	}
	if !strings.Contains(err.Error(), "res_1") || !strings.Contains(err.Error(), "res_2") {
		t.Fatalf("expected both session IDs in the message, got %q", err.Error())
	}
}

// TestModelSelectWithoutARenderedCatalogAsksForOne proves a select with no prior
// read is refused with the command that produces the catalog.
//
// An empty namespace is not "no profiles exist"; it is "nothing was rendered", and
// the two must not collapse into one message.
func TestModelSelectWithoutARenderedCatalogAsksForOne(t *testing.T) {
	_, err := resolveModelProfileSelector(nil, "res_1", "1")
	if err == nil {
		t.Fatal("expected a select without a rendered catalog to be rejected")
	}
	if !strings.Contains(err.Error(), "run model first") {
		t.Fatalf("expected the read hint, got %q", err.Error())
	}
}

// TestModelSelectResolvesRowNumberToTheOpaqueID proves the row number becomes the
// opaque profile ID before anything is submitted.
//
// The wire payload carries model_profile_id only, so a number can never reach the
// Endpoint as a selection key.
func TestModelSelectResolvesRowNumberToTheOpaqueID(t *testing.T) {
	namespace := modelNamespace("res_1",
		ModelCatalogViewRow{No: 1, ModelProfileID: "mp-1", DisplayName: "claude"},
		ModelCatalogViewRow{No: 2, ModelProfileID: "mp-2", DisplayName: "gpt"},
	)

	row, err := resolveModelProfileSelector(namespace, "res_1", "2")
	if err != nil {
		t.Fatalf("expected row 2 to resolve, got %v", err)
	}
	if row.ModelProfileID != "mp-2" {
		t.Fatalf("expected mp-2, got %q", row.ModelProfileID)
	}

	payload, err := json.Marshal(protocol.ModelSelectRequest{ModelProfileID: row.ModelProfileID})
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	if strings.Contains(string(payload), `"2"`) {
		t.Fatalf("the payload must not carry the row number, got %s", payload)
	}
	if !strings.Contains(string(payload), `"mp-2"`) {
		t.Fatalf("the payload must carry the opaque profile ID, got %s", payload)
	}
}

// TestModelSelectAcceptsTheOpaqueIDAndDisplayName proves an explicit selector
// resolves only when it names a profile that was actually rendered.
//
// Accepting an unseen ID would let a caller bypass the catalog the operator was
// shown, so the rendered set stays the only authority.
func TestModelSelectAcceptsTheOpaqueIDAndDisplayName(t *testing.T) {
	namespace := modelNamespace("res_1", ModelCatalogViewRow{No: 1, ModelProfileID: "mp-1", DisplayName: "claude"})

	byID, err := resolveModelProfileSelector(namespace, "res_1", "mp-1")
	if err != nil {
		t.Fatalf("expected the opaque ID to resolve, got %v", err)
	}
	if byID.No != 1 {
		t.Fatalf("expected row 1, got %d", byID.No)
	}

	byName, err := resolveModelProfileSelector(namespace, "res_1", "claude")
	if err != nil {
		t.Fatalf("expected the display name to resolve, got %v", err)
	}
	if byName.ModelProfileID != "mp-1" {
		t.Fatalf("expected mp-1, got %q", byName.ModelProfileID)
	}

	if _, err := resolveModelProfileSelector(namespace, "res_1", "mp-unseen"); err == nil {
		t.Fatal("expected a profile that was never rendered to be rejected")
	}
}

// TestModelSelectRejectsAnAmbiguousDisplayName proves two profiles sharing a
// display name are refused instead of one being chosen arbitrarily.
//
// Picking the first match would apply a configuration the operator did not select,
// and the two rows are indistinguishable by the token they typed.
func TestModelSelectRejectsAnAmbiguousDisplayName(t *testing.T) {
	namespace := modelNamespace("res_1",
		ModelCatalogViewRow{No: 1, ModelProfileID: "mp-1", DisplayName: "claude"},
		ModelCatalogViewRow{No: 2, ModelProfileID: "mp-2", DisplayName: "claude"},
	)

	_, err := resolveModelProfileSelector(namespace, "res_1", "claude")
	if err == nil {
		t.Fatal("expected an ambiguous display name to be rejected")
	}
	if !strings.Contains(err.Error(), "ambiguous") {
		t.Fatalf("expected an ambiguity message, got %q", err.Error())
	}
}

// TestModelRowNumberDetectionIsShared proves the standalone surface recognises a
// row number with the same rule the interactive surface uses.
//
// A second implementation would drift, and one surface would accept a number the
// other rejects.
func TestModelRowNumberDetectionIsShared(t *testing.T) {
	for _, token := range []string{"1", "12", "007"} {
		if !IsRowNumber(token) {
			t.Fatalf("expected %q to be a row number", token)
		}
	}
	for _, token := range []string{"", "mp-1", "claude", "1a", "-1", "1.5"} {
		if IsRowNumber(token) {
			t.Fatalf("expected %q not to be a row number", token)
		}
	}
}

// TestModelProfileLabelNamesTheProfile proves the operator-facing label carries the
// display name and the opaque ID, so a confirmation names what will be applied.
func TestModelProfileLabelNamesTheProfile(t *testing.T) {
	label := ModelProfileLabel(ModelCatalogViewRow{No: 2, ModelProfileID: "mp-2", DisplayName: "gpt"})
	if !strings.Contains(label, "gpt") || !strings.Contains(label, "mp-2") {
		t.Fatalf("expected the display name and the ID, got %q", label)
	}
}

// TestModelCatalogErrorSeparatesUnsupportedFromEmpty proves an unsupported adapter
// and an empty catalog produce different messages.
//
// Collapsing them would report an integration gap as "this session offers no
// profile", which sends the operator looking for a configuration problem that does
// not exist.
func TestModelCatalogErrorSeparatesUnsupportedFromEmpty(t *testing.T) {
	unsupported := ModelCatalogError("res_1", protocol.ModelCatalogUnsupported)
	if unsupported == nil {
		t.Fatal("expected an unsupported catalog to be an error")
	}
	if !strings.Contains(unsupported.Error(), "adapter") {
		t.Fatalf("expected the message to name the missing adapter, got %q", unsupported.Error())
	}
	if empty := ModelCatalogError("res_1", ""); empty != nil {
		t.Fatalf("an empty catalog is a real answer, got error %v", empty)
	}
}

// modelSelectStub advertises the model-select capability and answers the catalog
// seam, so an end-to-end select can reach the confirmation gate and the admission
// path instead of being rejected as an unsupported capability.
type modelSelectStub struct {
	*interactiveStub
	catalog protocol.ModelCatalog
}

// GetCapabilities advertises the standard model operations.
func (s modelSelectStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{
		Revision: "r-model",
		Capabilities: []protocol.Capability{
			{Name: protocol.OperationAgentModelList},
			{Name: protocol.OperationAgentModelSelect},
		},
	}, nil
}

// GetModelCatalog answers the read seam with one selectable profile.
func (s modelSelectStub) GetModelCatalog(context.Context, string, string, string) (protocol.ModelCatalog, error) {
	return s.catalog, nil
}

// modelSelectStubFixture returns a session-scoped fixture whose catalog offers two
// profiles, so a row number and an explicit ID both have something to resolve.
func modelSelectStubFixture() modelSelectStub {
	stub := scopeStub()
	return modelSelectStub{
		interactiveStub: stub,
		catalog: protocol.ModelCatalog{
			Profiles: []protocol.ModelProfile{
				{ModelProfileID: "mp-1", DisplayName: "claude", Available: true},
				{ModelProfileID: "mp-2", DisplayName: "gpt", Available: true},
			},
			CurrentProfileID: "mp-1",
			ObservedAtMS:     1700000000000,
		},
	}
}

// TestInteractiveModelSelectRequiresConfirmation proves a declined confirmation
// admits nothing, because applying a profile changes the live agent.
func TestInteractiveModelSelectRequiresConfirmation(t *testing.T) {
	stub := modelSelectStubFixture()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nmodel\nmodel 2\nn\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("declined model select admitted %d commands", stub.admit)
	}
	if !strings.Contains(output, "cancelled") {
		t.Fatalf("missing cancellation notice: %q", output)
	}
}

// TestInteractiveModelSelectCarriesTheGeneration proves the confirmed select
// submits the standard operation against the exact selected generation.
//
// An empty generation would be rejected by the Endpoint as generation_required, so
// the client must carry the one it resolved rather than leaving it blank.
func TestInteractiveModelSelectCarriesTheGeneration(t *testing.T) {
	stub := modelSelectStubFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\nmodel\nmodel 2\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 || len(stub.intents) != 1 {
		t.Fatalf("admitted %d commands with %d intents, want 1", stub.admit, len(stub.intents))
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationAgentModelSelect {
		t.Fatalf("operation=%q want %q", intent.Operation, protocol.OperationAgentModelSelect)
	}
	if intent.Target == nil || intent.Target.ResourceID != "res-1" {
		t.Fatalf("target=%+v want res-1", intent.Target)
	}
	if intent.Target.Generation != "generation-1" {
		t.Fatalf("generation=%q want generation-1", intent.Target.Generation)
	}
	if !strings.Contains(string(intent.Payload), "mp-2") {
		t.Fatalf("payload must carry the opaque profile ID, got %s", intent.Payload)
	}
	if strings.Contains(string(intent.Payload), `"2"`) {
		t.Fatalf("payload must not carry the row number, got %s", intent.Payload)
	}
}
