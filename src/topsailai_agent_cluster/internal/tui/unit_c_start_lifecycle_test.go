package tui

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/mattn/go-isatty"
	"topsailai_agent_cluster/internal/protocol"
)

// TestUnitCStartCancelPreservesLiveState verifies the actual start lifecycle boundary.
func TestUnitCStartCancelPreservesLiveState(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		t.Run(startFieldName(field), func(t *testing.T) {
			api := newUnitCAPI()
			state := seedUnitCState()
			before := cloneUnitCState(state)
			beforeCounts, _ := api.snapshot()
			_, err := executeInteractiveLine(context.Background(), api, &state, "start", unitCStartCancelLines(field), io.Discard, io.Discard, io.Discard, InteractiveOptions{})
			if err != nil {
				t.Fatalf("executeInteractiveLine: %v", err)
			}
			if !reflect.DeepEqual(state, before) {
				t.Fatalf("live state changed: before=%+v after=%+v", before, state)
			}
			afterCounts, intents := api.snapshot()
			if got := unitCAPIAdd(beforeCounts, afterCounts); got != (unitCAPICounts{}) {
				t.Fatalf("API delta=%+v, want zero", got)
			}
			if len(intents) != 0 {
				t.Fatalf("intents=%d, want zero", len(intents))
			}
		})
	}
}

// TestUnitCStartCancelKeepsReplSelection verifies the actual start lifecycle boundary.
func TestUnitCStartCancelKeepsReplSelection(t *testing.T) {
	api := newUnitCAPI()
	state := seedUnitCState()
	before := cloneUnitCState(state)
	_, err := executeInteractiveLine(context.Background(), api, &state, "start", unitCStartCancelLines(startFieldResource), io.Discard, io.Discard, io.Discard, InteractiveOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if state.EndpointID != before.EndpointID || state.ClusterSessionID != before.ClusterSessionID || state.ProviderGeneration != before.ProviderGeneration || state.Scope != before.Scope {
		t.Fatalf("selection changed: before=%+v after=%+v", before, state)
	}
}

// TestUnitCStartSessionScopeRejectsBeforePrompt verifies the actual start lifecycle boundary.
func TestUnitCStartSessionScopeRejectsBeforePrompt(t *testing.T) {
	api := newUnitCAPI()
	state := seedUnitCState()
	state.Scope.Kind = ScopeSession
	before := cloneUnitCState(state)
	beforeCounts, _ := api.snapshot()
	_, err := executeInteractiveLine(context.Background(), api, &state, "start", make(chan lineReadResult), io.Discard, io.Discard, io.Discard, InteractiveOptions{})
	if err == nil || !strings.Contains(err.Error(), "session") {
		t.Fatalf("error=%v, want session scope rejection", err)
	}
	if !reflect.DeepEqual(state, before) {
		t.Fatalf("state changed after scope rejection")
	}
	afterCounts, intents := api.snapshot()
	if got := unitCAPIAdd(beforeCounts, afterCounts); got != (unitCAPICounts{}) || len(intents) != 0 {
		t.Fatalf("API delta=%+v intents=%d", got, len(intents))
	}
}

// TestUnitCStartPromptEOFDoesNotSubmit verifies the actual start lifecycle boundary.
func TestUnitCStartPromptEOFDoesNotSubmit(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("start\n"), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("EOF admitted %d commands", stub.admit)
	}
	if strings.Count(output.String(), "start: endpoint ID required") != 1 {
		t.Fatalf("EOF emitted unexpected prompts: %q", output.String())
	}
}

// TestUnitCStartPromptFatalReaderReturnsOriginalError verifies the actual start lifecycle boundary.
func TestUnitCStartPromptFatalReaderReturnsOriginalError(t *testing.T) {
	sentinel := errors.New("unit-c reader failure")
	stub := startupStub()
	var output, diagnostics strings.Builder
	err := RunInteractive(context.Background(), stub, &unitCFailingReader{err: sentinel}, &output, &diagnostics, InteractiveOptions{})
	if !errors.Is(err, sentinel) {
		t.Fatalf("error=%v, want sentinel identity", err)
	}
	if stub.admit != 0 {
		t.Fatalf("fatal reader admitted %d commands", stub.admit)
	}
}

