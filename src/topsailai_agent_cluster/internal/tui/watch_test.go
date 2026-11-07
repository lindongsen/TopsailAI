package tui

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// watchStub counts inventory reads and can block or fail one read, so a test
// can prove single-flight, cancellation and failure de-duplication without
// depending on wall-clock timing.
type watchStub struct {
	interactiveStub
	mu    sync.Mutex
	calls int
	fail  error
	gate  chan struct{}
}

// GetInventory shadows the embedded stub so the watch loop is observable.
func (s *watchStub) GetInventory(ctx context.Context, id string) (protocol.InventoryReport, error) {
	s.mu.Lock()
	s.calls++
	fail := s.fail
	gate := s.gate
	perEndpoint := s.inventoryErrors[id]
	s.mu.Unlock()
	if gate != nil {
		select {
		case <-gate:
		case <-ctx.Done():
			return protocol.InventoryReport{}, ctx.Err()
		}
	}
	if fail != nil {
		return protocol.InventoryReport{}, fail
	}
	if perEndpoint != nil {
		return protocol.InventoryReport{}, perEndpoint
	}
	report, ok := s.reports[id]
	if !ok {
		return protocol.InventoryReport{}, errors.New("missing inventory")
	}
	return report, nil
}

// callCount reports how many inventory reads the loop performed.
func (s *watchStub) callCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

// setFail changes the injected failure for the next read.
func (s *watchStub) setFail(err error) {
	s.mu.Lock()
	s.fail = err
	s.mu.Unlock()
}

// newWatchStub serves the shared two-endpoint fixture.
func newWatchStub() *watchStub {
	return &watchStub{interactiveStub: *scopeStub()}
}

// watchManualTicks is an injected tick source, so no test waits on a real timer.
type watchManualTicks struct {
	ticks    chan time.Time
	mu       sync.Mutex
	releases int
}

// newWatchManualTicks builds an unbuffered source, so a tick is delivered only
// when the loop is actually waiting for one.
func newWatchManualTicks() *watchManualTicks {
	return &watchManualTicks{ticks: make(chan time.Time)}
}

// ticker satisfies WatchTicker and records release calls.
func (m *watchManualTicks) ticker(time.Duration) (<-chan time.Time, func()) {
	return m.ticks, func() {
		m.mu.Lock()
		m.releases++
		m.mu.Unlock()
	}
}

// tick delivers one tick and fails the test if the loop never receives it.
func (m *watchManualTicks) tick(t *testing.T) {
	t.Helper()
	select {
	case m.ticks <- time.Now():
	case <-time.After(2 * time.Second):
		t.Fatal("controller did not receive the tick")
	}
}

// releaseCount reports how many times the tick source was released.
func (m *watchManualTicks) releaseCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.releases
}

// waitForResult polls the controller for one published result. The controller
// publishes from its own goroutine, so the test observes completion instead of
// assuming it.
func waitForResult(t *testing.T, controller *watchController) watchResult {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if result, ok := controller.take(); ok {
			return result
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("controller published no result")
	return watchResult{}
}

// TestParseWatchArguments covers the interactive watch grammar.
func TestParseWatchArguments(t *testing.T) {
	cases := []struct {
		name     string
		rest     string
		interval time.Duration
		force    bool
		wantErr  bool
	}{
		{name: "WAT-U01 default", rest: "", interval: 5 * time.Second},
		{name: "WAT-U02 explicit seconds", rest: "2s", interval: 2 * time.Second},
		{name: "WAT-U03 sub-second rejected", rest: "500ms", wantErr: true},
		{name: "WAT-U04 zero rejected", rest: "0s", wantErr: true},
		{name: "WAT-U05 negative rejected", rest: "-1s", wantErr: true},
		{name: "WAT-U06 unparsable rejected", rest: "abc", wantErr: true},
		{name: "WAT-U07 two intervals rejected", rest: "1s 2s", wantErr: true},
		{name: "WAT-U08 force default", rest: "--force", interval: 10 * time.Second, force: true},
		{name: "WAT-U09 force below floor rejected", rest: "5s --force", wantErr: true},
		{name: "WAT-U10 force at floor", rest: "10s --force", interval: 10 * time.Second, force: true},
		{name: "WAT-U11 json rejected", rest: "--json", wantErr: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			request, err := parseWatchArguments(testCase.rest)
			if testCase.wantErr {
				if err == nil {
					t.Fatalf("rest=%q accepted, want an error", testCase.rest)
				}
				return
			}
			if err != nil {
				t.Fatalf("rest=%q error=%v", testCase.rest, err)
			}
			if request.Interval != testCase.interval || request.Force != testCase.force {
				t.Fatalf("rest=%q request=%+v, want interval=%s force=%v", testCase.rest, request, testCase.interval, testCase.force)
			}
		})
	}
}

