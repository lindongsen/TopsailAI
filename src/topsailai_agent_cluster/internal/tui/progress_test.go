package tui

import (
	"bytes"
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// progressStub is a diagnostics boundary that reports whether it can render
// progress lines. It exists so a test can prove the reporter honours the
// boundary decision instead of probing global terminal state.
type progressStub struct {
	bytes.Buffer
	eligible bool
	policy   ColorPolicy
}

// ProgressEligible reports the configured eligibility.
func (s *progressStub) ProgressEligible() bool { return s.eligible }

// ColorPolicy reports the configured colour policy.
func (s *progressStub) ColorPolicy() ColorPolicy { return s.policy }

// newProgressStub builds an eligible, colourless boundary so a test can assert on
// plain text without escape sequences interfering.
func newProgressStub() *progressStub {
	return &progressStub{eligible: true}
}

// pastThreshold moves the reporter's clock beyond the threshold, so a test can
// assert on emitted output without sleeping.
func pastThreshold(p *ActionProgress) {
	p.now = func() time.Time { return p.start.Add(progressThreshold + time.Millisecond) }
}

// TestProgressDisabledWithoutBoundary proves an unknown writer receives nothing.
// A writer that does not report a progress boundary must never be written to,
// because the reporter cannot know whether that stream can render the lines.
func TestProgressDisabledWithoutBoundary(t *testing.T) {
	var plain bytes.Buffer
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	if progress := NewActionProgress(&plain, request); progress != nil {
		t.Fatalf("expected nil reporter for a writer without a progress boundary, got %#v", progress)
	}
	if plain.Len() != 0 {
		t.Fatalf("expected no bytes written, got %q", plain.String())
	}
}

// TestProgressDisabledWhenBoundaryRefuses proves a boundary that reports itself
// ineligible stays silent, which is how a redirected diagnostics stream behaves.
func TestProgressDisabledWhenBoundaryRefuses(t *testing.T) {
	out := &progressStub{eligible: false}
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	if progress := NewActionProgress(out, request); progress != nil {
		t.Fatalf("expected nil reporter for an ineligible boundary, got %#v", progress)
	}
	if out.Len() != 0 {
		t.Fatalf("expected no bytes written, got %q", out.String())
	}
}

// TestProgressNilReporterIsSafe proves every method tolerates a nil reporter, so
// a caller disables progress by passing nil instead of branching at each site.
func TestProgressNilReporterIsSafe(t *testing.T) {
	var progress *ActionProgress
	progress.Stage("server received")
	progress.Tick()
}

// TestProgressSilentBelowThreshold proves a fast command prints nothing. The
// read commands answer in milliseconds, so a hint that appears and disappears
// within one frame would be noise rather than information.
func TestProgressSilentBelowThreshold(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	progress.Stage("server received")
	progress.Tick()
	if out.Len() != 0 {
		t.Fatalf("expected no output below the threshold, got %q", out.String())
	}
}

// TestProgressEmitsHeaderAndStages proves the block appears once the threshold
// passes, with the header first and each stage indented beneath it.
func TestProgressEmitsHeaderAndStages(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	progress.Stage("server received")
	progress.Stage("request delivered")
	progress.Tick()
	got := out.String()
	want := "sending message to session s-1 (ep-1)...\n" +
		progressStageIndent + "server received\n" +
		progressStageIndent + "request delivered\n"
	if got != want {
		t.Fatalf("unexpected progress block:\n got %q\nwant %q", got, want)
	}
}

// TestProgressHeaderPrintedOnce proves the header is not repeated when later
// stages arrive, so the block reads as one header plus a growing stage list.
func TestProgressHeaderPrintedOnce(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	progress.Stage("server received")
	progress.Stage("executing")
	got := out.String()
	if count := strings.Count(got, "sending message to"); count != 1 {
		t.Fatalf("expected the header once, got %d occurrences in %q", count, got)
	}
}

// TestProgressRepeatedStagePrintedOnce proves an unchanged state is not a new
// fact, so the wait loop cannot print the same row on every poll.
func TestProgressRepeatedStagePrintedOnce(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	for i := 0; i < 5; i++ {
		progress.Stage("executing")
		progress.Tick()
	}
	if count := strings.Count(out.String(), "executing"); count != 1 {
		t.Fatalf("expected the repeated stage once, got %d occurrences in %q", count, out.String())
	}
}

// TestProgressColourFollowsBoundary proves the styling comes from the boundary
// policy: an enabled policy emits SGR, a disabled one emits plain text.
func TestProgressColourFollowsBoundary(t *testing.T) {
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}

	coloured := &progressStub{eligible: true, policy: ColorPolicy{Enabled: true}}
	progress := NewActionProgress(coloured, request)
	pastThreshold(progress)
	progress.Stage("executing")
	if !strings.Contains(coloured.String(), ansiDim) {
		t.Fatalf("expected dim styling with colour enabled, got %q", coloured.String())
	}

	plain := newProgressStub()
	progress = NewActionProgress(plain, request)
	pastThreshold(progress)
	progress.Stage("executing")
	if strings.Contains(plain.String(), "\x1b") {
		t.Fatalf("expected no escape sequence with colour disabled, got %q", plain.String())
	}
}

