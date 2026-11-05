package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

// unitCReadReply is the addressed result of one underlying Read call.
type unitCReadReply struct {
	data []byte
	err  error
}

// unitCReadTicket identifies exactly one blocked Read invocation.
type unitCReadTicket struct {
	n        int
	capacity int
	reply    chan unitCReadReply
}

// unitCTicketReader exposes one independent ticket for every Read call.
type unitCTicketReader struct {
	mu      sync.Mutex
	calls   int
	closes  int
	closed  chan struct{}
	once    sync.Once
	entered chan unitCReadTicket
}

// newUnitCTicketReader creates a reader whose Read calls wait for addressed replies.
func newUnitCTicketReader() *unitCTicketReader {
	return &unitCTicketReader{closed: make(chan struct{}), entered: make(chan unitCReadTicket, 8)}
}

// Read publishes a ticket and accepts only that ticket's response.
func (r *unitCTicketReader) Read(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	r.mu.Lock()
	if r.closes > 0 {
		r.mu.Unlock()
		return 0, io.ErrClosedPipe
	}
	r.calls++
	ticket := unitCReadTicket{n: r.calls, capacity: len(p), reply: make(chan unitCReadReply, 1)}
	r.mu.Unlock()
	select {
	case r.entered <- ticket:
	case <-r.closed:
		return 0, io.ErrClosedPipe
	}
	select {
	case reply := <-ticket.reply:
		if len(reply.data) > len(p) {
			return 0, fmt.Errorf("ticket %d response exceeds capacity", ticket.n)
		}
		return copy(p, reply.data), reply.err
	case <-r.closed:
		return 0, io.ErrClosedPipe
	}
}

// Close releases every blocked ticket and records test-owned cleanup.
func (r *unitCTicketReader) Close() error {
	r.mu.Lock()
	r.closes++
	r.mu.Unlock()
	r.once.Do(func() { close(r.closed) })
	return nil
}

// Counts returns the number of reads and closes observed by the fixture.
func (r *unitCTicketReader) Counts() (int, int) {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.calls, r.closes
}

// unitCReply answers one ticket exactly once.
func unitCReply(ticket unitCReadTicket, data string, err error) error {
	if len(data) > ticket.capacity {
		return fmt.Errorf("ticket %d response too large", ticket.n)
	}
	select {
	case ticket.reply <- unitCReadReply{data: []byte(data), err: err}:
		return nil
	default:
		return fmt.Errorf("ticket %d already answered", ticket.n)
	}
}

// unitCStageWriter records output and notifies the driver after every write.
type unitCStageWriter struct {
	mu      sync.Mutex
	buffer  strings.Builder
	changed chan struct{}
}

// Write records a successful output write without assuming write boundaries.
func (w *unitCStageWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	_, _ = w.buffer.Write(p)
	w.mu.Unlock()
	select {
	case w.changed <- struct{}{}:
	default:
	}
	return len(p), nil
}

// String returns a detached output transcript.
func (w *unitCStageWriter) String() string {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.buffer.String()
}

// unitCFieldToken returns the independently pinned readiness token for a field.
func unitCFieldToken(field startDraftField) string {
	tokens := [...]string{
		"start: endpoint ID required (endpoint ID). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\nstart.endpoint> ",
		"start: compatibility resource identifier required (compatibility resource identifier). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\nstart.resource> ",
		"start: launch profile ID required (launch profile ID). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\nstart.profile> ",
		"start: launch profile revision required (launch profile revision). cancel/empty: cancel; q: quit; r: refresh; help: guidance; starts immediately when complete.\nstart.profile-revision> ",
	}
	return tokens[field]
}

// unitCDeadlineGate delegates a real expired WithDeadline after field readiness.
type unitCDeadlineGate struct {
	mu   sync.Mutex
	done chan struct{}
	err  error
	once sync.Once
}

// newUnitCDeadlineGate creates a stable, initially live notification context.
func newUnitCDeadlineGate() *unitCDeadlineGate { return &unitCDeadlineGate{done: make(chan struct{})} }

