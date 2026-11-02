package main

import (
	"context"
	"errors"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

func TestInteractiveRejectsJSONScope(t *testing.T) {
	err := runWithIO([]string{"--json", "interactive"}, strings.NewReader("quit\n"), &strings.Builder{}, &strings.Builder{}, true, nil)
	if err == nil || err.Error() != "interactive does not support --json or --yes" {
		t.Fatalf("unexpected JSON scope result: %v", err)
	}
}

func TestInteractiveRejectsNonTerminalBeforeNetwork(t *testing.T) {
	err := runWithIO([]string{"--server-url", "http://127.0.0.1:1", "interactive"}, strings.NewReader("quit\n"), &strings.Builder{}, &strings.Builder{}, false, nil)
	if err == nil || err.Error() != "interactive mode requires a terminal on stdin" {
		t.Fatalf("unexpected non-terminal result: %v", err)
	}
}

type sharedPathStub struct {
	calls   []string
	intents []protocol.ImmutableIntent
}

func (s *sharedPathStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	s.calls = append(s.calls, "list")
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}
func (s *sharedPathStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	s.calls = append(s.calls, "inventory")
	return protocol.InventoryReport{CollectionStatus: protocol.CollectionSucceeded}, nil
}
func (s *sharedPathStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	s.calls = append(s.calls, "capabilities")
	return protocol.CapabilityDescriptor{}, nil
}
func (s *sharedPathStub) GetCommand(context.Context, string) (map[string]any, error) {
	s.calls = append(s.calls, "command")
	return map[string]any{"status": "finished"}, nil
}
func (s *sharedPathStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	s.calls = append(s.calls, "history")
	return nil, nil
}
func (s *sharedPathStub) GetOutput(context.Context, string, string, string, int) (protocol.OutputSnapshotResponse, error) {
	s.calls = append(s.calls, "output")
	return protocol.OutputSnapshotResponse{}, nil
}
func (s *sharedPathStub) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.calls = append(s.calls, "admit")
	s.intents = append(s.intents, intent)
	return map[string]any{"command_id": "cmd-1"}, nil
}

func TestLegacyAndInteractiveShowUseSharedRunnerMethods(t *testing.T) {
	legacy := &sharedPathStub{}
	var legacyOut strings.Builder
	if err := show(context.Background(), legacy, &legacyOut, "ep", false); err != nil {
		t.Fatal(err)
	}
	interactive := &sharedPathStub{}
	var interactiveOut, interactiveErr strings.Builder
	if err := tui.RunInteractive(context.Background(), interactive, strings.NewReader("show ep\nquit\n"), &interactiveOut, &interactiveErr, tui.InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
	if got, want := strings.Join(legacy.calls, ","), "list,inventory,capabilities,history"; got != want {
		t.Fatalf("legacy calls=%q want=%q", got, want)
	}
	if got, want := strings.Join(interactive.calls, ","), "list,inventory,capabilities,history"; got != want {
		t.Fatalf("interactive calls=%q want=%q", got, want)
	}
}

func TestLegacyActionAndInteractiveSendShareIntentFields(t *testing.T) {
	legacy := &actionPathStub{}
	var legacyOut strings.Builder
	if err := action(context.Background(), legacy, &legacyOut, []string{"send", "ep", "session", `{"text":"hi"}`, "gen"}, true, false, 100, "", ""); err != nil {
		t.Fatal(err)
	}
	interactive := &actionPathStub{}
	var interactiveOut, interactiveErr strings.Builder
	input := "cd ep/session\nsend {\"text\":\"hi\"}\ny\nquit\n"
	if err := tui.RunInteractive(context.Background(), interactive, strings.NewReader(input), &interactiveOut, &interactiveErr, tui.InteractiveOptions{WaitTimeoutMS: 100}); err != nil {
		t.Fatal(err)
	}
	if len(legacy.intents) != 1 || len(interactive.intents) != 1 {
		t.Fatalf("intent counts legacy=%d interactive=%d", len(legacy.intents), len(interactive.intents))
	}
	left, right := legacy.intents[0], interactive.intents[0]
	if left.EndpointID != right.EndpointID || left.Operation != right.Operation || string(left.Payload) != string(right.Payload) || left.Target == nil || right.Target == nil || left.Target.ResourceID != right.Target.ResourceID || left.Target.Generation != right.Target.Generation {
		t.Fatalf("intent mismatch legacy=%+v interactive=%+v", left, right)
	}
}

type actionPathStub struct {
	intents []protocol.ImmutableIntent
}

func (s *actionPathStub) ListEndpoints(context.Context) ([]protocol.Endpoint, error) {
	return []protocol.Endpoint{{EndpointID: "ep"}}, nil
}
func (s *actionPathStub) GetInventory(context.Context, string) (protocol.InventoryReport, error) {
	return protocol.InventoryReport{ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}}, Sessions: []protocol.Session{{SessionID: "session", AdapterID: "adapter-1", Generation: "gen", State: "running", CollectionStatus: protocol.CollectionSucceeded}}}, nil
}
func (s *actionPathStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}}}, nil
}
func (s *actionPathStub) GetCommand(context.Context, string) (map[string]any, error) {
	return map[string]any{"status": "finished"}, nil
}
func (s *actionPathStub) ListCommands(context.Context, string, string, int) ([]map[string]any, error) {
	return nil, nil
}
func (s *actionPathStub) GetOutput(context.Context, string, string, string, int) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}
func (s *actionPathStub) AdmitCommand(_ context.Context, intent protocol.ImmutableIntent) (map[string]any, error) {
	s.intents = append(s.intents, intent)
	return map[string]any{"command_id": "cmd-1"}, nil
}

