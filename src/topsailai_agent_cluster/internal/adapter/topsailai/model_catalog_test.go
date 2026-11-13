package topsailai

import (
	"context"
	"errors"
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
//
// The catalog now makes two provider calls, so the assertion reads the first one.
// A runner that records only the last argv would silently assert the current-model
// read instead of the registry read, which is the surface this test exists to pin.
func TestModelCatalogInvokesTheProviderJSONSurface(t *testing.T) {
	runner := &perCallRunner{answers: [][]byte{[]byte(`[]`)}}
	instance := messagesAdapter(t, runner)
	sessionID := mintSession(t, instance)
	if _, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID)); err != nil {
		t.Fatal(err)
	}
	if len(runner.calls) == 0 {
		t.Fatal("the catalog must invoke the provider")
	}
	want := []string{"models", "list", "--json"}
	first := runner.calls[0]
	if len(first) != len(want) {
		t.Fatalf("expected argv %v, got %v", want, first)
	}
	for index := range want {
		if first[index] != want[index] {
			t.Fatalf("expected argv %v, got %v", want, first)
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

// TestModelCatalogReportsTheObservedCurrentProfile proves the catalog names the
// profile the session is using now.
//
// The registry document cannot answer this, so the adapter reads the provider's
// registered `agent.llm` instruction. This is the regression guard for the defect
// where the column was always empty: the assertion names the exact expected value
// per row, because a test that only asserted "not unknown" would pass on a catalog
// that marked every row current.
func TestModelCatalogReportsTheObservedCurrentProfile(t *testing.T) {
	runner := &perCallRunner{
		answers: [][]byte{
			[]byte(`[{"id":"m1","name":"claude","protocol":"openai-compatible"},{"id":"m2","name":"gpt","protocol":"openai-compatible"},{"id":"m3","name":"legacy","protocol":"openai-compatible","enabled":false}]`),
			[]byte(`{"ok":true,"exit_code":0,"delivery_state":"control_acknowledged","error_code":null,"response":{"status":"ok","result":"gpt"}}`),
		},
	}
	instance := messagesAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err != nil {
		t.Fatal(err)
	}
	if len(catalog.Profiles) != 3 {
		t.Fatalf("expected 3 profiles, got %d", len(catalog.Profiles))
	}
	want := []string{protocol.ModelCurrentNo, protocol.ModelCurrentYes, protocol.ModelCurrentNo}
	for index, profile := range catalog.Profiles {
		if profile.CurrentState != want[index] {
			t.Fatalf("profile %d (%s) current state = %q, want %q", index, profile.ProviderDisplayName, profile.CurrentState, want[index])
		}
		if err := protocol.ValidateModelCurrentState(profile.CurrentState); err != nil {
			t.Fatalf("profile %d published an invalid current state: %v", index, err)
		}
	}
}

// TestModelCatalogReadsTheCurrentModelThroughTheRegisteredInstruction proves the
// second read uses the provider's own instruction surface and the same argv shape
// as model selection, so the two call sites cannot drift.
func TestModelCatalogReadsTheCurrentModelThroughTheRegisteredInstruction(t *testing.T) {
	runner := &perCallRunner{
		answers: [][]byte{
			[]byte(`[{"id":"m1","name":"claude","protocol":"openai-compatible"}]`),
			[]byte(`{"ok":true,"response":{"status":"ok","result":"claude"}}`),
		},
	}
	instance := messagesAdapter(t, runner)
	sessionID := mintSession(t, instance)
	if _, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID)); err != nil {
		t.Fatal(err)
	}
	if len(runner.calls) != 2 {
		t.Fatalf("expected 2 provider calls, got %d: %v", len(runner.calls), runner.calls)
	}
	wantFirst := []string{"models", "list", "--json"}
	for index := range wantFirst {
		if runner.calls[0][index] != wantFirst[index] {
			t.Fatalf("first call = %v, want %v", runner.calls[0], wantFirst)
		}
	}
	second := runner.calls[1]
	if len(second) < 5 || second[0] != "runtime" || second[1] != "control" || second[2] != "call_instruction" {
		t.Fatalf("second call = %v, want the runtime control call_instruction surface", second)
	}
	payload := ""
	for index := 0; index+1 < len(second); index++ {
		if second[index] == "-a" {
			payload = second[index+1]
			break
		}
	}
	if payload == "" {
		t.Fatalf("second call = %v, want an -a payload", second)
	}
	if !strings.Contains(payload, `"instruction":"agent.llm"`) {
		t.Fatalf("second call payload = %q, want the agent.llm instruction", payload)
	}
}