// Deadline reports no scheduled timer because this test adapter arms after readiness.
func (c *unitCDeadlineGate) Deadline() (time.Time, bool) { return time.Time{}, false }

// Done returns the stable deadline notification channel.
func (c *unitCDeadlineGate) Done() <-chan struct{} { return c.done }

// Err returns the delegated standard-library deadline error.
func (c *unitCDeadlineGate) Err() error { c.mu.Lock(); defer c.mu.Unlock(); return c.err }

// Value does not expose test-controlled application configuration.
func (c *unitCDeadlineGate) Value(any) any { return nil }

// Arm obtains DeadlineExceeded from a real already-expired context before notifying.
func (c *unitCDeadlineGate) Arm() {
	c.once.Do(func() {
		real, cancel := context.WithDeadline(context.Background(), time.Unix(1, 0))
		defer cancel()
		<-real.Done()
		c.mu.Lock()
		c.err = real.Err()
		c.mu.Unlock()
		close(c.done)
	})
}

// unitCReferenceRun publishes one immutable result through a reusable done barrier.
type unitCReferenceRun struct {
	done chan struct{}
	err  error
}

// unitCReferenceDriver owns synchronization; only the test goroutine mutates its fields.
type unitCReferenceDriver struct {
	reader      *unitCTicketReader
	out, errOut *unitCStageWriter
	api         *unitCAPI
	run         *unitCReferenceRun
	cancel      context.CancelFunc
	abortWriter func()
	pending     *unitCReadTicket
	next        int
	lastToken   string
	lastOffset  int
	quitSent    bool
	eofSent     bool
}

// trace snapshots all relevant state without consuming a runner result.
func (d *unitCReferenceDriver) trace() string {
	counts, intents := d.api.snapshot()
	reads, closes := d.reader.Counts()
	state := "running"
	select {
	case <-d.run.done:
		state = fmt.Sprintf("returned(%v)", d.run.err)
	default:
	}
	return fmt.Sprintf("lastToken=%q offset=%d pending=%+v reads=%d closes=%d output=%q errOut=%q counts=%+v intents=%d runner=%s quit=%t eof=%t", d.lastToken, d.lastOffset, d.pending, reads, closes, d.out.String(), d.errOut.String(), counts, len(intents), state, d.quitSent, d.eofSent)
}

// cleanup always unblocks caller-owned input too, as a test-owner failure fallback.
func (d *unitCReferenceDriver) cleanup(t *testing.T) {
	t.Helper()
	// Successful assertions must inspect production close counts BEFORE this fallback.
	d.cancel()
	_ = d.reader.Close()
	if d.abortWriter != nil {
		d.abortWriter()
	}
	timer := time.NewTimer(3 * time.Second)
	defer timer.Stop()
	select {
	case <-d.run.done:
		if t.Failed() {
			t.Log(d.trace())
		}
	case <-timer.C:
		t.Errorf("cleanup could not join runner: %s", d.trace())
	}
}

// fail emits a full trace and runs test cleanup through testing's normal failure path.
func (d *unitCReferenceDriver) fail(t *testing.T, reason string) {
	t.Helper()
	t.Fatalf("%s: %s", reason, d.trace())
}

// accept retains exactly one monotonically numbered read ticket.
func (d *unitCReferenceDriver) accept(t *testing.T, ticket unitCReadTicket) {
	t.Helper()
	if d.pending != nil || ticket.n != d.next {
		d.fail(t, "invalid ticket sequence")
	}
	d.next++
	d.pending = &ticket
}

// boundary requires the exact output transcript plus an unanswered read ticket.
func (d *unitCReferenceDriver) boundary(t *testing.T, want, token string, ordinal int) {
	t.Helper()
	timer := time.NewTimer(3 * time.Second)
	defer timer.Stop()
	for {
		if d.out.String() == want && d.pending != nil {
			if d.pending.n != ordinal {
				d.fail(t, "wrong boundary ticket ordinal")
			}
			d.lastToken, d.lastOffset = token, len(want)-len(token)
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
		case <-d.run.done:
			d.fail(t, "runner ended before boundary")
		case <-timer.C:
			d.fail(t, "boundary watchdog expired")
		}
	}
}