// TestProgressNeverClaimsSuccess proves a progress row cannot assert an outcome
// before the receipt exists. Every stage row is a lifecycle state, so the block
// must never contain a completion claim.
func TestProgressNeverClaimsSuccess(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	for _, status := range []protocol.CommandStatus{
		protocol.StatusAdmitted,
		protocol.StatusDispatched,
		protocol.StatusEndpointAdmitted,
		protocol.StatusExecuting,
	} {
		progress.Stage(progressStage(map[string]any{"status": string(status)}))
	}
	got := strings.ToLower(out.String())
	for _, claim := range []string{"succeeded", "success", "completed", "done"} {
		if strings.Contains(got, claim) {
			t.Fatalf("progress claimed %q before the receipt: %q", claim, out.String())
		}
	}
}

// TestProgressStageMatchesReceiptWording proves the progress wording is derived
// from the same label function as the receipt, so the two can never disagree.
func TestProgressStageMatchesReceiptWording(t *testing.T) {
	state := map[string]any{"status": string(protocol.StatusExecuting)}
	want := StatusLabel(protocol.StatusExecuting, ReceiptForStatus(state))
	if got := progressStage(state); got != want {
		t.Fatalf("progress stage %q does not match receipt wording %q", got, want)
	}
	if got := progressStage(map[string]any{}); got != "" {
		t.Fatalf("expected no stage for a state without a status, got %q", got)
	}
}

// TestProgressTargetSanitizesIdentifiers proves an untrusted identifier cannot
// inject styling or move the cursor, because the header is written with trusted
// styling around it.
func TestProgressTargetSanitizesIdentifiers(t *testing.T) {
	request := ActionRequest{
		Operation:  protocol.OperationMessageSend,
		EndpointID: "ep\x1b[31m-1",
		ResourceID: "s\n-1",
	}
	header := progressHeader(request)
	if strings.Contains(header, "\x1b") {
		t.Fatalf("expected the escape sequence stripped, got %q", header)
	}
	if strings.Contains(header, "\n") {
		t.Fatalf("expected the newline flattened, got %q", header)
	}
}

// TestProgressStartNamesProfile proves a start names the launch profile and the
// Endpoint, because a start has no session target to name.
func TestProgressStartNamesProfile(t *testing.T) {
	request := ActionRequest{Operation: protocol.OperationAgentStart, EndpointID: "ep-1", Profile: "prof-1"}
	got := progressHeader(request)
	want := "starting agent from profile prof-1 on endpoint ep-1..."
	if got != want {
		t.Fatalf("unexpected start header: got %q want %q", got, want)
	}
}

