package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// modelRegistryStub adds the endpoint model registry seam to the shared interactive
// fixture, so the registry form can be driven through the real REPL.
//
// It counts reads and records the endpoint each read addressed, because the two
// behaviours worth proving are "which machine was read" and "was the machine read at
// all". A stub that only returned a document could not distinguish a registry read
// from a catalog read that happened to render the same rows.
type modelRegistryStub struct {
	*interactiveStub
	registryCalls int
	endpointsRead []string
	registry      protocol.ModelRegistry
}

// GetModelRegistry serves one deterministic registry and records the endpoint.
func (s *modelRegistryStub) GetModelRegistry(_ context.Context, endpointID string) (protocol.ModelRegistry, error) {
	s.registryCalls++
	s.endpointsRead = append(s.endpointsRead, endpointID)
	return s.registry, nil
}

// modelRegistryFixture serves two models on the first endpoint, with the second one
// selected, so a render has both a marked row and an unmarked row to distinguish.
func modelRegistryFixture() *modelRegistryStub {
	return &modelRegistryStub{
		interactiveStub: scopeStub(),
		registry: protocol.ModelRegistry{
			Entries: []protocol.ModelRegistryEntry{
				{ModelProfileID: "mp_alpha", ProviderDisplayName: "Alpha", Available: true},
				{ModelProfileID: "mp_beta", ProviderDisplayName: "Beta", Available: true},
			},
			CurrentProfileID: "mp_beta",
			CurrentSource:    protocol.ModelSourceWorkspace,
			ObservedAtMS:     1794470400000,
		},
	}
}

// TestModelRegistryReadsTheCurrentEndpointWithoutPrompting proves endpoint scope
// reads the machine the operator is already inside and never asks which machine to
// read, because the scope already answered that question.
func TestModelRegistryReadsTheCurrentEndpointWithoutPrompting(t *testing.T) {
	stub := modelRegistryFixture()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.registryCalls != 1 {
		t.Fatalf("registry reads=%d, want 1", stub.registryCalls)
	}
	if len(stub.endpointsRead) != 1 || stub.endpointsRead[0] != "endpoint-1" {
		t.Fatalf("read endpoints=%v, want [endpoint-1]", stub.endpointsRead)
	}
	if strings.Contains(output, "Choose an endpoint number") {
		t.Fatalf("endpoint scope must not prompt for an endpoint: %q", output)
	}
	if !strings.Contains(output, "Alpha") || !strings.Contains(output, "Beta") {
		t.Fatalf("registry rows are missing: %q", output)
	}
}

// TestModelRegistryPromptsForAnEndpointInWorkspaceScope proves workspace scope asks
// which machine to read, because a registry belongs to one machine and fanning out
// would mix rows whose model identifiers may collide.
func TestModelRegistryPromptsForAnEndpointInWorkspaceScope(t *testing.T) {
	stub := modelRegistryFixture()
	output, diagnostics := runScope(t, stub, "model\n1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "Choose an endpoint number or enter an endpoint ID") {
		t.Fatalf("workspace scope must prompt for an endpoint: %q", output)
	}
	if stub.registryCalls != 1 {
		t.Fatalf("registry reads=%d, want 1", stub.registryCalls)
	}
	if len(stub.endpointsRead) != 1 || stub.endpointsRead[0] != "endpoint-1" {
		t.Fatalf("read endpoints=%v, want [endpoint-1]", stub.endpointsRead)
	}
}

// TestModelRegistryCancelledPromptReadsNothing proves an empty answer cancels the
// command instead of reading an arbitrary machine. Cancelling a prompt is a decision,
// so it must not be reported as a failure and must not fall back to the first endpoint.
func TestModelRegistryCancelledPromptReadsNothing(t *testing.T) {
	stub := modelRegistryFixture()
	output, diagnostics := runScope(t, stub, "model\n\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.registryCalls != 0 {
		t.Fatalf("registry reads=%d, want 0 after a cancelled prompt", stub.registryCalls)
	}
	if strings.Contains(output, "Alpha") {
		t.Fatalf("a cancelled prompt must not render a registry: %q", output)
	}
}

// TestModelRegistryMarksTheModelInUse proves the row a launch would use is marked and
// the source is stated, so an operator can tell a machine-wide default from a folder
// override instead of reading one value as the whole truth.
func TestModelRegistryMarksTheModelInUse(t *testing.T) {
	stub := modelRegistryFixture()
	output, _ := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nexit\n", ColorPolicy{})
	if !strings.Contains(output, modelCurrentMarker+"Beta") {
		t.Fatalf("the model in use is not marked: %q", output)
	}
	if strings.Contains(output, modelCurrentMarker+"Alpha") {
		t.Fatalf("an unselected model is marked: %q", output)
	}
	if !strings.Contains(output, "the machine default") {
		t.Fatalf("the selection source is not stated: %q", output)
	}
}

// TestModelRegistryStatesAnAbsentSelection proves an unconfigured machine is stated
// plainly rather than rendered as a table with no marker. An absent selection is an
// observation, so it must not look like a lost selection or a rendering fault.
func TestModelRegistryStatesAnAbsentSelection(t *testing.T) {
	stub := modelRegistryFixture()
	stub.registry.CurrentProfileID = ""
	stub.registry.CurrentSource = protocol.ModelSourceInherited
	output, _ := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nexit\n", ColorPolicy{})
	if strings.Contains(output, modelCurrentMarker) {
		t.Fatalf("no row may be marked when no selection exists: %q", output)
	}
	if !strings.Contains(output, "no model is configured") {
		t.Fatalf("an absent selection is not stated: %q", output)
	}
}

