package tui

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

type runnerStubAPI struct {
	endpoints       []protocol.Endpoint
	reports         map[string]protocol.InventoryReport
	commands        map[string]map[string]any
	inventoryErrors map[string]error
	calls           []string
}

func (s *runnerStubAPI) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	s.calls = append(s.calls, "list")
	return s.endpoints, nil
}
func (s *runnerStubAPI) GetInventory(_ context.Context, id string) (protocol.InventoryReport, error) {
	s.calls = append(s.calls, "inventory:"+id)
	if err := s.inventoryErrors[id]; err != nil {
		return protocol.InventoryReport{}, err
	}
	return s.reports[id], nil
}
func (s *runnerStubAPI) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	s.calls = append(s.calls, "capabilities")
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}}}, nil
}
func (s *runnerStubAPI) GetCommand(_ context.Context, id string) (map[string]any, error) {
	s.calls = append(s.calls, "command:"+id)
	return s.commands[id], nil
}
func (s *runnerStubAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	s.calls = append(s.calls, "history")
	return nil, nil
}
func (s *runnerStubAPI) GetOutput(context.Context, string, string, string, int) (protocol.OutputSnapshotResponse, error) {
	s.calls = append(s.calls, "output")
	return protocol.OutputSnapshotResponse{Data: "log", ObservedAtMS: 10}, nil
}
func (s *runnerStubAPI) AdmitCommand(context.Context, protocol.ImmutableIntent) (map[string]any, error) {
	s.calls = append(s.calls, "admit")
	return map[string]any{"command_id": "cmd-1"}, nil
}

func TestCommandRunnerListUsesSharedQueryAndLegacyBytes(t *testing.T) {
	api := &runnerStubAPI{endpoints: []protocol.Endpoint{{EndpointID: "ep"}}, reports: map[string]protocol.InventoryReport{"ep": {CollectionStatus: protocol.CollectionSucceeded}}}
	var out strings.Builder
	if err := (CommandRunner{API: api, Policy: LegacyPolicy}).List(context.Background(), &out, "", false); err != nil {
		t.Fatal(err)
	}
	if got, want := out.String(), "NO  ENDPOINT  ADAPTER  SESSION  GENERATION  STATE        STALE  UNKNOWN  COLLECTION  LAST_SUCCESS_MS\n1   ep                                      no sessions  false  false    succeeded             never\n"; got != want {
		t.Fatalf("output=%q want=%q", got, want)
	}
	if got, want := strings.Join(api.calls, ","), "list,inventory:ep"; got != want {
		t.Fatalf("calls=%s want=%s", got, want)
	}
}

func TestCommandRunnerListHeadersColorAndJSONIsolation(t *testing.T) {
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep"}},
		reports: map[string]protocol.InventoryReport{"ep": {
			CollectionStatus: protocol.CollectionSucceeded,
			Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
			Sessions:         []protocol.Session{{SessionID: "session", AdapterID: "adapter", Generation: "generation", State: "running"}},
		}},
	}
	var plain strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &plain, io.Discard, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	for _, header := range tableHeaders {
		if !strings.Contains(plain.String(), header) {
			t.Fatalf("plain list missing header %q: %q", header, plain.String())
		}
	}
	if strings.Contains(plain.String(), "\x1b") {
		t.Fatalf("plain list contains ANSI bytes: %q", plain.String())
	}
	var colored strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &colored, io.Discard, "", false, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(colored.String(), ansiBoldCyan) || !strings.Contains(colored.String(), ansiReset) {
		t.Fatalf("colored list missing header styling: %q", colored.String())
	}
	var encoded strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &encoded, io.Discard, "", true, TableOptions{Color: ColorPolicy{Enabled: true}}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(encoded.String(), "ENDPOINT") || strings.Contains(encoded.String(), "\x1b") {
		t.Fatalf("JSON list contains presentation bytes: %q", encoded.String())
	}
	var rows []SessionRow
	if err := json.Unmarshal([]byte(encoded.String()), &rows); err != nil || len(rows) != 1 {
		t.Fatalf("JSON list=%q err=%v rows=%d", encoded.String(), err, len(rows))
	}
}