// TestModelCatalogKeepsEveryProfileUnknownWhenTheCurrentReadFails proves an
// unavailable observation degrades to unknown instead of failing the catalog.
//
// The menu is still usable without the current-model fact, so taking it away
// because one observation failed would remove a capability the operator needs.
// Every row must stay unknown: reporting "no" for all of them would be a definite
// negative the evidence does not support.
func TestModelCatalogKeepsEveryProfileUnknownWhenTheCurrentReadFails(t *testing.T) {
	cases := []struct {
		name    string
		answer  []byte
		runErr  error
		comment string
	}{
		{name: "provider error", answer: nil, runErr: errors.New("provider failed"), comment: "a failed invocation"},
		{name: "not ok", answer: []byte(`{"ok":false,"error_code":"control_failed"}`), comment: "a refused instruction"},
		{name: "no response", answer: []byte(`{"ok":true}`), comment: "a missing response document"},
		{name: "not ok status", answer: []byte(`{"ok":true,"response":{"status":"error","result":"claude"}}`), comment: "a non-ok status"},
		{name: "empty result", answer: []byte(`{"ok":true,"response":{"status":"ok","result":""}}`), comment: "an empty result"},
		{name: "malformed", answer: []byte(`not json`), comment: "an undecodable document"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			runner := &perCallRunner{
				answers: [][]byte{
					[]byte(`[{"id":"m1","name":"claude","protocol":"openai-compatible"},{"id":"m2","name":"gpt","protocol":"openai-compatible"}]`),
					testCase.answer,
				},
				errs: []error{nil, testCase.runErr},
			}
			instance := messagesAdapter(t, runner)
			sessionID := mintSession(t, instance)
			catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
			if err != nil {
				t.Fatalf("%s must not fail the catalog: %v", testCase.comment, err)
			}
			if len(catalog.Profiles) != 2 {
				t.Fatalf("expected 2 profiles, got %d", len(catalog.Profiles))
			}
			for index, profile := range catalog.Profiles {
				if profile.CurrentState != protocol.ModelCurrentUnknown {
					t.Fatalf("profile %d current state = %q, want %q for %s", index, profile.CurrentState, protocol.ModelCurrentUnknown, testCase.comment)
				}
			}
		})
	}
}

// TestModelCatalogReportsNoProfileWhenTheCurrentModelIsUnlisted proves an observed
// current model that matches no published profile marks every row "no".
//
// The provider can report a model the registry does not list, for example after a
// registry edit while the session keeps running. The observation is real, so the
// answer is a definite "no" for every published profile: the session is using
// something else. Reporting "unknown" here would throw away an observation the
// Endpoint actually made, and "unknown" must stay reserved for "not observed".
func TestModelCatalogReportsNoProfileWhenTheCurrentModelIsUnlisted(t *testing.T) {
	runner := &perCallRunner{
		answers: [][]byte{
			[]byte(`[{"id":"m1","name":"claude","protocol":"openai-compatible"}]`),
			[]byte(`{"ok":true,"response":{"status":"ok","result":"retired-model"}}`),
		},
	}
	instance := messagesAdapter(t, runner)
	sessionID := mintSession(t, instance)
	catalog, err := instance.ModelCatalog(context.Background(), modelCatalogQuery(sessionID))
	if err != nil {
		t.Fatal(err)
	}
	if len(catalog.Profiles) != 1 {
		t.Fatalf("expected 1 profile, got %d", len(catalog.Profiles))
	}
	if catalog.Profiles[0].CurrentState != protocol.ModelCurrentNo {
		t.Fatalf("current state = %q, want %q for an observed but unlisted current model", catalog.Profiles[0].CurrentState, protocol.ModelCurrentNo)
	}
}
