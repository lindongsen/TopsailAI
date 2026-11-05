package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
	"time"
)

// unitCWriteAttempt records one actual writer call observed by a fault gate.
type unitCWriteAttempt struct {
	Stage    string
	Text     string
	Err      error
	Reply    chan error
	Replied  bool
	ReplyErr error
}

// unitCWriteGate arms a deterministic writer fault after the target stage is ready.
type unitCWriteGate struct {
	mu        sync.Mutex
	armed     bool
	persist   bool
	err       error
	attempts  []unitCWriteAttempt
	changed   chan struct{}
	hit       chan unitCWriteAttempt
	abortCh   chan struct{}
	abortOnce sync.Once
}

// newUnitCWriteGate creates a gate with no startup fault armed.
func newUnitCWriteGate() *unitCWriteGate {
	return &unitCWriteGate{
		changed: make(chan struct{}, 1),
		hit:     make(chan unitCWriteAttempt, 1),
		abortCh: make(chan struct{}),
	}
}

// arm enables a one-shot or persistent failure for subsequent actual writes.
func (g *unitCWriteGate) arm(err error, persist bool) {
	g.mu.Lock()
	g.armed = true
	g.persist = persist
	g.err = err
	g.mu.Unlock()
}

// abort releases a writer blocked waiting for the test-side attempt reply.
func (g *unitCWriteGate) abort() {
	g.mu.Lock()
	g.armed = false
	g.mu.Unlock()
	g.abortOnce.Do(func() { close(g.abortCh) })
}

func (g *unitCWriteGate) reply(attempt unitCWriteAttempt, err error) {
	g.mu.Lock()
	for i := range g.attempts {
		if g.attempts[i].Reply == attempt.Reply {
			g.attempts[i].Replied = true
			g.attempts[i].ReplyErr = err
			break
		}
	}
	g.mu.Unlock()
	attempt.Reply <- err
}

// snapshot returns detached attempts and the current gate state.
func (g *unitCWriteGate) snapshot() ([]unitCWriteAttempt, bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	return append([]unitCWriteAttempt(nil), g.attempts...), g.armed
}

// write publishes the real Write attempt before waiting for its test-side reply.
func (g *unitCWriteGate) write(stage string, p []byte) error {
	g.mu.Lock()
	if !g.armed {
		g.mu.Unlock()
		return nil
	}
	persist, configuredErr := g.persist, g.err
	if !persist {
		g.armed = false
	}
	attempt := unitCWriteAttempt{Stage: stage, Text: string(p), Err: configuredErr, Reply: make(chan error, 1)}
	g.attempts = append(g.attempts, attempt)
	g.mu.Unlock()
	select {
	case g.hit <- attempt:
	case <-g.abortCh:
		return io.ErrClosedPipe
	}
	select {
	case err := <-attempt.Reply:
		return err
	case <-g.abortCh:
		return io.ErrClosedPipe
	}
}

// unitC10Writer applies a gate to one real RunInteractive output writer.
type unitC10Writer struct {
	stage string
	base  *unitCStageWriter
	gate  *unitCWriteGate
}

// Write records successful bytes and injects faults only after the gate is armed.
func (w *unitC10Writer) Write(p []byte) (int, error) {
	if err := w.gate.write(w.stage, p); err != nil {
		return 0, err
	}
	return w.base.Write(p)
}

// unitC10Driver launches RunInteractive with separately gated output streams.
type unitC10Driver struct {
	reader           *unitCTicketReader
	out              *unitCStageWriter
	errOut           *unitCStageWriter
	outGate, errGate *unitCWriteGate
	api              *unitCAPI
	run              *unitCReferenceRun
	cancel           context.CancelFunc
	pending          *unitCReadTicket
	next             int
	tracePhase       string
	traceMode        string
	traceStep        string
	baseline         unitCAPICounts
	after            unitCAPICounts
	baselineIntents  int
	currentIntents   int
	expectedErr      error
}

