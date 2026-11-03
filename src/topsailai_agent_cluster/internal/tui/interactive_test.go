package tui

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

type interactiveStub struct {
	endpoints          []protocol.Endpoint
	reports            map[string]protocol.InventoryReport
	intents            []protocol.ImmutableIntent
	admit              int
	failList           bool
	changeAfter        int
	generationSequence []string
	inventoryCalls     int
	getCommandErr      error
	admitErr           error
	admittedCommandID  string
}

func (s *interactiveStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	if s.failList {
		s.failList = false
		return nil, errors.New("temporary list failure")
	}
	return s.endpoints, nil
}
func (s *interactiveStub) GetInventory(_ context.Context, id string) (protocol.InventoryReport, error) {
	s.inventoryCalls++
	report, ok := s.reports[id]
	if !ok {
		return protocol.InventoryReport{}, errors.New("missing inventory")
	}
	if len(s.generationSequence) > 0 {
		index := s.inventoryCalls - 1
		if index >= len(s.generationSequence) {
			index = len(s.generationSequence) - 1
		}
		report.Sessions = append([]protocol.Session(nil), report.Sessions...)
		report.Sessions[0].Generation = s.generationSequence[index]
	} else if s.changeAfter > 0 && s.inventoryCalls >= s.changeAfter {
		report.Sessions = append([]protocol.Session(nil), report.Sessions...)
		report.Sessions[0].Generation = "generation-2"
	}
	return report, nil
}
func (s *interactiveStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}, {Name: protocol.OperationAgentStart}, {Name: protocol.OperationAgentResume}, {Name: protocol.OperationAgentStop}, {Name: protocol.OperationContextInject}, {Name: protocol.OperationExecutionInterrupt}}}, nil
}
func (s *interactiveStub) GetCommand(context.Context, string) (map[string]any, error) {
	if s.getCommandErr != nil {
		return nil, s.getCommandErr
	}
	return map[string]any{"status": string(protocol.StatusFinished)}, nil
}
func (s *interactiveStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}
func (s *interactiveStub) GetOutput(context.Context, string, string, string, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{Data: "log\x1b[31m"}, nil
}
func (s *interactiveStub) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.admit++
	s.intents = append(s.intents, intent)
	if s.admitErr != nil {
		return nil, s.admitErr
	}
	commandID := s.admittedCommandID
	if commandID == "" {
		commandID = "cmd-1"
	}
	return map[string]any{"command_id": commandID}, nil
}

func testInventory() protocol.InventoryReport {
	return protocol.InventoryReport{ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}}, Sessions: []protocol.Session{{SessionID: "session-1", AdapterID: "adapter-1", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded}}}
}

func TestInteractiveListUsesTableHeaders(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("list\nquit\n"), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	for _, header := range tableHeaders {
		if !strings.Contains(output.String(), header) {
			t.Fatalf("interactive list missing header %q: %q", header, output.String())
		}
	}
}

func TestInteractiveLoopContinuesAfterErrorAndQuit(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}, failList: true}
	var output, errorsOut strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("bad\nhelp\nquit\n"), &output, &errorsOut, InteractiveOptions{LineLimit: 128})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(errorsOut.String(), `unknown command "bad"`) || !strings.Contains(output.String(), "Current scope:") {
		t.Fatalf("recovery output missing: out=%q err=%q", output.String(), errorsOut.String())
	}
	if !strings.Contains(output.String(), "cluster> ") {
		t.Fatalf("prompt missing: %q", output.String())
	}
}

func TestInteractiveUseChangesPromptAndEOFIsSuccessful(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("cd endpoint-1/session-1\nstatus\n"), &output, &errorsOut, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(output.String(), "cluster[endpoint-1/-]> ") || !strings.Contains(output.String(), "running") {
		t.Fatalf("state output missing: %q", output.String())
	}
}