// TestUnitCStartPromptParentCancellationReturnsExactError uses an unanswered field ticket.
// TestUnitCStartPromptParentCancellationReturnsExactError verifies the actual start lifecycle boundary.
func TestUnitCStartPromptParentCancellationReturnsExactError(t *testing.T) {
	d := newUnitCBatch2Driver(t, "parent", true)
	d.startup(t, startFieldEndpoint)
	d.cancel()
	<-d.ledger.entered
	d.ledger.release()
	if err := d.waitRun(t); err != context.Canceled {
		t.Fatalf("parent error=%v", err)
	}
	d.assertUnchanged(t)
}

// terminalHarnessReadyWriter publishes complete, successfully forwarded prompt barriers.
type terminalHarnessReadyWriter struct {
	target              io.Writer
	readyPath, caseName string
	pending             []byte
	ordinal             int
}

// Write classifies each real prompt using the preceding scoped description.
func (w *terminalHarnessReadyWriter) Write(data []byte) (int, error) {
	n, err := w.target.Write(data)
	if err != nil {
		return n, err
	}
	if n != len(data) {
		return n, io.ErrShortWrite
	}
	w.pending = append(w.pending, data...)
	for {
		marker := []byte("workspace> ")
		index := bytes.Index(w.pending, marker)
		for f := startFieldEndpoint; f <= startFieldRevision; f++ {
			candidate := []byte("start." + startFieldName(f) + "> ")
			if pos := bytes.Index(w.pending, candidate); pos >= 0 && (index < 0 || pos < index) {
				index, marker = pos, candidate
			}
		}
		if index < 0 {
			return n, nil
		}
		text := string(w.pending[:index])
		field := "main"
		for f := startFieldEndpoint; f <= startFieldRevision; f++ {
			if strings.Contains(text, startFieldDescription(f)) {
				field = startFieldName(f)
			}
		}
		w.ordinal++
		event := map[string]any{"case": w.caseName, "ordinal": w.ordinal, "field": field, "pid": os.Getpid()}
		encoded, e := json.Marshal(event)
		if e != nil {
			return n, e
		}
		if e = os.WriteFile(w.readyPath+".tmp", encoded, 0600); e != nil {
			return n, e
		}
		if e = os.Rename(w.readyPath+".tmp", w.readyPath); e != nil {
			return n, e
		}
		w.pending = w.pending[index+len(marker):]
	}
}

