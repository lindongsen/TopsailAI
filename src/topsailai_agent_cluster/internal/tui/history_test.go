package tui

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// historyStubAPI implements CommandAPI plus the optional HistoryQuerier seam.
type historyStubAPI struct {
	endpoints   []protocol.Endpoint
	reports     map[string]protocol.InventoryReport
	inventoryEr map[string]error
	history     map[string]protocol.HistoryResult
	historyEr   map[string]error
	calls       []string
	// limits records the caller limit of every history read, so a test can
	// prove the value reached the seam instead of being dropped on the way.
	limits []int
}

func (s *historyStubAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	s.calls = append(s.calls, "list")
	return s.endpoints, nil
}

func (s *historyStubAPI) GetInventory(_ context.Context, id string) (protocol.InventoryReport, error) {
	s.calls = append(s.calls, "inventory:"+id)
	if err := s.inventoryEr[id]; err != nil {
		return protocol.InventoryReport{}, err
	}
	return s.reports[id], nil
}

func (s *historyStubAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{}, nil
}

func (s *historyStubAPI) GetCommand(context.Context, string) (map[string]any, error) {
	return nil, nil
}

func (s *historyStubAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}

func (s *historyStubAPI) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (s *historyStubAPI) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	return nil, nil
}

func (s *historyStubAPI) GetHistory(_ context.Context, endpointID string, limit int) (protocol.HistoryResult, error) {
	s.calls = append(s.calls, "history:"+endpointID)
	s.limits = append(s.limits, limit)
	if err := s.historyEr[endpointID]; err != nil {
		return protocol.HistoryResult{}, err
	}
	return s.history[endpointID], nil
}

// historylessAPI implements CommandAPI without the history seam, so the runner
// must report the missing capability instead of returning an empty table. It
// deliberately does not embed historyStubAPI, because an embedded GetHistory
// would be promoted and the seam check would wrongly succeed.
type historylessAPI struct {
	endpoints []protocol.Endpoint
	calls     []string
}

func (s *historylessAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	s.calls = append(s.calls, "list")
	return s.endpoints, nil
}

func (s *historylessAPI) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{}, nil
}

func (s *historylessAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{}, nil
}

func (s *historylessAPI) GetCommand(context.Context, string) (map[string]any, error) {
	return nil, nil
}

func (s *historylessAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}

func (s *historylessAPI) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (s *historylessAPI) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	return nil, nil
}

func historyLiveSession(resourceID, providerSessionID, generation string) protocol.Session {
	return protocol.Session{
		ClusterSessionID:   resourceID,
		ProviderSessionID:  providerSessionID,
		ProviderGeneration: generation,
		State:              "running",
	}
}

func TestJoinHistoryMarksLiveRowRoutable(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "wa-1", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning}}
	report := protocol.InventoryReport{Sessions: []protocol.Session{historyLiveSession("res_1", "wa-1", "gen-1")}}

	view := JoinHistory("ep-1", rows, report, true)
	if len(view.Rows) != 1 {
		t.Fatalf("rows=%d", len(view.Rows))
	}
	row := view.Rows[0]
	if !row.Joined || !row.Live {
		t.Fatalf("row not joined live: %+v", row)
	}
	if row.ResourceID != "res_1" || row.ProviderGeneration != "gen-1" {
		t.Fatalf("join did not supply routing identity: %+v", row)
	}
	if row.No != 1 {
		t.Fatalf("row number=%d", row.No)
	}
}

func TestJoinHistoryLeavesPastRowWithoutRoutingIdentity(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true}}
	report := protocol.InventoryReport{Sessions: []protocol.Session{historyLiveSession("res_1", "wa-other", "gen-1")}}

	view := JoinHistory("ep-1", rows, report, true)
	row := view.Rows[0]
	if !row.Joined {
		t.Fatalf("row should be joined: %+v", row)
	}
	if row.Live {
		t.Fatalf("row must not be live: %+v", row)
	}
	if row.ResourceID != "" || row.ProviderGeneration != "" {
		t.Fatalf("past row must carry no routing identity: %+v", row)
	}
}