// launchUnitC10Driver creates isolated reader, writers, API state and runner.
func launchUnitC10Driver(t *testing.T) *unitC10Driver {
	t.Helper()
	parent, cancel := context.WithCancel(context.Background())
	d := &unitC10Driver{
		reader:  newUnitCTicketReader(),
		out:     &unitCStageWriter{changed: make(chan struct{}, 1)},
		errOut:  &unitCStageWriter{changed: make(chan struct{}, 1)},
		outGate: newUnitCWriteGate(), errGate: newUnitCWriteGate(),
		api: newUnitCAPI(), run: &unitCReferenceRun{done: make(chan struct{})},
		cancel: cancel, next: 1,
	}
	t.Cleanup(func() {
		d.cancel()
		d.outGate.abort()
		d.errGate.abort()
		_ = d.reader.Close()
		select {
		case <-d.run.done:
		case <-time.After(3 * time.Second):
			t.Errorf("C10 cleanup did not join: %s", d.trace())
		}
	})
	go func() {
		d.run.err = RunInteractive(parent, d.api, d.reader,
			&unitC10Writer{stage: "output", base: d.out, gate: d.outGate},
			&unitC10Writer{stage: "errOut", base: d.errOut, gate: d.errGate},
			InteractiveOptions{CloseInput: true})
		close(d.run.done)
	}()
	return d
}
func (d *unitC10Driver) trace() string {
	counts, intents := d.api.snapshot()
	d.after, d.currentIntents = counts, len(intents)
	reads, closes := d.reader.Counts()
	outAttempts, outArmed := d.outGate.snapshot()
	errAttempts, errArmed := d.errGate.snapshot()
	formatAttempts := func(attempts []unitCWriteAttempt) string {
		parts := make([]string, 0, len(attempts))
		for i, attempt := range attempts {
			parts = append(parts, fmt.Sprintf("#%d{stream=%s bytes=%q configuredErr=%v replied=%t replyErr=%v}", i+1, attempt.Stage, attempt.Text, attempt.Err, attempt.Replied, attempt.ReplyErr))
		}
		return fmt.Sprintf("[%s]", strings.Join(parts, " "))
	}
	state := "running"
	actualErr := error(nil)
	select {
	case <-d.run.done:
		actualErr = d.run.err
		state = "joined"
	default:
	}
	return fmt.Sprintf("phase=%s mode=%s step=%s pending=%+v next=%d outGate{armed=%t persist=%t configuredErr=%v} errGate{armed=%t persist=%t configuredErr=%v} outAttempts=%s errAttempts=%s reads=%d closes=%d out=%q errOut=%q baseline=%+v after=%+v delta=%+v baselineIntents=%d currentIntents=%d intentDelta=%d runner=%s actualErr=%v errorsIs=%t", d.tracePhase, d.traceMode, d.traceStep, d.pending, d.next, outArmed, d.outGate.persist, d.outGate.err, errArmed, d.errGate.persist, d.errGate.err, formatAttempts(outAttempts), formatAttempts(errAttempts), reads, closes, d.out.String(), d.errOut.String(), d.baseline, d.after, unitCAPIAdd(d.baseline, d.after), d.baselineIntents, d.currentIntents, d.currentIntents-d.baselineIntents, state, actualErr, d.expectedErr != nil && errors.Is(actualErr, d.expectedErr))
}

// accept records one expected read ticket for the C10 test goroutine.
func (d *unitC10Driver) accept(t *testing.T, ticket unitCReadTicket) {
	t.Helper()
	if d.pending != nil || ticket.n != d.next {
		t.Fatalf("unexpected C10 ticket=%d want=%d", ticket.n, d.next)
	}
	d.next++
	d.pending = &ticket
}