// TestParseWatchArgumentsForceFloorNamesTheReason keeps the rejection actionable.
func TestParseWatchArgumentsForceFloorNamesTheReason(t *testing.T) {
	_, err := parseWatchArguments("5s --force")
	if err == nil || !strings.Contains(err.Error(), "10s") || !strings.Contains(err.Error(), "discovery") {
		t.Fatalf("error=%v, want the floor and its reason", err)
	}
}

// TestWatchControllerCollectsOncePerTick proves one tick performs exactly one
// collection and publishes rendered output.
func TestWatchControllerCollectsOncePerTick(t *testing.T) {
	stub := newWatchStub()
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, TableLayout{})
	defer controller.Stop()
	ticks.tick(t)
	result := waitForResult(t, controller)
	if result.err != nil {
		t.Fatalf("collection failed: %v", result.err)
	}
	if stub.callCount() != 2 {
		t.Fatalf("inventory reads=%d, want one per endpoint", stub.callCount())
	}
	if len(result.rows) != 2 {
		t.Fatalf("rows=%d, want one per endpoint", len(result.rows))
	}
	if !strings.Contains(string(result.output), "host-one") {
		t.Fatalf("rendered output missing endpoint data: %q", result.output)
	}
}

// TestWatchControllerSkipsTickWhileCollecting proves a tick that arrives during
// a collection is dropped instead of queuing an overlapping scan.
func TestWatchControllerSkipsTickWhileCollecting(t *testing.T) {
	stub := newWatchStub()
	gate := make(chan struct{})
	stub.gate = gate
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, TableLayout{})
	defer controller.Stop()
	ticks.tick(t)
	// The first collection is blocked, so the tick channel has no receiver and
	// a second tick cannot be delivered. Releasing the gate proves the loop
	// resumes with a single pending result rather than a backlog.
	close(gate)
	result := waitForResult(t, controller)
	if result.err != nil {
		t.Fatalf("collection failed: %v", result.err)
	}
	if stub.callCount() != 2 {
		t.Fatalf("inventory reads=%d, want exactly one collection", stub.callCount())
	}
}

// TestWatchControllerStopCancelsInFlightCollection proves Stop releases a
// blocked collection instead of waiting for it.
func TestWatchControllerStopCancelsInFlightCollection(t *testing.T) {
	stub := newWatchStub()
	stub.gate = make(chan struct{})
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, TableLayout{})
	ticks.tick(t)
	stopped := make(chan struct{})
	go func() {
		controller.Stop()
		close(stopped)
	}()
	select {
	case <-stopped:
	case <-time.After(2 * time.Second):
		t.Fatal("Stop did not cancel the in-flight collection")
	}
	if ticks.releaseCount() != 1 {
		t.Fatalf("tick releases=%d, want exactly one", ticks.releaseCount())
	}
}

// TestWatchControllerReportsRepeatedFailureOnce proves a permanently failing
// endpoint cannot flood the terminal on every tick.
func TestWatchControllerReportsRepeatedFailureOnce(t *testing.T) {
	stub := newWatchStub()
	stub.setFail(errors.New("endpoint unreachable"))
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, TableLayout{})
	defer controller.Stop()
	ticks.tick(t)
	first := waitForResult(t, controller)
	if first.err == nil {
		t.Fatal("expected a reported failure")
	}
	ticks.tick(t)
	// The second identical failure must publish nothing, so the pending slot
	// stays empty.
	time.Sleep(50 * time.Millisecond)
	if _, ok := controller.take(); ok {
		t.Fatal("repeated identical failure was reported again")
	}
}

// TestWatchControllerReportsRecoveryAfterFailure proves a recovered collection
// publishes success again instead of staying silent.
func TestWatchControllerReportsRecoveryAfterFailure(t *testing.T) {
	stub := newWatchStub()
	stub.setFail(errors.New("endpoint unreachable"))
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, TableLayout{})
	defer controller.Stop()
	ticks.tick(t)
	if result := waitForResult(t, controller); result.err == nil {
		t.Fatal("expected a reported failure")
	}
	stub.setFail(nil)
	ticks.tick(t)
	result := waitForResult(t, controller)
	if result.err != nil {
		t.Fatalf("recovery reported an error: %v", result.err)
	}
	if len(result.rows) == 0 {
		t.Fatal("recovery published no rows")
	}
}

// TestWatchControllerLeavesNoGoroutine proves Stop joins the loop.
func TestWatchControllerLeavesNoGoroutine(t *testing.T) {
	before := runtime.NumGoroutine()
	stub := newWatchStub()
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, TableLayout{})
	controller.Stop()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if runtime.NumGoroutine() <= before {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("goroutines=%d, want at most %d after Stop", runtime.NumGoroutine(), before)
}

