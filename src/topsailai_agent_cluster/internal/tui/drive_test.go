package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// driveCapabilityStub advertises the drive operations, because the shared
// interactive fixture advertises only the lifecycle operations it was written
// for and a drive command must be rejected by capability preflight otherwise.
type driveCapabilityStub struct {
	*interactiveStub
}

// GetCapabilities returns a descriptor that advertises both drive operations.
func (s driveCapabilityStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{
		Revision:     "r-drive",
		Capabilities: []protocol.Capability{{Name: protocol.OperationAgentDriveStart}, {Name: protocol.OperationAgentDriveStop}},
	}, nil
}

// driveStub returns a session-scoped fixture whose session carries a verified
// controller summary, so the read projection has something to render.
func driveStub() *interactiveStub {
	stub := scopeStub()
	report := stub.reports["endpoint-1"]
	report.Sessions[0].Drive = &protocol.DriveSummary{
		State:         protocol.DriveStateRunning,
		ControllerPID: 4242,
		RunID:         "run-1",
		Verified:      true,
		ObservedAtMS:  1700000000000,
	}
	stub.reports["endpoint-1"] = report
	return stub
}

// TestDriveIsUnavailableOutsideSessionScope proves the controller command never
// becomes reachable from a scope that has no selected session to control.
func TestDriveIsUnavailableOutsideSessionScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{
			name:  "workspace",
			input: "drive status\nquit\n",
			want:  `command "drive" is unavailable in workspace scope; available commands: list, endpoints, cd, show, start, stop, status, refresh, watch, help, quit`,
		},
		{
			name:  "endpoint",
			input: "cd host-one/endpoint-1\ndrive status\nquit\n",
			want:  `command "drive" is unavailable in endpoint scope; available commands: list, cd, show, start, stop, logs, status, refresh, watch, help, quit`,
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := driveStub()
			_, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			assertActionableError(t, diagnostics, "error: "+testCase.want)
			if stub.admit != 0 {
				t.Fatalf("rejected drive admitted %d commands", stub.admit)
			}
		})
	}
}

// TestDriveStatusRendersThePersistedControllerSummary proves the read projection
// reports the standard state together with its verification and freshness, so an
// unverified record is never presented as a live controller.
func TestDriveStatusRendersThePersistedControllerSummary(t *testing.T) {
	stub := driveStub()
	var out strings.Builder
	if err := (CommandRunner{API: stub, Policy: LegacyPolicy}).DriveStatus(context.Background(), &out, "endpoint-1", "res-1", false); err != nil {
		t.Fatalf("DriveStatus: %v", err)
	}
	for _, want := range []string{"session: res-1", "drive_state: running", "drive_verified: true", "drive_observed_at_ms: 1700000000000", "controller_pid: 4242", "drive_run_id: run-1"} {
		if !strings.Contains(out.String(), want) {
			t.Fatalf("drive status missing %q: %q", want, out.String())
		}
	}
	if stub.admit != 0 {
		t.Fatalf("drive status admitted %d commands", stub.admit)
	}
}

// TestDriveStatusReportsAnUnobservedControllerAsNotReported proves a provider
// that reported nothing is not rendered as a stopped controller, because the
// absence of an observation is not evidence that no controller exists.
func TestDriveStatusReportsAnUnobservedControllerAsNotReported(t *testing.T) {
	stub := scopeStub()
	var out strings.Builder
	if err := (CommandRunner{API: stub, Policy: LegacyPolicy}).DriveStatus(context.Background(), &out, "endpoint-1", "res-1", false); err != nil {
		t.Fatalf("DriveStatus: %v", err)
	}
	if !strings.Contains(out.String(), "drive_state: not_reported") || !strings.Contains(out.String(), "not proof that no driver exists") {
		t.Fatalf("unobserved controller rendered as a state: %q", out.String())
	}
	if strings.Contains(out.String(), "drive_state: none") {
		t.Fatalf("unobserved controller claimed a known state: %q", out.String())
	}
}

// TestDriveStatusRejectsUnprovableInventory proves the read projection fails
// closed instead of reporting a controller state from an incomplete report or an
// unreported session.
func TestDriveStatusRejectsUnprovableInventory(t *testing.T) {
	incomplete := scopeStub()
	report := incomplete.reports["endpoint-1"]
	report.ReportComplete = false
	incomplete.reports["endpoint-1"] = report
	cases := []struct {
		name       string
		stub       *interactiveStub
		resourceID string
		want       string
	}{
		{name: "incomplete report", stub: incomplete, resourceID: "res-1", want: `endpoint "endpoint-1" inventory is incomplete; drive state is unknown`},
		{name: "unreported session", stub: scopeStub(), resourceID: "res-missing", want: `session "res-missing" was not reported by endpoint "endpoint-1"`},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var out strings.Builder
			err := (CommandRunner{API: testCase.stub, Policy: LegacyPolicy}).DriveStatus(context.Background(), &out, "endpoint-1", testCase.resourceID, false)
			if err == nil || err.Error() != testCase.want {
				t.Fatalf("error=%v want %q", err, testCase.want)
			}
			if out.Len() != 0 {
				t.Fatalf("failed read wrote output: %q", out.String())
			}
		})
	}
}