// initial obtains the startup transcript once; later output comparisons are exact.
func (d *unitCReferenceDriver) initial(t *testing.T) string {
	t.Helper()
	timer := time.NewTimer(3 * time.Second)
	defer timer.Stop()
	for {
		text := d.out.String()
		if strings.HasSuffix(text, "workspace> ") && strings.Count(text, "workspace> ") == 1 && d.pending != nil {
			if d.pending.n != 1 {
				d.fail(t, "initial ordinal is not one")
			}
			return text
		}
		var entered <-chan unitCReadTicket
		if d.pending == nil {
			entered = d.reader.entered
		}
		select {
		case ticket := <-entered:
			d.accept(t, ticket)
		case <-d.out.changed:
		case <-d.run.done:
			d.fail(t, "runner ended during startup")
		case <-timer.C:
			d.fail(t, "startup watchdog expired")
		}
	}
}

// answer sends one reply and forgets the ticket only after the reply is accepted.
func (d *unitCReferenceDriver) answer(t *testing.T, text string, err error) {
	t.Helper()
	if d.pending == nil {
		d.fail(t, "answer without ticket")
	}
	if e := unitCReply(*d.pending, text, err); e != nil {
		d.fail(t, e.Error())
	}
	d.pending = nil
}

// await returns the cached immutable result; repeated calls never consume a channel value.
func (d *unitCReferenceDriver) await(t *testing.T) error {
	t.Helper()
	timer := time.NewTimer(3 * time.Second)
	defer timer.Stop()
	select {
	case <-d.run.done:
		return d.run.err
	case <-timer.C:
		d.fail(t, "runner join watchdog expired")
		return nil
	}
}

// continuation waits for a NEW prompt and the precise interruption diagnostic.
func (d *unitCReferenceDriver) continuation(t *testing.T, before string, ticket int) {
	t.Helper()
	timer := time.NewTimer(3 * time.Second)
	defer timer.Stop()
	for {
		if d.out.String() == before+"workspace> " && d.errOut.String() == "interrupted\n" {
			if d.pending == nil || d.pending.n != ticket {
				d.fail(t, "interrupt lost held ticket")
			}
			return
		}
		select {
		case <-d.out.changed:
		case <-d.errOut.changed:
		case <-d.run.done:
			d.fail(t, "interrupt exited instead of continuing")
		case <-timer.C:
			d.fail(t, "interrupt continuation watchdog expired")
		}
	}
}

// finishQuit services prefetch until EOF or joined completion, never treating a wakeup as completion.
func (d *unitCReferenceDriver) finishQuit(t *testing.T) error {
	t.Helper()
	if !d.quitSent || d.pending != nil {
		d.fail(t, "EOF pumping is allowed only after quit reply")
	}
	timer := time.NewTimer(3 * time.Second)
	defer timer.Stop()
	for {
		select {
		case <-d.run.done:
			return d.run.err
		case ticket := <-d.reader.entered:
			d.accept(t, ticket)
			if d.eofSent {
				d.fail(t, "read after terminal EOF")
			}
			d.answer(t, "", io.EOF)
			d.eofSent = true
		case <-d.out.changed:
		case <-d.errOut.changed:
		case <-timer.C:
			d.fail(t, "post-quit EOF/join watchdog expired")
		}
	}
}

