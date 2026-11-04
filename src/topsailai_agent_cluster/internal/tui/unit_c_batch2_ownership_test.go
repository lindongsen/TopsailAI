package tui

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"sync"
	"testing"
)

// unitCBatch2ReaderOnly deliberately does not expose the underlying closer.
type unitCBatch2ReaderOnly struct{ inner io.Reader }

// Read preserves only the declared reader capability.
func (r *unitCBatch2ReaderOnly) Read(p []byte) (int, error) { return r.inner.Read(p) }

// unitC17Write pairs a real pipe write with a completion receipt.
type unitC17Write struct {
	text string
	done chan error
}

// unitC17Source retains ownership of a controlled source or a real pipe producer.
type unitC17Source struct {
	ticket                 *unitCTicketReader
	pipe                   *io.PipeReader
	writer                 *io.PipeWriter
	jobs                   chan unitC17Write
	producerDone           chan struct{}
	entered                chan unitCReadTicket
	events                 chan unitCBatch2ReadEvent
	mu                     sync.Mutex
	calls, closes, returns int
}

// newUnitC17Source starts a bounded producer only for the actual pipe adapter.
func newUnitC17Source(kind string) *unitC17Source {
	s := &unitC17Source{events: make(chan unitCBatch2ReadEvent, 32)}
	if kind != "pipe" {
		s.ticket = newUnitCTicketReader()
		s.entered = s.ticket.entered
		return s
	}
	s.pipe, s.writer = io.Pipe()
	s.entered = make(chan unitCReadTicket, 8)
	s.jobs = make(chan unitC17Write)
	s.producerDone = make(chan struct{})
	go func() {
		defer close(s.producerDone)
		for job := range s.jobs {
			_, err := io.WriteString(s.writer, job.text)
			job.done <- err
		}
	}()
	return s
}

// Read publishes actual pipe entry and a detached actual return receipt.
func (s *unitC17Source) Read(p []byte) (int, error) {
	s.mu.Lock()
	s.calls++
	ordinal := s.calls
	s.mu.Unlock()
	var n int
	var err error
	if s.pipe != nil {
		s.entered <- unitCReadTicket{n: ordinal, capacity: len(p)}
		n, err = s.pipe.Read(p)
	} else {
		n, err = s.ticket.Read(p)
	}
	s.mu.Lock()
	s.returns++
	s.mu.Unlock()
	s.events <- unitCBatch2ReadEvent{ordinal: ordinal, n: n, err: err, text: string(p[:n])}
	return n, err
}

// Close records production authority separately from fallback test cleanup.
func (s *unitC17Source) Close() error {
	s.mu.Lock()
	s.closes++
	s.mu.Unlock()
	return s.rescue()
}

// rescue releases a source without incrementing production Close observations.
func (s *unitC17Source) rescue() error {
	if s.pipe != nil {
		return s.pipe.Close()
	}
	return s.ticket.Close()
}

// counts returns synchronized facts before any fallback cleanup.
func (s *unitC17Source) counts() (int, int, int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls, s.closes, s.returns
}

// supply pairs one addressed Read with a controlled reply or real producer write.
func (s *unitC17Source) supply(t *testing.T, ticket unitCReadTicket, text string, err error) {
	t.Helper()
	if s.pipe == nil {
		if got := unitCReply(ticket, text, err); got != nil {
			t.Fatal(got)
		}
		return
	}
	if err == io.EOF {
		_ = s.writer.Close()
		return
	}
	if err != nil || len(text) > ticket.capacity {
		t.Fatal("C17 invalid pipe supply")
	}
	job := unitC17Write{text: text, done: make(chan error, 1)}
	s.jobs <- job
	if got := <-job.done; got != nil {
		t.Fatalf("C17 producer: %v", got)
	}
}

// next returns one actual underlying Read entry.
func (s *unitC17Source) next(t *testing.T) unitCReadTicket {
	t.Helper()
	return <-s.entered
}

// receipt waits for the actual return of an addressed underlying Read.
func (s *unitC17Source) receipt(ordinal int) unitCBatch2ReadEvent {
	for {
		event := <-s.events
		if event.ordinal == ordinal {
			return event
		}
	}
}

// TestUnitCBatch2InputOwnership exercises every capability and ownership tuple.
func TestUnitCBatch2InputOwnership(t *testing.T) {
	for _, kind := range []string{"pipe", "controlled", "reader-only"} {
		for _, owned := range []bool{false, true} {
			for _, mode := range []string{"parent", "deadline", "fatal"} {
				for field := startFieldEndpoint; field <= startFieldRevision; field++ {
					t.Run(fmt.Sprintf("%s/close-%t/%s/%s", kind, owned, mode, startFieldName(field)), func(t *testing.T) {
						runUnitC17Ownership(t, kind, owned, mode, field)
					})
				}
			}
		}
	}
}

