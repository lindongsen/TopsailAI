package topsailai

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// modelCatalogQuery builds one catalog read for a mapped session.
func modelCatalogQuery(sessionID string) protocol.ModelCatalogQuery {
	return protocol.ModelCatalogQuery{Target: protocol.CommandTarget{Kind: "session", ResourceID: sessionID}}
}

// TestModelCatalogListsProfilesWithOpaqueIDs proves the catalog publishes opaque
// identifiers and never a provider name as the addressing key.
func TestModelCatalogListsProfilesWithOpaqueIDs(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[{"id":"m1","name":"claude","protocol":"openai-compatible","model":"claude-3"},{"id":"m2","name":"gpt","protocol":"openai-compatible","model":"gpt-4"}]`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err != nil {
		t.Fatal(err)
	}
	if len(catalog.Profiles) != 2 {
		t.Fatalf("expected 2 profiles, got %d", len(catalog.Profiles))
	}
	if catalog.Profiles[0].ModelProfileID == "claude" {
		t.Fatal("the provider name must never be the addressing key")
	}
	if catalog.Profiles[0].ProviderDisplayName != "claude" {
		t.Fatalf("expected the display name claude, got %q", catalog.Profiles[0].ProviderDisplayName)
	}
	if !catalog.Profiles[0].Available {
		t.Fatal("an enabled supported profile must be available")
	}
	if catalog.ObservedAtMS == 0 {
		t.Fatal("a catalog read must carry its observation time")
	}
}

// TestModelCatalogInvokesTheProviderJSONSurface proves the adapter consumes the
// provider's machine-readable list rather than parsing human text.
func TestModelCatalogInvokesTheProviderJSONSurface(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[]`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	if _, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID)); err != nil {
		t.Fatal(err)
	}
	want := []string{"models", "list", "--json"}
	if len(runner.args) != len(want) {
		t.Fatalf("expected argv %v, got %v", want, runner.args)
	}
	for index := range want {
		if runner.args[index] != want[index] {
			t.Fatalf("expected argv %v, got %v", want, runner.args)
		}
	}
}

// TestModelCatalogEmptyIsNotAnError proves an empty registry is a real answer.
//
// This is the distinction the whole read path exists to preserve: a session with
// no configured profile must not look like an adapter that cannot answer.
func TestModelCatalogEmptyIsNotAnError(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[]`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err != nil {
		t.Fatalf("an empty catalog is a real answer, got error %v", err)
	}
	if len(catalog.Profiles) != 0 {
		t.Fatalf("expected no profiles, got %d", len(catalog.Profiles))
	}
	if catalog.ErrorCode != "" {
		t.Fatalf("an empty catalog must carry no error code, got %q", catalog.ErrorCode)
	}
}

// TestModelCatalogKeepsDisabledProfilesVisible proves a disabled entry stays in
// the menu with its reason instead of disappearing.
func TestModelCatalogKeepsDisabledProfilesVisible(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[{"id":"m1","name":"legacy","protocol":"openai-compatible","enabled":false}]`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err != nil {
		t.Fatal(err)
	}
	if len(catalog.Profiles) != 1 {
		t.Fatalf("a disabled profile must stay visible, got %d profiles", len(catalog.Profiles))
	}
	if catalog.Profiles[0].Available {
		t.Fatal("a disabled profile must not be available")
	}
	if catalog.Profiles[0].UnavailableReason != protocol.ModelProfileDisabled {
		t.Fatalf("expected reason %q, got %q", protocol.ModelProfileDisabled, catalog.Profiles[0].UnavailableReason)
	}
}

// TestModelCatalogOmitsEnabledFieldMeansAvailable proves an omitted enabled field
// is read as enabled.
//
// The provider emits enabled only when the entry is disabled, so a plain bool
// would mark every healthy profile unavailable.
func TestModelCatalogOmitsEnabledFieldMeansAvailable(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[{"id":"m1","name":"claude","protocol":"openai-compatible"}]`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err != nil {
		t.Fatal(err)
	}
	if !catalog.Profiles[0].Available {
		t.Fatal("an omitted enabled field must be read as enabled")
	}
}

// TestModelCatalogMarksUnsupportedProtocolUnavailable proves a profile the
// provider cannot run is reported unavailable rather than offered.
func TestModelCatalogMarksUnsupportedProtocolUnavailable(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[{"id":"m1","name":"odd","protocol":"anthropic-native"}]`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err != nil {
		t.Fatal(err)
	}
	if catalog.Profiles[0].Available {
		t.Fatal("a profile with an unsupported protocol must not be available")
	}
	if catalog.Profiles[0].UnavailableReason != protocol.ModelProfileUnsupportedProtocol {
		t.Fatalf("expected reason %q, got %q", protocol.ModelProfileUnsupportedProtocol, catalog.Profiles[0].UnavailableReason)
	}
}