func TestJoinHistoryRejectsAmbiguousSameEndpointMatch(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "wa-dup", Resumable: true}}
	report := protocol.InventoryReport{Sessions: []protocol.Session{
		historyLiveSession("res_1", "wa-dup", "gen-1"),
		historyLiveSession("res_2", "wa-dup", "gen-2"),
	}}

	view := JoinHistory("ep-1", rows, report, true)
	row := view.Rows[0]
	if row.Joined || row.Live {
		t.Fatalf("ambiguous match must stay unjoined: %+v", row)
	}
	if !row.Ambiguous {
		t.Fatalf("ambiguous match must be marked ambiguous: %+v", row)
	}
	if row.ResourceID != "" || row.ProviderGeneration != "" {
		t.Fatalf("ambiguous match must supply no routing identity: %+v", row)
	}
}

// TestJoinHistorySeparatesAmbiguityFromUnavailableInventory proves the two
// unjoined outcomes are distinguishable, because they need different remedies: an
// unavailable inventory can be refreshed, while contradictory inventory data
// cannot.
func TestJoinHistorySeparatesAmbiguityFromUnavailableInventory(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "wa-dup", Resumable: true}}
	ambiguousReport := protocol.InventoryReport{Sessions: []protocol.Session{
		historyLiveSession("res_1", "wa-dup", "gen-1"),
		historyLiveSession("res_2", "wa-dup", "gen-2"),
	}}

	ambiguous := JoinHistory("ep-1", rows, ambiguousReport, true).Rows[0]
	unavailable := JoinHistory("ep-1", rows, protocol.InventoryReport{}, false).Rows[0]
	if !ambiguous.Ambiguous {
		t.Fatalf("ambiguous row must be marked ambiguous: %+v", ambiguous)
	}
	if unavailable.Ambiguous {
		t.Fatalf("an unavailable inventory must not be reported as ambiguous: %+v", unavailable)
	}
	if ambiguous.Joined || unavailable.Joined {
		t.Fatalf("neither row may be joined: ambiguous=%+v unavailable=%+v", ambiguous, unavailable)
	}
}

func TestJoinHistoryWithoutInventoryIsUnknownNotStopped(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "wa-1", Resumable: true}}

	view := JoinHistory("ep-1", rows, protocol.InventoryReport{}, false)
	if view.Joined {
		t.Fatal("view must report an unavailable join")
	}
	row := view.Rows[0]
	if row.Joined || row.Live {
		t.Fatalf("row must stay unjoined: %+v", row)
	}
	if row.ResourceID != "" || row.ProviderGeneration != "" {
		t.Fatalf("unjoined row must carry no routing identity: %+v", row)
	}
}

func TestJoinHistorySkipsEmptyProviderSessionID(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "", Resumable: true}}
	report := protocol.InventoryReport{Sessions: []protocol.Session{historyLiveSession("res_1", "", "gen-1")}}

	view := JoinHistory("ep-1", rows, report, true)
	if view.Rows[0].Joined || view.Rows[0].Live {
		t.Fatalf("empty provider session ID must never join: %+v", view.Rows[0])
	}
}

func TestJoinHistoryAssignsSequentialRowNumbers(t *testing.T) {
	rows := []protocol.HistoryRow{
		{ProviderSessionID: "wa-1"},
		{ProviderSessionID: "wa-2"},
		{ProviderSessionID: "wa-3"},
	}

	view := JoinHistory("ep-1", rows, protocol.InventoryReport{}, true)
	for index, row := range view.Rows {
		if row.No != index+1 {
			t.Fatalf("row %d number=%d", index, row.No)
		}
	}
}