func TestInteractiveSendDeclineDoesNotAdmitAndEscapeIsFiltered(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\nn\nlogs\nquit\n"), &output, &errorsOut, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("declined send admitted %d commands", stub.admit)
	}
	if strings.Contains(output.String(), "\x1b") {
		t.Fatalf("terminal escape leaked: %q", output.String())
	}
}

func TestInteractiveRejectsNilStreams(t *testing.T) {
	if err := RunInteractive(context.Background(), &interactiveStub{}, nil, io.Discard, io.Discard, InteractiveOptions{}); err == nil {
		t.Fatal("expected nil reader error")
	}
}

func TestInteractiveCommandsCoverShowLogsRefreshAndSend(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	input := "cd endpoint-1/session-1\nshow\nlogs\nrefresh\nsend {\"text\":\"hi\"}\ny\nstatus cmd-1\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 1 || !strings.Contains(output.String(), "command submitted") || !strings.Contains(output.String(), "running") {
		t.Fatalf("unexpected output=%q errors=%q admits=%d", output.String(), errorsOut.String(), stub.admit)
	}
}

func TestInteractiveLineLimitAndClear(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	input := "xxxxxxxxxxxx\ncd endpoint-1/session-1\ncd\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{LineLimit: 4}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errorsOut.String(), "exceeds") || !strings.Contains(output.String(), "cluster>") {
		t.Fatalf("limit/clear not covered: %q %q", output.String(), errorsOut.String())
	}
}

func TestSanitizeTerminalControls(t *testing.T) {
	clean := sanitizeTerminal([]byte("a\x1b[31mb\r\x00\u202e c\n"))
	if strings.ContainsAny(clean, "\x1b\r\x00") || strings.Contains(clean, "\u202e") {
		t.Fatalf("unsafe output: %q", clean)
	}
}

type shortWriter struct{ target strings.Builder }

func (w *shortWriter) Write(data []byte) (int, error) {
	n := 1
	if len(data) < n {
		n = len(data)
	}
	w.target.Write(data[:n])
	return n, nil
}
func TestSafeWriterHandlesShortWrites(t *testing.T) {
	var target shortWriter
	writer := newSafeWriter(&target)
	if _, err := writer.Write([]byte("hello\n")); err != nil {
		t.Fatal(err)
	}
	if target.target.String() != "hello\n" {
		t.Fatalf("short write lost data: %q", target.target.String())
	}
}

func TestInteractiveGenerationChangePreventsAdmission(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}, changeAfter: 3}
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 0 {
		t.Fatalf("generation change admitted %d commands", stub.admit)
	}
	if !strings.Contains(errorsOut.String(), "generation changed") {
		t.Fatalf("missing generation error: %q", errorsOut.String())
	}
}
func TestInteractiveShowRejectsSelectedGenerationChange(t *testing.T) {
	stub := &interactiveStub{
		endpoints:   []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:     map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
		changeAfter: 3,
	}
	var output, errorsOut strings.Builder
	input := "cd endpoint-1/session-1\nshow\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(errorsOut.String(), "selected session generation changed; use the session again") {
		t.Fatalf("missing generation fencing error: %q", errorsOut.String())
	}
	if strings.Contains(output.String(), "session: session-1 adapter=") {
		t.Fatalf("show returned details after generation change: %q", output.String())
	}
	if stub.inventoryCalls != 3 {
		t.Fatalf("inventory calls=%d want=2", stub.inventoryCalls)
	}
}

func TestReplacementInvalidationIsStickyAndRequiresUse(t *testing.T) {
	stub := &interactiveStub{
		endpoints:          []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:            map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
		generationSequence: []string{"generation-1", "generation-1", "generation-2", "generation-1", "generation-1", "generation-1"},
	}
	var output, errorsOut strings.Builder
	input := "cd endpoint-1/session-1\nrefresh\nrefresh\ncd endpoint-1/session-1\nstatus\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "cluster[endpoint-1/-!]> ") {
		t.Fatalf("missing invalidated prompt: %q", output.String())
	}
	if strings.Count(errorsOut.String(), "selected session generation changed; use the session again") != 1 {
		t.Fatalf("unexpected generation errors: %q", errorsOut.String())
	}
	if !strings.Contains(errorsOut.String(), "selected session invalidated; use the session again") {
		t.Fatalf("missing sticky invalidation error: %q", errorsOut.String())
	}
	if !strings.Contains(output.String(), "running") {
		t.Fatalf("explicit use did not restore operation: %q", output.String())
	}
}

