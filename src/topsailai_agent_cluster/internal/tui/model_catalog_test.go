package tui

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// modelCatalogStubAPI implements CommandAPI plus the optional ModelCatalogQuerier
// seam, so a test can prove the catalog reached the renderer.
type modelCatalogStubAPI struct {
	endpoints []protocol.Endpoint
	catalog   protocol.ModelCatalog
	err       error
	// calls records every seam invocation, so a test can prove the read happened
	// exactly once and with the arguments the caller supplied.
	calls []string
	// generations records the generation of every read, so a test can prove the
	// standalone path passes an empty generation instead of inventing one.
	generations []string
}

func (s *modelCatalogStubAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return s.endpoints, nil
}

func (s *modelCatalogStubAPI) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{}, nil
}

func (s *modelCatalogStubAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{}, nil
}

func (s *modelCatalogStubAPI) GetCommand(context.Context, string) (map[string]any, error) {
	return nil, nil
}

func (s *modelCatalogStubAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}

func (s *modelCatalogStubAPI) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (s *modelCatalogStubAPI) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	return nil, nil
}

func (s *modelCatalogStubAPI) GetModelCatalog(_ context.Context, endpointID, resourceID, generation string) (protocol.ModelCatalog, error) {
	s.calls = append(s.calls, endpointID+"/"+resourceID)
	s.generations = append(s.generations, generation)
	if s.err != nil {
		return protocol.ModelCatalog{}, s.err
	}
	return s.catalog, nil
}

// modelCataloglessAPI implements CommandAPI without the catalog seam, so the
// runner must report the missing capability instead of rendering an empty table.
// It deliberately does not embed modelCatalogStubAPI, because an embedded
// GetModelCatalog would be promoted and the seam check would wrongly succeed.
type modelCataloglessAPI struct {
	endpoints []protocol.Endpoint
}

func (s *modelCataloglessAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return s.endpoints, nil
}

func (s *modelCataloglessAPI) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{}, nil
}

func (s *modelCataloglessAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{}, nil
}

func (s *modelCataloglessAPI) GetCommand(context.Context, string) (map[string]any, error) {
	return nil, nil
}

func (s *modelCataloglessAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}

func (s *modelCataloglessAPI) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (s *modelCataloglessAPI) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	return nil, nil
}

// onlineEndpoint is the minimal endpoint the shared resolver accepts.
func onlineEndpoint(id, hostname string) protocol.Endpoint {
	return protocol.Endpoint{EndpointID: id, Hostname: hostname, ConnectionState: "online"}
}

// TestModelCatalogMissingSeamIsNotAnEmptyCatalog proves a client that cannot
// answer is reported as a missing capability. An empty table would read as "this
// session offers no profile", which is a different and false statement.
func TestModelCatalogMissingSeamIsNotAnEmptyCatalog(t *testing.T) {
	api := &modelCataloglessAPI{endpoints: []protocol.Endpoint{onlineEndpoint("ep-1", "host-1")}}
	var out, errOut bytes.Buffer

	err := legacyRunnerForTest(api).ModelCatalog(context.Background(), &out, &errOut, "ep-1", "res_1", "", false, TableOptions{})
	if err == nil {
		t.Fatalf("expected an error, got an empty catalog rendered as %q", out.String())
	}
	if !strings.Contains(err.Error(), "cannot query model profiles") {
		t.Fatalf("error = %q, want it to name the missing capability", err.Error())
	}
	if out.Len() != 0 {
		t.Fatalf("expected no table, got %q", out.String())
	}
}

// TestModelCatalogEmptyIsNotUnsupported proves an empty catalog and an
// unsupported catalog stay distinguishable. Both carry zero profiles, so only the
// error code and the wording separate "no profiles configured" from "no adapter
// can answer".
func TestModelCatalogEmptyIsNotUnsupported(t *testing.T) {
	empty := &modelCatalogStubAPI{
		endpoints: []protocol.Endpoint{onlineEndpoint("ep-1", "host-1")},
		catalog:   protocol.ModelCatalog{Profiles: nil, ObservedAtMS: 7},
	}
	var out, errOut bytes.Buffer
	if err := legacyRunnerForTest(empty).ModelCatalog(context.Background(), &out, &errOut, "ep-1", "res_1", "", false, TableOptions{}); err != nil {
		t.Fatalf("an empty catalog must not be an error: %v", err)
	}
	if !strings.Contains(out.String(), "offers no selectable model profile") {
		t.Fatalf("empty catalog output = %q, want it stated plainly", out.String())
	}

	unsupported := &modelCatalogStubAPI{
		endpoints: []protocol.Endpoint{onlineEndpoint("ep-1", "host-1")},
		catalog:   protocol.ModelCatalog{ErrorCode: protocol.ModelCatalogUnsupported},
	}
	var unsupportedOut, unsupportedErr bytes.Buffer
	err := legacyRunnerForTest(unsupported).ModelCatalog(context.Background(), &unsupportedOut, &unsupportedErr, "ep-1", "res_1", "", false, TableOptions{})
	if err == nil {
		t.Fatalf("an unsupported catalog must be an error, got %q", unsupportedOut.String())
	}
	// The contract is that the two conditions are distinguishable, not that the
	// machine code appears verbatim: an operator needs a remedy, and "no adapter
	// can answer" is an integration gap rather than a configuration choice.
	if !strings.Contains(err.Error(), "no model-catalog-capable adapter") {
		t.Fatalf("error = %q, want it to name the integration gap", err.Error())
	}
	if strings.Contains(unsupportedOut.String(), "offers no selectable model profile") {
		t.Fatalf("an unsupported catalog must not be reported as an empty one: %q", unsupportedOut.String())
	}
}

