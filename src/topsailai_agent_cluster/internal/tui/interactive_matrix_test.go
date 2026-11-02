package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

type matrixAPI struct {
	invs     []protocol.InventoryReport
	caps     []protocol.CapabilityDescriptor
	invCall  int
	capCall  int
	admit    int
	wait     int
	admitErr error
}

func (s *matrixAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}
func (s *matrixAPI) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	index := s.invCall
	s.invCall++
	if index >= len(s.invs) {
		index = len(s.invs) - 1
	}
	return s.invs[index], nil
}
func (s *matrixAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	index := s.capCall
	s.capCall++
	if index >= len(s.caps) {
		index = len(s.caps) - 1
	}
	return s.caps[index], nil
}
func (s *matrixAPI) GetCommand(context.Context, string) (map[string]any, error) {
	s.wait++
	return map[string]any{"status": string(protocol.StatusFinished)}, nil
}
func (*matrixAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}
func (*matrixAPI) GetOutput(context.Context, string, string, string, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}
func (s *matrixAPI) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	s.admit++
	if s.admitErr != nil {
		return nil, s.admitErr
	}
	return map[string]any{"command_id": "cmd-1"}, nil
}

func matrixInventory(generation string) protocol.InventoryReport {
	return protocol.InventoryReport{
		ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded,
		Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{{SessionID: "session-1", AdapterID: "adapter-1", Generation: generation, State: "running", CollectionStatus: protocol.CollectionSucceeded}},
	}
}
func matrixCapability(revision string) protocol.CapabilityDescriptor {
	return protocol.CapabilityDescriptor{Revision: revision, Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}}}
}
func runMatrix(t *testing.T, api *matrixAPI, input string) (string, string) {
	t.Helper()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), api, strings.NewReader(input), &output, &diagnostics, InteractiveOptions{WaitTimeoutMS: 100}); err != nil {
		t.Fatal(err)
	}
	return output.String(), diagnostics.String()
}

func TestInteractiveSendAdmissionCallMatrix(t *testing.T) {
	cases := []struct {
		name                    string
		api                     *matrixAPI
		input                   string
		capability, admit, wait int
		wantDiagnostic          string
	}{
		{name: "success", api: &matrixAPI{invs: []protocol.InventoryReport{matrixInventory("gen")}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev")}}, input: "cd ep/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n", capability: 3, admit: 1, wait: 1},
		{name: "declined", api: &matrixAPI{invs: []protocol.InventoryReport{matrixInventory("gen")}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev")}}, input: "cd ep/session-1\nsend {\"text\":\"hi\"}\nn\nquit\n", capability: 1, wantDiagnostic: "send cancelled"},
		{name: "invalidated", api: &matrixAPI{invs: []protocol.InventoryReport{matrixInventory("gen"), matrixInventory("gen"), matrixInventory("new")}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev")}}, input: "cd ep/session-1\nrefresh\nsend {\"text\":\"hi\"}\nquit\n", capability: 0, wantDiagnostic: "error: selected session generation changed; use the session again\nerror: selected session invalidated; use the session again"},
		{name: "freshness", api: &matrixAPI{invs: []protocol.InventoryReport{func() protocol.InventoryReport { r := matrixInventory("gen"); r.Sessions[0].Stale = true; return r }()}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev")}}, input: "cd ep/session-1\nquit\n", wantDiagnostic: "error: session \"session-1\" is not fresh: stale=true unknown=false collection_status=succeeded"},
		{name: "invalid payload", api: &matrixAPI{invs: []protocol.InventoryReport{matrixInventory("gen")}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev")}}, input: "cd ep/session-1\nsend null\nquit\n", wantDiagnostic: "error: payload must be a JSON object"},
		{name: "generation race", api: &matrixAPI{invs: []protocol.InventoryReport{matrixInventory("gen"), matrixInventory("gen"), matrixInventory("new")}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev")}}, input: "cd ep/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n", capability: 1, wantDiagnostic: "error: selected session generation changed; use the session again"},
		{name: "capability race", api: &matrixAPI{invs: []protocol.InventoryReport{matrixInventory("gen")}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev-1"), matrixCapability("rev-2")}}, input: "cd ep/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n", capability: 2, wantDiagnostic: "error: capability changed after confirmation; send cancelled"},
		{name: "uncertain admission", api: &matrixAPI{invs: []protocol.InventoryReport{matrixInventory("gen")}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev")}, admitErr: errors.New("transport timeout")}, input: "cd ep/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n", capability: 3, admit: 1, wantDiagnostic: "result unknown"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			output, diagnostics := runMatrix(t, tc.api, tc.input)
			if tc.api.capCall != tc.capability {
				t.Fatalf("capability/preparation calls=%d want=%d", tc.api.capCall, tc.capability)
			}
			if tc.api.admit != tc.admit {
				t.Fatalf("SubmitAction calls=%d want=%d", tc.api.admit, tc.admit)
			}
			if tc.api.wait != tc.wait {
				t.Fatalf("WaitAction calls=%d want=%d", tc.api.wait, tc.wait)
			}
			if tc.name == "declined" {
				if diagnostics != "" || strings.Count(output, "send cancelled\n") != 1 {
					t.Fatalf("output=%q diagnostics=%q want cancellation line and no diagnostic", output, diagnostics)
				}
			} else if tc.wantDiagnostic == "result unknown" {
				if !strings.HasPrefix(diagnostics, "error: command cli-") || !strings.Contains(diagnostics, " result unknown; use status cli-") || !strings.HasSuffix(diagnostics, "; transport timeout\n") {
					t.Fatalf("diagnostics=%q want exact uncertain-admission form", diagnostics)
				}
			} else if tc.wantDiagnostic != "" {
				want := tc.wantDiagnostic
				if !strings.HasSuffix(want, "\n") {
					want += "\n"
				}
				if diagnostics != want {
					t.Fatalf("diagnostics=%q want %q", diagnostics, want)
				}
			}
		})
	}
}

func TestInteractiveCapabilityDisappearanceAfterConfirmationRejects(t *testing.T) {
	api := &matrixAPI{invs: []protocol.InventoryReport{matrixInventory("gen")}, caps: []protocol.CapabilityDescriptor{matrixCapability("rev"), matrixCapability("rev"), {Revision: "rev", Capabilities: nil}}}
	_, diagnostics := runMatrix(t, api, "cd ep/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n")
	if api.admit != 0 || api.wait != 0 {
		t.Fatalf("calls submit=%d wait=%d want 0/0", api.admit, api.wait)
	}
	if !strings.Contains(diagnostics, `unsupported capability "message.send"`) {
		t.Fatalf("diagnostics=%q", diagnostics)
	}
}
