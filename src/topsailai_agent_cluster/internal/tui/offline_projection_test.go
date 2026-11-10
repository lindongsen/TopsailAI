package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// offlineAPI serves one endpoint with a configurable connection state.
type offlineAPI struct {
	state    string
	report   protocol.InventoryReport
	caps     protocol.CapabilityDescriptor
	admitted int
}

func (s *offlineAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep", InstanceID: "i1", ConnectionState: s.state}}, nil
}

func (s *offlineAPI) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return s.report, nil
}

func (s *offlineAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return s.caps, nil
}

func (s *offlineAPI) GetCommand(context.Context, string) (map[string]any, error) {
	return map[string]any{"status": string(protocol.StatusFinished)}, nil
}

func (*offlineAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}

func (*offlineAPI) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (s *offlineAPI) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	s.admitted++
	return map[string]any{"command_id": "cmd-1"}, nil
}

// offlineReport builds a successful retained inventory for one session.
func offlineReport() protocol.InventoryReport {
	return protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions:         []protocol.Session{{ClusterSessionID: "session-1", AdapterID: "adapter-1", ProviderGeneration: "gen-1", State: "running", CollectionStatus: protocol.CollectionSucceeded}},
	}
}

// TestListRowsMarksDisconnectedEndpointInventoryStale verifies that retained
// inventory from a disconnected endpoint is never presented as current.
func TestListRowsMarksDisconnectedEndpointInventoryStale(t *testing.T) {
	cases := []struct {
		name  string
		state string
		want  string
	}{
		{name: "online", state: "online", want: "ok"},
		{name: "offline", state: "offline", want: "ok/stale"},
		{name: "disconnected", state: "disconnected", want: "ok/stale"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			endpoints := []protocol.Endpoint{{EndpointID: "ep", ConnectionState: testCase.state}}
			rows := ListRows(endpoints, map[string]protocol.InventoryReport{"ep": offlineReport()}, "")
			if len(rows) != 1 {
				t.Fatalf("rows=%#v", rows)
			}
			if got := dataStatus(rows[0]); got != testCase.want {
				t.Fatalf("data status=%q, want %q", got, testCase.want)
			}
		})
	}
}

// TestListRowsMarksDisconnectedEndpointWithoutSessionsStale verifies the
// no-session projection also reports stale data.
func TestListRowsMarksDisconnectedEndpointWithoutSessionsStale(t *testing.T) {
	report := offlineReport()
	report.Sessions = nil
	endpoints := []protocol.Endpoint{{EndpointID: "ep", ConnectionState: "offline"}}
	rows := ListRows(endpoints, map[string]protocol.InventoryReport{"ep": report}, "")
	if len(rows) != 1 {
		t.Fatalf("rows=%#v", rows)
	}
	if got := dataStatus(rows[0]); got != "ok/stale" {
		t.Fatalf("data status=%q, want ok/stale", got)
	}
}

// TestFindSelectedRejectsDisconnectedEndpoint verifies that a stale retained
// inventory cannot authorize session-scoped actions.
func TestFindSelectedRejectsDisconnectedEndpoint(t *testing.T) {
	api := &offlineAPI{state: "offline", report: offlineReport(), caps: matrixCapability("rev-1")}
	state := &interactiveState{interactiveSelection: interactiveSelection{EndpointID: "ep", ClusterSessionID: "session-1", ProviderGeneration: "gen-1"}}
	_, _, _, err := findSelected(context.Background(), api, state)
	if err == nil {
		t.Fatal("disconnected endpoint selection unexpectedly succeeded")
	}
	if !strings.Contains(err.Error(), "not online") || !strings.Contains(err.Error(), "offline") {
		t.Fatalf("error=%q, want an offline diagnostic", err)
	}
}

// TestFindSelectedAcceptsOnlineEndpoint verifies the online path is unchanged.
func TestFindSelectedAcceptsOnlineEndpoint(t *testing.T) {
	api := &offlineAPI{state: "online", report: offlineReport(), caps: matrixCapability("rev-1")}
	state := &interactiveState{interactiveSelection: interactiveSelection{EndpointID: "ep", ClusterSessionID: "session-1", ProviderGeneration: "gen-1"}}
	endpoint, _, session, err := findSelected(context.Background(), api, state)
	if err != nil {
		t.Fatal(err)
	}
	if endpoint.EndpointID != "ep" || session == nil || session.ClusterSessionID != "session-1" {
		t.Fatalf("endpoint=%#v session=%#v", endpoint, session)
	}
}

// TestCDRowNumberRejectsDisconnectedEndpoint verifies that row navigation cannot
// enter a session scope from retained inventory of a disconnected endpoint.
func TestCDRowNumberRejectsDisconnectedEndpoint(t *testing.T) {
	api := &offlineAPI{state: "offline", report: offlineReport(), caps: matrixCapability("rev-1")}
	state := interactiveState{}
	rows := ListRows([]protocol.Endpoint{{EndpointID: "ep", ConnectionState: "offline"}}, map[string]protocol.InventoryReport{"ep": offlineReport()}, "")
	assignRowNumbers(rows)
	state.setRows(rows)
	before := state
	err := cdRowNumber(&state, api, context.Background(), 1)
	if err == nil {
		t.Fatal("row navigation into a disconnected endpoint unexpectedly succeeded")
	}
	if !strings.Contains(err.Error(), "not online") || !strings.Contains(err.Error(), "offline") {
		t.Fatalf("error=%q, want an offline diagnostic", err)
	}
	if state.Scope != before.Scope || state.EndpointID != before.EndpointID || state.ClusterSessionID != before.ClusterSessionID {
		t.Fatalf("state changed after offline rejection: before=%+v after=%+v", before, state)
	}
}

// TestResolveSessionInEndpointRejectsDisconnectedEndpoint verifies that named
// session navigation also refuses stale retained inventory.
func TestResolveSessionInEndpointRejectsDisconnectedEndpoint(t *testing.T) {
	state := interactiveState{}
	loaded := reportLoad{
		endpoints: []protocol.Endpoint{{EndpointID: "ep", ConnectionState: "offline"}},
		reports:   map[string]protocol.InventoryReport{"ep": offlineReport()},
	}
	outcome, err := resolveSessionInEndpoint(&state, loaded, "ep", "session-1")
	if err == nil {
		t.Fatal("session navigation into a disconnected endpoint unexpectedly succeeded")
	}
	if outcome != outcomeCancelled {
		t.Fatalf("outcome=%v, want outcomeCancelled", outcome)
	}
	if !strings.Contains(err.Error(), "not online") {
		t.Fatalf("error=%q, want an offline diagnostic", err)
	}
	if state.Scope.Kind != ScopeWorkspace {
		t.Fatalf("scope=%+v, want workspace scope", state.Scope)
	}
}
