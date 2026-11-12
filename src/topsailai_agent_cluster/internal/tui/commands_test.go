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
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}, {Name: protocol.OperationAgentStart}}}, nil
}
func (s *runnerStubAPI) GetCommand(_ context.Context, id string) (map[string]any, error) {
	s.calls = append(s.calls, "command:"+id)
	return s.commands[id], nil
}
func (s *runnerStubAPI) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	s.calls = append(s.calls, "history")
	return nil, nil
}
func (s *runnerStubAPI) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
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
	if got := out.String(); !strings.Contains(got, "NO │ SESSION_STATUS") || !strings.Contains(got, "─┼─") || !strings.Contains(got, "ep") {
		t.Fatalf("output=%q missing table separators", got)
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
			Sessions:         []protocol.Session{{ClusterSessionID: "session", AdapterID: "adapter", ProviderGeneration: "generation", State: "running"}},
		}},
	}
	var plain strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &plain, io.Discard, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	// The table is framed by horizontal rules, so locate the header row rather
	// than assuming it is the first line.
	plainHeader := ""
	for _, line := range strings.Split(plain.String(), "\n") {
		if strings.Contains(line, "SESSION_STATUS") {
			plainHeader = line
			break
		}
	}
	for _, header := range tableHeaders {
		if !strings.Contains(plainHeader, header) {
			t.Fatalf("plain list missing header %q: %q", header, plainHeader)
		}
	}
	if strings.Contains(plain.String(), "\x1b") {
		t.Fatalf("plain list contains ANSI bytes: %q", plain.String())
	}

	var coloredList, coloredCleanList strings.Builder
	options := TableOptions{Color: ColorPolicy{Enabled: true}}
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &coloredList, io.Discard, "", false, options); err != nil {
		t.Fatal(err)
	}
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &coloredCleanList, io.Discard, "", false, TableOptions{Color: options.Color, Clean: true}); err != nil {
		t.Fatal(err)
	}
	// The table is framed by rules, so the header is not the first line. Locate
	// it by DATA_STATUS, which every layout keeps.
	headerLine := func(text string) string {
		for _, line := range strings.Split(text, "\n") {
			if strings.Contains(line, "DATA_STATUS") {
				return line
			}
		}
		return ""
	}
	listHeader := headerLine(coloredList.String())
	cleanListHeader := headerLine(coloredCleanList.String())
	if listHeader != cleanListHeader {
		t.Fatalf("list/list --clean headers differ: list=%q clean=%q", listHeader, cleanListHeader)
	}
	for _, header := range columnHeaders(coloredColumns()) {
		assertStyledHeaderCell(t, listHeader, header)
	}
	if !strings.Contains(listHeader, ansiBoldCyan) || !strings.Contains(listHeader, ansiReset) {
		t.Fatalf("colored list missing exact header styling: %q", listHeader)
	}
	if !strings.Contains(coloredList.String(), ansiGreen+"running") || !strings.Contains(coloredList.String(), ansiReset) {
		t.Fatalf("colored list missing exact running style: %q", coloredList.String())
	}

	var noColor strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &noColor, io.Discard, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(noColor.String(), "\x1b[") || !strings.Contains(noColor.String(), " │ ") || !strings.Contains(noColor.String(), "─┼─") {
		t.Fatalf("no-color list lost required plain table output: %q", noColor.String())
	}
	if ResolveColorPolicy(true, true, false, false, true).Enabled {
		t.Fatal("NO_COLOR presence must disable header color")
	}

	var encoded strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &encoded, io.Discard, "", true, options); err != nil {
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

func assertStyledHeaderCell(t *testing.T, header, label string) {
	t.Helper()
	styled := ansiBoldCyan + label
	start := strings.Index(header, styled)
	if start < 0 {
		t.Fatalf("header cell %q missing style %q: %q", label, ansiBoldCyan, header)
	}
	end := strings.Index(header[start+len(styled):], ansiReset)
	if end < 0 {
		t.Fatalf("header cell %q missing reset %q: %q", label, ansiReset, header)
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

func TestCommandRunnerListCleanOmitsFailedEndpointsAndKeepsDiagnostics(t *testing.T) {
	api := &runnerStubAPI{
		endpoints:       []protocol.Endpoint{{EndpointID: "good"}, {EndpointID: "bad"}},
		reports:         map[string]protocol.InventoryReport{"good": {CollectionStatus: protocol.CollectionSucceeded}},
		inventoryErrors: map[string]error{"bad": errors.New("fixture failure")},
	}
	var out, diagnostics strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &out, &diagnostics, "", false, TableOptions{Clean: true}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "bad") || !strings.Contains(out.String(), "good") {
		t.Fatalf("clean list=%q", out.String())
	}
	if !strings.Contains(diagnostics.String(), "endpoint bad unavailable: fixture failure") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// TestCommandRunnerListCleanOmitsDisconnectedEndpoints proves --clean hides an
// endpoint that stopped reporting, not only one whose fetch failed. A
// disconnected endpoint still serves its last committed document, so it never
// produces a fetch error and its retained rows would otherwise survive the flag
// and appear as current sessions.
func TestCommandRunnerListCleanOmitsDisconnectedEndpoints(t *testing.T) {
	session := func(id string) protocol.InventoryReport {
		return protocol.InventoryReport{
			CollectionStatus: protocol.CollectionSucceeded,
			Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
			Sessions:         []protocol.Session{{ClusterSessionID: id, AdapterID: "adapter", ProviderGeneration: "generation", State: "running"}},
		}
	}
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{
			{EndpointID: "live-ep", ConnectionState: "online"},
			{EndpointID: "gone-ep", ConnectionState: "offline"},
		},
		reports: map[string]protocol.InventoryReport{
			"live-ep": session("session-live"),
			"gone-ep": session("session-gone"),
		},
	}
	var plain, clean strings.Builder
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &plain, io.Discard, "", false, TableOptions{}); err != nil {
		t.Fatal(err)
	}
	if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &clean, io.Discard, "", false, TableOptions{Clean: true}); err != nil {
		t.Fatal(err)
	}
	// The unfiltered table must show both, otherwise the clean assertion below
	// would pass for the wrong reason.
	if !strings.Contains(plain.String(), "gone-ep") || !strings.Contains(plain.String(), "live-ep") {
		t.Fatalf("plain list=%q, want both endpoints", plain.String())
	}
	if strings.Contains(clean.String(), "gone-ep") {
		t.Fatalf("clean list=%q, want the disconnected endpoint omitted", clean.String())
	}
	if !strings.Contains(clean.String(), "live-ep") {
		t.Fatalf("clean list=%q, want the online endpoint kept", clean.String())
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

// TestCommandRunnerJSONListHonoursClean proves --clean is not silently dropped
// on the JSON surface. A flag that the table honours and the JSON path ignores
// makes two callers disagree about the same query, and the JSON caller has no
// way to notice because the extra rows look like ordinary data.
func TestCommandRunnerJSONListHonoursClean(t *testing.T) {
	session := func(id string) protocol.InventoryReport {
		return protocol.InventoryReport{
			CollectionStatus: protocol.CollectionSucceeded,
			Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
			Sessions:         []protocol.Session{{ClusterSessionID: id, AdapterID: "adapter", ProviderGeneration: "generation", State: "running"}},
		}
	}
	api := &runnerStubAPI{
		endpoints: []protocol.Endpoint{
			{EndpointID: "live-ep", ConnectionState: "online"},
			{EndpointID: "gone-ep", ConnectionState: "offline"},
		},
		reports: map[string]protocol.InventoryReport{
			"live-ep": session("session-live"),
			"gone-ep": session("session-gone"),
		},
	}
	render := func(clean bool) []SessionRow {
		var out strings.Builder
		if err := (CommandRunner{API: api}).ListWithOptions(context.Background(), &out, io.Discard, "", true, TableOptions{Clean: clean}); err != nil {
			t.Fatal(err)
		}
		var rows []SessionRow
		if err := json.Unmarshal([]byte(out.String()), &rows); err != nil {
			t.Fatalf("json=%q: %v", out.String(), err)
		}
		return rows
	}
	if got := len(render(false)); got != 2 {
		t.Fatalf("unfiltered rows=%d, want 2", got)
	}
	rows := render(true)
	if len(rows) != 1 || rows[0].EndpointID != "live-ep" {
		t.Fatalf("clean rows=%+v, want only live-ep", rows)
	}
}

func TestCommandRunnerActionSharesPrepareSubmitWait(t *testing.T) {
	api := &runnerStubAPI{commands: map[string]map[string]any{"cmd-1": {"status": "finished"}}}
	runner := CommandRunner{API: api, NewID: func() string { return "fixed-id" }, Now: func() time.Time { return time.UnixMilli(100) }}
	intent, err := runner.PrepareAction(context.Background(), ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep", ResourceID: "session", ProviderGeneration: "gen", Payload: json.RawMessage(`{"text":"hi"}`), Confirmed: true})
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
		reports:   map[string]protocol.InventoryReport{"ep": {CollectionStatus: protocol.CollectionSucceeded, Sessions: []protocol.Session{{ClusterSessionID: "session", ProviderGeneration: "gen", State: "running"}}}},
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
	if err := (CommandRunner{API: api}).Logs(context.Background(), &out, "ep", "session", 128, 128, false, ColorPolicy{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "log") {
		t.Fatalf("logs=%q", out.String())
	}
}

func TestPrepareActionCarriesOptionalFolder(t *testing.T) {
	api := &runnerStubAPI{}
	runner := CommandRunner{API: api, Now: func() time.Time { return time.Unix(100, 0) }, NewID: func() string { return "start-1" }}
	for _, tc := range []struct {
		name   string
		folder string
	}{
		{name: "omitted"},
		{name: "provided", folder: "/tmp/work folder --safe"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			intent, err := runner.PrepareAction(context.Background(), ActionRequest{
				Operation:       protocol.OperationAgentStart,
				EndpointID:      "ep",
				Payload:         json.RawMessage(`{}`),
				Confirmed:       true,
				Profile:         "profile",
				ProfileRevision: "rev-1",
				Folder:          tc.folder,
			})
			if err != nil {
				t.Fatal(err)
			}
			if intent.Folder != tc.folder {
				t.Fatalf("folder = %q, want %q", intent.Folder, tc.folder)
			}
		})
	}
	if _, err := runner.PrepareAction(context.Background(), ActionRequest{
		Operation:       protocol.OperationAgentStart,
		EndpointID:      "ep",
		Payload:         json.RawMessage(`{}`),
		Confirmed:       true,
		Profile:         "profile",
		ProfileRevision: "rev-1",
		Folder:          " /tmp/unsafe ",
	}); err == nil {
		t.Fatal("whitespace-padded folder was accepted")
	}
}