// newUnitCReferenceDriver registers failure cleanup before launching the runner.
func newUnitCReferenceDriver(t *testing.T, mode string) (*unitCReferenceDriver, context.Context, *unitCDeadlineGate, chan os.Signal) {
	t.Helper()
	parent, cancel := context.WithCancel(context.Background())
	gate := newUnitCDeadlineGate()
	var runParent context.Context = parent
	if mode == "deadline" {
		runParent = gate
	}
	interrupt := make(chan os.Signal, 1)
	options := InteractiveOptions{CloseInput: mode != "interrupt"}
	if mode == "interrupt" {
		options.Interrupt = interrupt
	}
	d := &unitCReferenceDriver{
		reader: newUnitCTicketReader(),
		out:    &unitCStageWriter{changed: make(chan struct{}, 1)},
		errOut: &unitCStageWriter{changed: make(chan struct{}, 1)},
		api:    newUnitCAPI(), run: &unitCReferenceRun{done: make(chan struct{})}, next: 1,
		cancel: func() {
			cancel()
			if mode == "deadline" {
				gate.Arm()
			}
		},
	}
	t.Cleanup(func() { d.cleanup(t) })
	go func() {
		d.run.err = RunInteractive(runParent, d.api, d.reader, d.out, d.errOut, options)
		close(d.run.done)
	}()
	return d, parent, gate, interrupt
}

// TestUnitCStartRunInteractiveTerminationMatrix exercises every target after proven readiness.
func TestUnitCStartRunInteractiveTerminationMatrix(t *testing.T) {
	fields := []struct{ name, answer string }{
		{"endpoint", "endpoint-1\n"}, {"resource", "resource-1\n"},
		{"profile", "profile-1\n"}, {"profile-revision", "revision-1\n"},
	}
	for index, field := range fields {
		for _, mode := range []string{"parent", "deadline", "interrupt"} {
			if !t.Run(field.name+"-"+mode, func(t *testing.T) {
				d, parent, gate, interrupt := newUnitCReferenceDriver(t, mode)
				want := d.initial(t)
				startup := want
				d.answer(t, "start\n", nil)
				for i := 0; i <= index; i++ {
					token := unitCFieldToken(startDraftField(i))
					want += token
					d.boundary(t, want, token, i+2)
					if i < index {
						d.answer(t, fields[i].answer, nil)
					}
				}
				countsBefore, intents := d.api.snapshot()
				if parent.Err() != nil || gate.Err() != nil || countsBefore.Admit != 0 || len(intents) != 0 || d.errOut.String() != "" {
					d.fail(t, "not live and unsubmitted at readiness")
				}
				reads, closes := d.reader.Counts()
				if reads != index+2 || closes != 0 {
					d.fail(t, "unexpected read/close counts at boundary")
				}
				ticket := d.pending.n
				t.Logf("READY field=%s ticket=%d ordinal=%d offset=%d", field.name, ticket, index+2, d.lastOffset)
				var got error
				switch mode {
				case "parent":
					d.cancel()
					got = d.await(t)
					if got != parent.Err() || !errors.Is(got, context.Canceled) {
						d.fail(t, "parent error identity")
					}
				case "deadline":
					gate.Arm()
					got = d.await(t)
					if got != context.DeadlineExceeded || got != gate.Err() || !errors.Is(got, context.DeadlineExceeded) {
						d.fail(t, "deadline error identity")
					}
				case "interrupt":
					interrupt <- os.Interrupt
					d.continuation(t, want, ticket)
					_, closes = d.reader.Counts()
					if closes != 0 {
						d.fail(t, "field interrupt closed caller-owned input")
					}
					d.answer(t, "quit\n", nil)
					d.quitSent = true
					got = d.finishQuit(t)
					if got != nil {
						d.fail(t, "quit result is not nil")
					}
					want += "workspace> "
				}
				after, intents := d.api.snapshot()
				if unitCAPIAdd(countsBefore, after) != (unitCAPICounts{}) || len(intents) != 0 {
					d.fail(t, "post-boundary API dispatch")
				}
				wantErr := ""
				if mode == "interrupt" {
					wantErr = "interrupted\n"
				}
				if d.out.String() != want || d.errOut.String() != wantErr {
					d.fail(t, "final exact transcript mismatch")
				}
				reads, closes = d.reader.Counts()
				if mode == "interrupt" && closes != 0 {
					d.fail(t, "caller-owned input production-closed")
				}
				if mode != "interrupt" && (closes == 0 || reads != index+2) {
					d.fail(t, "owned cleanup/read count mismatch")
				}
				t.Logf("JOIN result=%v reads=%d closes=%d API=%+v suffix=%q errOut=%q", got, reads, closes, after, strings.TrimPrefix(want, startup), wantErr)
			}) {
				return
			}
		}
	}
}

