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

// ambiguousDriveStub reports the same session identifier on two endpoints, so a
// workspace-scope target that names no endpoint is genuinely ambiguous.
func ambiguousDriveStub() *interactiveStub {
	stub := driveStub()
	stub.reports["endpoint-2"] = scopeInventory("res-1", "generation-2")
	return stub
}

// TestDriveStatusResolvesTargetOutsideSessionScope proves the read projection is
// reachable from workspace and endpoint scope by naming the session, so an
// operator does not have to enter a session to inspect its controller.
func TestDriveStatusResolvesTargetOutsideSessionScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "workspace", input: "drive res-1\nquit\n"},
		{name: "endpoint", input: "cd host-one/endpoint-1\ndrive res-1\nquit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := driveStub()
			output, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics: %q", diagnostics)
			}
			if !strings.Contains(output, "session: res-1") || !strings.Contains(output, "drive_state: running") {
				t.Fatalf("drive status did not render the controller: %q", output)
			}
			if stub.admit != 0 {
				t.Fatalf("drive status admitted %d commands", stub.admit)
			}
		})
	}
}

// TestDriveStatusAcceptsARowNumberInWorkspaceScope proves the documented
// "drive [number]" form resolves the row rendered by the startup list, so the
// operator can use the same shorthand that cd and stop accept.
func TestDriveStatusAcceptsARowNumberInWorkspaceScope(t *testing.T) {
	stub := driveStub()
	output, diagnostics := runScope(t, stub, "drive 1\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(output, "session: res-1") || !strings.Contains(output, "drive_state: running") {
		t.Fatalf("row-number drive did not render the controller: %q", output)
	}
	if stub.admit != 0 {
		t.Fatalf("drive status admitted %d commands", stub.admit)
	}
}

// TestDriveRequiresATargetOutsideSessionScope proves a bare drive in a scope with
// no selected session fails closed instead of guessing which session to control.
func TestDriveRequiresATargetOutsideSessionScope(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "workspace", input: "drive\nexit\n", want: "drive requires a session in workspace scope; use drive <number> for a session row"},
		{name: "endpoint", input: "cd host-one/endpoint-1\ndrive\nexit\n", want: "drive requires a session in endpoint scope; use drive <number> for a session row"},
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

// TestDriveStartInWorkspaceScopeAdmitsTheExactTarget proves the mutating action
// submits the standard drive operation against the endpoint-scoped session the
// operator named, even though workspace scope has no current endpoint.
func TestDriveStartInWorkspaceScopeAdmitsTheExactTarget(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	output, diagnostics := runScope(t, stub, "drive start res-1\ny\nquit\n", ColorPolicy{})
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
	if intent.Target == nil || intent.Target.ResourceID != "res-1" || intent.Target.ProviderGeneration != "generation-1" {
		t.Fatalf("target=%+v want res-1/generation-1", intent.Target)
	}
	if intent.EndpointID != "endpoint-1" {
		t.Fatalf("endpoint=%q want endpoint-1", intent.EndpointID)
	}
	if !strings.Contains(output, "CommandID:") {
		t.Fatalf("missing durable receipt: %q", output)
	}
}

// TestDriveStopInWorkspaceScopeIsNotAgentStop proves the workspace-scope stop
// action still targets the controller rather than the agent.
func TestDriveStopInWorkspaceScopeIsNotAgentStop(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	_, diagnostics := runScope(t, stub, "drive stop res-1\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents=%d want 1", len(stub.intents))
	}
	if got := stub.intents[0].Operation; got != protocol.OperationAgentDriveStop {
		t.Fatalf("operation=%q want %q", got, protocol.OperationAgentDriveStop)
	}
}