// runUnitC17Ownership owns one runner, source, watcher and optional pipe producer.
func runUnitC17Ownership(t *testing.T, kind string, owned bool, mode string, field startDraftField) {
	t.Helper()
	source := newUnitC17Source(kind)
	var input io.Reader = source
	if kind == "reader-only" {
		// B2_READER_ONLY: capability action seam.
		input = &unitCBatch2ReaderOnly{inner: source}
	}
	_, closable := input.(io.Closer)
	if closable != (kind != "reader-only") {
		t.Fatal("C17 close policy: unexpected io.Closer capability")
	}
	parent, cancel := context.WithCancel(context.Background())
	deadline := newUnitCBatch2Deadline()
	var ctx context.Context = parent
	if mode == "deadline" {
		ctx = deadline
	}
	api := newUnitCAPI()
	out := &unitCStageWriter{changed: make(chan struct{}, 1)}
	diagnostics := &unitCStageWriter{changed: make(chan struct{}, 1)}
	gate := newUnitCWriteGate()
	ledger := newUnitCBatch2WatcherLedger()
	ledger.release()
	run := &unitCBatch2Run{done: make(chan struct{})}
	t.Cleanup(func() {
		cancel()
		deadline.Arm()
		gate.abort()
		ledger.release()
		_ = source.rescue()
		if source.writer != nil {
			_ = source.writer.Close()
		}
		waitClosed(t, run.done, "C17 cleanup runner")
		if source.jobs != nil {
			close(source.jobs)
			waitClosed(t, source.producerDone, "C17 producer join")
		}
	})
	go func() {
		run.err = RunInteractive(ctx, api, input, &unitC10Writer{stage: "output", base: out, gate: gate}, diagnostics,
			InteractiveOptions{CloseInput: owned, Interrupt: make(chan os.Signal), watcherBeforeDone: ledger.beforeDone, watcherExit: ledger.afterWait})
		close(run.done)
	}()
	source.supply(t, source.next(t), "start\n", nil)
	answers := []string{"endpoint-1\n", "resource-1\n", "profile-1\n"}
	for current := startFieldEndpoint; current < field; current++ {
		source.supply(t, source.next(t), answers[current], nil)
	}
	ready := unitCBatch2ReadyText(field)
	awaitExactOutput(t, out, ready)
	pending := source.next(t)
	if pending.n != int(field)+2 {
		t.Fatalf("C17 readiness: ordinal=%d", pending.n)
	}
	baseline, intents := api.snapshot()
	sentinel := errors.New("C17 fatal help writer")
	want := error(context.Canceled)
	if mode == "fatal" {
		gate.arm(nil, false)
		source.supply(t, pending, "help\n", nil)
		attempt := <-gate.hit
		help, stage := c10ExpectedWrite("help")
		if attempt.Text != help || attempt.Stage != stage {
			t.Fatal("C17 actual help boundary mismatch")
		}
		pending = source.next(t)
		gate.reply(attempt, sentinel)
		want = sentinel
	} else if mode == "deadline" {
		deadline.Arm()
		want = context.DeadlineExceeded
	} else {
		cancel()
	}
	expectedCloses := 0
	if owned && closable {
		expectedCloses = 1
	}
	if expectedCloses == 0 {
		calls, closes, returned := source.counts()
		returnedEarly := false
		select {
		case <-run.done:
			returnedEarly = true
		default:
		}
		// B2_CLOSE_POLICY: pre-cooperation observation seam.
		if closes != 0 {
			t.Fatalf("C17 close policy: caller-owned closes=%d", closes)
		}
		if calls != pending.n || returned != calls-1 || returnedEarly {
			t.Fatalf("C17 cooperative release: calls=%d returned=%d pending=%d runner=%t", calls, returned, pending.n, returnedEarly)
		}
		source.supply(t, pending, "", io.EOF)
	}
	waitClosed(t, run.done, "C17 actual runner join")
	if run.err != want || !errors.Is(run.err, want) {
		t.Fatalf("C17 terminal cause: got=%v want exact=%v", run.err, want)
	}
	event := source.receipt(pending.n)
	if event.n != 0 || (expectedCloses == 0 && event.err != io.EOF) || (expectedCloses == 1 && event.err != io.ErrClosedPipe) {
		t.Fatalf("C17 cooperative release: actual return=%+v", event)
	}
	_, closes, _ := source.counts()
	// B2_OWNED_CLOSE: post-return observation seam.
	if closes != expectedCloses {
		t.Fatalf("C17 close policy: closes=%d want=%d", closes, expectedCloses)
	}
	if source.writer != nil && expectedCloses == 1 {
		if _, err := io.WriteString(source.writer, "peer probe\n"); err != io.ErrClosedPipe {
			t.Fatalf("C17 close policy: peer Write=%v", err)
		}
	}
	after, afterIntents := api.snapshot()
	if unitCAPIAdd(baseline, after) != (unitCAPICounts{}) || len(afterIntents) != len(intents) {
		t.Fatal("C17 business delta")
	}
	if out.String() != ready || diagnostics.String() != "" {
		t.Fatalf("C17 transcript: out=%q diagnostics=%q", out.String(), diagnostics.String())
	}
	ledger.assertReleasedOrder(t)
	t.Logf("C17 real return: source=%s owned=%t ordinal=%d readError=%v closes=%d watcher=%+v", kind, owned, pending.n, event.err, closes, ledger.snapshot())
}
