package tui

import (
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// infoStub serves one endpoint whose single session carries a project workspace,
// so the detail renderer can be checked against a real reported value.
func infoStub() *interactiveStub {
	report := scopeInventory("res-1", "generation-1")
	report.Sessions[0].ProviderProjectWorkspace = "/TopsailAI/src/topsailai_agent_cluster"
	report.Sessions[0].ProviderDisplayName = "cluster work"
	return &interactiveStub{
		endpoints: []protocol.Endpoint{
			{EndpointID: "endpoint-1", Hostname: "host-one", ConnectionState: "online"},
			{EndpointID: "endpoint-2", Hostname: "host-two", ConnectionState: "online"},
		},
		reports: map[string]protocol.InventoryReport{
			"endpoint-1": report,
			"endpoint-2": scopeInventory("res-2", "generation-2"),
		},
	}
}

// TestInfoAcceptsRowNumberInWorkspaceScope proves the operator types the row
// number from the fleet list and the detail of that exact session is rendered.
func TestInfoAcceptsRowNumberInWorkspaceScope(t *testing.T) {
	stub := infoStub()
	output, diagnostics := runScope(t, stub, "list\ninfo 1\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	for _, want := range []string{
		"session_id: res-1",
		"provider_session_id: provider-res-1",
		"project_workspace: /TopsailAI/src/topsailai_agent_cluster",
		"endpoint_id: endpoint-1",
	} {
		if !strings.Contains(segment, want) {
			t.Fatalf("missing %q in info output: %q", want, segment)
		}
	}
}

// TestInfoAcceptsRowNumberInEndpointScope proves the endpoint list numbering is
// reused inside the endpoint scope.
func TestInfoAcceptsRowNumberInEndpointScope(t *testing.T) {
	stub := infoStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\nlist\ninfo 1\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "endpoint-1> ")
	if !strings.Contains(segment, "session_id: res-1") {
		t.Fatalf("missing session detail: %q", segment)
	}
}

// TestInfoDefaultsToCurrentSession proves session scope needs no argument.
func TestInfoDefaultsToCurrentSession(t *testing.T) {
	stub := infoStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ninfo\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "res-1> ")
	if !strings.Contains(segment, "session_id: res-1") {
		t.Fatalf("missing current session detail: %q", segment)
	}
	if !strings.Contains(segment, "project_workspace: /TopsailAI/src/topsailai_agent_cluster") {
		t.Fatalf("missing project workspace: %q", segment)
	}
}

// TestInfoRequiresTargetOutsideSessionScope proves the failure names the fix
// instead of silently rendering an arbitrary session.
func TestInfoRequiresTargetOutsideSessionScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{
			name:  "workspace",
			input: "info\nquit\n",
			want:  "info requires a session in workspace scope; use info <number> for a session row or info <session-id>",
		},
		{
			name:  "endpoint",
			input: "cd host-one/endpoint-1\ninfo\nquit\n",
			want:  "info requires a session in endpoint scope; use info <number> for a session row or info <session-id>",
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := infoStub()
			_, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			assertActionableError(t, diagnostics, "error: "+testCase.want)
		})
	}
}

