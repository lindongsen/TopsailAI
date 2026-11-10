package tui

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestInteractiveStartExactIntent pins quoted folders and inherited wait budgets.
func TestInteractiveStartExactIntent(t *testing.T) {
	for _, folder := range []string{`"/tmp/work folder"`, `""`, `'C:\work folder'`} {
		stub := &interactiveStub{}
		var out, diagnostics strings.Builder
		input := "start endpoint-1 compatibility --profile p --profile-revision r --folder " + folder + "\nquit\n"
		if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &out, &diagnostics, InteractiveOptions{WaitTimeoutMS: 1234}); err != nil {
			t.Fatal(err)
		}
		if diagnostics.Len() != 0 || len(stub.intents) != 1 {
			t.Fatalf("diagnostics=%q intents=%v", diagnostics.String(), stub.intents)
		}
		intent := stub.intents[0]
		if intent.Operation != protocol.OperationAgentStart || intent.EndpointID != "endpoint-1" || intent.Target != nil || intent.LaunchProfileID != "p" || intent.ProfileRevision != "r" || intent.Folder != folder[1:len(folder)-1] || intent.Budget.WaitTimeoutMS != 1234 {
			t.Fatalf("intent=%+v", intent)
		}
	}
}

// TestInteractiveSessionExactIntents checks every lifecycle/control operation and alias.
func TestInteractiveSessionExactIntents(t *testing.T) {
	for command, op := range map[string]string{"stop": protocol.OperationAgentStop, "btw": protocol.OperationContextInject, "interrupt": protocol.OperationExecutionInterrupt} {
		t.Run(command, func(t *testing.T) {
			stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
			payload := `{}`
			line := command
			if op == protocol.OperationContextInject {
				payload = `{"text":"literal --json is data"}`
				line += " " + payload
			}
			if op == protocol.OperationExecutionInterrupt {
				payload = `{"action":"soft_interrupt","message":"literal --json is data"}`
				line += " " + payload
			}
			var out, diagnostics strings.Builder
			if err := RunInteractive(context.Background(), stub, strings.NewReader("cd endpoint-1/session-1\n"+line+"\ny\nquit\n"), &out, &diagnostics, InteractiveOptions{WaitTimeoutMS: 321}); err != nil {
				t.Fatal(err)
			}
			if diagnostics.Len() != 0 || len(stub.intents) != 1 {
				t.Fatalf("diagnostics=%q intents=%v", diagnostics.String(), stub.intents)
			}
			i := stub.intents[0]
			if i.Operation != op || i.EndpointID != "endpoint-1" || i.Target == nil || i.Target.ResourceID != "session-1" || i.Target.ProviderGeneration != "generation-1" || string(i.Payload) != payload || i.Budget.WaitTimeoutMS != 321 {
				t.Fatalf("intent=%+v", i)
			}
			if !json.Valid(i.Payload) {
				t.Fatal("invalid payload")
			}
		})
	}
}

// TestInteractiveArgumentErrors checks malformed quoting and explicit machine-output rejection.
func TestInteractiveArgumentErrors(t *testing.T) {
	for _, input := range []string{`endpoint resource --profile p --profile-revision r --folder "unfinished`, `endpoint resource --profile`, `endpoint resource --profile p --profile-revision`, `endpoint resource --profile p --profile-revision r --folder`, `endpoint resource --unknown`, `endpoint`, ``} {
		if _, err := parseInteractiveStart(input); err == nil {
			t.Fatalf("accepted %q", input)
		}
	}
	for _, command := range []string{"stop", "interrupt", "btw"} {
		stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
		_, diagnostics := runScope(t, stub, "cd endpoint-1/session-1\n"+command+" --json\nquit\n", ColorPolicy{})
		if !strings.Contains(diagnostics, "non-interactive") && !strings.Contains(diagnostics, "does not support --json") {
			t.Fatalf("%s: %q", command, diagnostics)
		}
	}
}

// TestInteractiveLifecycleRejectsChangedGeneration prevents confirmation from authorizing a replacement.
func TestInteractiveLifecycleRejectsChangedGeneration(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}, generationSequence: []string{"generation-1", "generation-1", "generation-1", "generation-2"}}
	_, diagnostics := runScope(t, stub, "cd endpoint-1/session-1\nstop\ny\nquit\n", ColorPolicy{})
	if stub.admit != 0 || !strings.Contains(diagnostics, "generation changed") {
		t.Fatalf("admit=%d diagnostics=%q calls=%d", stub.admit, diagnostics, stub.inventoryCalls)
	}
}

// TestInteractiveResumeIsNotASessionCommand pins the scope boundary of the
// interactive resume spelling. Resume authorizes on a proven absence while session
// scope requires a live generation, so resume is offered only where a history row
// can be selected and session scope keeps rejecting the command word.
func TestInteractiveResumeIsNotASessionCommand(t *testing.T) {
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint} {
		if !containsCommand(availableCommands(kind), "resume") {
			t.Fatalf("resume must be offered in %s scope", kind)
		}
	}
	if containsCommand(availableCommands(ScopeSession), "resume") {
		t.Fatal("resume must not be offered in session scope")
	}
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	_, diagnostics := runScope(t, stub, "cd endpoint-1/session-1\nresume\nquit\n", ColorPolicy{})
	if stub.admit != 0 || !strings.Contains(diagnostics, `unavailable in session scope`) {
		t.Fatalf("admit=%d diagnostics=%q", stub.admit, diagnostics)
	}
}