// initial waits for the complete startup prompt and its first blocked Read.
func (d *unitC10Driver) initial(t *testing.T) {
	t.Helper()
	deadline := time.NewTimer(3 * time.Second)
	defer deadline.Stop()
	for {
		if strings.HasSuffix(d.out.String(), "workspace> ") && d.pending != nil {
			if d.pending.n != 1 {
				t.Fatalf("initial ticket=%d want=1", d.pending.n)
			}
			return
		}
		var entered <-chan unitCReadTicket
		if d.pending == nil {
			entered = d.reader.entered
		}
		select {
		case ticket := <-entered:
			d.accept(t, ticket)
		case <-d.out.changed:
		case <-deadline.C:
			t.Fatalf("C10 initial readiness timeout: %s", d.trace())
		}
	}
}

// answer replies to the one held Read ticket.
func (d *unitC10Driver) answer(t *testing.T, text string) {
	t.Helper()
	if d.pending == nil {
		t.Fatalf("C10 answer without pending ticket: %s", d.trace())
	}
	if err := unitCReply(*d.pending, text, nil); err != nil {
		t.Fatal(err)
	}
	d.pending = nil
}

// waitAttempt waits for an actual gated Write rather than an arm flag.
func (d *unitC10Driver) waitAttempt(t *testing.T, gate *unitCWriteGate) unitCWriteAttempt {
	t.Helper()
	select {
	case attempt := <-gate.hit:
		return attempt
	case <-time.After(3 * time.Second):
		t.Fatalf("C10 Write attempt timeout: %s", d.trace())
		return unitCWriteAttempt{}
	}
}

// waitBoundary waits for a complete field transcript and its held Read ticket.
func (d *unitC10Driver) waitBoundary(t *testing.T, want string, ordinal int) {
	t.Helper()
	deadline := time.NewTimer(3 * time.Second)
	defer deadline.Stop()
	for {
		if d.out.String() == want && d.pending != nil {
			if d.pending.n != ordinal {
				t.Fatalf("C10 boundary ticket=%d want=%d: %s", d.pending.n, ordinal, d.trace())
			}
			return
		}
		var entered <-chan unitCReadTicket
		if d.pending == nil {
			entered = d.reader.entered
		}
		select {
		case ticket := <-entered:
			d.accept(t, ticket)
		case <-d.out.changed:
		case <-d.errOut.changed:
		case <-deadline.C:
			t.Fatalf("C10 boundary timeout: %s", d.trace())
		}
	}
}

// advanceToField reaches a field while keeping its Read ticket unanswered.
func (d *unitC10Driver) advanceToField(t *testing.T, field int) string {
	d.initial(t)
	startup := d.out.String()
	d.answer(t, "start\n")
	want := startup
	for i := 0; i <= field; i++ {
		token := unitCFieldToken(startDraftField(i))
		want += token
		d.waitBoundary(t, want, i+2)
		if i < field {
			d.answer(t, []string{"endpoint-1\n", "resource-1\n", "profile-1\n"}[i])
		}
	}
	return want
}

// waitRunner waits for the cached runner result after the fault has fired.
func (d *unitC10Driver) waitRunner(t *testing.T) error {
	t.Helper()
	select {
	case <-d.run.done:
		return d.run.err
	case <-time.After(3 * time.Second):
		t.Fatalf("C10 runner timeout: %s", d.trace())
		return nil
	}
}

// c10ExpectedWrite returns the exact failing Write bytes and stream.
func c10ExpectedWrite(phase string) (string, string) {
	switch phase {
	case "prompt":
		return "start: endpoint ID required (endpoint ID). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\n", "output"
	case "help":
		return "start\n\nSyntax: start <endpoint> <resource> [--profile <id>] [--profile-revision <revision>] [--folder <path>] [--payload <json>]\nAvailable in: workspace, endpoint\nDescription: start an agent through the selected endpoint; interactive mode executes directly and does not support --json\n", "output"
	case "cancel":
		return "start cancelled\n", "output"
	case "output":
		return "command submitted: unit-c-command; use status unit-c-command to query\n", "output"
	case "errOut":
		return "error: start input requires one non-empty value\n", "errOut"
	default:
		return "", ""
	}
}

