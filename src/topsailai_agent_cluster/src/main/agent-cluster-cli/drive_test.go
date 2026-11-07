package main

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// drivePathStub records the intents the standalone drive command admits and
// serves an inventory whose session carries a verified controller summary.
type drivePathStub struct {
	intents []protocol.ImmutableIntent
}

// ListEndpoints returns one endpoint so the drive command has a target.
func (s *drivePathStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}

// GetInventory returns a complete report with one drive-annotated session.
func (s *drivePathStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters:         []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
		Sessions: []protocol.Session{{
			SessionID:        "session",
			AdapterID:        "adapter-1",
			Generation:       "gen",
			State:            "running",
			CollectionStatus: protocol.CollectionSucceeded,
			Drive:            &protocol.DriveSummary{State: protocol.DriveStateRunning, Verified: true, ControllerPID: 4242, ObservedAtMS: 1700000000000},
		}},
	}, nil
}

// GetCapabilities advertises both drive operations so preflight can pass.
func (s *drivePathStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{{Name: protocol.OperationAgentDriveStart}, {Name: protocol.OperationAgentDriveStop}}}, nil
}

// GetCommand returns an immediate terminal result.
func (s *drivePathStub) GetCommand(context.Context, string) (map[string]any, error) {
	return map[string]any{"status": "finished"}, nil
}

// ListCommands returns no history.
func (s *drivePathStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}

// GetOutput returns an empty bounded snapshot.
func (s *drivePathStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// AdmitCommand records the intent and returns a durable command identifier.
func (s *drivePathStub) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.intents = append(s.intents, intent)
	return map[string]any{"command_id": "cmd-1"}, nil
}

// TestDriveHelpAdvertisesTheStandaloneSyntax proves the help text and the
// dispatch agree, so an operator never reads a syntax the command rejects.
func TestDriveHelpAdvertisesTheStandaloneSyntax(t *testing.T) {
	var helpOut, helpDiagnostics strings.Builder
	if err := runWithIO([]string{"help", "drive"}, strings.NewReader(""), &helpOut, &helpDiagnostics, false, nil); err != nil {
		t.Fatal(err)
	}
	const syntax = "agent-cluster-cli [options] drive <start|stop|status> <endpoint> <session> [generation]"
	if !strings.Contains(helpOut.String(), syntax) {
		t.Fatalf("help=%q missing executable syntax %q", helpOut.String(), syntax)
	}
	if !strings.Contains(helpOut.String(), "drive stop leaves the agent running") {
		t.Fatalf("help=%q does not distinguish the controller from the agent", helpOut.String())
	}
}

// TestDriveStatusReadsThePersistedInventory proves the standalone read path
// renders the stored controller summary without admitting a command.
func TestDriveStatusReadsThePersistedInventory(t *testing.T) {
	stub := &drivePathStub{}
	var output strings.Builder
	if err := drive(context.Background(), stub, &output, []string{"status", "ep", "session"}, false, false, 100, ""); err != nil {
		t.Fatalf("drive status: %v", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("drive status admitted %d commands", len(stub.intents))
	}
	if !strings.Contains(output.String(), "drive_state: running") || !strings.Contains(output.String(), "controller_pid: 4242") {
		t.Fatalf("drive status output=%q", output.String())
	}
}

// TestDriveStatusRejectsAGeneration proves the read path refuses a generation,
// because a generation selects a command target and the read has no target.
func TestDriveStatusRejectsAGeneration(t *testing.T) {
	cases := []struct {
		name       string
		args       []string
		generation string
	}{
		{name: "positional generation", args: []string{"status", "ep", "session", "gen"}},
		{name: "generation flag", args: []string{"status", "ep", "session"}, generation: "gen"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := &drivePathStub{}
			err := drive(context.Background(), stub, &strings.Builder{}, testCase.args, false, false, 100, testCase.generation)
			const want = "drive status takes no generation; it reads the persisted inventory"
			if err == nil || err.Error() != want {
				t.Fatalf("error=%v want %q", err, want)
			}
			if len(stub.intents) != 0 {
				t.Fatalf("rejected read admitted %d commands", len(stub.intents))
			}
		})
	}
}