// TestProgressVerbCoversStandardOperations proves every standard mutating
// operation has a wording, and an unknown operation has none so it stays silent.
func TestProgressVerbCoversStandardOperations(t *testing.T) {
	operations := []string{
		protocol.OperationMessageSend,
		protocol.OperationContextInject,
		protocol.OperationExecutionInterrupt,
		protocol.OperationAgentStart,
		protocol.OperationAgentResume,
		protocol.OperationAgentStop,
		protocol.OperationAgentDriveStart,
		protocol.OperationAgentDriveStop,
		protocol.OperationCommandExec,
		ctlOperationPrefix + "heartbeat",
	}
	for _, operation := range operations {
		if progressVerb(operation) == "" {
			t.Fatalf("expected a verb for standard operation %q", operation)
		}
	}
	if got := progressVerb("provider.unknown"); got != "" {
		t.Fatalf("expected no verb for an unknown operation, got %q", got)
	}
}

// TestProgressWriteFailureIgnored proves a broken diagnostics stream cannot
// change the command outcome, because progress is best-effort presentation.
func TestProgressWriteFailureIgnored(t *testing.T) {
	out := &failingProgressWriter{}
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	progress.Stage("executing")
	progress.Tick()
}

// failingProgressWriter is an eligible boundary whose writes always fail.
type failingProgressWriter struct{}

// ProgressEligible reports eligibility so the reporter is constructed.
func (w *failingProgressWriter) ProgressEligible() bool { return true }

// ColorPolicy reports a disabled policy so the plain write path is exercised.
func (w *failingProgressWriter) ColorPolicy() ColorPolicy { return ColorPolicy{} }

// Write always fails, which the reporter must ignore.
func (w *failingProgressWriter) Write([]byte) (int, error) { return 0, errors.New("broken pipe") }

// TestProgressConcurrentStagesAreSafe proves a concurrent collector can report a
// stage from another goroutine without a data race on the buffered stages.
func TestProgressConcurrentStagesAreSafe(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(index int) {
			defer wg.Done()
			progress.Stage("endpoint-" + string(rune('a'+index)) + ": collected")
			progress.Tick()
		}(i)
	}
	wg.Wait()
	if out.Len() == 0 {
		t.Fatal("expected the concurrent stages to be written")
	}
}

// TestWaitForTerminalWithProgressReportsStages proves the wait loop reports the
// durable states it observes, so a progress row is evidence rather than a guess.
func TestWaitForTerminalWithProgressReportsStages(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	reader := &sequenceStateReader{states: []map[string]any{
		{"status": string(protocol.StatusAdmitted)},
		{"status": string(protocol.StatusExecuting)},
		{"status": string(protocol.StatusFinished)},
	}}
	state, err := WaitForTerminalWithProgress(context.Background(), reader, "cmd-1", time.Millisecond, progress)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if state["status"] != string(protocol.StatusFinished) {
		t.Fatalf("expected the terminal state, got %v", state["status"])
	}
	got := out.String()
	for _, want := range []string{"server received", "executing"} {
		if !strings.Contains(got, want) {
			t.Fatalf("expected stage %q in %q", want, got)
		}
	}
}

// sequenceStateReader serves one durable state per poll, then repeats the last.
type sequenceStateReader struct {
	mu     sync.Mutex
	states []map[string]any
	index  int
}

// GetCommand returns the next scripted state.
func (r *sequenceStateReader) GetCommand(context.Context, string) (map[string]any, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.index >= len(r.states) {
		return r.states[len(r.states)-1], nil
	}
	state := r.states[r.index]
	r.index++
	return state, nil
}