// c10Transcript returns the complete successful output expected after a staged fault.
func c10Transcript(start, phase string) string {
	const p = "NO │ ENDPOINT │ ADAPTER   │ SESSION_NAME │ SESSION_ID         │ SESSION_STATUS │ DATA_STATUS │ LAST_SUCCESS\n───┼──────────┼───────────┼──────────────┼────────────────────┼────────────────┼─────────────┼─────────────\n1  │ host-1   │ adapter-1 │              │ provider-session-1 │ running        │ ok          │            -\nlist: view sessions | <n> or cd <n>: select | start: launch agent | help: commands | q: quit\nworkspace> "
	const e = "start: endpoint ID required (endpoint ID). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\nstart.endpoint> "
	const r = "start: compatibility resource identifier required (compatibility resource identifier). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\nstart.resource> "
	const l = "start: launch profile ID required (launch profile ID). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\nstart.profile> "
	const v = "start: launch profile revision required (launch profile revision). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\nstart.profile-revision> "
	switch phase {
	case "prompt":
		return p
	case "help", "cancel", "errOut":
		return p + e
	case "output":
		return p + e + r + l + v
	}
	return start
}

// runWriterFault executes one phase/mode after proving phase readiness.
func runWriterFault(t *testing.T, phase, mode string) {
	t.Helper()
	sentinel := errors.New("unit-c-" + phase + "-" + mode)
	var baseline unitCAPICounts
	d := launchUnitC10Driver(t)
	d.expectedErr = sentinel
	field := 0
	gate := d.outGate
	trigger := "start\n"
	switch phase {
	case "prompt":
		d.initial(t)
		baseline, _ = d.api.snapshot()
	case "help", "cancel", "errOut":
		if phase == "errOut" {
			gate = d.errGate
			trigger = "two tokens\n"
		} else if phase == "help" {
			trigger = "help\n"
		} else {
			trigger = "cancel\n"
		}
		d.advanceToField(t, field)
		baseline, _ = d.api.snapshot()
	case "output":
		field = 3
		trigger = "revision-1\n"
		d.advanceToField(t, field)
		baseline, _ = d.api.snapshot()
	default:
		t.Fatalf("unknown C10 phase %q", phase)
	}
	d.tracePhase, d.traceMode, d.traceStep = phase, mode, "fault-ready"
	_, baselineItems := d.api.snapshot()
	d.baseline, d.baselineIntents = baseline, len(baselineItems)
	expectedOut := c10Transcript("", phase)
	if d.out.String() != expectedOut || d.pending == nil {
		t.Fatalf("%s readiness not established: %s", phase, d.trace())
	}
	gate.arm(sentinel, mode == "persistent")
	d.traceStep = "await-fault-attempt"
	d.answer(t, trigger)
	attempt := d.waitAttempt(t, gate)
	wantText, wantStream := c10ExpectedWrite(phase)
	if attempt.Err != sentinel || attempt.Stage != wantStream || attempt.Text != wantText {
		t.Fatalf("%s-%s invalid actual Write attempt=%+v wantText=%q wantStream=%s trace=%s", phase, mode, attempt, wantText, wantStream, d.trace())
	}
	gate.reply(attempt, sentinel)
	got := d.waitRunner(t)
	if got != sentinel || !errors.Is(got, sentinel) {
		t.Fatalf("%s-%s runner error=%v want exact sentinel=%v trace=%s", phase, mode, got, sentinel, d.trace())
	}
	counts, intents := d.api.snapshot()
	delta := unitCAPIAdd(baseline, counts)
	wantDelta := unitCAPICounts{}
	wantIntents := 0
	if phase == "output" {
		wantDelta = unitCAPICounts{Capability: 1, Admit: 1}
		wantIntents = 1
	}
	if delta != wantDelta || len(intents) != wantIntents {
		t.Fatalf("%s delta=%+v want=%+v counts=%+v intents=%d trace=%s", phase, delta, wantDelta, counts, len(intents), d.trace())
	}
	if got := d.out.String(); got != expectedOut {
		t.Fatalf("%s-%s complete output=%q want=%q trace=%s", phase, mode, got, expectedOut, d.trace())
	}
	if got := d.errOut.String(); got != "" {
		t.Fatalf("%s-%s unexpected errOut=%q trace=%s", phase, mode, got, d.trace())
	}
	attempts, armed := gate.snapshot()
	if len(attempts) != 1 || armed != (mode == "persistent") {
		t.Fatalf("%s-%s gate attempts=%d armed=%t trace=%s", phase, mode, len(attempts), armed, d.trace())
	}
}