// TestWatchControllerRejectsPartialCollection proves a partially failed
// collection is rejected instead of rendering an incomplete row set, because a
// shorter table would silently rebind row numbers.
func TestWatchControllerRejectsPartialCollection(t *testing.T) {
	stub := newWatchStub()
	stub.inventoryErrors = map[string]error{"endpoint-2": errors.New("adapter failed")}
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, TableLayout{})
	defer controller.Stop()
	ticks.tick(t)
	result := waitForResult(t, controller)
	if result.err == nil {
		t.Fatal("partial collection was accepted")
	}
	if len(result.rows) != 0 {
		t.Fatalf("partial collection published rows: %v", result.rows)
	}
}

// TestWatchControllerForcedModeUsesForcedCollection proves --force asks the
// Endpoint for a fresh collection instead of reading the projection.
func TestWatchControllerForcedModeUsesForcedCollection(t *testing.T) {
	stub := refreshScopeStub()
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: 10 * time.Second, Force: true}, ticks.ticker, ColorPolicy{}, TableLayout{})
	defer controller.Stop()
	ticks.tick(t)
	result := waitForResult(t, controller)
	if result.err != nil {
		t.Fatalf("forced collection failed: %v", result.err)
	}
	if len(stub.refreshCalls) != 2 {
		t.Fatalf("forced collections=%v, want one per endpoint", stub.refreshCalls)
	}
}

// TestWatchControllerProjectionModeDoesNotForce proves the default mode never
// triggers a provider discovery.
func TestWatchControllerProjectionModeDoesNotForce(t *testing.T) {
	stub := refreshScopeStub()
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, ColorPolicy{}, TableLayout{})
	defer controller.Stop()
	ticks.tick(t)
	if result := waitForResult(t, controller); result.err != nil {
		t.Fatalf("projection collection failed: %v", result.err)
	}
	if len(stub.refreshCalls) != 0 {
		t.Fatalf("projection mode forced a collection: %v", stub.refreshCalls)
	}
}

// watchEditorInput returns a deadline timeout for the first idlePolls reads, so
// the editor's idle hook is exercised without waiting on a real timer.
type watchEditorInput struct {
	reader    io.Reader
	idlePolls int
	polls     int
}

// Read reports a poll timeout until the idle budget is spent, then serves bytes.
func (f *watchEditorInput) Read(p []byte) (int, error) {
	if f.polls < f.idlePolls {
		f.polls++
		return 0, os.ErrDeadlineExceeded
	}
	return f.reader.Read(p)
}

// SetReadDeadline accepts every deadline, so the poll loop is the only timing.
func (f *watchEditorInput) SetReadDeadline(time.Time) error { return nil }

// fakeWatchSession records Idle and Stop calls and returns injected payloads.
type fakeWatchSession struct {
	mu       sync.Mutex
	payloads [][]byte
	idleErr  error
	idles    int
	stops    int
}

// Idle returns the next injected payload.
func (f *fakeWatchSession) Idle() ([]byte, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.idles++
	if f.idleErr != nil {
		return nil, f.idleErr
	}
	if len(f.payloads) == 0 {
		return nil, nil
	}
	payload := f.payloads[0]
	f.payloads = f.payloads[1:]
	return payload, nil
}

// Stop records the stop request.
func (f *fakeWatchSession) Stop() {
	f.mu.Lock()
	f.stops++
	f.mu.Unlock()
}

// counts reports the observed Idle and Stop calls.
func (f *fakeWatchSession) counts() (int, int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.idles, f.stops
}

// TestReadLineWithWatchAppliesRefreshWhileIdle proves a tick with no keypress
// prints the refresh and redraws the prompt.
func TestReadLineWithWatchAppliesRefreshWhileIdle(t *testing.T) {
	input := &watchEditorInput{reader: strings.NewReader("help\r"), idlePolls: 1}
	var out strings.Builder
	editor := NewTerminalEditor(input, &out, func() int { return 40 }, func() (func() error, error) { return func() error { return nil }, nil })
	watch := &fakeWatchSession{payloads: [][]byte{[]byte("row one\nrow two\n")}}
	line, overflow, err := editor.ReadLineWithWatch(context.Background(), "workspace> ", true, 64, watch)
	if err != nil || overflow || line != "help" {
		t.Fatalf("line=%q overflow=%v err=%v", line, overflow, err)
	}
	idles, stops := watch.counts()
	if idles == 0 {
		t.Fatal("idle hook never ran")
	}
	if stops != 1 {
		t.Fatalf("stops=%d, want the loop stopped on the first key", stops)
	}
	if !strings.Contains(out.String(), "row one\r\nrow two\r\n") {
		t.Fatalf("refresh payload was not printed with CRLF: %q", out.String())
	}
	if !strings.Contains(out.String(), "auto-refresh stopped") {
		t.Fatalf("stop was not announced: %q", out.String())
	}
}