// TestWaitForTerminalWithNilProgressKeepsBehaviour proves the nil reporter path
// returns exactly what the original wait returned.
func TestWaitForTerminalWithNilProgressKeepsBehaviour(t *testing.T) {
	reader := &sequenceStateReader{states: []map[string]any{
		{"status": string(protocol.StatusFinished)},
	}}
	state, err := WaitForTerminalWithProgress(context.Background(), reader, "cmd-1", time.Millisecond, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if state["status"] != string(protocol.StatusFinished) {
		t.Fatalf("expected the terminal state, got %v", state["status"])
	}
}

// TestProgressEndpointStageReportsFailure proves a failed Endpoint is reported as
// failed rather than omitted, because a silent gap would let the operator believe
// every Endpoint answered.
func TestProgressEndpointStageReportsFailure(t *testing.T) {
	failed := progressEndpointStage(endpointResult{endpointID: "ep-1", err: errors.New("boom")})
	if !strings.Contains(failed, "failed") {
		t.Fatalf("expected a failure stage, got %q", failed)
	}
	ok := progressEndpointStage(endpointResult{endpointID: "ep-1"})
	if !strings.Contains(ok, "collected") {
		t.Fatalf("expected a collected stage, got %q", ok)
	}
}

// TestRefreshWithProgressReportsEndpoints proves a forced collection reports each
// Endpoint as it completes, so a fleet refresh is not one opaque wait.
func TestRefreshWithProgressReportsEndpoints(t *testing.T) {
	stub := refreshScopeStub()
	out := newProgressStub()
	progress := NewProgress(out, "refreshing all endpoints...")
	pastThreshold(progress)
	var rendered bytes.Buffer
	if err := (CommandRunner{API: stub}).RefreshWithProgress(context.Background(), &rendered, &bytes.Buffer{}, "", false, TableOptions{}, progress); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	got := out.String()
	if !strings.Contains(got, "refreshing all endpoints...") {
		t.Fatalf("expected the refresh header, got %q", got)
	}
	if !strings.Contains(got, "collected") {
		t.Fatalf("expected a per-endpoint stage, got %q", got)
	}
}

// TestRefreshWithNilProgressKeepsBehaviour proves the nil reporter path renders
// the same table as before, so existing callers are unaffected.
func TestRefreshWithNilProgressKeepsBehaviour(t *testing.T) {
	stub := refreshScopeStub()
	var rendered bytes.Buffer
	if err := (CommandRunner{API: stub}).Refresh(context.Background(), &rendered, &bytes.Buffer{}, "", false, TableOptions{}); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rendered.Len() == 0 {
		t.Fatal("expected the refresh to render a table")
	}
}

// TestProgressHeaderNamesTheSession proves the progress header names the reported
// session name first, matching the confirmation question. The operator therefore
// reads the same target description before and after answering, instead of an
// opaque identifier that the interactive table never showed.
func TestProgressHeaderNamesTheSession(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationAgentDriveStart, EndpointID: "ep-1", ResourceID: "s-1", DisplayName: "Daily work"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	progress.Stage("server received")
	progress.Tick()
	want := `starting drive controller for session "Daily work" s-1 (ep-1)...` + "\n" +
		progressStageIndent + "server received\n"
	if got := out.String(); got != want {
		t.Fatalf("unexpected progress block:\n got %q\nwant %q", got, want)
	}
}

// TestProgressHeaderKeepsTheOldWordingWithoutAName proves an unnamed session keeps
// the previous header exactly, so the descriptive name never becomes a required
// field of the progress line.
func TestProgressHeaderKeepsTheOldWordingWithoutAName(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	progress.Stage("server received")
	progress.Tick()
	want := "sending message to session s-1 (ep-1)...\n" + progressStageIndent + "server received\n"
	if got := out.String(); got != want {
		t.Fatalf("unnamed session changed the header:\n got %q\nwant %q", got, want)
	}
}

// TestProgressHeaderSanitizesTheReportedName proves the reported name is sanitized
// before it reaches a trusted styled line, so a provider cannot inject terminal
// control sequences through a session name.
func TestProgressHeaderSanitizesTheReportedName(t *testing.T) {
	out := newProgressStub()
	request := ActionRequest{Operation: protocol.OperationMessageSend, EndpointID: "ep-1", ResourceID: "s-1", DisplayName: "evil\x1b[31mname"}
	progress := NewActionProgress(out, request)
	pastThreshold(progress)
	progress.Stage("server received")
	progress.Tick()
	got := out.String()
	if strings.Contains(got, "\x1b[31m") {
		t.Fatalf("reported name reached the terminal unsanitized: %q", got)
	}
	if !strings.Contains(got, `"evilname"`) {
		t.Fatalf("sanitized name is missing from the header: %q", got)
	}
}