func TestHistoryJSONCarriesNoRoutingIdentityForPastRows(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "wa-past", Resumable: true}}
	view := JoinHistory("ep-1", rows, protocol.InventoryReport{}, true)

	var out strings.Builder
	if err := RenderJSON(&out, view); err != nil {
		t.Fatal(err)
	}
	var decoded struct {
		Rows []map[string]json.RawMessage `json:"rows"`
	}
	if err := json.Unmarshal([]byte(out.String()), &decoded); err != nil {
		t.Fatal(err)
	}
	if len(decoded.Rows) != 1 {
		t.Fatalf("rows=%d", len(decoded.Rows))
	}
	for _, key := range []string{"resource_id", "generation"} {
		if _, ok := decoded.Rows[0][key]; ok {
			t.Fatalf("past history row must not expose %q: %s", key, out.String())
		}
	}
	if _, ok := decoded.Rows[0]["provider_session_id"]; !ok {
		t.Fatalf("history row must expose provider_session_id: %s", out.String())
	}
}

func TestCommandRunnerHistoryRequiresEndpointArgument(t *testing.T) {
	api := &historyStubAPI{}
	err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), io.Discard, io.Discard, "  ", 0, false, TableOptions{})
	if err == nil || !strings.Contains(err.Error(), "usage: history") {
		t.Fatalf("err=%v", err)
	}
	if len(api.calls) != 0 {
		t.Fatalf("usage error must not query: %v", api.calls)
	}
}

func TestCommandRunnerHistoryReportsMissingSeam(t *testing.T) {
	api := &historylessAPI{}
	err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), io.Discard, io.Discard, "ep-1", 0, false, TableOptions{})
	if err == nil || !strings.Contains(err.Error(), "history is unavailable") {
		t.Fatalf("err=%v", err)
	}
}

func TestCommandRunnerHistoryRejectsUnknownEndpoint(t *testing.T) {
	api := &historyStubAPI{endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}}}
	err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), io.Discard, io.Discard, "ep-missing", 0, false, TableOptions{})
	if err == nil || !strings.Contains(err.Error(), "was not found") {
		t.Fatalf("err=%v", err)
	}
}

func TestCommandRunnerHistoryRejectsAmbiguousHostname(t *testing.T) {
	api := &historyStubAPI{endpoints: []protocol.Endpoint{
		{EndpointID: "ep-b", Hostname: "ai-dev"},
		{EndpointID: "ep-a", Hostname: "ai-dev"},
	}}
	err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), io.Discard, io.Discard, "ai-dev", 0, false, TableOptions{})
	if err == nil {
		t.Fatal("ambiguous hostname must be rejected")
	}
	if !strings.Contains(err.Error(), "matches several endpoints") || !strings.Contains(err.Error(), "ep-a, ep-b") {
		t.Fatalf("err=%v", err)
	}
	if len(api.calls) != 1 {
		t.Fatalf("ambiguous hostname must not query history: %v", api.calls)
	}
}

func TestCommandRunnerHistoryResolvesUniqueHostname(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep-1", Hostname: "ai-dev"}},
		history:   map[string]protocol.HistoryResult{"ep-1": {Rows: []protocol.HistoryRow{{ProviderSessionID: "wa-1", Resumable: true}}}},
	}
	var out strings.Builder
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), &out, io.Discard, "ai-dev", 0, false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "wa-1") {
		t.Fatalf("out=%q", out.String())
	}
}

func TestCommandRunnerHistoryRendersJoinColumns(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}},
		history: map[string]protocol.HistoryResult{"ep-1": {Rows: []protocol.HistoryRow{
			{ProviderSessionID: "wa-live", Resumable: false, ResumeBlockedReason: protocol.ResumeBlockedProviderRunning},
			{ProviderSessionID: "wa-past", Resumable: true},
		}}},
		reports: map[string]protocol.InventoryReport{"ep-1": {Sessions: []protocol.Session{historyLiveSession("res_1", "wa-live", "gen-1")}}},
	}
	var out strings.Builder
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), &out, io.Discard, "ep-1", 0, false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	for _, want := range []string{"LIVE", "RESUMABLE", "wa-live", "wa-past", "provider_running"} {
		if !strings.Contains(text, want) {
			t.Fatalf("table missing %q: %q", want, text)
		}
	}
}