// TestReadLineWithWatchStopsBeforeApplyingKey proves the first key stops the
// loop before it is applied, so the key is never lost.
func TestReadLineWithWatchStopsBeforeApplyingKey(t *testing.T) {
	input := &watchEditorInput{reader: strings.NewReader("ab\r"), idlePolls: 1}
	var out strings.Builder
	editor := NewTerminalEditor(input, &out, func() int { return 40 }, func() (func() error, error) { return func() error { return nil }, nil })
	watch := &fakeWatchSession{}
	line, _, err := editor.ReadLineWithWatch(context.Background(), "workspace> ", true, 64, watch)
	if err != nil || line != "ab" {
		t.Fatalf("line=%q err=%v", line, err)
	}
	if _, stops := watch.counts(); stops != 1 {
		t.Fatalf("stops=%d, want exactly one", stops)
	}
}

// TestReadLineWithWatchPreservesBuffer proves a refresh does not disturb the
// partially typed buffer or the cursor.
func TestReadLineWithWatchPreservesBuffer(t *testing.T) {
	input := &watchEditorInput{reader: strings.NewReader("abc\x02X\r"), idlePolls: 1}
	var out strings.Builder
	editor := NewTerminalEditor(input, &out, func() int { return 40 }, func() (func() error, error) { return func() error { return nil }, nil })
	watch := &fakeWatchSession{payloads: [][]byte{[]byte("table\n")}}
	line, _, err := editor.ReadLineWithWatch(context.Background(), "workspace> ", true, 64, watch)
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	// Ctrl-B moves left, so X lands before the final character.
	if line != "abXc" {
		t.Fatalf("line=%q, want the buffer preserved across the refresh", line)
	}
}

// TestReadLineWithWatchReturnsRefreshFailure proves a refresh write failure is
// returned instead of swallowed.
func TestReadLineWithWatchReturnsRefreshFailure(t *testing.T) {
	sentinel := errors.New("refresh write failed")
	input := &watchEditorInput{reader: strings.NewReader("x\r"), idlePolls: 1}
	editor := NewTerminalEditor(input, exampleFailureWriter{err: sentinel}, func() int { return 40 }, func() (func() error, error) { return func() error { return nil }, nil })
	watch := &fakeWatchSession{payloads: [][]byte{[]byte("example: table\n")}}
	if _, _, err := editor.ReadLineWithWatch(context.Background(), "workspace> ", true, 64, watch); !errors.Is(err, sentinel) {
		t.Fatalf("err=%v, want the injected failure", err)
	}
}

// TestReadLineWithoutWatchIsUnchanged proves the plain read path never touches
// the watch seam.
func TestReadLineWithoutWatchIsUnchanged(t *testing.T) {
	input := &watchEditorInput{reader: strings.NewReader("help\r"), idlePolls: 1}
	var out strings.Builder
	editor := NewTerminalEditor(input, &out, func() int { return 40 }, func() (func() error, error) { return func() error { return nil }, nil })
	line, _, err := editor.ReadLine(context.Background(), "workspace> ", true, 64)
	if err != nil || line != "help" {
		t.Fatalf("line=%q err=%v", line, err)
	}
	if strings.Contains(out.String(), "auto-refresh") {
		t.Fatalf("plain read announced auto-refresh: %q", out.String())
	}
}

// TestToCRLFConvertsBareNewlines proves raw-mode output returns to column zero.
func TestToCRLFConvertsBareNewlines(t *testing.T) {
	cases := []struct{ in, want string }{
		{"a\nb", "a\r\nb"},
		{"a\r\nb", "a\r\nb"},
		{"\n", "\r\n"},
		{"plain", "plain"},
	}
	for _, testCase := range cases {
		if got := string(toCRLF([]byte(testCase.in))); got != testCase.want {
			t.Fatalf("toCRLF(%q)=%q, want %q", testCase.in, got, testCase.want)
		}
	}
}

// watchRecordingReader is a WatchLineReader that records the watch session it
// received, so a REPL test can prove the loop was armed and then stopped.
type watchRecordingReader struct {
	lines    []string
	mu       sync.Mutex
	sessions []WatchSession
	prompts  []string
}

// ReadLineWithWatch records the session and returns the next queued line.
func (r *watchRecordingReader) ReadLineWithWatch(_ context.Context, prompt string, _ bool, _ int, watch WatchSession) (string, bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.sessions = append(r.sessions, watch)
	r.prompts = append(r.prompts, prompt)
	if len(r.lines) == 0 {
		return "", false, io.EOF
	}
	line := r.lines[0]
	r.lines = r.lines[1:]
	return line, false, nil
}