// TestDriveStartRequiresConfirmation proves the mutating action is never
// submitted without --yes, so an unattended script cannot start a controller.
func TestDriveStartRequiresConfirmation(t *testing.T) {
	stub := &drivePathStub{}
	err := drive(context.Background(), stub, &strings.Builder{}, []string{"start", "ep", "session", "gen"}, false, false, 100, "")
	if err == nil || !strings.Contains(err.Error(), "confirmation required for drive start") {
		t.Fatalf("error=%v want a confirmation requirement", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("unconfirmed start admitted %d commands", len(stub.intents))
	}
}

// TestDriveStartRequiresAGeneration proves a mutating drive action cannot target
// an unspecified generation, because a stale generation must never be signalled.
func TestDriveStartRequiresAGeneration(t *testing.T) {
	stub := &drivePathStub{}
	err := drive(context.Background(), stub, &strings.Builder{}, []string{"start", "ep", "session"}, true, false, 100, "")
	if err == nil || err.Error() != "drive start requires a generation" {
		t.Fatalf("error=%v want a generation requirement", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("generation-less start admitted %d commands", len(stub.intents))
	}
}

// TestDriveStartAdmitsTheDriveOperation proves the confirmed standalone action
// submits the standard drive operation against the exact generation.
func TestDriveStartAdmitsTheDriveOperation(t *testing.T) {
	stub := &drivePathStub{}
	var output strings.Builder
	if err := drive(context.Background(), stub, &output, []string{"start", "ep", "session", "gen"}, true, false, 100, ""); err != nil {
		t.Fatalf("drive start: %v", err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents=%d want 1", len(stub.intents))
	}
	intent := stub.intents[0]
	if intent.Operation != protocol.OperationAgentDriveStart {
		t.Fatalf("operation=%q want %q", intent.Operation, protocol.OperationAgentDriveStart)
	}
	if intent.Target == nil || intent.Target.ResourceID != "session" || intent.Target.Generation != "gen" {
		t.Fatalf("target=%+v want session/gen", intent.Target)
	}
	// The legacy renderer emits the durable command result as JSON, so the
	// assertion targets the terminal status rather than a prose receipt.
	if !strings.Contains(output.String(), `"status": "finished"`) {
		t.Fatalf("missing durable result: %q", output.String())
	}
}

// TestDriveStopUsesTheDriveOperation proves the standalone stop path never
// degrades into an agent stop.
func TestDriveStopUsesTheDriveOperation(t *testing.T) {
	stub := &drivePathStub{}
	if err := drive(context.Background(), stub, &strings.Builder{}, []string{"stop", "ep", "session"}, true, false, 100, "gen"); err != nil {
		t.Fatalf("drive stop: %v", err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents=%d want 1", len(stub.intents))
	}
	if got := stub.intents[0].Operation; got != protocol.OperationAgentDriveStop {
		t.Fatalf("operation=%q want %q", got, protocol.OperationAgentDriveStop)
	}
}

// TestDriveRejectsMalformedArguments proves every malformed form fails before a
// command is admitted, so a typo cannot become a mutating request.
func TestDriveRejectsMalformedArguments(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want string
	}{
		{name: "no arguments", args: nil, want: "usage: drive <start|stop|status> <endpoint> <session> [generation]"},
		{name: "unknown action", args: []string{"bogus", "ep", "session"}, want: "usage: drive <start|stop|status> <endpoint> <session> [generation]"},
		{name: "missing session", args: []string{"start", "ep"}, want: "usage: drive start <endpoint> <session> [generation]"},
		{name: "misplaced flag", args: []string{"start", "ep", "session", "--json"}, want: `option "--json" must be written before the command; run help drive for valid syntax`},
		{name: "surplus argument", args: []string{"start", "ep", "session", "gen", "extra"}, want: `unexpected arguments "extra"; run help drive for valid syntax`},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := &drivePathStub{}
			err := drive(context.Background(), stub, &strings.Builder{}, testCase.args, true, false, 100, "")
			if err == nil || err.Error() != testCase.want {
				t.Fatalf("error=%v want %q", err, testCase.want)
			}
			if len(stub.intents) != 0 {
				t.Fatalf("malformed drive admitted %d commands", len(stub.intents))
			}
		})
	}
}

// TestDriveOperationMappingIsClosed proves the accepted action vocabulary is
// exactly the documented one, so no undocumented action reaches the API.
func TestDriveOperationMappingIsClosed(t *testing.T) {
	cases := []struct {
		action string
		want   string
		known  bool
	}{
		{action: "start", want: protocol.OperationAgentDriveStart, known: true},
		{action: "stop", want: protocol.OperationAgentDriveStop, known: true},
		{action: "status", want: "", known: true},
		{action: "restart", want: "", known: false},
		{action: "", want: "", known: false},
	}
	for _, testCase := range cases {
		t.Run(testCase.action, func(t *testing.T) {
			got, known := driveOperation(testCase.action)
			if got != testCase.want || known != testCase.known {
				t.Fatalf("driveOperation(%q)=(%q,%t) want (%q,%t)", testCase.action, got, known, testCase.want, testCase.known)
			}
		})
	}
}