// TestUnitCStartWriterFaultMatrix covers five live stages and both gate modes.
func TestUnitCStartWriterFaultMatrix(t *testing.T) {
	for _, phase := range []string{"prompt", "help", "cancel", "output", "errOut"} {
		for _, mode := range []string{"once", "persistent"} {
			if !t.Run(phase+"-"+mode, func(t *testing.T) { runWriterFault(t, phase, mode) }) {
				return
			}
		}
	}
}

// TestUnitCStartWriteGatePolicies verifies replies and both real Write results.
func TestUnitCStartWriteGatePolicies(t *testing.T) {
	for _, tc := range []struct {
		name    string
		persist bool
	}{
		{name: "once", persist: false},
		{name: "persistent", persist: true},
	} {
		if !t.Run(tc.name, func(t *testing.T) {
			sentinel := errors.New("unit-c-gate-" + tc.name)
			gate := newUnitCWriteGate()
			t.Cleanup(gate.abort)
			gate.arm(sentinel, tc.persist)
			writer := &unitC10Writer{stage: "output", base: &unitCStageWriter{changed: make(chan struct{}, 1)}, gate: gate}
			write := func(text string) (int, error) {
				t.Helper()
				type result struct {
					n   int
					err error
				}
				done := make(chan result, 1)
				go func() {
					n, err := writer.Write([]byte(text))
					done <- result{n, err}
				}()
				timer := time.NewTimer(3 * time.Second)
				defer timer.Stop()
				for {
					select {
					case attempt := <-gate.hit:
						gate.reply(attempt, sentinel)
					case got := <-done:
						return got.n, got.err
					case <-timer.C:
						gate.abort()
						<-done // Join the current gate implementation after abort.
						t.Fatalf("gate policy diagnostic timeout: mode=%s write=%q", tc.name, text)
					}
				}
			}
			n, err := write("first")
			if n != 0 || err != sentinel || !errors.Is(err, sentinel) {
				t.Fatalf("first Write result: mode=%s n=%d err=%v want=%v", tc.name, n, err, sentinel)
			}
			first, firstArmed := gate.snapshot()
			if len(first) != 1 || first[0].Text != "first" || first[0].Stage != "output" || first[0].Err != sentinel {
				t.Fatalf("first attempt: mode=%s attempts=%+v", tc.name, first)
			}
			n, err = write("second")
			wantN, wantErr, wantText, wantAttempts := 6, error(nil), "second", 1
			if tc.persist {
				wantN, wantErr, wantText, wantAttempts = 0, sentinel, "", 2
			}
			if n != wantN || err != wantErr || (tc.persist && !errors.Is(err, sentinel)) {
				t.Fatalf("second Write result mismatch: mode=%s n=%d err=%v wantN=%d wantErr=%v", tc.name, n, err, wantN, wantErr)
			}
			attempts, armed := gate.snapshot()
			if firstArmed != tc.persist || armed != tc.persist || len(attempts) != wantAttempts {
				t.Fatalf("gate state: mode=%s firstArmed=%t armed=%t attempts=%+v", tc.name, firstArmed, armed, attempts)
			}
			if tc.persist && (attempts[1].Text != "second" || attempts[1].Stage != "output" || attempts[1].Err != sentinel) {
				t.Fatalf("second attempt: %+v", attempts[1])
			}
			if got := writer.base.String(); got != wantText {
				t.Fatalf("gate transcript: mode=%s got=%q want=%q", tc.name, got, wantText)
			}
		}) {
			return
		}
	}
}
func TestUnitCStartOutputFaultPreservesAdmissionAccounting(t *testing.T) {
	sentinel := errors.New("unit-c-output-final-render")
	d := launchUnitC10Driver(t)
	d.expectedErr = sentinel
	d.tracePhase, d.traceMode, d.traceStep = "output", "once", "revision-readiness"
	expectedReadiness := c10Transcript("", "output")
	d.advanceToField(t, 3)
	beforeTranscript := expectedReadiness
	baseline, baselineIntents := d.api.snapshot()
	d.baseline, d.baselineIntents = baseline, len(baselineIntents)
	if d.out.String() != beforeTranscript || len(baselineIntents) != 0 {
		t.Fatalf("revision readiness changed state: %s", d.trace())
	}
	d.outGate.arm(sentinel, false)
	d.answer(t, "revision-1\n")
	attempt := d.waitAttempt(t, d.outGate)
	wantAck := "command submitted: unit-c-command; use status unit-c-command to query\n"
	if attempt.Text != wantAck || attempt.Stage != "output" || attempt.Err != sentinel {
		t.Fatalf("acknowledgement=%q stage=%s err=%v want=%q trace=%s", attempt.Text, attempt.Stage, attempt.Err, wantAck, d.trace())
	}
	d.outGate.reply(attempt, sentinel)
	if got := d.waitRunner(t); got != sentinel || !errors.Is(got, sentinel) {
		t.Fatalf("result=%v want=%v trace=%s", got, sentinel, d.trace())
	}
	counts, intents := d.api.snapshot()
	wantDelta := unitCAPICounts{Capability: 1, Admit: 1}
	if got := unitCAPIAdd(baseline, counts); got != wantDelta || len(intents)-len(baselineIntents) != 1 {
		t.Fatalf("delta=%+v want=%+v intents=%d trace=%s", got, wantDelta, len(intents), d.trace())
	}
	if counts.List != baseline.List || counts.Inventory != baseline.Inventory || counts.Command != baseline.Command || counts.ListCommands != baseline.ListCommands || counts.Output != baseline.Output {
		t.Fatalf("unexpected nonzero API delta: before=%+v after=%+v trace=%s", baseline, counts, d.trace())
	}
	if got := d.out.String(); got != beforeTranscript {
		t.Fatalf("successful transcript=%q want=%q trace=%s", got, beforeTranscript, d.trace())
	}
	if got := d.errOut.String(); got != "" {
		t.Fatalf("unexpected errOut=%q trace=%s", got, d.trace())
	}
}

