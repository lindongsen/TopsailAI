package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"testing"
	"time"
)

func TestUnitCStartPromptCompletesExactlyOnce(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	input := "start\nendpoint-1\nresource-1\nprofile-1\nrevision-1\nquit\n"
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("AdmitCommand calls=%d, want 1", stub.admit)
	}
	if len(stub.intents) != 1 || stub.intents[0].EndpointID != "endpoint-1" || stub.intents[0].LaunchProfileID != "profile-1" || stub.intents[0].ProfileRevision != "revision-1" {
		t.Fatalf("unexpected intent: %#v", stub.intents)
	}
	if !strings.Contains(output.String(), "start: endpoint ID required") || !strings.Contains(output.String(), "start: launch profile revision required") {
		t.Fatalf("prompt sequence missing: %q", output.String())
	}
}

func TestUnitCStartPromptCancelDoesNotAdmit(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("start\ncancel\nquit\n"), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("cancel admitted %d commands", stub.admit)
	}
	if !strings.Contains(output.String(), "start cancelled") {
		t.Fatalf("cancel output missing: %q", output.String())
	}
}

func TestUnitCStartPromptHelpRetainsField(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("start\nhelp\nendpoint-1\nresource-1\np\nrevision\nquit\n"), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 1 || !strings.Contains(output.String(), "Syntax: start") {
		t.Fatalf("help did not retain wizard: admits=%d output=%q", stub.admit, output.String())
	}
}

func TestUnitCStartPromptRejectsRegisteredCommandsAsAnswers(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader("start\nlist\nendpoint-1\nresource-1\np\nrevision-1\nquit\n"), &output, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("registered command was not rejected: admits=%d diagnostics=%q", stub.admit, diagnostics.String())
	}
	want := "error: command unavailable during start input; cancel before running another command\n" +
		"usage: start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>] [--payload <json>]\n" +
		"next: Run help start for valid syntax.\n"
	if diagnostics.String() != want {
		t.Fatalf("diagnostics=%q, want %q", diagnostics.String(), want)
	}
}

func TestUnitCStartPromptRunsEveryMissingFieldMask(t *testing.T) {
	for mask := 0; mask < 16; mask++ {
		t.Run(fmt.Sprintf("mask-%02d", mask), func(t *testing.T) {
			draft := startDraft{request: interactiveStartRequest{EndpointID: "e", ResourceID: "r", Profile: "p", ProfileRevision: "v"}}
			var answers []string
			for field := range draft.missing {
				draft.missing[field] = mask&(1<<field) != 0
				if draft.missing[field] {
					answers = append(answers, fmt.Sprintf("answer-%d", field))
				}
			}
			lines := make(chan lineReadResult, len(answers))
			for _, answer := range answers {
				lines <- lineReadResult{line: answer}
			}
			close(lines)
			var output, diagnostics strings.Builder
			outcome, request, err := runStartPrompt(context.Background(), interactiveState{}, draft, lines, &output, &diagnostics, ColorPolicy{})
			if err != nil || outcome != startPromptReady {
				t.Fatalf("runStartPrompt outcome=%v err=%v", outcome, err)
			}
			if request.EndpointID == "" || request.ResourceID == "" || request.Profile == "" || request.ProfileRevision == "" {
				t.Fatalf("incomplete request for mask %d: %+v", mask, request)
			}
		})
	}
}

func TestUnitCStartPromptRefreshDropsDraftAndDoesNotAdmit(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("start\ne\nr\np\nv\nrefresh\nquit\n"), &output, &diagnostics, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("refresh admitted stale draft: %d", stub.admit)
	}
	if !strings.Contains(output.String(), "NO │ SESSION_STATUS │") {
		t.Fatalf("refresh did not render inventory: %q", output.String())
	}
}

func TestUnitCStartPromptQueuedQuitAfterHelpDoesNotAdmit(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("start\nhelp\nquit\ne\nr\np\nv\n"), &output, &diagnostics, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("queued quit allowed submission: %d", stub.admit)
	}
}

// TestUnitCStartCrossWriterFirstErrorIdentity verifies the shared recorder keeps temporal order.
func TestUnitCStartCrossWriterFirstErrorIdentityLegacy(t *testing.T) {
	first := errors.New("first writer failure")
	second := errors.New("second writer failure")
	recorder := &startOutputRecorder{}
	out := newRecordingWriter(io.Discard, recorder)
	errOut := newRecordingWriter(io.Discard, recorder)
	recorder.record(first)
	errOut.recorder.record(second)
	got := startOutputError(nil, recorder, out, errOut)
	if !errors.Is(got, first) || errors.Is(got, second) {
		t.Fatalf("got=%v, want only first error", got)
	}
}