func TestCommandRunnerListEmptyAndPartialFailure(t *testing.T) {
	api := &runnerStubAPI{endpoints: []protocol.Endpoint{{EndpointID: "good"}, {EndpointID: "bad"}}, reports: map[string]protocol.InventoryReport{
		"good": {CollectionStatus: protocol.CollectionSucceeded},
	}, inventoryErrors: map[string]error{"bad": errors.New("fixture failure")}}
	var out, diagnostics strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &out, &diagnostics, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "ENDPOINT") || !strings.Contains(out.String(), "good") || !strings.Contains(out.String(), "no sessions") {
		t.Fatalf("partial list=%q", out.String())
	}
	if !strings.Contains(diagnostics.String(), "endpoint bad unavailable: fixture failure") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
	api = &runnerStubAPI{endpoints: []protocol.Endpoint{{EndpointID: "empty"}}, reports: map[string]protocol.InventoryReport{"empty": {CollectionStatus: protocol.CollectionSucceeded}}}
	out.Reset()
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &out, io.Discard, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "ENDPOINT") || !strings.Contains(out.String(), "no sessions") {
		t.Fatalf("empty list=%q", out.String())
	}
}

func TestRenderJSONHasStableBytes(t *testing.T) {
	var out strings.Builder
	if err := RenderJSON(&out, map[string]any{"status": "finished"}); err != nil {
		t.Fatal(err)
	}
	if got, want := out.String(), "{\n  \"status\": \"finished\"\n}\n"; got != want {
		t.Fatalf("json=%q want=%q", got, want)
	}
}

func TestCommandRunnerJSONAndStatus(t *testing.T) {
	api := &runnerStubAPI{endpoints: []protocol.Endpoint{{EndpointID: "ep"}}, reports: map[string]protocol.InventoryReport{"ep": {CollectionStatus: protocol.CollectionSucceeded}}, commands: map[string]map[string]any{"cmd": {"status": "finished"}}}
	var out strings.Builder
	if err := (CommandRunner{API: api}).List(context.Background(), &out, "", true); err != nil {
		t.Fatal(err)
	}
	var rows []SessionRow
	if err := json.Unmarshal([]byte(out.String()), &rows); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if err := (CommandRunner{API: api}).Status(context.Background(), &out, "cmd", false); err != nil {
		t.Fatal(err)
	}
	if out.String() != "confirmed result\n" {
		t.Fatalf("status=%q", out.String())
	}
}

func TestCommandRunnerActionSharesPrepareSubmitWait(t *testing.T) {
	api := &runnerStubAPI{commands: map[string]map[string]any{"cmd-1": {"status": "finished"}}}
	runner := CommandRunner{API: api, NewID: func() string { return "fixed-id" }, Now: func() time.Time { return time.UnixMilli(100) }}
	intent, err := runner.PrepareAction(context.Background(), ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep", ResourceID: "session", Generation: "gen", Payload: json.RawMessage(`{"text":"hi"}`), Confirmed: true})
	if err != nil {
		t.Fatal(err)
	}
	if intent.CommandID != "fixed-id" || intent.ExecuteBeforeAtMS != 300100 {
		t.Fatalf("intent=%+v", intent)
	}
	action, err := runner.SubmitAction(context.Background(), intent)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := runner.WaitAction(context.Background(), action, protocol.Budget{WaitTimeoutMS: 100}); err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(api.calls, ","); got != "capabilities,admit,command:cmd-1" {
		t.Fatalf("calls=%s", got)
	}
}

func TestCommandRunnerRenderActionUsesPolicySpecificFormat(t *testing.T) {
	var out strings.Builder
	if err := (CommandRunner{Policy: LegacyPolicy}).RenderAction(&out, map[string]any{"status": "finished"}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "\"status\": \"finished\"") {
		t.Fatalf("legacy output=%q", out.String())
	}
	out.Reset()
	if err := (CommandRunner{Policy: InteractivePolicy}).RenderAction(&out, map[string]any{"status": "finished"}); err != nil {
		t.Fatal(err)
	}
	if got, want := out.String(), "confirmed result\n"; got != want {
		t.Fatalf("interactive output=%q want=%q", got, want)
	}
	if _, err := io.WriteString(io.Discard, ""); err != nil {
		t.Fatal(err)
	}
}

func TestCommandRunnerShowAndLogs(t *testing.T) {
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{{EndpointID: "ep"}},
		reports:   map[string]protocol.InventoryReport{"ep": {CollectionStatus: protocol.CollectionSucceeded, Sessions: []protocol.Session{{SessionID: "session", Generation: "gen", State: "running"}}}},
		commands:  map[string]map[string]any{"unused": {"status": "finished"}},
	}
	var out strings.Builder
	if err := (CommandRunner{API: api}).Show(context.Background(), &out, "session", false); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "session: session") {
		t.Fatalf("show=%q", out.String())
	}
	out.Reset()
	if err := (CommandRunner{API: api}).Logs(context.Background(), &out, "ep", "session", 128, false); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "log") {
		t.Fatalf("logs=%q", out.String())
	}
}
