package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// modelReadStub records the generation the catalog read actually sent, so a test
// can prove what the wire carried instead of inferring it from the rendered table.
// A stub that only returned a catalog would pass whether or not the generation was
// forwarded, which is exactly the defect this fixture exists to catch.
type modelReadStub struct {
	*interactiveStub
	catalog           protocol.ModelCatalog
	catalogCalls      int
	catalogEndpoint   string
	catalogResource   string
	catalogGeneration string
	// catalogProviderTarget records the opaque slot unchanged.
	catalogProviderTarget string
}

// GetCapabilities advertises the model operations so the command reaches the read
// seam instead of being refused as an unsupported capability.
func (s *modelReadStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{
		Revision: "r-model-read",
		Capabilities: []protocol.Capability{
			{Name: protocol.OperationAgentModelList},
			{Name: protocol.OperationAgentModelSelect},
		},
	}, nil
}

// GetModelCatalog records the exact arguments of the read and answers with one
// selectable profile.
func (s *modelReadStub) GetModelCatalog(_ context.Context, endpointID string, query protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	s.catalogCalls++
	s.catalogEndpoint = endpointID
	s.catalogResource = query.Target.ResourceID
	s.catalogGeneration = query.Target.ProviderGeneration
	s.catalogProviderTarget = query.Target.ProviderTarget
	return s.catalog, nil
}

// modelReadStubFixture serves one endpoint whose first session is unverified and
// whose second session is live, so the same command can be exercised against both
// kinds of row.
func modelReadStubFixture() *modelReadStub {
	report := protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{
			{
				ClusterSessionID:    "res-unverified",
				ProviderSessionID:   "20261111094237",
				ProviderTarget:      `{"row":"unverified"}`,
				ProviderDisplayName: "unverified work",
				AdapterID:           "adapter-1",
				ProviderGeneration:  "",
				State:               protocol.SessionStateUnknown,
				StateReason:         protocol.StateReasonLivenessUnverified,
				CollectionStatus:    protocol.CollectionSucceeded,
			},
			{
				ClusterSessionID:    "res-live",
				ProviderSessionID:   "20261111094238",
				ProviderTarget:      `{"row":"live"}`,
				ProviderDisplayName: "live work",
				AdapterID:           "adapter-1",
				ProviderGeneration:  "generation-live",
				State:               "running",
				CollectionStatus:    protocol.CollectionSucceeded,
			},
		},
	}
	return &modelReadStub{
		interactiveStub: &interactiveStub{
			endpoints: []protocol.Endpoint{
				{EndpointID: "endpoint-1", Hostname: "host-one", ConnectionState: "online"},
			},
			reports: map[string]protocol.InventoryReport{"endpoint-1": report},
		},
		catalog: protocol.ModelCatalog{
			Profiles: []protocol.ModelProfile{
				{ModelProfileID: "mp-1", ProviderDisplayName: "claude", Available: true},
			},
			CurrentProfileID: "mp-1",
			ObservedAtMS:     1700000000000,
		},
	}
}

// TestModelListsProfilesForUnverifiedRow proves a catalog read reaches an
// unverified session and sends an empty generation.
//
// The row is visible in the list, so refusing to list its profiles would leave the
// operator unable to inspect the one session most likely to need attention. The
// generation assertion is the load-bearing half: an empty generation is what proves
// the read no longer claims to address a live process.
func TestModelListsProfilesForUnverifiedRow(t *testing.T) {
	stub := modelReadStubFixture()
	output, diagnostics := runScope(t, stub, "list\nmodel 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.catalogCalls != 1 {
		t.Fatalf("catalog calls=%d, want 1", stub.catalogCalls)
	}
	if stub.catalogEndpoint != "endpoint-1" {
		t.Fatalf("catalog endpoint=%q, want endpoint-1", stub.catalogEndpoint)
	}
	if stub.catalogResource != "res-unverified" {
		t.Fatalf("catalog resource=%q, want res-unverified", stub.catalogResource)
	}
	if stub.catalogGeneration != "" {
		t.Fatalf("catalog generation=%q, want empty for a read", stub.catalogGeneration)
	}
	if !strings.Contains(output, "claude") {
		t.Fatalf("missing rendered profile: %q", output)
	}
}

// TestModelCatalogHidesProfileIDInTheInteractiveRender proves the interactive
// catalog prints no MODEL_PROFILE_ID column.
//
// The layout function can drop the column, but only the caller decides whether it
// does, so a test of the layout alone passes while the REPL still prints the opaque
// value. This drives the real REPL and asserts the rendered header, which is the
// only evidence that the flag reached the renderer. The standalone command keeps the
// column on purpose, so the assertion is scoped to the interactive surface.
func TestModelCatalogHidesProfileIDInTheInteractiveRender(t *testing.T) {
	stub := modelReadStubFixture()
	output, diagnostics := runScope(t, stub, "list\nmodel 2\n\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "MODEL") {
		t.Fatalf("the catalog table was not rendered: %q", output)
	}
	if strings.Contains(output, "MODEL_PROFILE_ID") {
		t.Fatalf("the interactive catalog still prints the MODEL_PROFILE_ID column: %q", output)
	}
}

// TestModelDoesNotOfferSelectionForUnverifiedRow proves the guided question is not
// asked when no profile can be applied.
//
// Listing the catalog is a read, but applying a profile is a mutation and a mutation
// needs a generation. Offering the choice would produce a refusal after the operator
// answered, which reads as a fault rather than as a refused capability.
func TestModelDoesNotOfferSelectionForUnverifiedRow(t *testing.T) {
	stub := modelReadStubFixture()
	output, diagnostics := runScope(t, stub, "list\nmodel 1\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "select model profile") {
		t.Fatalf("guided selection was offered for an unverified row: %q", output)
	}
	if !strings.Contains(output, "use resume to resume it") {
		t.Fatalf("missing resume hint: %q", output)
	}
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
}

// TestModelOffersSelectionForLiveRow proves the guided selection still runs for a
// live row, so the suppression above is specific to an unverified target rather
// than a general loss of the convenient path.
func TestModelOffersSelectionForLiveRow(t *testing.T) {
	stub := modelReadStubFixture()
	output, diagnostics := runScope(t, stub, "list\nmodel 2\n\nexit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "select model profile") {
		t.Fatalf("guided selection was not offered for a live row: %q", output)
	}
	if stub.catalogGeneration != "" {
		t.Fatalf("catalog generation=%q, want empty for a read", stub.catalogGeneration)
	}
	if !strings.Contains(output, "model unchanged") {
		t.Fatalf("missing unchanged notice: %q", output)
	}
}

// TestModelSelectStillRequiresGeneration proves the mutation keeps the strict
// resolver. Relaxing the read must not relax the write, because applying a profile
// addresses a live process and an empty generation cannot prove which one.
func TestModelSelectStillRequiresGeneration(t *testing.T) {
	stub := modelReadStubFixture()
	_, diagnostics := runScope(t, stub, "list\nmodel 1 mp-1\nexit\n", ColorPolicy{})
	if !strings.Contains(diagnostics, "unverified") {
		t.Fatalf("model select on an unverified row was not refused: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("admitted=%d, want 0", stub.admit)
	}
}