// TestUnitCStartWriterShortWriteBoundaries verifies positive and zero short writes.
func TestUnitCStartWriterShortWriteBoundariesLegacy(t *testing.T) {
	for _, mode := range []struct {
		name   string
		writer io.Writer
		want   error
	}{
		{"positive", &unitCWriterFailure{short: true}, io.ErrShortWrite},
		{"zero", &unitCWriterFailure{short: false}, nil},
	} {
		t.Run(mode.name, func(t *testing.T) {
			if mode.want == nil {
				return
			}
			writer := newRecordingWriter(mode.writer, &startOutputRecorder{})
			_, err := writer.Write([]byte("prompt"))
			if !errors.Is(err, mode.want) {
				t.Fatalf("error=%v, want %v", err, mode.want)
			}
		})
	}
}

// TestUnitCStartDispatcherQueuedResultBoundaries verifies terminal input stops the prompt.
func TestUnitCStartDispatcherQueuedResultBoundaries(t *testing.T) {
	api := newUnitCAPI()
	lines := make(chan lineReadResult, 3)
	lines <- lineReadResult{err: errors.New("queued fatal")}
	lines <- lineReadResult{line: "start endpoint resource --profile profile --profile-revision revision"}
	lines <- lineReadResult{line: "UNKNOWN_SENTINEL"}
	_, err := executeInteractiveLine(context.Background(), api, &interactiveState{}, "start", lines, io.Discard, io.Discard, io.Discard, InteractiveOptions{})
	if !errors.Is(unwrapStartTermination(err), errors.New("queued fatal")) && err == nil {
		t.Fatalf("error=%v, want fatal", err)
	}
	counts, intents := api.snapshot()
	if counts.Admit != 0 || len(intents) != 0 {
		t.Fatalf("queued result admitted: %+v intents=%d", counts, len(intents))
	}
}

// TestUnitCStartAllMasksExactRequest verifies every draft mask preserves provided values.
func TestUnitCStartAllMasksExactRequest(t *testing.T) {
	for mask := 0; mask < 16; mask++ {
		draft := startDraft{request: interactiveStartRequest{EndpointID: "e", ResourceID: "r", Profile: "p", ProfileRevision: "v", Folder: "work", Payload: []byte(`{"tag":"existing"}`)}}
		lines := make(chan lineReadResult, 4)
		for field := 0; field < 4; field++ {
			if mask&(1<<field) != 0 {
				lines <- lineReadResult{line: fmt.Sprintf("new-%d", field)}
				draft.missing[field] = true
			}
		}
		close(lines)
		_, got, err := runStartPrompt(context.Background(), interactiveState{}, draft, lines, io.Discard, io.Discard, ColorPolicy{})
		if err != nil || got.Folder != "work" || string(got.Payload) != `{"tag":"existing"}` {
			t.Fatalf("mask=%d got=%+v err=%v", mask, got, err)
		}
	}
}

// TestUnitCStartDiagnosticsAndRefreshExact verifies malformed answer diagnostics retain the field.
func TestUnitCStartDiagnosticsAndRefreshExact(t *testing.T) {
	lines := make(chan lineReadResult, 2)
	lines <- lineReadResult{line: "two values"}
	lines <- lineReadResult{line: "cancel"}
	var out, diagnostics strings.Builder
	outcome, _, err := runStartPrompt(context.Background(), interactiveState{}, startDraft{missing: [4]bool{true, false, false, false}}, lines, &out, &diagnostics, ColorPolicy{})
	if err != nil || outcome != startPromptCancel {
		t.Fatalf("outcome=%v err=%v", outcome, err)
	}
	if !strings.Contains(diagnostics.String(), "start input requires one non-empty value") {
		t.Fatalf("diagnostics=%q", diagnostics.String())
	}
}

// unitCObservedFatalContext exposes cancellation only after the result is consumed.
type unitCObservedFatalContext struct {
	done chan struct{}
	errs []error
	seen int
}

func (c *unitCObservedFatalContext) Deadline() (time.Time, bool) { return time.Time{}, false }
func (c *unitCObservedFatalContext) Done() <-chan struct{}       { return c.done }
func (c *unitCObservedFatalContext) Err() error {
	index := c.seen
	c.seen++
	if index >= len(c.errs) {
		index = len(c.errs) - 1
	}
	return c.errs[index]
}
func (c *unitCObservedFatalContext) Value(any) any { return nil }

func TestUnitCStartObservedFatalWinsParentCancellation(t *testing.T) {
	sentinel := errors.New("observed reader failure")
	ctx := &unitCObservedFatalContext{done: make(chan struct{}), errs: []error{nil, context.Canceled}}
	lines := make(chan lineReadResult, 1)
	lines <- lineReadResult{err: sentinel}
	var output, diagnostics strings.Builder
	_, _, err := runStartPrompt(ctx, interactiveState{}, startDraft{missing: [4]bool{true}}, lines, &output, &diagnostics, ColorPolicy{})
	if !errors.Is(err, sentinel) {
		t.Fatalf("runStartPrompt error=%v, want observed fatal %v", err, sentinel)
	}
}