// TestModelRegistryStatesAnEmptyRegistry proves an endpoint that offers no model is
// stated plainly instead of rendering an empty table that looks like a fault.
func TestModelRegistryStatesAnEmptyRegistry(t *testing.T) {
	stub := modelRegistryFixture()
	stub.registry = protocol.ModelRegistry{CurrentSource: protocol.ModelSourceInherited}
	output, _ := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nexit\n", ColorPolicy{})
	if !strings.Contains(output, "offers no model to launches") {
		t.Fatalf("an empty registry is not stated: %q", output)
	}
}

// TestModelRegistryStatesABoundedWindow proves a truncated registry says so, because
// a bounded window presented as the complete list hides models that exist.
func TestModelRegistryStatesABoundedWindow(t *testing.T) {
	stub := modelRegistryFixture()
	stub.registry.Truncated = true
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "bounded provider window") {
		t.Fatalf("a truncated registry is not stated: %q", diagnostics)
	}
}

// TestModelRegistryNamesAnUnsupportedEndpoint proves an endpoint with no capable
// adapter is reported as unsupported rather than as a provider failure, because the
// remedy is to configure an adapter and not to investigate a healthy provider.
func TestModelRegistryNamesAnUnsupportedEndpoint(t *testing.T) {
	stub := modelRegistryFixture()
	stub.registry = protocol.ModelRegistry{ErrorCode: protocol.ModelRegistryUnsupported}
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel\nexit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: the model registry is unavailable for endpoint \"endpoint-1\": no configured adapter can report the models it offers")
}

// TestModelRegistryDropsEveryOtherRowNamespace proves rendering the registry clears
// the other tables' row numbers, so a number from a table the operator can no longer
// see cannot be applied to a row of this one.
func TestModelRegistryDropsEveryOtherRowNamespace(t *testing.T) {
	stub := modelRegistryFixture()
	state := &interactiveState{
		Scope:          ScopeState{Kind: ScopeEndpoint, EndpointID: "endpoint-1"},
		history:        &historyNamespace{EndpointID: "endpoint-1", Rows: map[int]HistoryViewRow{1: {No: 1}}},
		modelCatalog:   &modelCatalogNamespace{ClusterSessionID: "res_1", Rows: map[int]ModelCatalogViewRow{1: {No: 1}}},
		projectCatalog: &projectCatalogNamespace{EndpointID: "endpoint-1", Rows: map[int]protocol.Project{1: {ProjectID: "prj_1"}}},
	}
	var out, diagnostics strings.Builder
	if err := interactiveModelRegistry(context.Background(), stub, state, "", nil, &out, &out, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("interactiveModelRegistry: %v", err)
	}
	if state.history != nil || state.modelCatalog != nil || state.projectCatalog != nil {
		t.Fatalf("a stale namespace survived the registry render: history=%v catalog=%v project=%v", state.history, state.modelCatalog, state.projectCatalog)
	}
}

// TestModelRegistryKeepsTheSessionCatalogInSessionScope proves the new form did not
// change what a bare model means inside a session. Session scope already names one
// session, so a bare model there must still read that session's catalog and must not
// read the endpoint registry.
func TestModelRegistryKeepsTheSessionCatalogInSessionScope(t *testing.T) {
	stub := modelReadStubFixture()
	output, _ := runScope(t, stub, "list\ncd 2\nmodel\nexit\n", ColorPolicy{})
	if stub.catalogCalls != 1 {
		t.Fatalf("catalog reads=%d, want 1", stub.catalogCalls)
	}
	if !strings.Contains(output, "claude") {
		t.Fatalf("the session catalog is not rendered: %q", output)
	}
}

// TestModelRegistryKeepsTheSessionTokenFormOutsideSessionScope proves a token still
// means a session outside session scope, so the registry form did not swallow the
// documented "model <number-or-session>" behaviour.
func TestModelRegistryKeepsTheSessionTokenFormOutsideSessionScope(t *testing.T) {
	stub := modelReadStubFixture()
	output, _ := runScope(t, stub, "list\nmodel 1\nexit\n", ColorPolicy{})
	if stub.catalogCalls != 1 {
		t.Fatalf("catalog reads=%d, want 1", stub.catalogCalls)
	}
	if strings.Contains(output, "Choose an endpoint number") {
		t.Fatalf("a token must not trigger the endpoint prompt: %q", output)
	}
	if !strings.Contains(output, "claude") {
		t.Fatalf("the session catalog is not rendered: %q", output)
	}
}

// TestModelRegistryRejectsAnOption proves the registry form refuses an option instead
// of silently ignoring it, so a mistyped flag cannot look like a successful read.
func TestModelRegistryRejectsAnOption(t *testing.T) {
	stub := modelRegistryFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nmodel --json\nexit\n", ColorPolicy{})
	if stub.registryCalls != 0 {
		t.Fatalf("registry reads=%d, want 0 for a rejected option", stub.registryCalls)
	}
	if !strings.Contains(diagnostics, "error:") {
		t.Fatalf("a rejected option is not reported: %q", diagnostics)
	}
}