func TestInvalidatedSelectionRejectsTargetOperationsWithoutAdmission(t *testing.T) {
	stub := &interactiveStub{
		endpoints:          []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:            map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
		generationSequence: []string{"generation-1", "generation-1", "generation-2"},
	}
	var output, errorsOut strings.Builder
	input := "cd endpoint-1/session-1\nrefresh\nshow\nlogs\nstatus\nsend {\"text\":\"blocked\"}\ny\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if stub.admit != 0 {
		t.Fatalf("invalidated send admitted %d commands", stub.admit)
	}
	if strings.Count(errorsOut.String(), "selected session invalidated; use the session again") != 4 {
		t.Fatalf("unexpected invalidation errors: %q", errorsOut.String())
	}
}

func TestInteractiveHelpDescribesListCleanBehavior(t *testing.T) {
	stub := &interactiveStub{}
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("help list\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	text := output.String()
	for _, phrase := range []string{"list [endpoint] [--clean]", "failed to report", "--clean", "stderr"} {
		if !strings.Contains(text, phrase) {
			t.Fatalf("REPL help missing %q: %q", phrase, text)
		}
	}
	if strings.Contains(text, "table [endpoint]") {
		t.Fatalf("removed table command remains in help: %q", text)
	}
}

func TestInteractiveHelpSharesListDescriptionWithCLI(t *testing.T) {
	lines := CommandHelpLines()
	if len(lines) == 0 || !strings.Contains(lines[0], "list [endpoint] [--clean]") {
		t.Fatalf("missing list help line: %q", lines)
	}
	for _, line := range lines {
		if strings.HasPrefix(line, "table ") {
			t.Fatalf("removed table command remains: %q", lines)
		}
	}
}

func TestInteractiveTableCommandReportsRemoval(t *testing.T) {
	_, errorsOut := runInputScenario(t, &interactiveStub{}, "table\nquit\n", 8192)
	if !strings.Contains(errorsOut, `"table" has been removed; use "list --clean"`) {
		t.Fatalf("removal error=%q", errorsOut)
	}
}

func TestInteractiveHelpTableIsUnknown(t *testing.T) {
	var output strings.Builder
	if err := RunInteractive(context.Background(), &interactiveStub{}, strings.NewReader("help table\nquit\n"), &output, &output, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	text := output.String()
	if !strings.Contains(text, `unknown help command "table"`) || strings.Contains(text, "available commands: list, table") {
		t.Fatalf("unexpected help table output: %q", text)
	}
}

func TestInteractiveDetailedHelpIncludesFieldSemantics(t *testing.T) {
	var output strings.Builder
	if err := RunInteractive(context.Background(), &interactiveStub{}, strings.NewReader("help list\nquit\n"), &output, io.Discard, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	text := output.String()
	for _, phrase := range []string{"Syntax: list [endpoint] [--clean]", "SESSION_NAME:", "SESSION_ID:", "SESSION_STATUS:", "DATA_STATUS:", "LAST_SUCCESS:"} {
		if !strings.Contains(text, phrase) {
			t.Fatalf("detailed help missing %q: %q", phrase, text)
		}
	}
	if strings.Contains(text, "\x1b[") {
		t.Fatalf("detailed help contains ANSI: %q", text)
	}
}

func TestInteractiveListRowsBindSessionThroughCD(t *testing.T) {
	stub := &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1", DisplayName: "host-a"}},
		reports: map[string]protocol.InventoryReport{"endpoint-1": {
			ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded,
			Adapters: []protocol.AdapterSummary{{AdapterID: "topsailai-main", ProviderType: "topsailai", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}},
			Sessions: []protocol.Session{{SessionID: "res-1", AdapterID: "topsailai-main", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded}},
		}},
	}
	var output, errorsOut strings.Builder
	input := "list\ncd endpoint-1/res-1\nstatus\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "NO") || !strings.Contains(output.String(), "host-a") || !strings.Contains(output.String(), "topsailai") {
		t.Fatalf("missing readable row presentation: %q", output.String())
	}
	if !strings.Contains(output.String(), "cluster[endpoint-1/-]>") {
		t.Fatalf("cd did not bind session: %q errors=%q", output.String(), errorsOut.String())
	}
}

func TestInteractiveUseCommandIsRemovedAndBindsNothing(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("list\nuse 1\nuse endpoint-1 session-1\nquit\n"), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	assertActionableErrors(t, errorsOut.String(),
		`error: "use" has been removed; use "cd" to navigate`,
		`error: "use" has been removed; use "cd" to navigate`,
	)
	if strings.Contains(output.String(), "cluster[endpoint-1/-]>") {
		t.Fatalf("removed use command bound a session: %q", output.String())
	}
}

func TestParseInteractiveStartCarriesArgumentsAndRejectsJSON(t *testing.T) {
	request, err := parseInteractiveStart("endpoint-1 resource-1 --profile topsailai-main --profile-revision topsailai-v1 --folder /tmp/work")
	if err != nil {
		t.Fatal(err)
	}
	if request.EndpointID != "endpoint-1" || request.ResourceID != "resource-1" || request.Profile != "topsailai-main" || request.ProfileRevision != "topsailai-v1" || request.Folder != "/tmp/work" {
		t.Fatalf("request=%+v", request)
	}
	request, err = parseInteractiveStart("endpoint-1 resource-1 --profile p --profile-revision r --folder \"\"")
	if err != nil {
		t.Fatal(err)
	}
	if request.Folder != "" {
		t.Fatalf("empty folder=%q", request.Folder)
	}
	if _, err := parseInteractiveStart("endpoint-1 resource-1 --json"); err == nil || !strings.Contains(err.Error(), "does not support --json") {
		t.Fatalf("json error=%v", err)
	}
}

func TestInteractiveStartSubmitsAgentStartAndRendersReceipt(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	input := "start endpoint-1 resource-1 --profile p --profile-revision r --folder /tmp/work\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if errorsOut.Len() != 0 || stub.admit != 1 {
		t.Fatalf("output=%q errors=%q admits=%d", output.String(), errorsOut.String(), stub.admit)
	}
	for _, expected := range []string{"CommandID: cmd-1", "Status: finished", "DeliveryBoundary:", "EffectCertainty:", "ErrorCode:"} {
		if !strings.Contains(output.String(), expected) {
			t.Fatalf("output missing %q: %q", expected, output.String())
		}
	}
}

