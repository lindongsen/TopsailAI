package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"net/http"
	"net/http/httptest"
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
func (s *sharedPathStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
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
	if got, want := strings.Join(interactive.calls, ","), "list,inventory,list,inventory,capabilities,history"; got != want {
		t.Fatalf("interactive calls=%q want=%q", got, want)
	}
}

func TestLegacyActionAndInteractiveSendShareIntentFields(t *testing.T) {
	legacy := &actionPathStub{}
	var legacyOut strings.Builder
	if err := action(context.Background(), legacy, &legacyOut, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", `{"text":"hi"}`, "gen"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatal(err)
	}
	interactive := &actionPathStub{}
	var interactiveOut, interactiveErr strings.Builder
	input := "cd ep/session\nsend {\"text\":\"hi\"}\nquit\n"
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
func (s *actionPathStub) GetOutput(context.Context, string, string, string, int, int) (protocol.OutputSnapshotResponse, error) {
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
	if !strings.Contains(output.String(), "workspace>") {
		t.Fatalf("interactive output=%q", output.String())
	}
}

// TestInteractiveLinesEntryPointRejectsOutOfRange proves the startup budget is
// validated through the real entry point before the editor takes the terminal,
// so an operator who asks for an unsupported count is told instead of silently
// receiving a shorter tail.
func TestInteractiveLinesEntryPointRejectsOutOfRange(t *testing.T) {
	cases := []struct {
		name string
		args []string
		want string
	}{
		{name: "below the minimum", args: []string{"-i", "--lines", "99"}, want: "--lines 99 is outside the interactive range 100-1000"},
		{name: "above the maximum", args: []string{"-i", "--lines", "1001"}, want: "--lines 1001 is outside the interactive range 100-1000"},
		{name: "trailing flag below the minimum", args: []string{"interactive", "--lines", "50"}, want: "--lines 50 is outside the interactive range 100-1000"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var output, diagnostics strings.Builder
			code := runExitCode(testCase.args, strings.NewReader("quit\n"), &output, &diagnostics, func() bool { return true })
			if code != 2 {
				t.Fatalf("exit code=%d want=2 diagnostics=%q", code, diagnostics.String())
			}
			if !strings.Contains(diagnostics.String(), testCase.want) {
				t.Fatalf("diagnostics=%q want substring %q", diagnostics.String(), testCase.want)
			}
			if strings.Contains(output.String(), "workspace>") {
				t.Fatalf("the REPL started despite a rejected budget: %q", output.String())
			}
		})
	}
}

