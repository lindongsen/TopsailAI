package tui

import (
	"context"
	"errors"
	"io"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// unitCBatch2Run publishes a cached result only through done.
type unitCBatch2Run struct {
	done chan struct{}
	err  error
}

// unitCBatch2WatcherFacts is detached only under the ledger lock.
type unitCBatch2WatcherFacts struct {
	entries, releases, returns, exits int
	beforeRelease                     bool
	joined                            bool // Diagnostic only.
}

// unitCBatch2WatcherLedger binds callback release and exit publication.
type unitCBatch2WatcherLedger struct {
	mu               sync.Mutex
	facts            unitCBatch2WatcherFacts
	entered          chan struct{}
	releaseRequested chan struct{}
	returned         chan struct{}
	exitObserved     chan struct{}
	releaseOnce      sync.Once
}

// newUnitCBatch2WatcherLedger creates one callback ownership lease.
func newUnitCBatch2WatcherLedger() *unitCBatch2WatcherLedger {
	return &unitCBatch2WatcherLedger{
		entered: make(chan struct{}), releaseRequested: make(chan struct{}),
		returned: make(chan struct{}), exitObserved: make(chan struct{}),
	}
}

// beforeDone publishes entry before blocking and return before deferred Done.
func (l *unitCBatch2WatcherLedger) beforeDone() {
	l.mu.Lock()
	l.facts.entries++
	if l.facts.entries == 1 {
		close(l.entered)
	}
	l.mu.Unlock()
	<-l.releaseRequested
	l.mu.Lock()
	l.facts.returns++
	if l.facts.returns == 1 {
		close(l.returned)
	}
	l.mu.Unlock()
}

// release hands back callback ownership exactly once.
func (l *unitCBatch2WatcherLedger) release() {
	l.releaseOnce.Do(func() {
		l.mu.Lock()
		l.facts.releases++
		close(l.releaseRequested)
		l.mu.Unlock()
	})
}

// afterWait captures actual causal return, not a racy watcherDone bool claim.
func (l *unitCBatch2WatcherLedger) afterWait(joined bool) {
	l.mu.Lock()
	l.facts.exits++
	l.facts.joined = joined
	l.facts.beforeRelease = l.facts.beforeRelease ||
		l.facts.releases != 1 || l.facts.returns != 1
	if l.facts.exits == 1 {
		close(l.exitObserved)
	}
	l.mu.Unlock()
}

// snapshot detaches all mutable facts under one mutex.
func (l *unitCBatch2WatcherLedger) snapshot() unitCBatch2WatcherFacts {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.facts
}

// assertReleasedOrder runs only in the controlling test goroutine.
func (l *unitCBatch2WatcherLedger) assertReleasedOrder(t *testing.T) {
	t.Helper()
	f := l.snapshot()
	// B2_WATCHER_EXIT_LEDGER: detached observation sensitivity seam.
	if f.entries != 1 || f.releases != 1 || f.returns != 1 || f.exits != 1 || f.beforeRelease {
		t.Fatalf("C16 watcher barrier: facts=%+v", f)
	}
}

// unitCBatch2ReadEvent observes a real inner Read return, not channel enqueue.
type unitCBatch2ReadEvent struct {
	ordinal int
	n       int
	err     error
	text    string
}

// unitCBatch2ReadObserver retains ownership and exposes the final delivery seam.
type unitCBatch2ReadObserver struct {
	inner          *unitCTicketReader
	calls          int // Only the single reader worker accesses calls.
	finalOrdinal   int
	onFinal        func()
	finalHit       chan struct{}
	events         chan unitCBatch2ReadEvent
	closeReady     chan struct{}
	closeReadyOnce sync.Once
}

// Read cancels at final answer delivery before bufio can consume the bytes.
func (r *unitCBatch2ReadObserver) Read(p []byte) (int, error) {
	r.calls++
	ordinal := r.calls
	n, err := r.inner.Read(p)
	if ordinal == r.finalOrdinal && n > 0 && err == nil {
		r.onFinal()
		close(r.finalHit)
	}
	r.events <- unitCBatch2ReadEvent{ordinal: ordinal, n: n, err: err, text: string(p[:n])}
	return n, err
}

// Close preserves the production io.Closer capability of the concrete input.
func (r *unitCBatch2ReadObserver) Close() error {
	if r.closeReady != nil {
		<-r.closeReady
	}
	return r.inner.Close()
}

// releaseClose completes explicit quit/EOF cooperation before owned Close.
func (r *unitCBatch2ReadObserver) releaseClose() {
	if r.closeReady != nil {
		r.closeReadyOnce.Do(func() { close(r.closeReady) })
	}
}

// unitCBatch2Deadline preserves real deadline errors and synchronizes installed children.
type unitCBatch2Deadline struct {
	*unitCDeadlineGate
	mu        sync.Mutex
	next      int
	callbacks map[int]func()
}

// newUnitCBatch2Deadline creates a candidate-local cancellation registration adapter.
func newUnitCBatch2Deadline() *unitCBatch2Deadline {
	return &unitCBatch2Deadline{unitCDeadlineGate: newUnitCDeadlineGate(), callbacks: make(map[int]func())}
}

// AfterFunc registers derived context cancellation without a propagation goroutine.
func (g *unitCBatch2Deadline) AfterFunc(f func()) func() bool {
	g.mu.Lock()
	if g.Err() != nil {
		g.mu.Unlock()
		go f()
		return func() bool { return false }
	}
	g.next++
	id := g.next
	g.callbacks[id] = f
	g.mu.Unlock()
	return func() bool {
		g.mu.Lock()
		defer g.mu.Unlock()
		_, pending := g.callbacks[id]
		delete(g.callbacks, id)
		return pending
	}
}

// Arm publishes a real expired deadline then completes every registered propagation.
func (g *unitCBatch2Deadline) Arm() {
	g.mu.Lock()
	g.unitCDeadlineGate.Arm()
	callbacks := g.callbacks
	g.callbacks = make(map[int]func())
	g.mu.Unlock()
	for _, callback := range callbacks {
		callback()
	}
}

// unitCBatch2Config installs seams before any worker starts.
type unitCBatch2Config struct {
	mode         string
	closeInput   bool
	finalOrdinal int
}

// unitCBatch2Driver owns one bounded interactive lifecycle.
type unitCBatch2Driver struct {
	reader          *unitCTicketReader
	observer        *unitCBatch2ReadObserver
	output, errors  *unitCStageWriter
	outGate         *unitCWriteGate
	api             *unitCAPI
	run             *unitCBatch2Run
	parent          context.Context
	cancel          context.CancelFunc
	gate            *unitCBatch2Deadline
	interrupt       chan os.Signal
	ledger          *unitCBatch2WatcherLedger
	pending         *unitCReadTicket
	baseline        unitCAPICounts
	baselineIntents int
	ready           string
}

// newUnitCBatch2Driver preserves ordinary matrix callers.
func newUnitCBatch2Driver(t *testing.T, mode string, closeInput bool) *unitCBatch2Driver {
	t.Helper()
	return newUnitCBatch2Configured(t, unitCBatch2Config{mode: mode, closeInput: closeInput})
}

// newUnitCBatch2Configured installs hooks and recovery responsibility before launch.
func newUnitCBatch2Configured(t *testing.T, cfg unitCBatch2Config) *unitCBatch2Driver {
	t.Helper()
	parent, cancel := context.WithCancel(context.Background())
	gate := newUnitCBatch2Deadline()
	var ctx context.Context = parent
	if cfg.mode == "deadline" {
		ctx = gate
	}
	d := &unitCBatch2Driver{
		reader: newUnitCTicketReader(), output: &unitCStageWriter{changed: make(chan struct{}, 1)},
		errors: &unitCStageWriter{changed: make(chan struct{}, 1)}, outGate: newUnitCWriteGate(),
		api: newUnitCAPI(), run: &unitCBatch2Run{done: make(chan struct{})}, parent: ctx, cancel: cancel, gate: gate,
		interrupt: make(chan os.Signal, 1), ledger: newUnitCBatch2WatcherLedger(),
	}
	d.observer = &unitCBatch2ReadObserver{inner: d.reader, finalOrdinal: cfg.finalOrdinal,
		finalHit: make(chan struct{}), events: make(chan unitCBatch2ReadEvent, 32), onFinal: cancel}
	if cfg.mode == "deadline" {
		d.observer.onFinal = gate.Arm
	}
	if cfg.mode == "interrupt" && cfg.closeInput {
		d.observer.closeReady = make(chan struct{})
	}
	options := InteractiveOptions{CloseInput: cfg.closeInput, Interrupt: d.interrupt,
		watcherBeforeDone: d.ledger.beforeDone, watcherExit: d.ledger.afterWait}
	t.Cleanup(func() {
		d.observer.releaseClose()
		d.cancel()
		d.gate.Arm()
		d.outGate.abort()
		d.ledger.release()
		_ = d.reader.Close()
		waitClosed(t, d.run.done, "C16 cleanup join")
	})
	go func() {
		d.run.err = RunInteractive(ctx, d.api, d.observer, &unitC10Writer{stage: "output", base: d.output, gate: d.outGate}, d.errors, options)
		close(d.run.done)
	}()
	return d
}

// next obtains an addressed Read; its watchdog is diagnostic only.
func (d *unitCBatch2Driver) next(t *testing.T) unitCReadTicket {
	t.Helper()
	select {
	case ticket := <-d.reader.entered:
		return ticket
	case <-time.After(3 * time.Second):
		t.Fatal("C16 input ticket did not arrive")
		return unitCReadTicket{}
	}
}

// reply supplies exactly one line to exactly one Read.
func (d *unitCBatch2Driver) reply(t *testing.T, ticket unitCReadTicket, line string, err error) {
	t.Helper()
	if got := unitCReply(ticket, line, err); got != nil {
		t.Fatal(got)
	}
}

// unitCBatch2ReadyText pins the entire independent prompt transcript.
func unitCBatch2ReadyText(field startDraftField) string {
	want := c10Transcript("", "prompt")
	for current := startFieldEndpoint; current <= field; current++ {
		want += unitCFieldToken(current)
	}
	return want
}

// awaitExactOutput is awakened by actual writes, never by timed polling.
func awaitExactOutput(t *testing.T, output *unitCStageWriter, want string) {
	t.Helper()
	for {
		got := output.String()
		if got == want {
			return
		}
		if !strings.HasPrefix(want, got) {
			t.Fatalf("C16 readiness: output=%q want=%q", got, want)
		}
		<-output.changed
	}
}

// startup stops with the target prompt complete and its Read unanswered.
func (d *unitCBatch2Driver) startup(t *testing.T, field startDraftField) {
	t.Helper()
	d.reply(t, d.next(t), "start\n", nil)
	answers := []string{"endpoint-1\n", "resource-1\n", "profile-1\n"}
	for current := startFieldEndpoint; current < field; current++ {
		d.reply(t, d.next(t), answers[current], nil)
	}
	want := unitCBatch2ReadyText(field)
	awaitExactOutput(t, d.output, want)
	ticket := d.next(t)
	if ticket.n != int(field)+2 {
		t.Fatalf("C16 readiness: ticket=%d want=%d", ticket.n, int(field)+2)
	}
	d.pending = &ticket
	d.ready = want
	// B2_AFTER_READY: detached observation sensitivity seam.
	if d.output.String() != want || len(ticket.reply) != 0 {
		t.Fatal("C16 readiness: target changed or answered")
	}
	counts, intents := d.api.snapshot()
	d.baseline = counts
	d.baselineIntents = len(intents)
	t.Logf("readiness field=%s ordinal=%d unanswered=true", startFieldName(field), ticket.n)
}

// holdWizardHelp freezes execution while command cancel is installed.
func (d *unitCBatch2Driver) holdWizardHelp(t *testing.T) unitCWriteAttempt {
	t.Helper()
	d.outGate.arm(nil, false)
	ticket := *d.pending
	d.pending = nil
	d.reply(t, ticket, "help\n", nil)
	attempt := <-d.outGate.hit
	want, stage := c10ExpectedWrite("help")
	if attempt.Text != want || attempt.Stage != stage {
		t.Fatalf("C16 priority: actual help attempt=%+v", attempt)
	}
	return attempt
}

// processedInterrupt observes actual controller processing, not signal buffering.
func (d *unitCBatch2Driver) processedInterrupt() {
	d.interrupt <- os.Interrupt
	<-d.ledger.entered
}

// supplyEOF delivers a real terminal Read and verifies the observer receipt.
func (d *unitCBatch2Driver) supplyEOF(t *testing.T, ticket unitCReadTicket) {
	t.Helper()
	d.reply(t, ticket, "", io.EOF)
	for {
		event := <-d.observer.events
		if event.ordinal != ticket.n {
			continue
		}
		if event.n != 0 || event.err != io.EOF {
			t.Fatalf("C16 priority: EOF receipt=%+v", event)
		}
		return
	}
}

// readEvent receives the detached actual return receipt for one ordinal.
func (d *unitCBatch2Driver) readEvent(ordinal int) unitCBatch2ReadEvent {
	for {
		event := <-d.observer.events
		if event.ordinal == ordinal {
			return event
		}
	}
}

// assertUnchanged rejects any of the seven business deltas or new intents.
func (d *unitCBatch2Driver) assertUnchanged(t *testing.T) {
	t.Helper()
	after, intents := d.api.snapshot()
	if unitCAPIAdd(d.baseline, after) != (unitCAPICounts{}) || len(intents) != d.baselineIntents {
		t.Fatalf("C16 business delta: before=%+v after=%+v intents=%d", d.baseline, after, len(intents))
	}
}

// assertTerminal checks full transcripts, watcher facts and actual production ownership.
func (d *unitCBatch2Driver) assertTerminal(t *testing.T, out, errOut string, closes int) {
	t.Helper()
	d.assertUnchanged(t)
	if d.output.String() != out || d.errors.String() != errOut {
		t.Fatalf("C16 transcript: out=%q want=%q errors=%q want=%q", d.output.String(), out, d.errors.String(), errOut)
	}
	_, got := d.reader.Counts()
	if got != closes {
		t.Fatalf("C16 command close: got=%d want=%d", got, closes)
	}
	waitClosed(t, d.ledger.exitObserved, "watcher exit")
	d.ledger.assertReleasedOrder(t)
}

// interruptContinuation keeps callback held through main continuation and quit cooperation.
func (d *unitCBatch2Driver) interruptContinuation(t *testing.T) {
	t.Helper()
	help := unitCBatch2HelpText()
	awaitExactOutput(t, d.output, d.ready+help+"workspace> ")
	awaitExactOutput(t, d.errors, "interrupted\n")
	_, closes := d.reader.Counts()
	// B2_COMMAND_CLOSE: detached pre-quit close observation.
	if closes != 0 {
		t.Fatalf("C16 command close: before quit=%d", closes)
	}
	d.assertUnchanged(t)
	d.reply(t, d.next(t), "quit\n", nil)
	d.supplyEOF(t, d.next(t))
	d.observer.releaseClose()
}

// unitCBatch2HelpText pins all successful wizard help writes, not only its first Write.
func unitCBatch2HelpText() string {
	first, _ := c10ExpectedWrite("help")
	return first + "Parameters:\n" +
		"  endpoint: endpoint ID\n  resource: compatibility resource identifier\n  --profile: launch profile ID (required)\n  --profile-revision: launch profile revision (required)\n  --folder: optional working folder; empty value is treated as omitted\n  --task: optional literal initial task text; no JSON is required\n  --json: rejected in interactive mode\nExamples:\n" +
		"  start\n" +
		"  start endpoint-1 ignored-resource --profile topsailai-main --profile-revision topsailai-v1\n" +
		`  start endpoint-1 ignored-resource --profile topsailai-main --profile-revision topsailai-v1 --task "summarize the open issues"` + "\n" +
		"Project launch: start [endpoint] selects a live adapter and project (or manual folder), then asks for the initial task. Without an endpoint argument it prints a numbered endpoint list and accepts a bare number, so no endpoint identifier has to be typed. Empty/cancel cancels. Legacy explicit --profile syntax and clients without launch queries use the endpoint/resource/profile/revision prompts; q quits, r refreshes, and help repeats guidance.\n"
}

// waitRun reads the cached result after the runner publication barrier.
func (d *unitCBatch2Driver) waitRun(t *testing.T) error {
	t.Helper()
	waitClosed(t, d.run.done, "C16 runner return")
	return d.run.err
}

// waitClosed provides a diagnostic watchdog, never a successful absence proof.
func waitClosed(t *testing.T, ch <-chan struct{}, label string) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(3 * time.Second):
		t.Fatalf("%s did not occur", label)
	}
}

// assertExactContext checks identity as well as standard error classification.
func assertExactContext(t *testing.T, got, want error) {
	t.Helper()
	if got != want || !errors.Is(got, want) {
		t.Fatalf("C16 parent priority: error=%v want exact=%v", got, want)
	}
}

// assertNoAPIActivity checks all seven counters and intents.
func assertNoAPIActivity(t *testing.T, api *unitCAPI) {
	t.Helper()
	counts, intents := api.snapshot()
	if counts != (unitCAPICounts{}) || len(intents) != 0 {
		t.Fatalf("C16 business delta: counts=%+v intents=%d", counts, len(intents))
	}
}

// unitCBatch2StartupAPI exposes actual first ListEndpoints entry, without shared fixture edits.
type unitCBatch2StartupAPI struct {
	*unitCAPI
	entered chan struct{}
}

// ListEndpoints records the allowed call and waits for actual context termination.
func (a *unitCBatch2StartupAPI) ListEndpoints(ctx context.Context) ([]protocol.Endpoint, error) {
	_, _ = a.unitCAPI.ListEndpoints(ctx)
	close(a.entered)
	<-ctx.Done()
	return nil, ctx.Err()
}
