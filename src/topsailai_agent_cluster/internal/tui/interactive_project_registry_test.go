package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// projectRegistryStub adds the project catalog seam and the two registration
// capabilities to the shared interactive fixture, so the registry mutations can
// be driven through the real REPL.
type projectRegistryStub struct {
	*interactiveStub
	catalogCalls int
	catalog      protocol.ProjectCatalog
}

// GetCapabilities advertises the registration operations for focused tests.
func (s *projectRegistryStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{
		{Name: protocol.OperationProjectList},
		{Name: protocol.OperationProjectAdd},
		{Name: protocol.OperationProjectRemove},
	}}, nil
}

// GetProjectCatalog serves one deterministic catalog and counts the reads, so a
// test can prove a row selector never re-reads the catalog.
func (s *projectRegistryStub) GetProjectCatalog(context.Context, string) (protocol.ProjectCatalog, error) {
	s.catalogCalls++
	return s.catalog, nil
}

// projectRegistryFixture serves two projects on the first endpoint.
func projectRegistryFixture() *projectRegistryStub {
	return &projectRegistryStub{
		interactiveStub: scopeStub(),
		catalog: protocol.ProjectCatalog{
			Projects: []protocol.Project{
				{ProjectID: "prj_alpha", Name: "Alpha", Path: "/work/alpha"},
				{ProjectID: "prj_beta", Name: "Beta", Path: "/work/beta"},
			},
		},
	}
}

// TestProjectRemoveResolvesARenderedRowLocally proves a row number addresses the
// project the operator saw, carries the exact provider path in the opaque slot,
// and never re-reads the catalog to resolve a number.
func TestProjectRemoveResolvesARenderedRowLocally(t *testing.T) {
	stub := projectRegistryFixture()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nproject\nproject remove 2\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d, want 1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationProjectRemove || intent.EndpointID != "endpoint-1" {
		t.Fatalf("wrong remove intent: %+v", intent)
	}
	if intent.Target == nil || intent.Target.ResourceID != "prj_beta" || intent.Target.Kind != "project" {
		t.Fatalf("wrong remove target: %+v", intent.Target)
	}
	if intent.Target.ProviderGeneration != "" {
		t.Fatalf("remove must not carry a generation: %+v", intent.Target)
	}
	if !strings.Contains(intent.Target.ProviderTarget, "/work/beta") {
		t.Fatalf("opaque slot does not carry the exact provider path: %q", intent.Target.ProviderTarget)
	}
	if stub.catalogCalls != 1 {
		t.Fatalf("catalog reads=%d, want 1 (the render only)", stub.catalogCalls)
	}
	if !strings.Contains(output, "the folder is not deleted") {
		t.Fatalf("confirmation does not state the folder survives: %q", output)
	}
}

// TestProjectRemoveResolvesAProjectIDFromAFreshCatalog proves a named project ID
// is resolved against a fresh catalog read, because the operator may name a
// project the current table does not show.
func TestProjectRemoveResolvesAProjectIDFromAFreshCatalog(t *testing.T) {
	stub := projectRegistryFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nproject remove prj_alpha\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d, want 1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Target == nil || intent.Target.ResourceID != "prj_alpha" {
		t.Fatalf("wrong remove target: %+v", intent.Target)
	}
	if !strings.Contains(intent.Target.ProviderTarget, "/work/alpha") {
		t.Fatalf("opaque slot does not carry the exact provider path: %q", intent.Target.ProviderTarget)
	}
}

// TestProjectRemoveRefusesARowWithoutARenderedCatalog proves a row number is a
// position in a table the operator saw, so it is refused when no catalog was
// rendered instead of being guessed.
func TestProjectRemoveRefusesARowWithoutARenderedCatalog(t *testing.T) {
	stub := projectRegistryFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nproject remove 1\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "no project catalog has been rendered") {
		t.Fatalf("refusal does not name the missing catalog: %q", diagnostics)
	}
}

// TestProjectRemoveRefusesAnUnknownProjectID proves an identifier that is not in
// the catalog is refused locally, before any intent is submitted.
func TestProjectRemoveRefusesAnUnknownProjectID(t *testing.T) {
	stub := projectRegistryFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nproject remove prj_missing\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "is not in the current catalog") {
		t.Fatalf("refusal does not name the unknown project: %q", diagnostics)
	}
}

// TestProjectAddSubmitsATargetlessIntent proves registration carries no target,
// because the resource does not exist yet, and forwards the folder verbatim so
// the Endpoint alone decides whether it is acceptable.
func TestProjectAddSubmitsATargetlessIntent(t *testing.T) {
	stub := projectRegistryFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nproject add /work/gamma gamma\ny\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted=%d, want 1", stub.admit)
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationProjectAdd || intent.EndpointID != "endpoint-1" {
		t.Fatalf("wrong add intent: %+v", intent)
	}
	if intent.Target != nil {
		t.Fatalf("add must carry no target: %+v", intent.Target)
	}
	payload := string(intent.Payload)
	if !strings.Contains(payload, "/work/gamma") || !strings.Contains(payload, "gamma") {
		t.Fatalf("payload does not carry the folder and name: %q", payload)
	}
}

// TestProjectAddRefusesAnEmptyFolder proves the usage error is reported locally
// instead of submitting a payload the Endpoint would refuse.
func TestProjectAddRefusesAnEmptyFolder(t *testing.T) {
	stub := projectRegistryFixture()
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nproject add\nexit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
	if !strings.Contains(diagnostics, "usage: project add <folder> [name]") {
		t.Fatalf("refusal does not state the grammar: %q", diagnostics)
	}
}