// recorded returns the sessions and prompts observed so far.
func (r *watchRecordingReader) recorded() ([]WatchSession, []string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]WatchSession(nil), r.sessions...), append([]string(nil), r.prompts...)
}

// runWatchREPL drives the REPL with an armed watch reader. ReadLine delegates to
// the same reader with no watch, mirroring production where both seams are the
// same terminal editor.
func runWatchREPL(t *testing.T, stub InteractiveAPI, lines []string, ticks WatchTicker) (string, string, *watchRecordingReader) {
	t.Helper()
	reader := &watchRecordingReader{lines: lines}
	var out, diagnostics strings.Builder
	options := InteractiveOptions{
		ReadLine: func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
			return reader.ReadLineWithWatch(ctx, prompt, history, limit, nil)
		},
		WatchReader: reader,
		Ticks:       ticks,
	}
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, options); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	return out.String(), diagnostics.String(), reader
}

// TestInteractiveWatchArmsTheLoop proves watch prints its status line and arms
// exactly one loop for the following prompt, and that the intent is consumed so
// a later prompt does not silently re-arm it.
func TestInteractiveWatchArmsTheLoop(t *testing.T) {
	stub := newWatchStub()
	out, diagnostics, reader := runWatchREPL(t, stub, []string{"watch", "list", "quit"}, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(out, "auto-refresh: 5s projection (any key stops)") {
		t.Fatalf("status line missing: %q", out)
	}
	sessions, _ := reader.recorded()
	if len(sessions) != 3 {
		t.Fatalf("prompts=%d, want three", len(sessions))
	}
	if sessions[0] != nil {
		t.Fatal("a loop was armed before watch was requested")
	}
	if sessions[1] == nil {
		t.Fatal("watch did not arm a loop for the following prompt")
	}
	if sessions[2] != nil {
		t.Fatal("watch re-armed itself on a later prompt")
	}
}

// TestInteractiveWatchForceRequiresRefresher proves --force fails closed when
// the client cannot force a collection.
func TestInteractiveWatchForceRequiresRefresher(t *testing.T) {
	stub := newWatchStub()
	out, diagnostics, reader := runWatchREPL(t, stub, []string{"watch --force", "quit"}, nil)
	if !strings.Contains(diagnostics, "forced collection") {
		t.Fatalf("diagnostics=%q, want a forced-collection rejection", diagnostics)
	}
	if strings.Contains(out, "auto-refresh:") {
		t.Fatalf("rejected watch still armed a loop: %q", out)
	}
	sessions, _ := reader.recorded()
	for _, session := range sessions {
		if session != nil {
			t.Fatal("rejected watch armed a loop")
		}
	}
}

// TestInteractiveWatchForceArmsWithRefresher proves --force arms when the client
// supports forced collection.
func TestInteractiveWatchForceArmsWithRefresher(t *testing.T) {
	stub := refreshScopeStub()
	out, diagnostics, reader := runWatchREPL(t, stub, []string{"watch --force", "quit"}, nil)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if !strings.Contains(out, "auto-refresh: 10s forced collection (any key stops)") {
		t.Fatalf("status line missing: %q", out)
	}
	sessions, _ := reader.recorded()
	if len(sessions) < 2 || sessions[1] == nil {
		t.Fatal("--force did not arm a loop")
	}
}

// TestInteractiveWatchRejectsSessionScope proves the scope matrix refuses watch
// in session scope, because a forced refresh can invalidate the pinned session.
func TestInteractiveWatchRejectsSessionScope(t *testing.T) {
	stub := newWatchStub()
	out, diagnostics, _ := runWatchREPL(t, stub, []string{"cd endpoint-1/res-1", "watch", "quit"}, nil)
	if !strings.Contains(diagnostics, `command "watch" is unavailable in session scope`) {
		t.Fatalf("diagnostics=%q, want a scope rejection", diagnostics)
	}
	if strings.Contains(out, "auto-refresh:") {
		t.Fatalf("session-scope watch armed a loop: %q", out)
	}
}

// TestInteractiveWatchRequiresTickCapableReader proves a reader without the
// watch seam refuses the command instead of pretending to support it.
func TestInteractiveWatchRequiresTickCapableReader(t *testing.T) {
	stub := newWatchStub()
	var out, diagnostics strings.Builder
	lines := []string{"watch", "quit"}
	read := func(context.Context, string, bool, int) (string, bool, error) {
		if len(lines) == 0 {
			return "", false, io.EOF
		}
		line := lines[0]
		lines = lines[1:]
		return line, false, nil
	}
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(diagnostics.String(), "requires a terminal") {
		t.Fatalf("diagnostics=%q, want an explicit refusal", diagnostics.String())
	}
}

// TestReplWatchPrintsRebindingDiagnostic proves a changed row set is announced,
// so a row number never changes silently.
func TestReplWatchPrintsRebindingDiagnostic(t *testing.T) {
	state := &interactiveState{}
	state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
	controller := &watchController{pending: &watchResult{rows: []SessionRow{
		{No: 1, EndpointID: "endpoint-1", SessionID: "res-2", Generation: "generation-2"},
	}}}
	watch := &replWatch{controller: controller, state: state}
	payload, err := watch.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if !strings.Contains(string(payload), "row numbers rebound") {
		t.Fatalf("payload=%q, want a rebinding diagnostic", payload)
	}
	if state.Rows[1].SessionID != "res-2" {
		t.Fatalf("rows were not rebound: %+v", state.Rows)
	}
}

// TestReplWatchStaysSilentForIdenticalRows proves an unchanged table prints
// nothing, so a static inventory does not reprint on every tick. The fixture
// carries rendered output, because the real success path always populates it;
// a fixture without output would pass this assertion without exercising it.
func TestReplWatchStaysSilentForIdenticalRows(t *testing.T) {
	rows := []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}}
	state := &interactiveState{}
	state.setRows(rows)
	watch := &replWatch{controller: &watchController{}, state: state}
	watch.controller.pending = &watchResult{rows: rows, output: []byte("NO | SESSION_ID\n1  | res-1\n")}
	first, err := watch.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if len(first) == 0 {
		t.Fatal("the first collection printed nothing, so the operator never sees a table")
	}
	watch.controller.pending = &watchResult{rows: rows, output: []byte("NO | SESSION_ID\n1  | res-1\n")}
	second, err := watch.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if len(second) != 0 {
		t.Fatalf("payload=%q, want silence for an identical table", second)
	}
}