// TestDriveStatusJSONCarriesTheRequestIdentity proves a JSON caller can correlate
// the answer with the request it sent without parsing prose.
func TestDriveStatusJSONCarriesTheRequestIdentity(t *testing.T) {
	stub := driveStub()
	var out strings.Builder
	if err := (CommandRunner{API: stub, Policy: LegacyPolicy}).DriveStatus(context.Background(), &out, "endpoint-1", "res-1", true); err != nil {
		t.Fatalf("DriveStatus: %v", err)
	}
	for _, want := range []string{`"endpoint_id": "endpoint-1"`, `"session_id": "res-1"`, `"generation": "generation-1"`, `"state": "running"`, `"verified": true`} {
		if !strings.Contains(out.String(), want) {
			t.Fatalf("drive status JSON missing %q: %q", want, out.String())
		}
	}
}

// TestInteractiveDriveDefaultsToTheReadProjection proves a bare drive never
// mutates anything, so an operator who only wants the state cannot start a
// controller by accident.
func TestInteractiveDriveDefaultsToTheReadProjection(t *testing.T) {
	stub := driveStub()
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("bare drive admitted %d commands", stub.admit)
	}
	if !strings.Contains(output, "drive_state: running") {
		t.Fatalf("bare drive did not render the state: %q", output)
	}
}

// TestInteractiveDriveStartRequiresConfirmation proves the mutating drive action
// is never submitted without an explicit operator confirmation.
func TestInteractiveDriveStartRequiresConfirmation(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive start\nn\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 0 {
		t.Fatalf("declined drive start admitted %d commands", stub.admit)
	}
	if !strings.Contains(output, "drive start cancelled") {
		t.Fatalf("missing cancellation notice: %q", output)
	}
}

// TestInteractiveDriveStartAdmitsTheDriveOperation proves the confirmed action
// submits the standard drive operation against the exact selected generation.
func TestInteractiveDriveStartAdmitsTheDriveOperation(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive start\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 || len(stub.intents) != 1 {
		t.Fatalf("admitted %d commands with %d intents, want 1", stub.admit, len(stub.intents))
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationAgentDriveStart {
		t.Fatalf("operation=%q want %q", intent.Operation, protocol.OperationAgentDriveStart)
	}
	if intent.Target == nil || intent.Target.ResourceID != "res-1" || intent.Target.Generation != "generation-1" {
		t.Fatalf("target=%+v want res-1/generation-1", intent.Target)
	}
	if !strings.Contains(output, "CommandID:") {
		t.Fatalf("missing durable receipt: %q", output)
	}
}

// TestInteractiveDriveStopIsNotAgentStop proves stopping the controller is a
// distinct operation, because an operator who stops a driver must not stop the
// agent that the driver was driving.
func TestInteractiveDriveStopIsNotAgentStop(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive stop\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents=%d want 1", len(stub.intents))
	}
	if got := stub.intents[0].Operation; got != protocol.OperationAgentDriveStop {
		t.Fatalf("operation=%q want %q", got, protocol.OperationAgentDriveStop)
	}
	if got := stub.intents[0].Operation; got == protocol.OperationAgentStop {
		t.Fatalf("drive stop was submitted as agent stop")
	}
}

// TestInteractiveDriveRejectsUnknownActionsAndOptions proves the interactive
// grammar stays closed: an unknown action and a non-interactive option are both
// rejected before any command is admitted.
func TestInteractiveDriveRejectsUnknownActionsAndOptions(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "unknown action", input: "cd host-one/endpoint-1/res-1\ndrive bogus\nquit\n", want: "usage: drive [start|stop|status]"},
		{name: "non-interactive option", input: "cd host-one/endpoint-1/res-1\ndrive --json\nquit\n", want: `option "--json" is available only in non-interactive mode; JSON output is available only with the standalone command`},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := driveCapabilityStub{interactiveStub: driveStub()}
			_, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if !strings.Contains(diagnostics, testCase.want) {
				t.Fatalf("diagnostics=%q want %q", diagnostics, testCase.want)
			}
			if stub.admit != 0 {
				t.Fatalf("rejected drive admitted %d commands", stub.admit)
			}
		})
	}
}