// TestUnitCStartPromptTerminalHarness runs only at the explicit external terminal boundary.
// TestUnitCStartPromptTerminalHarness verifies the actual start lifecycle boundary.
func TestUnitCStartPromptTerminalHarness(t *testing.T) {
	if os.Getenv("UNIT_C_TERMINAL") != "1" {
		t.Skip("explicit terminal harness enablement required")
	}
	info, err := os.Stdin.Stat()
	if err != nil {
		t.Fatal(err)
	}
	if !isatty.IsTerminal(os.Stdin.Fd()) {
		t.Fatal("real terminal input is required")
	}
	dir := os.Getenv("UNIT_C_TERMINAL_DIR")
	if !filepath.IsAbs(dir) {
		t.Fatal("absolute artifact directory required")
	}
	name := os.Getenv("UNIT_C_TERMINAL_CASE")
	switch name {
	case "complete", "help-invalid", "cancel", "quit", "refresh", "command-interrupt", "numeric-literal", "residual-half-line":
	default:
		t.Fatalf("unknown terminal case %q", name)
	}
	api := newUnitCAPI()
	var output, diag strings.Builder
	transcript, err := os.Create(filepath.Join(dir, "terminal-transcript.txt"))
	if err != nil {
		t.Fatal(err)
	}
	defer transcript.Close()
	writer := &terminalHarnessReadyWriter{target: io.MultiWriter(os.Stdout, &output, transcript), readyPath: filepath.Join(dir, "readiness.json"), caseName: name}
	signals := make(chan os.Signal, 2)
	signal.Notify(signals, os.Interrupt)
	defer signal.Stop(signals)
	err = RunInteractive(context.Background(), api, os.Stdin, writer, io.MultiWriter(os.Stderr, &diag, transcript), InteractiveOptions{Interrupt: signals})
	counts, intents := api.snapshot()
	want := unitCAPICounts{List: 1, Inventory: 1}
	completed := name == "complete" || name == "help-invalid" || name == "numeric-literal"
	if completed {
		want.Capability = 1
		want.Admit = 1
		want.Command = 1
	}
	if name == "refresh" {
		want.List = 2
		want.Inventory = 2
	}
	writeJSON := func(base string, value any) {
		t.Helper()
		data, e := json.MarshalIndent(value, "", "  ")
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(filepath.Join(dir, base), data, 0600); e != nil {
			t.Fatal(e)
		}
	}
	writeJSON("terminal-counts.json", counts)
	writeJSON("terminal-intents.json", intents)
	if err != nil || counts != want || len(intents) != want.Admit {
		t.Fatalf("F5 %s err=%v counts=%+v want=%+v intents=%v", name, err, counts, want, intents)
	}
	if completed {
		if name == "numeric-literal" {
			i := intents[0]
			if i.EndpointID != "1" || i.LaunchProfileID != "3" || i.ProfileRevision != "4" || i.Target != nil || i.CapabilityRevision != "cap-live-2" {
				t.Fatalf("numeric intent=%+v", i)
			}
		} else {
			unitC3CheckIntent(t, intents[0], `{}`, "")
		}
		if strings.Count(output.String(), "command submitted:") != 1 {
			t.Fatal("submission acknowledgement count")
		}
	}
	if name == "help-invalid" {
		if diag.String() != "error: start input requires one non-empty value\nusage: start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>] [--task <text>]\nnext: Run help start for valid syntax.\n" {
			t.Fatalf("validation diagnostic=%q", diag.String())
		}
	}
	if name == "command-interrupt" || name == "residual-half-line" {
		if diag.String() != "interrupted\n" {
			t.Fatalf("interrupt diagnostic=%q", diag.String())
		}
	} else if name != "help-invalid" && diag.Len() != 0 {
		t.Fatalf("unexpected diagnostics=%q", diag.String())
	}
	if name == "cancel" || name == "refresh" {
		if strings.Count(output.String(), "start cancelled\n") != 1 {
			t.Fatal("cancel acknowledgement")
		}
	}
	if name == "refresh" && strings.Count(output.String(), "provider-session-1") != 2 {
		t.Fatal("refreshed row missing")
	}
	writeJSON("terminal-result.json", map[string]any{"case": name, "status": "PASS", "pid": os.Getpid(), "stdin": info.Name(), "char_device": true, "signals_subscribed": true, "diagnostics": diag.String()})
	fmt.Println("UNITC_RESULT PASS", name)
}

// TestUnitCStartRecordingWriterPreservesFailureAndShortWrite verifies the actual start lifecycle boundary.
func TestUnitCStartRecordingWriterPreservesFailureAndShortWrite(t *testing.T) {
	sentinel := errors.New("writer sentinel")
	writer := &recordingWriter{writer: &unitCWriterFailure{err: sentinel, failAfter: 1}}
	if _, err := writer.Write([]byte("prompt")); !errors.Is(err, sentinel) || !errors.Is(writer.Error(), sentinel) {
		t.Fatalf("recording writer error=%v recorded=%v, want sentinel", err, writer.Error())
	}
	short := &recordingWriter{writer: &unitCWriterFailure{short: true}}
	if _, err := short.Write([]byte("prompt")); !errors.Is(err, io.ErrShortWrite) || !errors.Is(short.Error(), io.ErrShortWrite) {
		t.Fatalf("short write error=%v recorded=%v, want io.ErrShortWrite", err, short.Error())
	}
}

