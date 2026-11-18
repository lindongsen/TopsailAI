package tui

import (
	"context"
	"sort"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestListRowsCarriesReportedMessageCounts proves the inventory -> row link.
//
// The cell tests build SessionRow literals, so they prove the renderer prints a
// value it was handed. They cannot prove ListRows carries the value out of the
// persisted report, which is the link that makes `list` read only stored data.
// Deleting `Messages: session.Messages` from ListRows left the whole package
// green, so this test exists to fail when that link is removed.
func TestListRowsCarriesReportedMessageCounts(t *testing.T) {
	endpoints := []protocol.Endpoint{{EndpointID: "e1", ConnectionState: "online"}}
	reports := map[string]protocol.InventoryReport{
		"e1": {
			CollectionStatus: protocol.CollectionSucceeded,
			Adapters:         []protocol.AdapterSummary{{AdapterID: "a1", CollectionStatus: protocol.CollectionSucceeded}},
			Sessions: []protocol.Session{
				{ClusterSessionID: "res_1", AdapterID: "a1", State: "running", Messages: &protocol.MessageCounts{Inbound: 4, Outbound: 72}},
				{ClusterSessionID: "res_2", AdapterID: "a1", State: "running"},
			},
		},
	}
	rows := ListRows(endpoints, reports, "")
	if len(rows) != 2 {
		t.Fatalf("rows=%d want=2", len(rows))
	}
	if rows[0].Messages == nil {
		t.Fatal("measured row lost its reported counts")
	}
	if got := *rows[0].Messages; got.Inbound != 4 || got.Outbound != 72 {
		t.Fatalf("measured row counts=%+v want={4 72}", got)
	}
	// An unmeasured row must stay unmeasured. Substituting a zero would state a
	// measurement the provider never made.
	if rows[1].Messages != nil {
		t.Fatalf("unmeasured row gained counts: %+v", *rows[1].Messages)
	}
}

// TestListReadsOnlyPersistedInventory proves `list` issues no request beyond the
// two reads that return stored data.
//
// The human's rule is that `list` may only use what the Server already holds, so
// it must never trigger a collection or a provider read. The stub records every
// CommandAPI method it is asked for, and the assertion names the exact set, so a
// render that reached for capabilities, a command, output, or an admitted intent
// fails here. Counting calls is used rather than elapsed time, because a fast
// render is not evidence that nothing was asked.
func TestListReadsOnlyPersistedInventory(t *testing.T) {
	api := &recordingAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "e1", ConnectionState: "online"}},
		reports: map[string]protocol.InventoryReport{
			"e1": {
				CollectionStatus: protocol.CollectionSucceeded,
				Adapters:         []protocol.AdapterSummary{{AdapterID: "a1", CollectionStatus: protocol.CollectionSucceeded}},
				Sessions: []protocol.Session{
					{ClusterSessionID: "res_1", AdapterID: "a1", ProviderSessionID: "p-1", State: "running", Messages: &protocol.MessageCounts{Inbound: 2, Outbound: 102}},
				},
			},
		},
	}
	var out, errors strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &out, &errors, "", false, TableOptionsFor(&out)); err != nil {
		t.Fatalf("list: %v", err)
	}
	want := []string{"GetInventory", "ListEndpoints"}
	if got := api.calledMethods(); strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("list called %v want %v", got, want)
	}
	// The counts must come from the report, not from a second read.
	if !strings.Contains(out.String(), "2/102") {
		t.Fatalf("rendered table has no reported counts: %q", out.String())
	}
}

// recordingAPI records which CommandAPI methods a render used.
//
// Every method is recorded, including the ones `list` is expected to avoid, so
// the assertion can fail. A stub that only counted the methods it expected to be
// called would pass no matter what the render did.
type recordingAPI struct {
	endpoints []protocol.Endpoint
	reports   map[string]protocol.InventoryReport
	calls     []string
}

func (s *recordingAPI) record(name string) { s.calls = append(s.calls, name) }

func (s *recordingAPI) calledMethods() []string {
	seen := make(map[string]struct{}, len(s.calls))
	unique := make([]string, 0, len(s.calls))
	for _, name := range s.calls {
		if _, duplicate := seen[name]; duplicate {
			continue
		}
		seen[name] = struct{}{}
		unique = append(unique, name)
	}
	sort.Strings(unique)
	return unique
}

func (s *recordingAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	s.record("ListEndpoints")
	return s.endpoints, nil
}

func (s *recordingAPI) GetInventory(_ context.Context, endpointID string) (protocol.InventoryReport, error) {
	s.record("GetInventory")
	return s.reports[endpointID], nil
}

func (s *recordingAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	s.record("GetCapabilities")
	return protocol.CapabilityDescriptor{}, nil
}

func (s *recordingAPI) GetCommand(context.Context, string) (map[string]any, error) {
	s.record("GetCommand")
	return map[string]any{}, nil
}

func (s *recordingAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	s.record("ListCommands")
	return nil, nil
}

func (s *recordingAPI) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	s.record("GetOutput")
	return protocol.OutputSnapshotResponse{}, nil
}

func (s *recordingAPI) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	s.record("AdmitCommand")
	return map[string]any{}, nil
}