// TestInteractiveLinesEntryPointAcceptsTheWindow proves every supported startup
// value still enters the REPL, so the range check never rejects a valid budget.
func TestInteractiveLinesEntryPointAcceptsTheWindow(t *testing.T) {
	for _, value := range []string{"100", "300", "1000"} {
		t.Run("lines "+value, func(t *testing.T) {
			var output, diagnostics strings.Builder
			code := runExitCode([]string{"-i", "--lines", value}, strings.NewReader("quit\n"), &output, &diagnostics, func() bool { return true })
			if code != 0 {
				t.Fatalf("exit code=%d diagnostics=%q", code, diagnostics.String())
			}
			if !strings.Contains(output.String(), "workspace>") {
				t.Fatalf("interactive output=%q", output.String())
			}
		})
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
	// A help request is a successful request: it must not be reported as a
	// failure, and it must be written to stdout so "cli -h | less" works.
	err := runWithIO([]string{"-h"}, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err != nil {
		t.Fatalf("help error=%v", err)
	}
	if diagnostics.Len() != 0 {
		t.Fatalf("help wrote diagnostics=%q", diagnostics.String())
	}
	text := output.String()
	for _, phrase := range []string{"[--endpoint <id>] list [--clean]", "failed to report", "--clean", "stderr"} {
		if !strings.Contains(text, phrase) {
			t.Fatalf("CLI help missing %q: %q", phrase, text)
		}
	}
	if strings.Contains(text, "table [endpoint]") {
		t.Fatalf("removed table command remains in help: %q", text)
	}
}

// TestSplitTerminatorSeparatesLiteralTail pins the "--" rule that lets a payload
// begin with a dash. Before the terminator a dash token is an option, so it must
// still be rejected; after it the token is data and must never be inspected.
func TestSplitTerminatorSeparatesLiteralTail(t *testing.T) {
	cases := []struct {
		name     string
		args     []string
		wantHead []string
		wantTail []string
	}{
		{
			name:     "no terminator keeps the whole line",
			args:     []string{"send", "ep", "res", "hello"},
			wantHead: []string{"send", "ep", "res", "hello"},
			wantTail: nil,
		},
		{
			name:     "terminator splits head from literal tail",
			args:     []string{"send", "ep", "res", "--", "--help"},
			wantHead: []string{"send", "ep", "res"},
			wantTail: []string{"--help"},
		},
		{
			name:     "command word is never a terminator",
			args:     []string{"--", "ep"},
			wantHead: []string{"--", "ep"},
			wantTail: nil,
		},
		{
			name:     "only the first terminator splits",
			args:     []string{"ctl", "ep", "res", "act", "--", "--", "x"},
			wantHead: []string{"ctl", "ep", "res", "act"},
			wantTail: []string{"--", "x"},
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			head, tail := splitTerminator(testCase.args)
			if strings.Join(head, "\x00") != strings.Join(testCase.wantHead, "\x00") {
				t.Fatalf("head=%q want %q", head, testCase.wantHead)
			}
			if strings.Join(tail, "\x00") != strings.Join(testCase.wantTail, "\x00") {
				t.Fatalf("tail=%q want %q", tail, testCase.wantTail)
			}
		})
	}
}

// TestHelpRequestStopsAtTerminator proves the two rules do not collide: a help
// request before "--" is answered, and the same token after "--" is payload.
func TestHelpRequestStopsAtTerminator(t *testing.T) {
	requested, target := helpRequest([]string{"send", "ep", "res", "--help"})
	if !requested || target != "send" {
		t.Fatalf("requested=%v target=%q, want the send help", requested, target)
	}
	requested, target = helpRequest([]string{"send", "ep", "res", "--", "--help"})
	if requested {
		t.Fatalf("a terminator must end help detection, got target=%q", target)
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

func TestNonInteractiveHelpMatchesDispatchAndFlagPlacement(t *testing.T) {
	var output, diagnostics strings.Builder
	if err := runWithIO([]string{"help"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatal(err)
	}
	text := output.String()
	for _, command := range []string{"list", "refresh", "show", "info", "logs", "status", "send", "btw", "control", "start", "resume", "stop", "drive", "help"} {
		if !strings.Contains(text, " "+command) {
			t.Fatalf("help missing dispatched command %q: %q", command, text)
		}
	}
	for _, interactiveOnly := range []string{"inject", "cd", "quit"} {
		if strings.Contains(text, "[options] "+interactiveOnly+" ") {
			t.Fatalf("non-interactive help leaked command %q: %q", interactiveOnly, text)
		}
	}
	if !strings.Contains(text, "agent-cluster-cli [options] start <endpoint> <resource> [text] [generation]") {
		t.Fatalf("start syntax does not show flags before command: %q", text)
	}

	output.Reset()
	if err := runWithIO([]string{"help", "start"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "Syntax: agent-cluster-cli [options] start <endpoint> <resource> [text] [generation]") || strings.Contains(output.String(), "--payload") {
		t.Fatalf("standalone start detail is inconsistent: %q", output.String())
	}
	output.Reset()
	if err := runWithIO([]string{"help", "inject"}, strings.NewReader(""), &output, &diagnostics, false, nil); err == nil {
		t.Fatal("non-interactive help accepted the removed inject spelling")
	}
	if err := runWithIO([]string{"help", "interrupt"}, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("non-interactive help rejected the dispatched interrupt command: %v", err)
	}
	if !strings.Contains(output.String(), "Syntax: agent-cluster-cli [options] interrupt <endpoint> <resource> [text] [generation]") {
		t.Fatalf("standalone interrupt help=%q", output.String())
	}
}

// TestBtwReachesConfirmationGate proves the only context injection spelling
// reaches the confirmation gate without contacting a Server.
func TestBtwReachesConfirmationGate(t *testing.T) {
	var output, diagnostics strings.Builder
	err := runWithIO([]string{"--server-url", "http://127.0.0.1:1", "btw", "ep", "res", `{"text":"x"}`}, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err == nil {
		t.Fatal("btw unexpectedly succeeded")
	}
	if !strings.Contains(err.Error(), "confirmation required for btw target=res") {
		t.Fatalf("btw error=%v", err)
	}
}

// TestStandalonePlainTextPayloadsNeedNoJSON proves every text-carrying
// standalone command accepts plain text and produces the standard payload.
func TestStandalonePlainTextPayloadsNeedNoJSON(t *testing.T) {
	for _, tc := range []struct {
		operation, value, want string
	}{
		{"send", "hello world", `{"text":"hello world"}`},
		{"btw", "the notes are in docs/", `{"text":"the notes are in docs/"}`},
		{"control", "soft stop now", `{"action":"soft_interrupt","message":"stop now"}`},
		{"control", "hard", `{"action":"hard_interrupt"}`},
		{"start", "summarize the open issues", `{"task":"summarize the open issues"}`},
	} {
		got, err := resolveActionPayload(tc.operation, tc.value)
		if err != nil {
			t.Fatalf("%s %q: %v", tc.operation, tc.value, err)
		}
		if string(got) != tc.want {
			t.Fatalf("%s %q payload=%s want=%s", tc.operation, tc.value, got, tc.want)
		}
	}
	if _, err := resolveActionPayload("control", "hard with a message"); err == nil {
		t.Fatal("hard interrupt accepted a message")
	}
	if _, err := resolveActionPayload("start", "   "); err == nil {
		t.Fatal("blank task accepted")
	}
}

// TestStandalonePlainTextMessageReachesIntent proves the plain text path builds
// the same immutable intent as the JSON form, without contacting a Server.
func TestStandalonePlainTextMessageReachesIntent(t *testing.T) {
	plain := &actionPathStub{}
	var plainOut strings.Builder
	if err := action(context.Background(), plain, &plainOut, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", "hello world", "gen"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatal(err)
	}
	jsonForm := &actionPathStub{}
	var jsonOut strings.Builder
	if err := action(context.Background(), jsonForm, &jsonOut, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", `{"text":"hello world"}`, "gen"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if len(plain.intents) != 1 || len(jsonForm.intents) != 1 {
		t.Fatalf("intent counts plain=%d json=%d", len(plain.intents), len(jsonForm.intents))
	}
	if string(plain.intents[0].Payload) != string(jsonForm.intents[0].Payload) {
		t.Fatalf("payload plain=%s json=%s", plain.intents[0].Payload, jsonForm.intents[0].Payload)
	}
}

func TestListDispatchMatchesAdvertisedSyntaxAgainstIsolatedServer(t *testing.T) {
	server := newListBehaviorServer(t)
	defer server.Close()

	tests := []struct {
		name       string
		args       []string
		wantIDs    []string
		wantOutput string
		wantError  string
		wantDiag   string
	}{
		{
			name:    "global endpoint before list",
			args:    []string{"--server-url", server.URL, "--token", "test-token", "--endpoint", "endpoint-1", "list"},
			wantIDs: []string{"A1", "A2"},
		},
		{
			name:       "unclean retains failed endpoint",
			args:       []string{"--server-url", server.URL, "--token", "test-token", "list"},
			wantIDs:    []string{"A1", "A2", "B1", "B2"},
			wantOutput: "endpoint-3",
			wantDiag:   "endpoint-3 unavailable",
		},
		{
			name:     "clean after list",
			args:     []string{"--server-url", server.URL, "--token", "test-token", "list", "--clean"},
			wantIDs:  []string{"A1", "A2", "B1", "B2"},
			wantDiag: "endpoint-3 unavailable",
		},
		{
			name:    "global endpoint and clean",
			args:    []string{"--server-url", server.URL, "--token", "test-token", "--endpoint", "endpoint-1", "list", "--clean"},
			wantIDs: []string{"A1", "A2"},
		},
		{
			name:      "endpoint positional argument rejected",
			args:      []string{"--server-url", server.URL, "--token", "test-token", "list", "endpoint-1"},
			wantError: "usage: agent-cluster-cli [options] [--endpoint <id>] list [--clean]",
		},
		{
			name:    "global endpoint after list is honoured",
			args:    []string{"--server-url", server.URL, "--token", "test-token", "list", "--endpoint", "endpoint-1"},
			wantIDs: []string{"A1", "A2"},
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var output, diagnostics strings.Builder
			err := runWithIO(tc.args, strings.NewReader(""), &output, &diagnostics, false, nil)
			if tc.wantError != "" {
				if err == nil || err.Error() != tc.wantError {
					t.Fatalf("error=%v want=%q output=%q diagnostics=%q", err, tc.wantError, output.String(), diagnostics.String())
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v diagnostics=%q", err, diagnostics.String())
			}
			if got := listSessionIDs(output.String()); !sameStringSet(got, tc.wantIDs) {
				t.Fatalf("session IDs=%v want=%v output=%q", got, tc.wantIDs, output.String())
			}
			if tc.wantOutput != "" && !strings.Contains(output.String(), tc.wantOutput) {
				t.Fatalf("output=%q missing %q", output.String(), tc.wantOutput)
			}
			if tc.name == "clean after list" && strings.Contains(output.String(), "endpoint-3") {
				t.Fatalf("clean output retained failed endpoint: %q", output.String())
			}
			if tc.wantDiag != "" && !strings.Contains(diagnostics.String(), tc.wantDiag) {
				t.Fatalf("diagnostics=%q missing %q", diagnostics.String(), tc.wantDiag)
			}
		})
	}
}

// listSessionIDs extracts the SESSION_ID cell from a rendered table.
//
// The column index is resolved from the header row rather than hardcoded, so
// adding or removing a column cannot silently make this helper read a different
// field and report an empty or wrong ID set.
func listSessionIDs(output string) []string {
	idIndex := -1
	var ids []string
	for _, line := range strings.Split(output, "\n") {
		cells := strings.Split(line, " │ ")
		if idIndex < 0 {
			for position, cell := range cells {
				if strings.TrimSpace(cell) == "SESSION_ID" {
					idIndex = position
				}
			}
			continue
		}
		if len(cells) <= idIndex || cells[0] == "NO" || strings.Trim(cells[0], "─") == "" {
			continue
		}
		id := strings.TrimSpace(cells[idIndex])
		if id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}

func sameStringSet(got, want []string) bool {
	if len(got) != len(want) {
		return false
	}
	seen := make(map[string]bool, len(got))
	for _, value := range got {
		seen[value] = true
	}
	for _, value := range want {
		if !seen[value] {
			return false
		}
	}
	return true
}

func TestListBehaviorTestsDoNotUseProductionPortsOrToken(t *testing.T) {
	server := newListBehaviorServer(t)
	defer server.Close()
	var output, diagnostics strings.Builder
	err := runWithIO([]string{"--server-url", server.URL, "--token", "test-token", "--endpoint", "endpoint-1", "list", "--clean"}, strings.NewReader(""), &output, &diagnostics, false, nil)
	if err != nil {
		t.Fatalf("isolated list failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if !sameStringSet(listSessionIDs(output.String()), []string{"A1", "A2"}) {
		t.Fatalf("isolated output=%q", output.String())
	}
}

func newListBehaviorServer(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer test-token" {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		switch r.URL.Path {
		case "/api/v1/endpoints":
			writeListTestEnvelope(w, http.StatusOK, "success", []protocol.Endpoint{
				{EndpointID: "endpoint-1", DisplayName: "endpoint-1", ConnectionState: "online"},
				{EndpointID: "endpoint-2", DisplayName: "endpoint-2", ConnectionState: "online"},
				{EndpointID: "endpoint-3", DisplayName: "endpoint-3", ConnectionState: "offline"},
			})
		case "/api/v1/endpoints/endpoint-1/session-state":
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory("A1", "A2"))
		case "/api/v1/endpoints/endpoint-2/session-state":
			writeListTestEnvelope(w, http.StatusOK, "success", listTestInventory("B1", "B2"))
		case "/api/v1/endpoints/endpoint-3/session-state":
			writeListTestEnvelope(w, http.StatusServiceUnavailable, "failed", nil)
		default:
			writeListTestEnvelope(w, http.StatusNotFound, "not found", nil)
		}
	}))
}

func listTestInventory(sessionIDs ...string) protocol.InventoryReport {
	sessions := make([]protocol.Session, 0, len(sessionIDs))
	for _, id := range sessionIDs {
		sessions = append(sessions, protocol.Session{SessionID: id, ProviderSessionID: id, AdapterID: "adapter-1", Generation: "generation-1", State: "running", CollectionStatus: protocol.CollectionSucceeded})
	}
	return protocol.InventoryReport{ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", DataKnown: true, CollectionStatus: protocol.CollectionSucceeded}}, Sessions: sessions}
}

func writeListTestEnvelope(w http.ResponseWriter, status int, message string, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"code": status, "message": message, "data": data})
}

func TestListHelpAndDispatchContract(t *testing.T) {
	var helpOut, helpDiagnostics strings.Builder
	if err := runWithIO([]string{"help", "list"}, strings.NewReader(""), &helpOut, &helpDiagnostics, false, nil); err != nil {
		t.Fatal(err)
	}
	const syntax = "agent-cluster-cli [options] [--endpoint <id>] list [--clean]"
	if !strings.Contains(helpOut.String(), syntax) {
		t.Fatalf("help=%q missing executable syntax %q", helpOut.String(), syntax)
	}
	server := newListBehaviorServer(t)
	defer server.Close()
	var output, diagnostics strings.Builder
	args := []string{"--server-url", server.URL, "--token", "test-token", "--endpoint", "endpoint-1", "list", "--clean"}
	if err := runWithIO(args, strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("advertised syntax failed: %v diagnostics=%q", err, diagnostics.String())
	}
	if !strings.Contains(output.String(), "endpoint-1") {
		t.Fatalf("dispatch output=%q", output.String())
	}
}

// TestResolveInteractiveSelection pins the -i flag contract.
func TestResolveInteractiveSelection(t *testing.T) {
	cases := []struct {
		name      string
		shortFlag bool
		args      []string
		want      bool
		wantErr   string
	}{
		{name: "flag only", shortFlag: true, args: nil, want: true},
		{name: "neither", shortFlag: false, args: nil, want: false},
		{name: "command only", shortFlag: false, args: []string{"interactive"}, want: true},
		{name: "flag and command agree", shortFlag: true, args: []string{"interactive"}, want: true},
		{name: "flag with other command", shortFlag: true, args: []string{"list"}, wantErr: `-i cannot be combined with the "list" command`},
		{name: "other command only", shortFlag: false, args: []string{"list"}, want: false},
		{name: "command with extra argument", shortFlag: false, args: []string{"interactive", "extra"}, wantErr: "usage: interactive"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := resolveInteractiveSelection(tc.shortFlag, tc.args)
			if tc.wantErr != "" {
				if err == nil || err.Error() != tc.wantErr {
					t.Fatalf("error=%v want %q", err, tc.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != tc.want {
				t.Fatalf("selected=%t want %t", got, tc.want)
			}
		})
	}
}

// TestResolveInteractiveLines covers the startup line budget. An absent --lines
// selects the interactive default, a value inside the window is kept, and an
// explicit value outside the window is rejected instead of being clamped.
func TestResolveInteractiveLines(t *testing.T) {
	cases := []struct {
		name    string
		args    []string
		want    int
		wantErr string
	}{
		{name: "absent selects the interactive default", args: nil, want: tui.DefaultInteractiveMaxLines},
		{name: "the minimum is accepted", args: []string{"--lines", "100"}, want: 100},
		{name: "a value inside the window is accepted", args: []string{"--lines", "300"}, want: 300},
		{name: "the maximum is accepted", args: []string{"--lines", "1000"}, want: 1000},
		{name: "below the minimum is rejected", args: []string{"--lines", "99"}, wantErr: "--lines 99 is outside the interactive range 100-1000; the standalone logs command accepts any positive count"},
		{name: "above the maximum is rejected", args: []string{"--lines", "1001"}, wantErr: "--lines 1001 is outside the interactive range 100-1000; the standalone logs command accepts any positive count"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			flags := flag.NewFlagSet("agent-cluster-cli", flag.ContinueOnError)
			lines := flags.Int("lines", 100, "trailing output lines")
			if err := flags.Parse(testCase.args); err != nil {
				t.Fatalf("Parse: %v", err)
			}
			got, err := resolveInteractiveLines(flags, *lines)
			if testCase.wantErr != "" {
				if err == nil || err.Error() != testCase.wantErr {
					t.Fatalf("error=%v want %q", err, testCase.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if got != testCase.want {
				t.Fatalf("lines=%d want=%d", got, testCase.want)
			}
		})
	}
}

// TestStandaloneLinesDefaultStaysIndependent proves the standalone surface keeps
// its own default, so the interactive budget never silently changes a script.
func TestStandaloneLinesDefaultStaysIndependent(t *testing.T) {
	if tui.DefaultInteractiveMaxLines == 100 {
		t.Fatalf("the interactive default must differ from the standalone default")
	}
}

// TestInteractiveShortFlagEntryPoint exercises -i through the real entry point.
func TestInteractiveShortFlagEntryPoint(t *testing.T) {
	cases := []struct {
		name     string
		args     []string
		input    string
		terminal bool
		wantCode int
		wantErr  string
	}{
		{name: "short flag quits", args: []string{"-i"}, input: "quit\n", terminal: true, wantCode: 0},
		{name: "long command still works", args: []string{"interactive"}, input: "quit\n", terminal: true, wantCode: 0},
		{name: "short flag with json", args: []string{"--json", "-i"}, input: "quit\n", terminal: true, wantCode: 2, wantErr: "interactive does not support --json or --yes"},
		{name: "short flag without terminal", args: []string{"-i"}, input: "quit\n", terminal: false, wantCode: 2, wantErr: "interactive mode requires a terminal on stdin"},
		{name: "short flag with command", args: []string{"-i", "list"}, input: "quit\n", terminal: true, wantCode: 2, wantErr: `-i cannot be combined with the "list" command`},
		{name: "no command", args: nil, input: "quit\n", terminal: true, wantCode: 2, wantErr: "a command is required: list, show, logs, send, stop"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var out, errOut strings.Builder
			code := runExitCode(tc.args, strings.NewReader(tc.input), &out, &errOut, func() bool { return tc.terminal })
			if code != tc.wantCode {
				t.Fatalf("code=%d want %d (stderr=%q)", code, tc.wantCode, errOut.String())
			}
			if tc.wantErr != "" && !strings.Contains(errOut.String(), tc.wantErr) {
				t.Fatalf("stderr=%q want %q", errOut.String(), tc.wantErr)
			}
			if tc.wantCode == 0 && !strings.Contains(out.String(), "workspace>") {
				t.Fatalf("prompt missing: %q", out.String())
			}
		})
	}
}

// TestEndpointsHelpAndDispatchContract pins the advertised syntax and proves the
// dispatch path against an isolated Server, including the JSON projection, the
// optional ID filter and the rejection of surplus arguments.
func TestEndpointsHelpAndDispatchContract(t *testing.T) {
	var helpOut, helpDiagnostics strings.Builder
	if err := runWithIO([]string{"help", "endpoints"}, strings.NewReader(""), &helpOut, &helpDiagnostics, false, nil); err != nil {
		t.Fatal(err)
	}
	const syntax = "agent-cluster-cli [options] [--endpoint <id>] endpoints [endpoint-id]"
	if !strings.Contains(helpOut.String(), syntax) {
		t.Fatalf("help=%q missing executable syntax %q", helpOut.String(), syntax)
	}

	server := newListBehaviorServer(t)
	defer server.Close()
	base := []string{"--server-url", server.URL, "--token", "test-token"}

	var output, diagnostics strings.Builder
	if err := runWithIO(append(append([]string{}, base...), "endpoints"), strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("endpoints failed: %v diagnostics=%q", err, diagnostics.String())
	}
	text := output.String()
	for _, want := range []string{"ENDPOINT_ID", "endpoint-1", "endpoint-2", "endpoint-3", "online(2)", "offline(1)"} {
		if !strings.Contains(text, want) {
			t.Fatalf("endpoints output=%q missing %q", text, want)
		}
	}
	if strings.Contains(text, "\x1b") {
		t.Fatalf("non-terminal endpoints output contains ANSI bytes: %q", text)
	}

	// The global --endpoint flag narrows the listing to one endpoint.
	output.Reset()
	if err := runWithIO(append(append([]string{}, base...), "--endpoint", "endpoint-2", "endpoints"), strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("filtered endpoints failed: %v", err)
	}
	if filtered := output.String(); !strings.Contains(filtered, "endpoint-2") || strings.Contains(filtered, "endpoint-1") {
		t.Fatalf("filtered endpoints output=%q", filtered)
	}

	// A positional endpoint ID is the same filter.
	output.Reset()
	if err := runWithIO(append(append([]string{}, base...), "endpoints", "endpoint-3"), strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("positional filter failed: %v", err)
	}
	if filtered := output.String(); !strings.Contains(filtered, "endpoint-3") || strings.Contains(filtered, "endpoint-1") {
		t.Fatalf("positional filter output=%q", filtered)
	}

	// JSON mode carries the reported fields and no presentation bytes.
	output.Reset()
	if err := runWithIO(append(append([]string{}, base...), "--json", "endpoints"), strings.NewReader(""), &output, &diagnostics, false, nil); err != nil {
		t.Fatalf("JSON endpoints failed: %v", err)
	}
	var decoded []protocol.Endpoint
	if err := json.Unmarshal([]byte(output.String()), &decoded); err != nil {
		t.Fatalf("JSON endpoints=%q err=%v", output.String(), err)
	}
	if len(decoded) != 3 || decoded[0].EndpointID != "endpoint-1" || decoded[0].ConnectionState != "online" {
		t.Fatalf("JSON endpoints=%#v", decoded)
	}

	// Surplus arguments are rejected instead of silently listing everything.
	for _, args := range [][]string{
		append(append([]string{}, base...), "endpoints", "endpoint-1", "endpoint-2"),
		append(append([]string{}, base...), "--endpoint", "endpoint-1", "endpoints", "endpoint-2"),
		append(append([]string{}, base...), "endpoints", "--clean"),
	} {
		if err := runWithIO(args, strings.NewReader(""), io.Discard, io.Discard, false, nil); err == nil {
			t.Fatalf("endpoints accepted invalid arguments %v", args)
		}
	}
}

// unreadableInput fails the test if a command reads the command input stream.
type unreadableInput struct {
	reads int
}

func (u *unreadableInput) Read([]byte) (int, error) {
	u.reads++
	return 0, errors.New("command input must not be read")
}

// TestStandaloneSendWithoutTextReadsMultiLineBlock proves a bare send collects
// one multi-line block terminated by a standalone EOF line.
func TestStandaloneSendWithoutTextReadsMultiLineBlock(t *testing.T) {
	stub := &actionPathStub{}
	var out strings.Builder
	input := strings.NewReader("first line\nsecond line\nEOF\n")
	if err := action(context.Background(), stub, &out, input, io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session"}, true, false, 100, "", "", "", "", "gen"); err != nil {
		t.Fatal(err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intent count=%d", len(stub.intents))
	}
	if got, want := string(stub.intents[0].Payload), `{"text":"first line\nsecond line"}`; got != want {
		t.Fatalf("payload=%s want=%s", got, want)
	}
	if stub.intents[0].Target == nil || stub.intents[0].Target.Generation != "gen" {
		t.Fatalf("target=%+v", stub.intents[0].Target)
	}
}

// TestStandaloneSendMultiLineEndsAtEndOfInput proves Ctrl+D (end of input)
// finishes the block without a terminator line.
func TestStandaloneSendMultiLineEndsAtEndOfInput(t *testing.T) {
	stub := &actionPathStub{}
	var out strings.Builder
	input := strings.NewReader("first\nsecond\n")
	if err := action(context.Background(), stub, &out, input, io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intent count=%d", len(stub.intents))
	}
	if got, want := string(stub.intents[0].Payload), `{"text":"first\nsecond"}`; got != want {
		t.Fatalf("payload=%s want=%s", got, want)
	}
}

// TestStandaloneSendMultiLineRejectsEmptyBlock proves an immediately terminated
// block submits nothing instead of an empty message.
func TestStandaloneSendMultiLineRejectsEmptyBlock(t *testing.T) {
	for _, input := range []string{"EOF\n", "", "\n\nEOF\n"} {
		stub := &actionPathStub{}
		var out strings.Builder
		err := action(context.Background(), stub, &out, strings.NewReader(input), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session"}, true, false, 100, "", "", "", "", "")
		if err == nil || err.Error() != "payload must not be empty" {
			t.Fatalf("input=%q error=%v", input, err)
		}
		if len(stub.intents) != 0 {
			t.Fatalf("input=%q admitted %d intents", input, len(stub.intents))
		}
	}
}

// TestStandaloneSendWithTextDoesNotReadInput proves the explicit text argument
// keeps its previous behaviour and never consumes the command input stream.
func TestStandaloneSendWithTextDoesNotReadInput(t *testing.T) {
	stub := &actionPathStub{}
	var out strings.Builder
	input := &unreadableInput{}
	if err := action(context.Background(), stub, &out, input, io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", "hello world", "gen"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatal(err)
	}
	if input.reads != 0 {
		t.Fatalf("explicit text read the input stream %d times", input.reads)
	}
	if got, want := string(stub.intents[0].Payload), `{"text":"hello world"}`; got != want {
		t.Fatalf("payload=%s want=%s", got, want)
	}
}

// allCapabilityStub advertises every text-carrying operation so a test can
// reach the payload path of btw and control.
type allCapabilityStub struct {
	actionPathStub
}

func (s *allCapabilityStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	return protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{
		{Name: protocol.OperationMessageSend},
		{Name: protocol.OperationContextInject},
		{Name: protocol.OperationExecutionInterrupt},
	}}, nil
}

// TestStandaloneControlKeepsItsGrammar proves control keeps its previous
// grammar: only send and btw gain multi-line input.
func TestStandaloneControlKeepsItsGrammar(t *testing.T) {
	stub := &allCapabilityStub{}
	var out strings.Builder
	input := &unreadableInput{}
	if err := action(context.Background(), stub, &out, input, io.Discard, tui.ColorPolicy{}, []string{"control", "ep", "session"}, true, false, 100, "", "", "", "", "gen"); err != nil {
		t.Fatalf("control: %v", err)
	}
	if input.reads != 0 {
		t.Fatalf("control read the input stream %d times", input.reads)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("control intent count=%d", len(stub.intents))
	}
}

// TestStandaloneContextInjectMultiLineReadsBlock proves a bare btw
// reads a multi-line context block from the command input, so context text never
// has to be quoted into one line.
func TestStandaloneContextInjectMultiLineReadsBlock(t *testing.T) {
	for _, operation := range []string{"btw"} {
		stub := &allCapabilityStub{}
		var out strings.Builder
		input := strings.NewReader("first line\n  indented line\nEOF\n")
		if err := action(context.Background(), stub, &out, input, io.Discard, tui.ColorPolicy{}, []string{operation, "ep", "session"}, true, false, 100, "", "", "", "", "gen"); err != nil {
			t.Fatalf("%s: %v", operation, err)
		}
		if len(stub.intents) != 1 {
			t.Fatalf("%s intent count=%d", operation, len(stub.intents))
		}
		if got, want := string(stub.intents[0].Payload), `{"text":"first line\n  indented line"}`; got != want {
			t.Fatalf("%s payload=%s want=%s", operation, got, want)
		}
	}
}

// TestStandaloneContextInjectMultiLineRejectsEmptyBlock proves an immediately
// terminated context block submits nothing instead of an empty context.
func TestStandaloneContextInjectMultiLineRejectsEmptyBlock(t *testing.T) {
	for _, operation := range []string{"btw"} {
		for _, input := range []string{"EOF\n", "", "\n\nEOF\n"} {
			stub := &allCapabilityStub{}
			var out strings.Builder
			err := action(context.Background(), stub, &out, strings.NewReader(input), io.Discard, tui.ColorPolicy{}, []string{operation, "ep", "session"}, true, false, 100, "", "", "", "", "gen")
			if err == nil || err.Error() != "payload must not be empty" {
				t.Fatalf("%s input=%q error=%v", operation, input, err)
			}
			if len(stub.intents) != 0 {
				t.Fatalf("%s input=%q admitted %d intents", operation, input, len(stub.intents))
			}
		}
	}
}

// TestStandaloneContextInjectMultiLineEndsAtEndOfInput proves Ctrl+D finishes
// the context block, so a piped stream needs no terminator line.
func TestStandaloneContextInjectMultiLineEndsAtEndOfInput(t *testing.T) {
	stub := &allCapabilityStub{}
	var out strings.Builder
	if err := action(context.Background(), stub, &out, strings.NewReader("only line\n"), io.Discard, tui.ColorPolicy{}, []string{"btw", "ep", "session"}, true, false, 100, "", "", "", "", "gen"); err != nil {
		t.Fatalf("btw: %v", err)
	}
	if got, want := string(stub.intents[0].Payload), `{"text":"only line"}`; got != want {
		t.Fatalf("payload=%s want=%s", got, want)
	}
}

// TestStandaloneContextInjectWithTextDoesNotReadInput proves an explicit text
// argument keeps its previous behaviour and never consumes the command input.
func TestStandaloneContextInjectWithTextDoesNotReadInput(t *testing.T) {
	for _, operation := range []string{"btw"} {
		stub := &allCapabilityStub{}
		var out strings.Builder
		input := &unreadableInput{}
		if err := action(context.Background(), stub, &out, input, io.Discard, tui.ColorPolicy{}, []string{operation, "ep", "session", "hello context", "gen"}, true, false, 100, "", "", "", "", ""); err != nil {
			t.Fatalf("%s: %v", operation, err)
		}
		if input.reads != 0 {
			t.Fatalf("%s explicit text read the input stream %d times", operation, input.reads)
		}
		if got, want := string(stub.intents[0].Payload), `{"text":"hello context"}`; got != want {
			t.Fatalf("%s payload=%s want=%s", operation, got, want)
		}
	}
}

// TestStandaloneContextInjectMultiLineRejectsUnreadableInput proves a missing
// stream is reported instead of silently submitting an empty context.
func TestStandaloneContextInjectMultiLineRejectsUnreadableInput(t *testing.T) {
	stub := &allCapabilityStub{}
	var out strings.Builder
	err := action(context.Background(), stub, &out, nil, io.Discard, tui.ColorPolicy{}, []string{"btw", "ep", "session"}, true, false, 100, "", "", "", "", "gen")
	if err == nil || err.Error() != "multi-line input requires a readable stream" {
		t.Fatalf("error=%v", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("admitted %d intents", len(stub.intents))
	}
}

// TestStandaloneSendMultiLineRejectsUnreadableInput proves a missing stream is
// reported instead of silently submitting an empty message.
func TestStandaloneSendMultiLineRejectsUnreadableInput(t *testing.T) {
	stub := &actionPathStub{}
	var out strings.Builder
	err := action(context.Background(), stub, &out, nil, io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session"}, true, false, 100, "", "", "", "", "")
	if err == nil || err.Error() != "multi-line input requires a readable stream" {
		t.Fatalf("error=%v", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("admitted %d intents", len(stub.intents))
	}
}

// TestStandaloneSendHintsMultiLineOnTerminal proves a bare send on a terminal
// announces how to finish the block, so the operator never faces a silent wait.
func TestStandaloneSendHintsMultiLineOnTerminal(t *testing.T) {
	var output, diagnostics strings.Builder
	input := strings.NewReader("body line\nEOF\n")
	// The unreachable Server fails the command after the block is read; the hint
	// must already be visible by then.
	_ = runWithIO([]string{"--server-url", "http://127.0.0.1:1", "send", "ep", "res"}, input, &output, &diagnostics, true, nil)
	if !strings.Contains(diagnostics.String(), tui.MultiLineHint) {
		t.Fatalf("diagnostics=%q want multi-line hint", diagnostics.String())
	}
}

// TestStandaloneSendHintOnlyForBareSendOnTerminal proves the hint is scoped to
// the one case that reads the block, so it never pollutes other invocations.
func TestStandaloneSendHintOnlyForBareSendOnTerminal(t *testing.T) {
	cases := []struct {
		name     string
		args     []string
		terminal bool
	}{
		{name: "explicit text", args: []string{"send", "ep", "res", "hello"}, terminal: true},
		{name: "non terminal", args: []string{"send", "ep", "res"}, terminal: false},
		{name: "other operation", args: []string{"btw", "ep", "res"}, terminal: true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var output, diagnostics strings.Builder
			_ = runWithIO(append([]string{"--server-url", "http://127.0.0.1:1"}, tc.args...), strings.NewReader("body\nEOF\n"), &output, &diagnostics, tc.terminal, nil)
			if strings.Contains(diagnostics.String(), tui.MultiLineHint) {
				t.Fatalf("diagnostics=%q must not carry the multi-line hint", diagnostics.String())
			}
		})
	}
}

// TestInteractiveSendAcceptsProseContainingJSONFlag guards the regression where a substring
// match on "--json" rejected ordinary message text before admission.
func TestInteractiveSendAcceptsProseContainingJSONFlag(t *testing.T) {
	for _, text := range []string{"please add --json to the config", "the flag is --json-output", "hello world"} {
		t.Run(text, func(t *testing.T) {
			stub := &actionPathStub{}
			var out, diagnostics strings.Builder
			input := "cd ep/session\nsend " + text + "\nquit\n"
			if err := tui.RunInteractive(context.Background(), stub, strings.NewReader(input), &out, &diagnostics, tui.InteractiveOptions{WaitTimeoutMS: 100}); err != nil {
				t.Fatal(err)
			}
			if diagnostics.Len() != 0 {
				t.Fatalf("diagnostics=%q", diagnostics.String())
			}
			if len(stub.intents) != 1 {
				t.Fatalf("intents=%d, want 1", len(stub.intents))
			}
			want := `{"text":"` + text + `"}`
			if got := string(stub.intents[0].Payload); got != want {
				t.Fatalf("payload=%q, want %q", got, want)
			}
		})
	}
}

// TestInteractiveSendRejectsBareJSONFlag keeps the original guard for a payload that is
// itself the flag token.
func TestInteractiveSendRejectsBareJSONFlag(t *testing.T) {
	stub := &actionPathStub{}
	var out, diagnostics strings.Builder
	input := "cd ep/session\nsend --json\nquit\n"
	if err := tui.RunInteractive(context.Background(), stub, strings.NewReader(input), &out, &diagnostics, tui.InteractiveOptions{WaitTimeoutMS: 100}); err != nil {
		t.Fatal(err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("intents=%d, want 0", len(stub.intents))
	}
	if !strings.Contains(diagnostics.String(), "does not support --json") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// TestActionRejectsMisplacedFlag keeps a trailing flag from becoming a target generation.
func TestActionRejectsMisplacedFlag(t *testing.T) {
	for _, args := range [][]string{
		{"send", "ep", "session", "hello", "--json"},
		{"send", "ep", "session", "--json"},
		{"stop", "ep", "session", "--json"},
	} {
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			stub := &actionPathStub{}
			err := action(context.Background(), stub, &strings.Builder{}, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, args, true, false, 100, "", "", "", "", "")
			if err == nil || !strings.Contains(err.Error(), "must be written before the command") {
				t.Fatalf("err=%v", err)
			}
			if len(stub.intents) != 0 {
				t.Fatalf("intents=%d, want 0", len(stub.intents))
			}
		})
	}
}

// TestActionAcceptsDashLeadingTextThroughJSONPayload confirms the documented escape hatch:
// a message that is itself a flag token is still deliverable as a JSON object payload.
func TestActionAcceptsDashLeadingTextThroughJSONPayload(t *testing.T) {
	stub := &actionPathStub{}
	if err := action(context.Background(), stub, &strings.Builder{}, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", `{"text":"--json"}`, "gen"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatalf("err=%v", err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents=%d, want 1", len(stub.intents))
	}
	if got := string(stub.intents[0].Payload); got != `{"text":"--json"}` {
		t.Fatalf("payload=%q", got)
	}
	if stub.intents[0].Target == nil || stub.intents[0].Target.Generation != "gen" {
		t.Fatalf("target=%+v", stub.intents[0].Target)
	}
}

// TestActionAcceptsNegativeGeneration keeps a negative numeric generation usable, because a
// leading dash alone does not make a token a flag.
func TestActionAcceptsNegativeGeneration(t *testing.T) {
	stub := &actionPathStub{}
	if err := action(context.Background(), stub, &strings.Builder{}, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", "hello", "-1"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatalf("err=%v", err)
	}
	if len(stub.intents) != 1 || stub.intents[0].Target == nil || stub.intents[0].Target.Generation != "-1" {
		t.Fatalf("intents=%+v", stub.intents)
	}
}

// TestActionRejectsUnquotedMultiWordText proves an unquoted message is rejected instead of
// being silently truncated to its first word, which previously became the payload while the
// second word became the target generation.
func TestActionRejectsUnquotedMultiWordText(t *testing.T) {
	stub := &actionPathStub{}
	err := action(context.Background(), stub, &strings.Builder{}, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", "please", "add", "to", "the", "config"}, true, false, 100, "", "", "", "", "")
	if err == nil || !strings.Contains(err.Error(), "quote the message text") {
		t.Fatalf("err=%v", err)
	}
	if !strings.Contains(err.Error(), "please add to the config") {
		t.Fatalf("error must echo the whole intended message: %v", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("intents=%d, want 0", len(stub.intents))
	}
}

// TestActionAcceptsQuotedMultiWordText keeps the documented quoted form working.
func TestActionAcceptsQuotedMultiWordText(t *testing.T) {
	stub := &actionPathStub{}
	if err := action(context.Background(), stub, &strings.Builder{}, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", "please add to the config"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatalf("err=%v", err)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents=%d, want 1", len(stub.intents))
	}
	if got := string(stub.intents[0].Payload); got != `{"text":"please add to the config"}` {
		t.Fatalf("payload=%q", got)
	}
}

// TestActionAcceptsTextAndGeneration keeps the full documented positional form working.
func TestActionAcceptsTextAndGeneration(t *testing.T) {
	stub := &actionPathStub{}
	if err := action(context.Background(), stub, &strings.Builder{}, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", "hello", "gen-1"}, true, false, 100, "", "", "", "", ""); err != nil {
		t.Fatalf("err=%v", err)
	}
	if len(stub.intents) != 1 || stub.intents[0].Target == nil || stub.intents[0].Target.Generation != "gen-1" {
		t.Fatalf("intents=%+v", stub.intents)
	}
	if got := string(stub.intents[0].Payload); got != `{"text":"hello"}` {
		t.Fatalf("payload=%q", got)
	}
}

// TestActionAcceptsGenerationFlagWithText proves the flag form frees the generation slot.
func TestActionAcceptsGenerationFlagWithText(t *testing.T) {
	stub := &actionPathStub{}
	if err := action(context.Background(), stub, &strings.Builder{}, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"send", "ep", "session", "hello"}, true, false, 100, "", "", "", "", "gen-1"); err != nil {
		t.Fatalf("err=%v", err)
	}
	if len(stub.intents) != 1 || stub.intents[0].Target == nil || stub.intents[0].Target.Generation != "gen-1" {
		t.Fatalf("intents=%+v", stub.intents)
	}
}

// TestActionRejectsExtraStopPositionals keeps stop from accepting a stray text argument and
// proves the error does not suggest quoting a message, because stop carries no message text.
func TestActionRejectsExtraStopPositionals(t *testing.T) {
	stub := &actionPathStub{}
	err := action(context.Background(), stub, &strings.Builder{}, strings.NewReader(""), io.Discard, tui.ColorPolicy{}, []string{"stop", "ep", "session", "gen-1", "extra"}, true, false, 100, "", "", "", "", "")
	if err == nil || !strings.Contains(err.Error(), "unexpected arguments") {
		t.Fatalf("err=%v", err)
	}
	if strings.Contains(err.Error(), "quote the message text") {
		t.Fatalf("stop has no message text, so the error must not suggest quoting it: %v", err)
	}
	if !strings.Contains(err.Error(), "extra") {
		t.Fatalf("error must echo the unexpected argument: %v", err)
	}
	if len(stub.intents) != 0 {
		t.Fatalf("intents=%d, want 0", len(stub.intents))
	}
}