// TestReplWatchPrintsChangedPayload proves a changed table is printed even when
// the row identity is unchanged, because a status change must reach the operator.
func TestReplWatchPrintsChangedPayload(t *testing.T) {
	rows := []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1", State: "running"}}
	state := &interactiveState{}
	state.setRows(rows)
	watch := &replWatch{controller: &watchController{}, state: state}
	watch.controller.pending = &watchResult{rows: rows, output: []byte("1 | res-1 | running\n")}
	if _, err := watch.Idle(); err != nil {
		t.Fatalf("Idle: %v", err)
	}
	changed := []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1", State: "stopped"}}
	watch.controller.pending = &watchResult{rows: changed, output: []byte("1 | res-1 | stopped\n")}
	payload, err := watch.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if !strings.Contains(string(payload), "stopped") {
		t.Fatalf("payload=%q, want the changed table", payload)
	}
}

// TestReplWatchPrintsRebindingForIdenticalBytes proves a generation change is
// announced even when the rendered table is byte-identical, because the table
// does not display the generation and a silent rebinding would retarget a row
// number the operator is about to use.
func TestReplWatchPrintsRebindingForIdenticalBytes(t *testing.T) {
	state := &interactiveState{}
	state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
	watch := &replWatch{controller: &watchController{}, state: state}
	payload := []byte("1 | res-1\n")
	watch.controller.pending = &watchResult{rows: []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}}, output: payload}
	if _, err := watch.Idle(); err != nil {
		t.Fatalf("Idle: %v", err)
	}
	watch.controller.pending = &watchResult{rows: []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-2"}}, output: payload}
	printed, err := watch.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if !strings.Contains(string(printed), "row numbers rebound") {
		t.Fatalf("payload=%q, want a rebinding diagnostic for identical bytes", printed)
	}
}