// TestInfoResolvesProviderSessionIDAcrossEndpoints proves a literal identifier
// works in workspace scope without a rendered list.
func TestInfoResolvesProviderSessionIDAcrossEndpoints(t *testing.T) {
	stub := infoStub()
	output, diagnostics := runScope(t, stub, "info provider-res-2\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "workspace> ")
	if !strings.Contains(segment, "session_id: res-2") {
		t.Fatalf("wrong session resolved: %q", segment)
	}
	if !strings.Contains(segment, "endpoint_id: endpoint-2") {
		t.Fatalf("wrong endpoint resolved: %q", segment)
	}
}

// TestInfoRejectsForeignRowInEndpointScope proves a number rendered for another
// endpoint is never silently retargeted.
func TestInfoRejectsForeignRowInEndpointScope(t *testing.T) {
	stub := infoStub()
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"})
	state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-2", ClusterSessionID: "res-2", ProviderGeneration: "generation-2"}})
	_, diagnostics := runLine(t, stub, state, "info 1")
	assertActionableError(t, diagnostics, `error: row 1 belongs to endpoint "endpoint-2", not the current endpoint "endpoint-1"; run list in that endpoint first`)
}

// TestInfoRejectsJSONOption proves interactive mode refuses the standalone flag.
func TestInfoRejectsJSONOption(t *testing.T) {
	stub := infoStub()
	_, diagnostics := runScope(t, stub, "info res-1 --json\nquit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: option "--json" is available only in non-interactive mode; JSON output is available only with the standalone command`)
}

// TestInfoIsReadOnly proves the command changes neither the selected session nor
// the rendered row numbers, so an inspection cannot disturb the operator's place.
func TestInfoIsReadOnly(t *testing.T) {
	stub := infoStub()
	report := stub.reports["endpoint-1"]
	report.Sessions = append(report.Sessions, protocol.Session{
		ClusterSessionID:   "res-1b",
		AdapterID:          "adapter-1",
		ProviderGeneration: "generation-1b",
		State:              "stopped",
		CollectionStatus:   protocol.CollectionSucceeded,
	})
	stub.reports["endpoint-1"] = report
	state := &interactiveState{}
	state.enterEndpoint(protocol.Endpoint{EndpointID: "endpoint-1", Hostname: "host-one"})
	state.setRows([]SessionRow{
		{No: 1, EndpointID: "endpoint-1", ClusterSessionID: "res-1", ProviderGeneration: "generation-1"},
		{No: 2, EndpointID: "endpoint-1", ClusterSessionID: "res-1b", ProviderGeneration: "generation-1b"},
	})
	before := state.Scope
	rowsBefore := make(map[int]SessionRow, len(state.Rows))
	for no, row := range state.Rows {
		rowsBefore[no] = row
	}
	output, diagnostics := runLine(t, stub, state, "info 2")
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session_id: res-1b") {
		t.Fatalf("wrong session rendered: %q", output)
	}
	if state.Scope != before {
		t.Fatalf("scope changed: %+v -> %+v", before, state.Scope)
	}
	if len(state.Rows) != len(rowsBefore) {
		t.Fatalf("row count changed: %d -> %d", len(rowsBefore), len(state.Rows))
	}
	for no, row := range rowsBefore {
		if state.Rows[no] != row {
			t.Fatalf("row %d changed: %+v -> %+v", no, row, state.Rows[no])
		}
	}
	if stub.admit != 0 {
		t.Fatalf("info admitted %d commands", stub.admit)
	}
}

// TestInfoSanitizesProviderValues proves untrusted provider metadata cannot emit
// terminal control sequences or forge an extra detail line.
func TestInfoSanitizesProviderValues(t *testing.T) {
	var out strings.Builder
	session := protocol.Session{
		ClusterSessionID:         "res-1",
		ProviderProjectWorkspace: "/tmp/\x1b[31mevil\x1b[0m\nsession_id: forged",
	}
	if err := RenderSessionInfo(&out, protocol.Endpoint{EndpointID: "endpoint-1"}, session); err != nil {
		t.Fatalf("RenderSessionInfo: %v", err)
	}
	rendered := out.String()
	if strings.Contains(rendered, "\x1b") {
		t.Fatalf("escape sequence survived: %q", rendered)
	}
	for _, line := range strings.Split(rendered, "\n") {
		if strings.HasPrefix(line, "session_id:") && !strings.HasPrefix(line, "session_id: res-1") {
			t.Fatalf("forged detail line survived: %q", rendered)
		}
	}
	if !strings.Contains(rendered, "project_workspace: /tmp/") {
		t.Fatalf("workspace value lost: %q", rendered)
	}
}

// TestInfoRendersEmptyWorkspaceWithoutInventing proves an unreported workspace
// stays visibly empty instead of being replaced by a plausible guess.
func TestInfoRendersEmptyWorkspaceWithoutInventing(t *testing.T) {
	var out strings.Builder
	if err := RenderSessionInfo(&out, protocol.Endpoint{EndpointID: "endpoint-1"}, protocol.Session{ClusterSessionID: "res-1"}); err != nil {
		t.Fatalf("RenderSessionInfo: %v", err)
	}
	if !strings.Contains(out.String(), "project_workspace: \n") {
		t.Fatalf("missing empty workspace line: %q", out.String())
	}
}

// TestInfoRendersDriveDetail proves info reports the controller detail of the
// selected session, including the process identity, so an operator does not have
// to run a second command to learn what a drive start actually created.
func TestInfoRendersDriveDetail(t *testing.T) {
	var out strings.Builder
	session := protocol.Session{
		ClusterSessionID: "res-1",
		Drive: &protocol.DriveSummary{
			State:         protocol.DriveStateRunning,
			Verified:      true,
			ControllerPID: 4321,
			RunID:         "run-abc",
			ObservedAtMS:  1700000000000,
		},
	}
	if err := RenderSessionInfo(&out, protocol.Endpoint{EndpointID: "endpoint-1"}, session); err != nil {
		t.Fatalf("RenderSessionInfo: %v", err)
	}
	rendered := out.String()
	for _, want := range []string{
		"drive_state: running",
		"drive_verified: true",
		"controller_pid: 4321",
		"drive_run_id: run-abc",
	} {
		if !strings.Contains(rendered, want) {
			t.Fatalf("missing %q in info output: %q", want, rendered)
		}
	}
	assertRenderedInstant(t, rendered, "drive_observed_at", 1700000000000)
}

// TestInfoReportsAbsentDriveAsNotReported proves an unreported controller is
// stated rather than omitted. Omitting it would let an operator read a missing
// line as "no controller exists", which the provider never claimed.
func TestInfoReportsAbsentDriveAsNotReported(t *testing.T) {
	var out strings.Builder
	if err := RenderSessionInfo(&out, protocol.Endpoint{EndpointID: "endpoint-1"}, protocol.Session{ClusterSessionID: "res-1"}); err != nil {
		t.Fatalf("RenderSessionInfo: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, "drive_state: not_reported") {
		t.Fatalf("missing not_reported drive state: %q", rendered)
	}
	if !strings.Contains(rendered, "not proof that no driver exists") {
		t.Fatalf("missing absence caveat: %q", rendered)
	}
}

// TestInfoAndDriveStatusShareDriveDetail proves the two surfaces cannot drift.
// They render the same fields from one source, so a field added to one is never
// silently missing from the other.
func TestInfoAndDriveStatusShareDriveDetail(t *testing.T) {
	drive := &protocol.DriveSummary{
		State:         protocol.DriveStateRunning,
		Verified:      true,
		ControllerPID: 4321,
		RunID:         "run-abc",
		ObservedAtMS:  1700000000000,
		Reason:        "launched",
	}
	var info strings.Builder
	if err := RenderSessionInfo(&info, protocol.Endpoint{EndpointID: "endpoint-1"}, protocol.Session{ClusterSessionID: "res-1", Drive: drive}); err != nil {
		t.Fatalf("RenderSessionInfo: %v", err)
	}
	var status strings.Builder
	if err := renderDriveStatus(&status, driveStatusView{ClusterSessionID: "res-1", Drive: drive}); err != nil {
		t.Fatalf("renderDriveStatus: %v", err)
	}
	for _, line := range driveDetailLines(drive) {
		want := line.label + ": " + line.value
		if !strings.Contains(info.String(), want) {
			t.Fatalf("info is missing %q: %q", want, info.String())
		}
		if !strings.Contains(status.String(), want) {
			t.Fatalf("drive status is missing %q: %q", want, status.String())
		}
	}
}

// TestInfoSanitizesDriveValues proves the drive detail is escaped like every
// other provider value, so a controller reason cannot inject a control sequence
// or forge an extra detail line.
func TestInfoSanitizesDriveValues(t *testing.T) {
	var out strings.Builder
	session := protocol.Session{
		ClusterSessionID: "res-1",
		Drive: &protocol.DriveSummary{
			State:  protocol.DriveStateRunning,
			Reason: "launched\x1b[31m\nsession_id: forged",
		},
	}
	if err := RenderSessionInfo(&out, protocol.Endpoint{EndpointID: "endpoint-1"}, session); err != nil {
		t.Fatalf("RenderSessionInfo: %v", err)
	}
	rendered := out.String()
	if strings.Contains(rendered, "\x1b") {
		t.Fatalf("escape sequence survived: %q", rendered)
	}
	for _, line := range strings.Split(rendered, "\n") {
		if strings.HasPrefix(line, "session_id:") && !strings.HasPrefix(line, "session_id: res-1") {
			t.Fatalf("forged detail line survived: %q", rendered)
		}
	}
}

// TestInfoRendersProviderPID proves the provider-reported session PID reaches the
// operator. The PID is the provider's own process identity, so it is the only
// value that lets an operator correlate a cluster row with a local process.
func TestInfoRendersProviderPID(t *testing.T) {
	stub := infoStub()
	stub.reports["endpoint-1"].Sessions[0].ProviderPID = 4242
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ninfo\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "res-1> ")
	if !strings.Contains(segment, "provider_pid: 4242") {
		t.Fatalf("missing provider PID in info output: %q", segment)
	}
}

// TestInfoLeavesUnreportedProviderPIDEmpty proves an absent PID is never printed
// as "0". A zero would read as a real process identity that happens to be
// unusable, so the value is left empty, matching every other unreported field in
// this detail view.
func TestInfoLeavesUnreportedProviderPIDEmpty(t *testing.T) {
	stub := infoStub()
	stub.reports["endpoint-1"].Sessions[0].ProviderPID = 0
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ninfo\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	segment := segmentBeforePrompt(output, "res-1> ")
	if !strings.Contains(segment, "provider_pid: \n") {
		t.Fatalf("missing empty provider_pid line: %q", segment)
	}
	if strings.Contains(segment, "provider_pid: 0") {
		t.Fatalf("unreported PID printed as a process identity: %q", segment)
	}
	if strings.Contains(segment, "provider_pid: not_reported") {
		t.Fatalf("unreported PID printed as a label instead of empty: %q", segment)
	}
}