// TestStandaloneResumeHelpSurvivesRemoval proves the operation stays reachable through
// the standalone CLI, so removing the interactive spelling never removes the capability.
func TestStandaloneResumeHelpSurvivesRemoval(t *testing.T) {
	var out strings.Builder
	if err := PrintNonInteractiveCommandHelp(&out, "resume"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "resume <endpoint> <resource>") {
		t.Fatalf("standalone resume help=%q", out.String())
	}
}

// TestInteractiveNewCommandHelpAndScope covers every newly exposed session command.
func TestInteractiveNewCommandHelpAndScope(t *testing.T) {
	for _, name := range []string{"btw", "interrupt", "control"} {
		var out strings.Builder
		if err := PrintCommandHelp(&out, name); err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(out.String(), "Available in: session") {
			t.Fatalf("%s help=%q", name, out.String())
		}
		if !commandAllowed(name, ScopeSession) || commandAllowed(name, ScopeEndpoint) || commandAllowed(name, ScopeWorkspace) {
			t.Fatalf("invalid scopes for %s", name)
		}
	}
}

// TestInteractiveStopHelpAndScope proves stop is the one lifecycle command reachable
// from every scope, because a row number is enough to name its target.
func TestInteractiveStopHelpAndScope(t *testing.T) {
	var out strings.Builder
	if err := PrintCommandHelp(&out, "stop"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Available in: workspace, endpoint, session") {
		t.Fatalf("stop help=%q", out.String())
	}
	for _, kind := range []ScopeKind{ScopeWorkspace, ScopeEndpoint, ScopeSession} {
		if !commandAllowed("stop", kind) {
			t.Fatalf("stop must be allowed in %s scope", kind)
		}
	}
}

// TestStartMinimalProfileArguments omits the optional folder and rejects empty identities.
func TestStartMinimalProfileArguments(t *testing.T) {
	request, err := parseInteractiveStart("endpoint resource --profile p --profile-revision r")
	if err != nil || request.Folder != "" {
		t.Fatalf("request=%+v err=%v", request, err)
	}
	for _, args := range []string{`"" resource --profile p --profile-revision r`, `endpoint "" --profile p --profile-revision r`} {
		if _, err := parseInteractiveStart(args); err == nil {
			t.Fatalf("accepted %q", args)
		}
	}
}

// TestInteractiveStartPayload pins the plain-text task payload.
func TestInteractiveStartPayload(t *testing.T) {
	stub := &interactiveStub{}
	var out, diagnostics strings.Builder
	input := `start endpoint-1 resource-1 --profile p --profile-revision r --task "literal --json data"` + "\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &out, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if diagnostics.Len() != 0 || len(stub.intents) != 1 || string(stub.intents[0].Payload) != `{"task":"literal --json data"}` {
		t.Fatalf("diagnostics=%q intents=%+v", diagnostics.String(), stub.intents)
	}
}

// TestInteractivePayloadValidationRejectsJSONArguments verifies no JSON payload argument is admitted.
func TestInteractivePayloadValidationRejectsJSONArguments(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	_, diagnostics := runScope(t, stub, `start endpoint-1 resource-1 --profile p --profile-revision r --payload nope`+"\nquit\n", ColorPolicy{})
	if stub.admit != 0 || !strings.Contains(diagnostics, "--payload") {
		t.Fatalf("admit=%d diagnostics=%q", stub.admit, diagnostics)
	}
}

// TestInteractiveStartKeepsCommandIDWhenStatusQueryFails prevents unsafe resubmission advice.
func TestInteractiveStartKeepsCommandIDWhenStatusQueryFails(t *testing.T) {
	stub := &interactiveStub{getCommandErr: errors.New("status unavailable"), admittedCommandID: "accepted-123"}
	var out, diagnostics strings.Builder
	input := "start endpoint-1 resource-1 --profile p --profile-revision r\nstatus\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &out, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 || !strings.Contains(out.String(), "command submitted: accepted-123") || !strings.Contains(diagnostics.String(), "command accepted-123 status unavailable; use status accepted-123") {
		t.Fatalf("admit=%d out=%q diagnostics=%q", stub.admit, out.String(), diagnostics.String())
	}
}

// TestInteractiveStartReportsUncertainAdmissionID verifies an ambiguous admission is never retried.
func TestInteractiveStartReportsUncertainAdmissionID(t *testing.T) {
	stub := &interactiveStub{admitErr: errors.New("transport lost")}
	var out, diagnostics strings.Builder
	input := "start endpoint-1 resource-1 --profile p --profile-revision r\nstatus\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &out, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 || !strings.Contains(diagnostics.String(), "result unknown; use status cli-") {
		t.Fatalf("admit=%d out=%q diagnostics=%q", stub.admit, out.String(), diagnostics.String())
	}
}