func TestInteractiveHelpIncludesStart(t *testing.T) {
	var output strings.Builder
	if err := PrintCommandHelp(&output, "start"); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "start <endpoint> <resource>") || !strings.Contains(output.String(), "Available in: workspace, endpoint") {
		t.Fatalf("help=%q", output.String())
	}
}

func TestInteractiveSessionLifecycleAndControlCommands(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	input := "cd endpoint-1/session-1\nresume\ny\ninject {\"text\":\"context\"}\ny\ninterrupt {\"action\":\"interrupt\"}\ny\nstop\nn\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if errorsOut.Len() != 0 {
		t.Fatalf("unexpected diagnostics: %q", errorsOut.String())
	}
	if stub.admit != 3 {
		t.Fatalf("admitted %d commands, want 3 after declined stop", stub.admit)
	}
	for _, phrase := range []string{"resume session-1?", "inject session-1?", "interrupt session-1?", "stop cancelled"} {
		if !strings.Contains(output.String(), phrase) {
			t.Fatalf("output missing %q: %q", phrase, output.String())
		}
	}
}

func TestInteractiveSessionActionsRequireSessionScope(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	_, diagnostics := runScope(t, stub, "resume\nstop\ninject {}\ninterrupt {}\nquit\n", ColorPolicy{})
	for _, name := range []string{"resume", "stop", "inject", "interrupt"} {
		if !strings.Contains(diagnostics, `command "`+name+`" is unavailable in workspace scope`) {
			t.Fatalf("missing scope rejection for %s: %q", name, diagnostics)
		}
	}
	if stub.admit != 0 {
		t.Fatalf("scope-rejected actions admitted %d commands", stub.admit)
	}
}