// TestUnitCStartPromptWriterFailuresTerminateWithoutAdmit verifies the actual start lifecycle boundary.
func TestUnitCStartPromptWriterFailuresTerminateWithoutAdmit(t *testing.T) {
	sentinel := errors.New("prompt writer sentinel")
	cases := []struct {
		name string
		out  io.Writer
		err  io.Writer
		line string
	}{
		{name: "prompt", out: &unitCWriterFailure{err: sentinel, failAfter: 1}, err: io.Discard, line: "answer\n"},
		{name: "field-diagnostic", out: io.Discard, err: &unitCWriterFailure{err: sentinel, failAfter: 1}, line: "! extra\n"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			stub := startupStub()
			input := strings.NewReader("start\n" + tc.line)
			got := RunInteractive(context.Background(), stub, input, tc.out, tc.err, InteractiveOptions{})
			if !errors.Is(got, sentinel) {
				t.Fatalf("RunInteractive error=%v, want sentinel", got)
			}
			if stub.admit != 0 {
				t.Fatalf("writer failure admitted %d commands", stub.admit)
			}
		})
	}
}

// TestUnitCStartPromptCancelPreservesDraftStateForEachField verifies the actual start lifecycle boundary.
func TestUnitCStartPromptCancelPreservesDraftStateForEachField(t *testing.T) {
	for field := startDraftField(0); field <= startFieldRevision; field++ {
		t.Run(startFieldName(field), func(t *testing.T) {
			draft := startDraft{
				request: interactiveStartRequest{EndpointID: "ep", ResourceID: "res", Profile: "profile", ProfileRevision: "revision"},
			}
			draft.missing[field] = true
			before := draft
			lines := make(chan lineReadResult, 1)
			lines <- lineReadResult{line: "cancel"}
			close(lines)
			var output, diagnostics strings.Builder
			outcome, request, err := runStartPrompt(context.Background(), interactiveState{}, draft, lines, &output, &output, &diagnostics, ColorPolicy{})
			if err != nil || outcome != startPromptCancel {
				t.Fatalf("outcome=%v err=%v, want cancel", outcome, err)
			}
			if !reflect.DeepEqual(request, interactiveStartRequest{}) {
				t.Fatalf("cancel returned request %+v", request)
			}
			if !reflect.DeepEqual(draft, before) {
				t.Fatalf("cancel mutated draft: before=%+v after=%+v", before, draft)
			}
		})
	}
}

// TestUnitCStartPromptParentTerminationEachField cancels only after the actual prompt.
// TestUnitCStartPromptParentTerminationEachField verifies the actual start lifecycle boundary.
func TestUnitCStartPromptParentTerminationEachField(t *testing.T) {
	for field := startFieldEndpoint; field <= startFieldRevision; field++ {
		t.Run(startFieldName(field), func(t *testing.T) {
			parent, cancel := context.WithCancel(context.Background())
			defer cancel()
			draft := startDraft{request: interactiveStartRequest{EndpointID: "ep", ResourceID: "res", Profile: "profile", ProfileRevision: "revision"}}
			draft.missing[field] = true
			out := &unitCStageWriter{changed: make(chan struct{}, 1)}
			joined := make(chan struct{})
			go func() {
				defer close(joined)
				for out.String() != unitCFieldToken(field) {
					<-out.changed
				}
				cancel()
			}()
			var diag strings.Builder
			_, _, err := runStartPrompt(parent, interactiveState{}, draft, make(chan lineReadResult), out, out, &diag, ColorPolicy{})
			<-joined
			if err != context.Canceled || out.String() != unitCFieldToken(field) || diag.Len() != 0 {
				t.Fatalf("field cancellation err=%v output=%q diagnostics=%q", err, out.String(), diag.String())
			}
		})
	}
}