// TestUnitCStartTicketReaderSanity preserves the existing sanity entry point.
func TestUnitCStartTicketReaderSanity(t *testing.T) {
	d, parent, _, _ := newUnitCReferenceDriver(t, "parent")
	startup := d.initial(t)
	d.answer(t, "start\n", nil)
	token := unitCFieldToken(startFieldEndpoint)
	d.boundary(t, startup+token, token, 2)
	d.cancel()
	if got := d.await(t); got != parent.Err() || !errors.Is(got, context.Canceled) {
		d.fail(t, "sanity error identity")
	}
	reads, closes := d.reader.Counts()
	counts, intents := d.api.snapshot()
	if reads != 2 || closes == 0 || counts.Admit != 0 || len(intents) != 0 || d.errOut.String() != "" {
		d.fail(t, "sanity close/join contract")
	}
}

// TestUnitCReferenceExpiredDeadlineStartup verifies a genuine timer context before startup.
func TestUnitCReferenceExpiredDeadlineStartup(t *testing.T) {
	ctx, cancel := context.WithDeadline(context.Background(), time.Unix(1, 0))
	defer cancel()
	reader := newUnitCTicketReader()
	api := newUnitCAPI()
	err := RunInteractive(ctx, api, reader, io.Discard, io.Discard, InteractiveOptions{CloseInput: true})
	counts, intents := api.snapshot()
	reads, _ := reader.Counts()
	if err != context.DeadlineExceeded || reads != 0 || counts != (unitCAPICounts{}) || len(intents) != 0 {
		t.Fatalf("err=%v reads=%d counts=%+v", err, reads, counts)
	}
}

func TestUnitCStartInitialAndStartupTermination(t *testing.T) {
	parent, cancel := context.WithCancel(context.Background())
	cancel()
	reader := newUnitCTicketReader()
	api := newUnitCAPI()
	var output, diagnostics strings.Builder
	err := RunInteractive(parent, api, reader, &output, &diagnostics, InteractiveOptions{})
	reads, _ := reader.Counts()
	if !errors.Is(err, context.Canceled) || reads != 0 || output.Len() != 0 || diagnostics.Len() != 0 {
		t.Fatalf("pre-cancel result=%v reads=%d output=%q diagnostics=%q", err, reads, output.String(), diagnostics.String())
	}
}

func TestUnitCStartTerminationPriority(t *testing.T) {
	sentinel := errors.New("observed-fatal")
	err := RunInteractive(context.Background(), newUnitCAPI(), &unitCFailingReader{err: sentinel}, io.Discard, io.Discard, InteractiveOptions{})
	if !errors.Is(err, sentinel) {
		t.Fatalf("error=%v want %v", err, sentinel)
	}
}

func TestUnitCStartTerminationQueuedInputs(t *testing.T) {
	parent, cancel := context.WithCancel(context.Background())
	cancel()
	var out, diagnostics strings.Builder
	err := RunInteractive(parent, newUnitCAPI(), strings.NewReader("start\nendpoint-1\nresource-1\nprofile-1\nrevision-1\nUNKNOWN_SENTINEL\n"), &out, &diagnostics, InteractiveOptions{})
	if !errors.Is(err, context.Canceled) || strings.Contains(diagnostics.String(), "UNKNOWN_SENTINEL") {
		t.Fatalf("result=%v diagnostics=%q", err, diagnostics.String())
	}
}

func TestUnitCStartCancelAllowsNextCommand(t *testing.T) {
	var out, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), newUnitCAPI(), strings.NewReader("start\ncancel\nquit\n"), &out, &diagnostics, InteractiveOptions{}); err != nil {
		t.Fatal(err)
	}
}