// TestModelCatalogRowsAreNumberedFromOne proves the rendered row numbers are the
// values an operator types, and that they start at one rather than at zero.
func TestModelCatalogRowsAreNumberedFromOne(t *testing.T) {
	catalog := protocol.ModelCatalog{
		CurrentProfileID: "mp-2",
		Profiles: []protocol.ModelProfile{
			{ModelProfileID: "mp-1", DisplayName: "fast", Available: true},
			{ModelProfileID: "mp-2", DisplayName: "deep", Available: true, Current: true},
			{ModelProfileID: "mp-3", DisplayName: "legacy", Available: false, UnavailableReason: protocol.ModelProfileDisabled},
		},
	}
	view := NewModelCatalogView("ep-1", "res_1", catalog)
	if len(view.Rows) != 3 {
		t.Fatalf("rows = %d, want 3", len(view.Rows))
	}
	for i, row := range view.Rows {
		if row.No != i+1 {
			t.Fatalf("row %d number = %d, want %d", i, row.No, i+1)
		}
	}
	if view.Rows[2].ModelProfileID != "mp-3" {
		t.Fatalf("row 3 profile = %q, want mp-3", view.Rows[2].ModelProfileID)
	}
	if view.CurrentProfileID != "mp-2" {
		t.Fatalf("current profile = %q, want mp-2", view.CurrentProfileID)
	}
}

// TestModelCatalogUnavailableProfileStaysVisible proves an unavailable profile is
// still listed with its reason. The operator asked which profiles exist, so
// hiding one would answer a different question.
func TestModelCatalogUnavailableProfileStaysVisible(t *testing.T) {
	catalog := protocol.ModelCatalog{Profiles: []protocol.ModelProfile{
		{ModelProfileID: "mp-1", DisplayName: "legacy", Available: false, UnavailableReason: protocol.ModelProfileDisabled},
	}}
	view := NewModelCatalogView("ep-1", "res_1", catalog)
	if len(view.Rows) != 1 {
		t.Fatalf("rows = %d, want the unavailable profile to stay visible", len(view.Rows))
	}
	if view.Rows[0].Available {
		t.Fatalf("row must stay unavailable")
	}
	if view.Rows[0].UnavailableReason != protocol.ModelProfileDisabled {
		t.Fatalf("reason = %q, want %q", view.Rows[0].UnavailableReason, protocol.ModelProfileDisabled)
	}
}

// TestModelCatalogHidesProfileIDColumn proves the opaque profile ID column is
// dropped when the caller asked for a narrow table, so the row number and the
// display name remain readable.
func TestModelCatalogHidesProfileIDColumn(t *testing.T) {
	wide := layoutModelCatalogColumns(TableOptions{})
	if !hasColumn(wide, columnID) {
		t.Fatalf("wide layout must keep %q", columnID)
	}
	narrow := layoutModelCatalogColumns(TableOptions{HideSessionID: true})
	if hasColumn(narrow, columnID) {
		t.Fatalf("narrow layout must drop %q", columnID)
	}
	if !hasColumn(narrow, columnNo) || !hasColumn(narrow, columnName) {
		t.Fatalf("narrow layout must keep the row number and the display name: %#v", narrow)
	}
}

// hasColumn reports whether a column key is present in a layout.
func hasColumn(columns []tableColumn, key string) bool {
	for _, column := range columns {
		if column.key == key {
			return true
		}
	}
	return false
}

// TestModelAliasResolvesButIsNotCompletable proves "m" dispatches to "model"
// while staying out of the completion list. A one-character alias is already
// complete when typed, so offering it would only create a false ambiguity.
func TestModelAliasResolvesButIsNotCompletable(t *testing.T) {
	if got := commandAliases["m"]; got != "model" {
		t.Fatalf(`commandAliases["m"] = %q, want "model"`, got)
	}
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession} {
		if !commandAllowed("model", kind) {
			t.Fatalf("model must be available in scope %v", kind)
		}
		for _, name := range completableCommands(kind) {
			if name == "m" {
				t.Fatalf("scope %v completion must not offer the one-character alias m", kind)
			}
		}
	}
}