// TestUnitCStartPromptPreReadQuitDoesNotDispatchQueuedStart verifies the actual start lifecycle boundary.
func TestUnitCStartPromptPreReadQuitDoesNotDispatchQueuedStart(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	input := strings.NewReader("start\nhelp\nquit\ne\nr\np\nv\n")
	if err := RunInteractive(context.Background(), stub, input, &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 0 || strings.Contains(output.String(), "command submitted") {
		t.Fatalf("queued start dispatched: admits=%d output=%q", stub.admit, output.String())
	}
}

// TestUnitCStartTicketReaderSanity (matrix file) proves one field-boundary cancellation and reader join.
// The committed C9 matrix covers all twelve field/termination combinations.

// TestUnitCStartInitialAndStartupTermination proves pre-termination does not start lifecycle workers.

// TestUnitCStartWriterFaultMatrix verifies pre-admission writer failures preserve identity.
// TestUnitCStartWriterFaultLegacy verifies the actual start lifecycle boundary.
func TestUnitCStartWriterFaultLegacy(t *testing.T) {
	phases := []struct {
		name   string
		output bool
	}{{"prompt", true}, {"diagnostic", false}}
	for _, phase := range phases {
		t.Run(phase.name, func(t *testing.T) {
			sentinel := errors.New("unit-c-" + phase.name)
			api := newUnitCAPI()
			var out, errOut io.Writer = io.Discard, io.Discard
			if phase.output {
				out = &unitCWriterFailure{err: sentinel, failAfter: 1}
			} else {
				errOut = &unitCWriterFailure{err: sentinel, failAfter: 1}
			}
			lines := make(chan lineReadResult, 1)
			if !phase.output {
				lines <- lineReadResult{line: "bad value"}
			}
			_, err := executeInteractiveLine(context.Background(), api, &interactiveState{}, "start", lines, out, out, errOut, InteractiveOptions{})
			if !errors.Is(unwrapStartTermination(err), sentinel) && !errors.Is(err, sentinel) {
				t.Fatalf("error=%v, want sentinel", err)
			}
			counts, intents := api.snapshot()
			if counts.Admit != 0 || len(intents) != 0 {
				t.Fatalf("admitted after writer fault: %+v intents=%d", counts, len(intents))
			}
		})
	}
}

// TestUnitCStartScaleCostContract verifies bounded prompt work at two in-memory scales.

// TestUnitCStartOwnedReaderWatcherConvergence verifies owned reader cleanup after cancellation.

// TestUnitCStartTerminationPriority verifies an observed parent cancellation wins over normal EOF.

// TestUnitCStartInputOwnershipMatrix verifies CloseInput is honored only for owned input.

// TestUnitCStartStdinOwnershipChild records the non-global ownership rule without replacing os.Stdin.

// TestUnitCStartTerminationQueuedInputs verifies terminal prompt results do not admit queued commands.

// TestUnitCStartCancelAllowsNextCommand distinguishes ordinary cancel from fatal termination.

// TestUnitCStartWizardIntentExactlyOnce verifies exact start intent mapping.
// TestUnitCStartWizardIntentExactlyOnce verifies the actual start lifecycle boundary.
func TestUnitCStartWizardIntentExactlyOnce(t *testing.T) {
	api := newUnitCAPI()
	state := interactiveState{}
	lines := make(chan lineReadResult, 1)
	_, err := executeInteractiveLine(context.Background(), api, &state, "start endpoint-1 resource-1 --profile profile-1 --profile-revision revision-1", lines, io.Discard, io.Discard, io.Discard, InteractiveOptions{})
	if err != nil {
		t.Fatal(err)
	}
	counts, intents := api.snapshot()
	if counts.Capability != 1 || counts.Admit != 1 || len(intents) != 1 {
		t.Fatalf("counts=%+v intents=%d", counts, len(intents))
	}
	intent := intents[0]
	if intent.EndpointID != "endpoint-1" || intent.Operation != protocol.OperationAgentStart || intent.LaunchProfileID != "profile-1" || intent.ProfileRevision != "revision-1" || intent.Target != nil {
		t.Fatalf("unexpected intent=%+v", intent)
	}
}