// TestDriveRejectsATargetOutsideTheCurrentEndpoint proves endpoint scope never
// retargets a session that belongs to another endpoint, because the operator
// named a session the current table does not contain.
func TestDriveRejectsATargetOutsideTheCurrentEndpoint(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1\ndrive start res-2\nquit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: session "res-2" was not found on endpoint "endpoint-1"`)
	if stub.admit != 0 {
		t.Fatalf("rejected drive admitted %d commands", stub.admit)
	}
}

// TestDriveRejectsAnAmbiguousWorkspaceTarget proves a session identifier reported
// by several endpoints is rejected instead of being silently retargeted, because
// the operator named no endpoint.
func TestDriveRejectsAnAmbiguousWorkspaceTarget(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: ambiguousDriveStub()}
	_, diagnostics := runScope(t, stub, "drive start res-1\nquit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, `error: multiple sessions match "res-1"; use drive <number> with a row from list`)
	if stub.admit != 0 {
		t.Fatalf("ambiguous drive admitted %d commands", stub.admit)
	}
}

// TestDriveInSessionScopeRejectsATarget proves session scope keeps its pinned
// selection and refuses an argument, because the scope already names the target.
func TestDriveInSessionScopeRejectsATarget(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive res-1\nquit\n", ColorPolicy{})
	assertActionableError(t, diagnostics, "error: invalid arguments")
	if stub.admit != 0 {
		t.Fatalf("rejected drive admitted %d commands", stub.admit)
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
	for _, want := range []string{"session: res-1", "drive_state: running", "drive_verified: true", "controller_pid: 4242", "drive_run_id: run-1"} {
		if !strings.Contains(out.String(), want) {
			t.Fatalf("drive status missing %q: %q", want, out.String())
		}
	}
	assertRenderedInstant(t, out.String(), "drive_observed_at", 1700000000000)
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
	for _, want := range []string{`"endpoint_id": "endpoint-1"`, `"cluster_session_id": "res-1"`, `"provider_generation": "generation-1"`, `"state": "running"`, `"verified": true`} {
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
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive\nexit\n", ColorPolicy{})
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
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive start\nn\nexit\n", ColorPolicy{})
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
	output, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive start\ny\nexit\n", ColorPolicy{})
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
	if intent.Target == nil || intent.Target.ResourceID != "res-1" || intent.Target.ProviderGeneration != "generation-1" {
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
	_, diagnostics := runScope(t, stub, "cd host-one/endpoint-1/res-1\ndrive stop\ny\nexit\n", ColorPolicy{})
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
		{name: "unknown action", input: "cd host-one/endpoint-1/res-1\ndrive bogus\nexit\n", want: "usage: drive [start|stop|status]"},
		{name: "non-interactive option", input: "cd host-one/endpoint-1/res-1\ndrive --json\nexit\n", want: `option "--json" is available only in non-interactive mode; JSON output is available only with the standalone command`},
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

// namedDriveStub returns the drive fixture with a reported session name, so a test
// can prove the confirmation question and the progress header both name the
// session the operator selected.
func namedDriveStub() *interactiveStub {
	stub := driveStub()
	report := stub.reports["endpoint-1"]
	report.Sessions[0].ProviderDisplayName = "Daily work"
	stub.reports["endpoint-1"] = report
	return stub
}

// TestDriveStartConfirmationNamesTheSession proves the drive start question names
// the reported session name first, then the provider session identifier, then the
// opaque cluster resource ID. The interactive table hides SESSION_ID, so the
// question is the only place the operator sees the provider identifier, and the
// reported name is the only value they saw in the table.
func TestDriveStartConfirmationNamesTheSession(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: namedDriveStub()}
	output, diagnostics := runScope(t, stub, "drive start res-1\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	const question = `drive start session (Daily work) (provider-res-1)? Confirm drive start?`
	if !strings.Contains(output, question) {
		t.Fatalf("drive start question does not name the session: %q", output)
	}
	// The reported name must precede both identifiers, because it is the value the
	// operator can match against the row they selected.
	if strings.Index(question, "Daily work") > strings.Index(question, "provider-res-1") {
		t.Fatalf("reported name is not the first value in the question: %q", question)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
}

// TestDriveStopConfirmationNamesTheSession proves the sibling drive action uses the
// same wording, because both share one confirmation label. A fix applied to only
// one of the two actions would leave the operator reading two different target
// descriptions for the same session.
func TestDriveStopConfirmationNamesTheSession(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: namedDriveStub()}
	output, diagnostics := runScope(t, stub, "drive stop res-1\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	const question = `drive stop session (Daily work) (provider-res-1)? Confirm drive stop?`
	if !strings.Contains(output, question) {
		t.Fatalf("drive stop question does not name the session: %q", output)
	}
}

// TestDriveConfirmationNamesTheProviderIDWithoutAName proves a session the provider
// reported no name for still names the provider session identifier, and omits the
// empty name rather than printing "()". The name is descriptive report data, so its
// absence must not degrade the question into an opaque resource ID.
func TestDriveConfirmationNamesTheProviderIDWithoutAName(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	output, diagnostics := runScope(t, stub, "drive start res-1\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	const question = "drive start session (provider-res-1)? Confirm drive start?"
	if !strings.Contains(output, question) {
		t.Fatalf("unnamed session changed the question: %q", output)
	}
}

// TestDriveConfirmationSanitizesTheReportedName proves the reported name is
// untrusted provider text. It is interpolated into a trusted styled line, so an
// escape sequence must be stripped instead of reaching the terminal.
func TestDriveConfirmationSanitizesTheReportedName(t *testing.T) {
	stub := driveCapabilityStub{interactiveStub: driveStub()}
	report := stub.reports["endpoint-1"]
	report.Sessions[0].ProviderDisplayName = "evil\x1b[31mname"
	stub.reports["endpoint-1"] = report
	output, diagnostics := runScope(t, stub, "drive start res-1\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if strings.Contains(output, "\x1b[31m") {
		t.Fatalf("reported name reached the terminal unsanitized: %q", output)
	}
	if !strings.Contains(output, "evilname") {
		t.Fatalf("sanitized name is missing from the question: %q", output)
	}
}