// TestUnitCStartCrossWriterFirstErrorIdentity uses actual Write calls in temporal order.
func TestUnitCStartCrossWriterFirstErrorIdentity(t *testing.T) {
	e1 := errors.New("first writer failure")
	e2 := errors.New("second writer failure")
	recorder := &startOutputRecorder{}
	errSink := &unitCScriptSink{steps: []unitCScriptWriteStep{{count: 0, err: e1}}}
	outSink := &unitCScriptSink{steps: []unitCScriptWriteStep{{count: 0, err: e2}}}
	errOut := newRecordingWriter(errSink, recorder)
	out := newRecordingWriter(outSink, recorder)
	if _, err := errOut.Write([]byte("diagnostic")); !errors.Is(err, e1) {
		t.Fatalf("errOut=%v want e1", err)
	}
	if _, err := out.Write([]byte("output")); !errors.Is(err, e2) {
		t.Fatalf("out=%v want e2", err)
	}
	got := startOutputError(nil, recorder, out, errOut)
	if !errors.Is(got, e1) || errors.Is(got, e2) {
		t.Fatalf("got=%v want first e1 only", got)
	}
	if len(errSink.calls) != 1 || string(errSink.calls[0]) != "diagnostic" || len(outSink.calls) != 1 || string(outSink.calls[0]) != "output" {
		t.Fatalf("actual calls errOut=%q out=%q", errSink.calls, outSink.calls)
	}
	if _, err := out.Write([]byte("later")); err != nil {
		t.Fatalf("later successful write=%v", err)
	}
	if !errors.Is(recorder.err, e1) || errors.Is(recorder.err, e2) {
		t.Fatalf("recorder changed after later write: %v", recorder.err)
	}
}