// TestReplWatchReportsFailureAsDiagnostic proves a failed refresh never ends the
// session and never mutates row bindings.
func TestReplWatchReportsFailureAsDiagnostic(t *testing.T) {
	state := &interactiveState{}
	state.setRows([]SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1"}})
	controller := &watchController{pending: &watchResult{err: errors.New("endpoint unreachable")}}
	watch := &replWatch{controller: controller, state: state}
	payload, err := watch.Idle()
	if err != nil {
		t.Fatalf("Idle returned an error instead of a diagnostic: %v", err)
	}
	if !strings.Contains(string(payload), "auto-refresh: endpoint unreachable") {
		t.Fatalf("payload=%q, want a diagnostic line", payload)
	}
	if state.Rows[1].SessionID != "res-1" {
		t.Fatalf("a failed refresh mutated row bindings: %+v", state.Rows)
	}
}

// TestReplWatchSanitizesFailureText proves provider text cannot inject terminal
// control sequences through a diagnostic.
func TestReplWatchSanitizesFailureText(t *testing.T) {
	state := &interactiveState{}
	controller := &watchController{pending: &watchResult{err: errors.New("bad\x1b[31mred")}}
	watch := &replWatch{controller: controller, state: state}
	payload, err := watch.Idle()
	if err != nil {
		t.Fatalf("Idle: %v", err)
	}
	if strings.Contains(string(payload), "\x1b") {
		t.Fatalf("payload=%q, want control sequences stripped", payload)
	}
}

// TestSameRowIdentityComparesIdentityNotText proves a status change alone is not
// a rebinding, while a generation change is.
func TestSameRowIdentityComparesIdentityNotText(t *testing.T) {
	current := map[int]SessionRow{1: {No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1", State: "running"}}
	cases := []struct {
		name string
		rows []SessionRow
		want bool
	}{
		{name: "status change only", rows: []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-1", State: "stopped"}}, want: true},
		{name: "generation change", rows: []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-1", Generation: "generation-2"}}, want: false},
		{name: "session change", rows: []SessionRow{{No: 1, EndpointID: "endpoint-1", SessionID: "res-2", Generation: "generation-1"}}, want: false},
		{name: "row count change", rows: nil, want: false},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := sameRowIdentity(current, testCase.rows); got != testCase.want {
				t.Fatalf("sameRowIdentity=%v, want %v", got, testCase.want)
			}
		})
	}
}

// TestWatchCommandSurface proves the command is registered in exactly the two
// supported scopes and resolves through its alias.
func TestWatchCommandSurface(t *testing.T) {
	if !commandAllowed("watch", ScopeWorkspace) || !commandAllowed("watch", ScopeEndpoint) {
		t.Fatal("watch must be available in workspace and endpoint scope")
	}
	if commandAllowed("watch", ScopeSession) {
		t.Fatal("watch must not be available in session scope")
	}
	if canonicalCommandName("w") != "watch" {
		t.Fatalf("alias w resolved to %q", canonicalCommandName("w"))
	}
	workspace := strings.Join(availableCommands(ScopeWorkspace), ", ")
	if !strings.Contains(workspace, "refresh, watch, help") {
		t.Fatalf("workspace availability=%q, want watch after refresh", workspace)
	}
	endpoint := strings.Join(availableCommands(ScopeEndpoint), ", ")
	if !strings.Contains(endpoint, "refresh, watch, help") {
		t.Fatalf("endpoint availability=%q, want watch after refresh", endpoint)
	}
}

// TestWatchHelpDocumentsTheStopRule proves help states the syntax and the rule
// that any keypress stops the loop.
func TestWatchHelpDocumentsTheStopRule(t *testing.T) {
	var out strings.Builder
	if err := PrintScopedCommandHelp(&out, "watch", ScopeWorkspace); err != nil {
		t.Fatalf("PrintScopedCommandHelp: %v", err)
	}
	text := out.String()
	for _, want := range []string{"watch [interval] [--force]", "workspace, endpoint", "any keypress stops the loop"} {
		if !strings.Contains(text, want) {
			t.Fatalf("help missing %q: %q", want, text)
		}
	}
}

// layoutBuffer is a test output boundary that reports a fixed layout, so a
// render can be compared against the watch path without a real terminal.
type layoutBuffer struct {
	bytes.Buffer
	layout TableLayout
}

// TableLayout reports the fixed layout this test boundary was built with.
func (b *layoutBuffer) TableLayout() TableLayout { return b.layout }

// renderListBoundary renders the list exactly as the REPL does: straight into
// the output boundary, so trusted styling is never filtered.
func renderListBoundary(t *testing.T, stub *watchStub, filter string, color ColorPolicy, layout TableLayout) []byte {
	t.Helper()
	loaded, err := loadReports(context.Background(), stub, filter)
	if err != nil {
		t.Fatalf("loadReports: %v", err)
	}
	boundary := &layoutBuffer{layout: layout}
	if err := renderListRows(boundary, io.Discard, loaded, filter, false, tableOptionsFor(boundary, color, false, nil)); err != nil {
		t.Fatalf("renderListRows: %v", err)
	}
	return boundary.Bytes()
}

// watchRender drives one collection through the controller and returns the
// rendered bytes, so a test observes the real auto-refresh path.
func watchRender(t *testing.T, color ColorPolicy, layout TableLayout) []byte {
	t.Helper()
	stub := newWatchStub()
	ticks := newWatchManualTicks()
	controller := newWatchController(context.Background(), stub, "", watchRequest{Interval: time.Second}, ticks.ticker, color, layout)
	defer controller.Stop()
	ticks.tick(t)
	result := waitForResult(t, controller)
	if result.err != nil {
		t.Fatalf("collection failed: %v", result.err)
	}
	return result.output
}

// TestWatchRenderKeepsColorWhenEnabled proves the auto-refresh table keeps the
// styling a manual list shows. The watch table is rendered into a buffer, so a
// sanitizing writer that drops SGR silently strips every colour and leaves the
// operator with an uncoloured table.
func TestWatchRenderKeepsColorWhenEnabled(t *testing.T) {
	color := ColorPolicy{Enabled: true}
	output := watchRender(t, color, TableLayout{})
	if !bytes.Contains(output, []byte(ansiReset)) {
		t.Fatalf("watch output carries no SGR reset: %q", output)
	}
	want := renderListBoundary(t, newWatchStub(), "", color, TableLayout{})
	if !bytes.Equal(output, want) {
		t.Fatalf("watch output differs from the list render\nwatch=%q\nlist =%q", output, want)
	}
}

// TestWatchRenderStripsColorWhenDisabled proves a colourless policy still
// produces plain text, so redirected output carries no escape sequence.
func TestWatchRenderStripsColorWhenDisabled(t *testing.T) {
	output := watchRender(t, ColorPolicy{}, TableLayout{})
	if bytes.Contains(output, []byte("\x1b")) {
		t.Fatalf("watch output carries an escape sequence: %q", output)
	}
}

// TestWatchRenderKeepsStateVisible proves the state signal survives the watch
// path. Colour replaces the SESSION_STATUS column, so a watch table that loses
// colour while also omitting the column would hide the state completely.
func TestWatchRenderKeepsStateVisible(t *testing.T) {
	colored := watchRender(t, ColorPolicy{Enabled: true}, TableLayout{})
	if bytes.Contains(colored, []byte("SESSION_STATUS")) {
		t.Fatalf("coloured watch output keeps the redundant state column: %q", colored)
	}
	if !bytes.Contains(colored, []byte(ansiReset)) {
		t.Fatalf("coloured watch output lost both the state column and its colour: %q", colored)
	}
	plain := watchRender(t, ColorPolicy{}, TableLayout{})
	if !bytes.Contains(plain, []byte("SESSION_STATUS")) {
		t.Fatalf("colourless watch output dropped the only state signal: %q", plain)
	}
}

// TestWatchRenderHonoursTerminalWidth proves the auto-refresh table is fitted to
// the terminal the operator watches. The table is rendered into a buffer, so a
// renderer that reads the buffer's layout would never bound the width.
func TestWatchRenderHonoursTerminalWidth(t *testing.T) {
	const width = 40
	bounded := watchRender(t, ColorPolicy{}, TableLayout{Width: width})
	for _, line := range strings.Split(strings.TrimSuffix(string(bounded), "\n"), "\n") {
		if got := displayWidth(line); got > width {
			t.Fatalf("line width=%d exceeds %d: %q", got, width, line)
		}
	}
	unbounded := watchRender(t, ColorPolicy{}, TableLayout{})
	widest := 0
	for _, line := range strings.Split(strings.TrimSuffix(string(unbounded), "\n"), "\n") {
		if got := displayWidth(line); got > widest {
			widest = got
		}
	}
	if widest <= width {
		t.Fatalf("fixture widest line=%d never needed fitting, so the bound is unproven", widest)
	}
}

// TestWatchWriterReportsTheBoundaryLayout proves the render seam reports the
// real output layout instead of the internal buffer's, which is what lets the
// table fit the terminal.
func TestWatchWriterReportsTheBoundaryLayout(t *testing.T) {
	var buffer bytes.Buffer
	writer := &watchWriter{safeWriter: &safeWriter{target: &buffer, keepSGR: true}, layout: TableLayout{Width: 72, Full: true}}
	if got := writer.TableLayout(); got != (TableLayout{Width: 72, Full: true}) {
		t.Fatalf("layout=%+v, want the configured boundary layout", got)
	}
	if _, err := writer.Write([]byte(ansiBoldCyan + "x" + ansiReset)); err != nil {
		t.Fatalf("write: %v", err)
	}
	if err := writer.Flush(); err != nil {
		t.Fatalf("flush: %v", err)
	}
	if got := buffer.String(); got != ansiBoldCyan+"x"+ansiReset {
		t.Fatalf("kept=%q, want the trusted SGR sequence preserved", got)
	}
}

// TestWatchWriterStillStripsNonStylingEscapes proves keeping SGR does not widen
// the allow list, so a cursor or title sequence can never reach the terminal.
func TestWatchWriterStillStripsNonStylingEscapes(t *testing.T) {
	var buffer bytes.Buffer
	writer := &watchWriter{safeWriter: &safeWriter{target: &buffer, keepSGR: true}, layout: TableLayout{}}
	if _, err := writer.Write([]byte("\x1b[2J\x1b]0;title\x07" + ansiGreen + "ok" + ansiReset)); err != nil {
		t.Fatalf("write: %v", err)
	}
	if err := writer.Flush(); err != nil {
		t.Fatalf("flush: %v", err)
	}
	if got := buffer.String(); got != ansiGreen+"ok"+ansiReset {
		t.Fatalf("kept=%q, want only the styling sequence", got)
	}
}