func TestCommandRunnerHistoryJSONEmitsJoinedView(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}},
		history:   map[string]protocol.HistoryResult{"ep-1": {Rows: []protocol.HistoryRow{{ProviderSessionID: "wa-live"}}, ObservedAtMS: 77}},
		reports:   map[string]protocol.InventoryReport{"ep-1": {Sessions: []protocol.Session{historyLiveSession("res_1", "wa-live", "gen-1")}}},
	}
	var out strings.Builder
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), &out, io.Discard, "ep-1", 0, true, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	var view HistoryView
	if err := json.Unmarshal([]byte(out.String()), &view); err != nil {
		t.Fatal(err)
	}
	if view.EndpointID != "ep-1" || view.ObservedAtMS != 77 || !view.Joined {
		t.Fatalf("view=%+v", view)
	}
	if len(view.Rows) != 1 || !view.Rows[0].Live || view.Rows[0].ResourceID != "res_1" {
		t.Fatalf("rows=%+v", view.Rows)
	}
}

func TestCommandRunnerHistoryReportsTruncation(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}},
		history:   map[string]protocol.HistoryResult{"ep-1": {Rows: []protocol.HistoryRow{{ProviderSessionID: "wa-1"}}, Truncated: true}},
	}
	var out, diagnostics strings.Builder
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), &out, &diagnostics, "ep-1", 0, false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(diagnostics.String(), "bounded provider window") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

func TestCommandRunnerHistoryReportsUnjoinedInventory(t *testing.T) {
	api := &historyStubAPI{
		endpoints:   []protocol.Endpoint{{EndpointID: "ep-1"}},
		history:     map[string]protocol.HistoryResult{"ep-1": {Rows: []protocol.HistoryRow{{ProviderSessionID: "wa-1"}}}},
		inventoryEr: map[string]error{"ep-1": errors.New("inventory unavailable")},
	}
	var out, diagnostics strings.Builder
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), &out, &diagnostics, "ep-1", 0, false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(diagnostics.String(), "unjoined") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
	if !strings.Contains(out.String(), "unjoined") {
		t.Fatalf("table must label unjoined rows: %q", out.String())
	}
}

func TestCommandRunnerHistorySurfacesProviderErrorCode(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}},
		history:   map[string]protocol.HistoryResult{"ep-1": {ErrorCode: protocol.HistoryUnsupported}},
	}
	err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), io.Discard, io.Discard, "ep-1", 0, false, TableOptions{})
	if err == nil || !strings.Contains(err.Error(), protocol.HistoryUnsupported) {
		t.Fatalf("err=%v", err)
	}
}

func TestCommandRunnerHistoryPropagatesTransportError(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}},
		historyEr: map[string]error{"ep-1": errors.New("endpoint_unavailable")},
	}
	err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), io.Discard, io.Discard, "ep-1", 0, false, TableOptions{})
	if err == nil || !strings.Contains(err.Error(), "endpoint_unavailable") {
		t.Fatalf("err=%v", err)
	}
}

func TestCommandRunnerHistoryEmptySuccessIsNotAnError(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}},
		history:   map[string]protocol.HistoryResult{"ep-1": {Rows: nil}},
	}
	var out strings.Builder
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), &out, io.Discard, "ep-1", 0, false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "wa-") {
		t.Fatalf("empty success must render no rows: %q", out.String())
	}
}