// TestModelCatalogCollapsesDuplicateNames proves two entries sharing a name yield
// one profile.
//
// The provider keys its registry by name, so a duplicate name resolves to one
// selectable model. Minting one identifier per entry would publish the same
// identifier twice and show two rows that select the same thing.
func TestModelCatalogCollapsesDuplicateNames(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[{"id":"m1","name":"claude","protocol":"openai-compatible"},{"id":"m2","name":"claude","protocol":"openai-compatible"}]`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err != nil {
		t.Fatal(err)
	}
	if len(catalog.Profiles) != 1 {
		t.Fatalf("a duplicate provider name must collapse to one profile, got %d", len(catalog.Profiles))
	}
}

// TestModelCatalogRejectsAnOversizedDocument proves the byte bound is enforced
// before decoding, so an oversized document is labelled rather than parsed.
//
// The adapter is built with the production output bound rather than the small
// test bound, because the catalog bound is narrower than the runner bound: with a
// narrow runner bound the runner rejects the document first and the catalog bound
// is never reached, so the test would pass without exercising it.
func TestModelCatalogRejectsAnOversizedDocument(t *testing.T) {
	runner := &fakeRunner{out: []byte(strings.Repeat("x", protocol.MaxModelCatalogBytes+1))}
	instance, err := newWithRunner(Config{AdapterID: "a1", Executable: "/provider", MaxOutput: defaultMaxOut, ResourceMapper: newFakeMapper(), PlatformProbe: func() (PlatformCapabilities, error) {
		return PlatformCapabilities{ProcAvailable: true, PidfdAvailable: true}, nil
	}}, runner)
	if err != nil {
		t.Fatal(err)
	}
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err == nil {
		t.Fatal("an oversized catalog must be rejected")
	}
	if catalog.ErrorCode != protocol.ModelCatalogTooLarge {
		t.Fatalf("expected code %q, got %q", protocol.ModelCatalogTooLarge, catalog.ErrorCode)
	}
}

// TestModelCatalogRejectsAProfileAsTheTarget proves a profile identifier cannot be
// used as the session target.
//
// Profiles and sessions share one mapping table, so a profile identifier would
// otherwise resolve and be treated as a session.
func TestModelCatalogRejectsAProfileAsTheTarget(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[]`)}
	instance := newTestAdapter(t, runner)
	profileID, err := instance.resourceID(context.Background(), modelProviderKeyPrefix+"claude")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(profileID)); err == nil {
		t.Fatal("a model profile must not be accepted as a session target")
	}
}

// TestModelCatalogRejectsANonSessionKind proves the target kind is checked before
// the mapping is consulted.
func TestModelCatalogRejectsANonSessionKind(t *testing.T) {
	runner := &fakeRunner{out: []byte(`[]`)}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	query := protocol.ModelCatalogQuery{Target: protocol.CommandTarget{Kind: "endpoint", ResourceID: sessionID}}
	if _, err := instance.ModelCatalog(context.Background(), query); err == nil {
		t.Fatal("a non-session target must be rejected")
	}
}

// TestModelCatalogReportsProviderFailure proves a failed provider call is labelled
// as a provider error rather than returned as an empty catalog.
func TestModelCatalogReportsProviderFailure(t *testing.T) {
	runner := &fakeRunner{out: []byte(``), err: errModelProfileUnknown}
	instance := newTestAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err == nil {
		t.Fatal("a provider failure must be reported")
	}
	if catalog.ErrorCode != protocol.ModelCatalogProviderError {
		t.Fatalf("expected code %q, got %q", protocol.ModelCatalogProviderError, catalog.ErrorCode)
	}
}

// TestDescribeDeclaresModelListAsReadOnlyView proves the read capability is
// advertised separately from the write capability.
//
// A credential that may look at the menu must not thereby be able to change the
// model, so the two operations must not share a permission.
func TestDescribeDeclaresModelListAsReadOnlyView(t *testing.T) {
	descriptor, err := newTestAdapter(t, &fakeRunner{}).Describe(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	var list, selectCapability *protocol.Capability
	for index := range descriptor.Capabilities.Capabilities {
		capability := &descriptor.Capabilities.Capabilities[index]
		switch capability.Name {
		case protocol.OperationAgentModelList:
			list = capability
		case protocol.OperationAgentModelSelect:
			selectCapability = capability
		}
	}
	if list == nil {
		t.Fatal("agent.model.list must be advertised")
	}
	if selectCapability == nil {
		t.Fatal("agent.model.select must be advertised")
	}
	if list.SafetyClass != protocol.SafetyClassReadOnly {
		t.Fatalf("expected the read-only safety class, got %q", list.SafetyClass)
	}
	if list.RequiredPermission != "view" {
		t.Fatalf("expected the view permission, got %q", list.RequiredPermission)
	}
	if selectCapability.RequiredPermission == list.RequiredPermission {
		t.Fatal("reading the menu and changing the model must not share a permission")
	}
}

// TestControlActionsUseTheSafetyClassVocabulary proves the control family no
// longer hardcodes a bare string.
func TestControlActionsUseTheSafetyClassVocabulary(t *testing.T) {
	set, err := ParseControlActionSet([]byte(`{"actions":[{"name":"demo","permission":"control","command":["runtime","control","demo","-s","{session}","--json"]}]}`))
	if err != nil {
		t.Fatal(err)
	}
	capabilities := controlActionCapabilities(set)
	if len(capabilities) != 1 {
		t.Fatalf("expected 1 capability, got %d", len(capabilities))
	}
	if err := protocol.ValidateSafetyClass(capabilities[0].SafetyClass); err != nil {
		t.Fatalf("a control action must declare a valid safety class: %v", err)
	}
}