func TestInteractiveControlAliasesAreDocumented(t *testing.T) {
	var aliasOutput, canonicalOutput strings.Builder
	for _, name := range []string{"btw", "control"} {
		if err := PrintCommandHelp(&aliasOutput, name); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"inject", "interrupt"} {
		if err := PrintCommandHelp(&canonicalOutput, name); err != nil {
			t.Fatal(err)
		}
	}
	if aliasOutput.String() != canonicalOutput.String() {
		t.Fatalf("alias help differs from canonical help: alias=%q canonical=%q", aliasOutput.String(), canonicalOutput.String())
	}
	if !strings.Contains(aliasOutput.String(), "Available in: session") {
		t.Fatalf("alias help missing scope: %q", aliasOutput.String())
	}
}

func TestInteractiveSessionActionValidation(t *testing.T) {
	cases := []struct {
		name  string
		input string
		want  string
	}{
		{name: "resume arguments", input: "cd endpoint-1/session-1\nresume extra\nquit\n", want: "usage: resume"},
		{name: "stop arguments", input: "cd endpoint-1/session-1\nstop extra\nquit\n", want: "usage: stop"},
		{name: "inject missing payload", input: "cd endpoint-1/session-1\ninject\nquit\n", want: "usage: inject <json>"},
		{name: "interrupt missing payload", input: "cd endpoint-1/session-1\ninterrupt\nquit\n", want: "usage: interrupt <json>"},
		{name: "inject json option", input: "cd endpoint-1/session-1\ninject {} --json\nquit\n", want: "does not support --json"},
		{name: "interrupt invalid payload", input: "cd endpoint-1/session-1\ninterrupt nope\nquit\n", want: "payload must be a JSON object"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
			_, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if !strings.Contains(diagnostics, testCase.want) {
				t.Fatalf("diagnostics=%q want %q", diagnostics, testCase.want)
			}
			if stub.admit != 0 {
				t.Fatalf("invalid action admitted %d commands", stub.admit)
			}
		})
	}
}

func TestInteractiveControlAliasesExecuteSharedOperations(t *testing.T) {
	stub := &interactiveStub{endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}}, reports: map[string]protocol.InventoryReport{"endpoint-1": testInventory()}}
	var output, errorsOut strings.Builder
	input := "cd endpoint-1/session-1\nbtw {\"text\":\"alias context\"}\ny\ncontrol {\"action\":\"interrupt\"}\ny\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if errorsOut.Len() != 0 || stub.admit != 2 {
		t.Fatalf("output=%q errors=%q admits=%d", output.String(), errorsOut.String(), stub.admit)
	}
	for _, phrase := range []string{"inject session-1?", "interrupt session-1?"} {
		if !strings.Contains(output.String(), phrase) {
			t.Fatalf("output missing %q: %q", phrase, output.String())
		}
	}
}

func TestHelpCommandNamesReturnsStableSortedNames(t *testing.T) {
	names := HelpCommandNames()
	if len(names) == 0 || names[0] != "cd" || names[len(names)-1] != "stop" {
		t.Fatalf("unexpected help names: %v", names)
	}
	for index := 1; index < len(names); index++ {
		if names[index-1] > names[index] {
			t.Fatalf("help names are not sorted: %v", names)
		}
	}
}