// TestUnitCStartWriterShortWriteBoundaries distinguishes raw recorder and safeWriter contracts.
func TestUnitCStartWriterShortWriteBoundaries(t *testing.T) {
	t.Run("raw-positive", func(t *testing.T) {
		recorder := &startOutputRecorder{}
		raw := newRecordingWriter(&unitCScriptSink{steps: []unitCScriptWriteStep{{count: 2}}}, recorder)
		n, err := raw.Write([]byte("prompt"))
		if n != 2 || !errors.Is(err, io.ErrShortWrite) || !errors.Is(recorder.err, io.ErrShortWrite) {
			t.Fatalf("n=%d err=%v recorded=%v", n, err, recorder.err)
		}
	})
	t.Run("raw-zero", func(t *testing.T) {
		recorder := &startOutputRecorder{}
		raw := newRecordingWriter(&unitCScriptSink{steps: []unitCScriptWriteStep{{count: 0}}}, recorder)
		n, err := raw.Write([]byte("prompt"))
		if n != 0 || !errors.Is(err, io.ErrShortWrite) || !errors.Is(recorder.err, io.ErrShortWrite) {
			t.Fatalf("n=%d err=%v recorded=%v", n, err, recorder.err)
		}
	})
	t.Run("raw-error-preserved", func(t *testing.T) {
		sentinel := errors.New("raw error")
		raw := newRecordingWriter(&unitCScriptSink{steps: []unitCScriptWriteStep{{count: 2, err: sentinel}}}, &startOutputRecorder{})
		n, err := raw.Write([]byte("prompt"))
		if n != 2 || !errors.Is(err, sentinel) || errors.Is(err, io.ErrShortWrite) {
			t.Fatalf("n=%d err=%v", n, err)
		}
	})
	t.Run("safe-positive-short-retries", func(t *testing.T) {
		target := &unitCScriptSink{steps: []unitCScriptWriteStep{{count: 2}, {count: 4}}}
		writer := newSafeWriter(target)
		if _, err := writer.Write([]byte("prompt")); err != nil {
			t.Fatalf("safeWriter error=%v", err)
		}
		if len(target.calls) != 2 || string(target.calls[0]) != "prompt" || string(target.calls[1]) != "ompt" {
			t.Fatalf("safeWriter calls=%q", target.calls)
		}
	})
	t.Run("safe-zero-is-short-write", func(t *testing.T) {
		target := &unitCScriptSink{steps: []unitCScriptWriteStep{{count: 0}}}
		if _, err := newSafeWriter(target).Write([]byte("prompt")); !errors.Is(err, io.ErrShortWrite) {
			t.Fatalf("safeWriter error=%v want io.ErrShortWrite", err)
		}
	})
}