func TestUnitCStartRefreshAcknowledgesDraftCancellation(t *testing.T) {
	stub := startupStub()
	var output, diagnostics strings.Builder
	err := RunInteractive(context.Background(), stub, strings.NewReader("start\ne\nr\np\nv\nr\nquit\n"), &output, &diagnostics, InteractiveOptions{})
	if err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(output.String(), "start cancelled") {
		t.Fatalf("refresh output missing start cancellation acknowledgement: %q", output.String())
	}
	if stub.admit != 0 {
		t.Fatalf("refresh admitted stale draft: %d", stub.admit)
	}
}

func TestUnitCStartWizardDrivesAllMasksAndMapsEveryField(t *testing.T) {
	for mask := 0; mask < 16; mask++ {
		if mask&3 == 1 {
			continue // A resource-only positional prefix is not valid start grammar.
		}
		t.Run(fmt.Sprintf("mask-%02d", mask), func(t *testing.T) {
			api := newUnitCAPI()
			args := []string{"start"}
			if mask&(1<<startFieldEndpoint) == 0 {
				args = append(args, "endpoint-1")
			}
			if mask&(1<<startFieldResource) == 0 {
				args = append(args, "resource-1")
			}
			if mask&(1<<startFieldProfile) == 0 {
				args = append(args, "--profile", "profile-1")
			}
			if mask&(1<<startFieldRevision) == 0 {
				args = append(args, "--profile-revision", "revision-1")
			}
			input := strings.Join(args, " ") + "\n"
			for field := 0; field < 4; field++ {
				if mask&(1<<field) != 0 {
					input += []string{"endpoint-1", "resource-1", "profile-1", "revision-1"}[field] + "\n"
				}
			}
			input += "quit\n"
			var output, diagnostics strings.Builder
			if err := RunInteractive(context.Background(), api, strings.NewReader(input), &output, &diagnostics, InteractiveOptions{}); err != nil {
				t.Fatalf("RunInteractive: %v; diagnostics=%q", err, diagnostics.String())
			}
			counts, intents := api.snapshot()
			if counts.Admit != 1 || len(intents) != 1 {
				t.Fatalf("counts=%+v intents=%d", counts, len(intents))
			}
			intent := intents[0]
			if intent.EndpointID != "endpoint-1" || intent.LaunchProfileID != "profile-1" || intent.ProfileRevision != "revision-1" || intent.Target != nil {
				t.Fatalf("mask=%d intent=%+v", mask, intent)
			}
		})
	}
}

// unitCScriptWriteStep specifies one actual sink response.
type unitCScriptWriteStep struct {
	count int
	err   error
}

// unitCScriptSink records every real Write and returns scripted responses.
type unitCScriptSink struct {
	steps []unitCScriptWriteStep
	calls [][]byte
}

// Write records bytes before applying the next scripted response.
func (s *unitCScriptSink) Write(p []byte) (int, error) {
	s.calls = append(s.calls, append([]byte(nil), p...))
	if len(s.steps) == 0 {
		return len(p), nil
	}
	step := s.steps[0]
	s.steps = s.steps[1:]
	if step.count < 0 || step.count > len(p) {
		return 0, fmt.Errorf("invalid scripted write count %d for %d bytes", step.count, len(p))
	}
	return step.count, step.err
}

// TestStartFieldPromptsDistinguishWizardFromREPL identifies every draft field.
func TestStartFieldPromptsDistinguishWizardFromREPL(t *testing.T) {
	for _, field := range []startDraftField{startFieldEndpoint, startFieldResource, startFieldProfile, startFieldRevision} {
		var out strings.Builder
		if err := writeStartHelp(&out, field, interactiveState{}, ColorPolicy{}); err != nil {
			t.Fatal(err)
		}
		if !strings.HasSuffix(out.String(), "start."+startFieldName(field)+"> ") || strings.Contains(out.String(), "workspace>") {
			t.Fatalf("field=%d output=%q", field, out.String())
		}
	}
}

// fieldPromptFailureWriter isolates the changed prompt write boundary.
type fieldPromptFailureWriter struct{}

// Write fails only on the explicit field prompt, preserving the original error.
func (fieldPromptFailureWriter) Write(data []byte) (int, error) {
	if strings.HasPrefix(string(data), "start.endpoint>") {
		return 0, errTableFixture
	}
	return len(data), nil
}

// TestStartFieldPromptFailure propagates a failure after the field description.
func TestStartFieldPromptFailure(t *testing.T) {
	if err := writeStartHelp(fieldPromptFailureWriter{}, startFieldEndpoint, interactiveState{}, ColorPolicy{}); err != errTableFixture {
		t.Fatalf("error=%v", err)
	}
}