// TestCommandRunnerHistoryRejectsOfflineEndpoint proves a disconnected endpoint is
// refused before the query is dispatched.
//
// A history query is a live provider read forwarded through the endpoint channel, so
// an offline endpoint can only fail after the transport budget expires. Checking
// connectivity first reports the real cause immediately and keeps history consistent
// with every other endpoint-scoped command.
func TestCommandRunnerHistoryRejectsOfflineEndpoint(t *testing.T) {
	cases := []struct {
		name   string
		target string
	}{
		{name: "exact endpoint id", target: "ep-1"},
		{name: "unique hostname", target: "ai-dev"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			api := &historyStubAPI{endpoints: []protocol.Endpoint{
				{EndpointID: "ep-1", Hostname: "ai-dev", ConnectionState: "offline"},
			}}
			err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), io.Discard, io.Discard, testCase.target, 0, false, TableOptions{})
			want := `endpoint "ep-1" is not online: connection_state=offline`
			if err == nil || !strings.Contains(err.Error(), want) {
				t.Fatalf("err=%v, want %q", err, want)
			}
			if len(api.calls) != 1 || api.calls[0] != "list" {
				t.Fatalf("offline endpoint must not query history: %v", api.calls)
			}
		})
	}
}

// TestCommandRunnerHistoryForwardsLimit proves the standalone surface passes the
// caller limit to the history seam instead of dropping it. The seam is the only
// place the value can be applied, so a dropped limit would silently ignore the
// operator's request.
func TestCommandRunnerHistoryForwardsLimit(t *testing.T) {
	api := &historyStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep-1"}},
		history:   map[string]protocol.HistoryResult{"ep-1": {Rows: []protocol.HistoryRow{{ProviderSessionID: "wa-1", Resumable: true}}}},
	}
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).History(context.Background(), io.Discard, io.Discard, "ep-1", 7, false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if len(api.limits) != 1 || api.limits[0] != 7 {
		t.Fatalf("limits=%v want=[7]", api.limits)
	}
}

// TestJoinHistoryMarksUnverifiedRowVisibleButNotEnterable covers the case a
// container restart creates: the provider still reports the session record, but
// no process holds it, so the Endpoint reports no generation. The row must stay
// visible and resumable, because resume is the only operation that can recover
// it, and it must not be reported as live, because entering it would require a
// generation that does not exist.
func TestJoinHistoryMarksUnverifiedRowVisibleButNotEnterable(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "wa-dead", Resumable: true}}
	report := protocol.InventoryReport{Sessions: []protocol.Session{historyLiveSession("res_dead", "wa-dead", "")}}

	view := JoinHistory("ep-1", rows, report, true)
	if len(view.Rows) != 1 {
		t.Fatalf("rows=%d", len(view.Rows))
	}
	row := view.Rows[0]
	if !row.Joined {
		t.Fatalf("row should be joined: %+v", row)
	}
	if row.Live {
		t.Fatalf("row without a generation must not be live: %+v", row)
	}
	if !row.Unverified {
		t.Fatalf("row without a generation must be unverified: %+v", row)
	}
	if row.ProviderGeneration != "" {
		t.Fatalf("unverified row must carry no generation: %+v", row)
	}
	if got := historyLiveCell(row); got != "unverified" {
		t.Fatalf("live cell=%q want=unverified", got)
	}
}

// TestJoinHistoryKeepsVerifiedRowLive guards the boundary of the change above:
// a row whose generation was reported must still be live and must not be
// labelled unverified, so the new state cannot swallow the ordinary case.
func TestJoinHistoryKeepsVerifiedRowLive(t *testing.T) {
	rows := []protocol.HistoryRow{{ProviderSessionID: "wa-1", Resumable: false}}
	report := protocol.InventoryReport{Sessions: []protocol.Session{historyLiveSession("res_1", "wa-1", "gen-1")}}

	view := JoinHistory("ep-1", rows, report, true)
	row := view.Rows[0]
	if !row.Live || row.Unverified {
		t.Fatalf("verified row must be live and not unverified: %+v", row)
	}
	if got := historyLiveCell(row); got != "yes" {
		t.Fatalf("live cell=%q want=yes", got)
	}
}