func TestUnitCStartFinalResultRenderFaultPreservesCommand(t *testing.T) {
	for _, tc := range []struct {
		name    string
		persist bool
	}{
		{name: "once", persist: false},
		{name: "persistent", persist: true},
	} {
		if !t.Run(tc.name, func(t *testing.T) {
			sentinel := errors.New("unit-c-final-render-" + tc.name)
			d := launchUnitC10Driver(t)
			d.expectedErr = sentinel
			d.tracePhase, d.traceMode, d.traceStep = "final-render", tc.name, "revision-readiness"
			d.advanceToField(t, 3)
			start := c10Transcript("", "output")
			if d.out.String() != start || d.errOut.String() != "" || d.pending == nil || d.pending.n != 5 {
				t.Fatalf("revision readiness changed state: %s", d.trace())
			}
			baseline, baselineIntents := d.api.snapshot()
			d.baseline, d.baselineIntents = baseline, len(baselineIntents)
			d.outGate.arm(nil, false)
			d.answer(t, "revision-1\n")
			ack := d.waitAttempt(t, d.outGate)
			const wantAck = "command submitted: unit-c-command; use status unit-c-command to query\n"
			if ack.Text != wantAck || ack.Stage != "output" || ack.Err != nil {
				t.Fatalf("ack=%+v want text=%q trace=%s", ack, wantAck, d.trace())
			}
			counts, intents := d.api.snapshot()
			if delta := unitCAPIAdd(baseline, counts); delta != (unitCAPICounts{Capability: 1, Admit: 1}) || len(intents)-len(baselineIntents) != 1 || counts.Command != baseline.Command {
				t.Fatalf("ack boundary delta=%+v intents=%d counts=%+v trace=%s", unitCAPIAdd(baseline, counts), len(intents)-len(baselineIntents), counts, d.trace())
			}
			d.outGate.arm(sentinel, tc.persist)
			d.outGate.reply(ack, nil)
			final := d.waitAttempt(t, d.outGate)
			const wantFinal = "CommandID: unit-c-command\nStatus: finished\nDeliveryBoundary: \nEffectCertainty: \nErrorCode: \n"
			if final.Text != wantFinal || final.Stage != "output" || final.Err != sentinel {
				t.Fatalf("final=%+v want text=%q trace=%s", final, wantFinal, d.trace())
			}
			d.traceStep = "final-attempt-before-reply"
			counts, intents = d.api.snapshot()
			wantBeforeReply := start + wantAck
			if d.out.String() != wantBeforeReply || d.errOut.String() != "" {
				t.Fatalf("final pre-reply transcript out=%q want=%q errOut=%q trace=%s", d.out.String(), wantBeforeReply, d.errOut.String(), d.trace())
			}
			if got := unitCAPIAdd(baseline, counts); got != (unitCAPICounts{Capability: 1, Command: 1, Admit: 1}) || len(intents)-len(baselineIntents) != 1 {
				t.Fatalf("final pre-reply delta=%+v intents=%d trace=%s", got, len(intents)-len(baselineIntents), d.trace())
			}
			d.outGate.reply(final, sentinel)
			if got := d.waitRunner(t); got != sentinel || !errors.Is(got, sentinel) {
				t.Fatalf("runner=%v want=%v trace=%s", got, sentinel, d.trace())
			}
			counts, intents = d.api.snapshot()
			wantDelta := unitCAPICounts{Capability: 1, Command: 1, Admit: 1}
			if got := unitCAPIAdd(baseline, counts); got != wantDelta || len(intents)-len(baselineIntents) != 1 {
				t.Fatalf("delta=%+v want=%+v intents=%d trace=%s", got, wantDelta, len(intents)-len(baselineIntents), d.trace())
			}
			if got := d.out.String(); got != start+wantAck {
				t.Fatalf("transcript=%q want=%q trace=%s", got, start+wantAck, d.trace())
			}
			if got := d.errOut.String(); got != "" {
				t.Fatalf("errOut=%q trace=%s", got, d.trace())
			}
			attempts, armed := d.outGate.snapshot()
			if len(attempts) != 2 || armed != tc.persist || attempts[0].Text != wantAck || attempts[1].Text != wantFinal {
				t.Fatalf("gate attempts=%+v armed=%t trace=%s", attempts, armed, d.trace())
			}
		}) {
			return
		}
	}
}