// TestModelCatalogAcceptsHostnameAndRejectsAmbiguity proves the endpoint argument
// is resolved like history and messages: a unique hostname works, and a hostname
// shared by several endpoints is rejected with the candidate list instead of
// silently picking one.
func TestModelCatalogAcceptsHostnameAndRejectsAmbiguity(t *testing.T) {
	unique := &modelCatalogStubAPI{
		endpoints: []protocol.Endpoint{onlineEndpoint("ep-1", "host-1")},
		catalog:   protocol.ModelCatalog{Profiles: []protocol.ModelProfile{{ModelProfileID: "mp-1", DisplayName: "fast", Available: true}}},
	}
	var out, errOut bytes.Buffer
	if err := legacyRunnerForTest(unique).ModelCatalog(context.Background(), &out, &errOut, "host-1", "res_1", "", false, TableOptions{}); err != nil {
		t.Fatalf("a unique hostname must resolve: %v", err)
	}
	if len(unique.calls) != 1 || unique.calls[0] != "ep-1/res_1" {
		t.Fatalf("seam calls = %#v, want one read for ep-1/res_1", unique.calls)
	}

	ambiguous := &modelCatalogStubAPI{endpoints: []protocol.Endpoint{
		onlineEndpoint("ep-1", "shared"),
		onlineEndpoint("ep-2", "shared"),
	}}
	var ambiguousOut, ambiguousErr bytes.Buffer
	err := legacyRunnerForTest(ambiguous).ModelCatalog(context.Background(), &ambiguousOut, &ambiguousErr, "shared", "res_1", "", false, TableOptions{})
	if err == nil {
		t.Fatalf("an ambiguous hostname must be rejected")
	}
	if !strings.Contains(err.Error(), "ep-1, ep-2") {
		t.Fatalf("error = %q, want the sorted candidate list", err.Error())
	}
	if len(ambiguous.calls) != 0 {
		t.Fatalf("an ambiguous hostname must not reach the seam: %#v", ambiguous.calls)
	}
}

// TestModelCatalogPassesGenerationThrough proves the generation the caller
// supplies reaches the seam unchanged, so the interactive path can bind the read
// to the session it resolved while the standalone path passes none.
func TestModelCatalogPassesGenerationThrough(t *testing.T) {
	api := &modelCatalogStubAPI{
		endpoints: []protocol.Endpoint{onlineEndpoint("ep-1", "host-1")},
		catalog:   protocol.ModelCatalog{Profiles: []protocol.ModelProfile{{ModelProfileID: "mp-1", DisplayName: "fast", Available: true}}},
	}
	var out, errOut bytes.Buffer
	if err := legacyRunnerForTest(api).ModelCatalog(context.Background(), &out, &errOut, "ep-1", "res_1", "gen-9", false, TableOptions{}); err != nil {
		t.Fatalf("read failed: %v", err)
	}
	if len(api.generations) != 1 || api.generations[0] != "gen-9" {
		t.Fatalf("generations = %#v, want gen-9 forwarded unchanged", api.generations)
	}
}

// TestModelCatalogTruncationIsLabelled proves a shortened catalog is never
// presented as complete.
func TestModelCatalogTruncationIsLabelled(t *testing.T) {
	api := &modelCatalogStubAPI{
		endpoints: []protocol.Endpoint{onlineEndpoint("ep-1", "host-1")},
		catalog: protocol.ModelCatalog{
			Truncated: true,
			Profiles:  []protocol.ModelProfile{{ModelProfileID: "mp-1", DisplayName: "fast", Available: true}},
		},
	}
	var out, errOut bytes.Buffer
	if err := legacyRunnerForTest(api).ModelCatalog(context.Background(), &out, &errOut, "ep-1", "res_1", "", false, TableOptions{}); err != nil {
		t.Fatalf("read failed: %v", err)
	}
	// The contract is that a shortened catalog is never presented as complete, not
	// that a particular word is used. The diagnostic must say some profiles are
	// missing, so an operator cannot read the table as the full set.
	if !strings.Contains(errOut.String(), "not listed") {
		t.Fatalf("diagnostics = %q, want the shortened catalog labelled as incomplete", errOut.String())
	}
}

// legacyRunnerForTest builds the runner the standalone command uses.
func legacyRunnerForTest(api CommandAPI) CommandRunner {
	return CommandRunner{API: api, Policy: LegacyPolicy}
}