func TestEntryExitCodesAndInjectedTTY(t *testing.T) {
	cases := []struct {
		name     string
		args     []string
		terminal bool
		wantCode int
		wantErr  string
	}{
		{name: "quit", args: []string{"interactive"}, terminal: true, wantCode: 0},
		{name: "exit", args: []string{"interactive"}, terminal: true, wantCode: 0},
		{name: "eof", args: []string{"interactive"}, terminal: true, wantCode: 0},
		{name: "non tty", args: []string{"interactive"}, terminal: false, wantCode: 2, wantErr: "interactive mode requires a terminal on stdin"},
		{name: "json scope", args: []string{"--json", "interactive"}, terminal: true, wantCode: 2, wantErr: "interactive does not support --json or --yes"},
		{name: "unknown", args: []string{"unknown"}, terminal: true, wantCode: 2, wantErr: `unknown command "unknown"`},
		{name: "missing command", args: nil, terminal: true, wantCode: 2, wantErr: "a command is required: list, show, logs, send, stop"},
	}
	inputs := map[string]string{"quit": "quit\n", "exit": "exit\n", "eof": ""}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var output, diagnostics strings.Builder
			code := runExitCode(tc.args, strings.NewReader(inputs[tc.name]), &output, &diagnostics, func() bool { return tc.terminal })
			if code != tc.wantCode {
				t.Fatalf("exit code=%d want=%d diagnostics=%q", code, tc.wantCode, diagnostics.String())
			}
			if tc.wantErr != "" {
				want := tc.wantErr + "\n"
				if diagnostics.String() != want {
					t.Fatalf("diagnostics=%q want %q", diagnostics.String(), want)
				}
			}
		})
	}
}

func TestInjectedTTYTrueEntersInteractiveWithoutRealTerminal(t *testing.T) {
	var output, diagnostics strings.Builder
	code := runExitCode([]string{"interactive"}, strings.NewReader("quit\n"), &output, &diagnostics, func() bool { return true })
	if code != 0 {
		t.Fatalf("exit code=%d diagnostics=%q", code, diagnostics.String())
	}
	if !strings.Contains(output.String(), "cluster") || !strings.Contains(output.String(), ">") {
		t.Fatalf("interactive output=%q", output.String())
	}
}

func TestInteractiveFatalWriterMapsToExitCode(t *testing.T) {
	code := runExitCode([]string{"interactive"}, strings.NewReader("quit\n"), &failingMainWriter{}, &strings.Builder{}, func() bool { return true })
	if code != 2 {
		t.Fatalf("exit code=%d want=2", code)
	}
}

type failingMainWriter struct{}

func (*failingMainWriter) Write([]byte) (int, error) { return 0, errors.New("write failed") }

func TestPromptInterruptMapsToExitCode130(t *testing.T) {
	input, inputWriter := io.Pipe()
	defer inputWriter.Close()
	signals := make(chan os.Signal, 1)
	go func() {
		time.Sleep(10 * time.Millisecond)
		signals <- os.Interrupt
	}()
	var output, diagnostics strings.Builder
	code, err := runWithSignals([]string{"interactive"}, input, &output, &diagnostics, func() bool { return true }, signals)
	if code != 130 {
		t.Fatalf("exit code=%d want=130 diagnostics=%q", code, diagnostics.String())
	}
	if !errors.Is(err, tui.ErrInteractiveInterrupt) {
		t.Fatalf("error=%v want interactive interrupt", err)
	}
}

func TestCLIHelpDescribesListCleanBehavior(t *testing.T) {
	var output, diagnostics strings.Builder
	err := runWithIO([]string{"-h"}, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil || err.Error() != "flag: help requested" {
		t.Fatalf("help error=%v", err)
	}
	text := diagnostics.String()
	for _, phrase := range []string{"list [endpoint] [--clean]", "failed to report", "--clean", "stderr"} {
		if !strings.Contains(text, phrase) {
			t.Fatalf("CLI help missing %q: %q", phrase, text)
		}
	}
	if strings.Contains(text, "table [endpoint]") {
		t.Fatalf("removed table command remains in help: %q", text)
	}
}

func TestRemovedTableCommandReturnsMigrationError(t *testing.T) {
	var output, diagnostics strings.Builder
	code, err := runWithSignals([]string{"table"}, strings.NewReader(""), &output, &diagnostics, func() bool { return false }, nil)
	if code != 2 || err == nil {
		t.Fatalf("code=%d err=%v diagnostics=%q", code, err, diagnostics.String())
	}
	if !strings.Contains(diagnostics.String(), `"table" has been removed; use "list --clean"`) || strings.Contains(output.String(), "ENDPOINT") {
		t.Fatalf("unexpected removal output=%q diagnostics=%q", output.String(), diagnostics.String())
	}
}
