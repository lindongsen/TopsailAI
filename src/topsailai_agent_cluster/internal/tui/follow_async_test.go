package tui

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// followSettleTimeout bounds every wait for an asynchronous stream open. The open
// is a local stub call in these tests, so the real cost is one goroutine
// scheduling hop; the bound only has to be long enough to survive a loaded CI
// machine and short enough that a genuine hang fails the test instead of hanging
// the suite.
const followSettleTimeout = 2 * time.Second

// followRecorder is the accessor set every streaming stub shares. The stream is
// opened off the prompt path, so a test must wait for the record instead of
// reading it immediately after the REPL returns.
type followRecorder interface {
	followRequests() []outputRequest
	followCount() int
}

// waitFollowCount waits until the stub has recorded n opened streams. It is the
// only correct way to assert that a stream opened, because the open runs in its
// own goroutine and the REPL returns before it completes.
func waitFollowCount(t *testing.T, stub followRecorder, n int) {
	t.Helper()
	deadline := time.Now().Add(followSettleTimeout)
	for stub.followCount() < n {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %d opened streams, got %d", n, stub.followCount())
		}
		time.Sleep(time.Millisecond)
	}
}

// waitFollowRequests waits until the stub has recorded n follow requests and
// returns them, so an assertion on the request content stays exact while the
// race is removed.
func waitFollowRequests(t *testing.T, stub followRecorder, n int) []outputRequest {
	t.Helper()
	waitFollowCount(t, stub, n)
	return stub.followRequests()
}

// waitFollowIdle polls a session until it has a payload to hand the terminal. A
// start failure is recorded by the open goroutine, so the first poll can
// legitimately return nothing.
func waitFollowIdle(t *testing.T, session WatchSession) []byte {
	t.Helper()
	deadline := time.Now().Add(followSettleTimeout)
	for {
		payload, err := session.Idle()
		if err != nil {
			t.Fatalf("Idle: %v", err)
		}
		if len(payload) > 0 {
			return payload
		}
		if time.Now().After(deadline) {
			t.Fatal("timed out waiting for the session to report a start failure")
		}
		time.Sleep(time.Millisecond)
	}
}

// armedFollowCount reports how many recorded prompts carried a stream.
//
// Arming is synchronous: the REPL decides whether to arm before it draws the
// prompt, and only the transport open is asynchronous. This count is therefore
// the reliable way to assert that nothing was armed, because an opened-stream
// count is written by a goroutine and cannot prove absence.
func armedFollowCount(reader *watchRecordingReader) int {
	sessions, _ := reader.recorded()
	count := 0
	for _, session := range sessions {
		if session != nil {
			count++
		}
	}
	return count
}

// waitActionFollowRequests waits until the stub has recorded the entry tail plus
// n action tails, then returns the action tails. Entering a session arms a tail
// of its own, so the first request belongs to the scenario rather than to the
// action under test, exactly as actionFollowRequests already assumes.
func waitActionFollowRequests(t *testing.T, stub *sendFollowStub, n int) []outputRequest {
	t.Helper()
	waitFollowCount(t, stub, n+1)
	return actionFollowRequests(stub)
}

// waitAutomaticSteps waits until the stub has recorded n automatic steps and
// returns them. A step is recorded by the goroutine that opens the stream, so a
// test that reads the slice immediately after the REPL returns can see fewer
// steps than the run produced.
func waitAutomaticSteps(t *testing.T, stub interface{ automaticSteps() []string }, n int) []string {
	t.Helper()
	deadline := time.Now().Add(followSettleTimeout)
	for len(stub.automaticSteps()) < n {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %d automatic steps, got %v", n, stub.automaticSteps())
		}
		time.Sleep(time.Millisecond)
	}
	return stub.automaticSteps()
}

// settleFollowCount waits until the stub has recorded n opened streams and then
// confirms it stays at n for a short window. It is the honest form of an absence
// assertion: an open runs in its own goroutine, so reading the count once cannot
// prove that no further open is still on its way.
func settleFollowCount(t *testing.T, stub followRecorder, n int) {
	t.Helper()
	waitFollowCount(t, stub, n)
	deadline := time.Now().Add(50 * time.Millisecond)
	for time.Now().Before(deadline) {
		if stub.followCount() != n {
			t.Fatalf("streams opened=%d, want it to stay at %d", stub.followCount(), n)
		}
		time.Sleep(time.Millisecond)
	}
}

// idlePollTimeout bounds one prompt's idle polling. The stub open fails or stays
// silent immediately, so the poll only has to outlast one goroutine scheduling
// hop; a longer bound would make a silent stream slow down the whole suite.
const idlePollTimeout = 200 * time.Millisecond

// idlePollingReader is a watch reader that polls the armed session before it
// returns the queued line, which is what the real terminal editor does while it
// waits for a keypress.
//
// The poll is load-bearing for any test about an asynchronous open. The REPL
// stops the session as soon as the read returns, so a reader that returns
// immediately ends the prompt before the open goroutine has run. A start failure
// is then correctly not reported, because there is no prompt left to report to,
// and the test would be asserting a behaviour the production editor never
// exercises.
//
// The payload each prompt observed is recorded, because the poll consumes it.
// A test therefore asserts on payloadAt instead of calling Idle again, which
// would find nothing.
type idlePollingReader struct {
	*watchRecordingReader
	timeout time.Duration

	mu       sync.Mutex
	payloads [][]byte
}

// ReadLineWithWatch polls the armed session, records what it saw, then returns
// the next queued line exactly as the recording reader does.
func (r *idlePollingReader) ReadLineWithWatch(ctx context.Context, prompt string, history bool, limit int, watch WatchSession) (string, bool, error) {
	var seen []byte
	if watch != nil {
		deadline := time.Now().Add(r.timeout)
		for time.Now().Before(deadline) {
			payload, err := watch.Idle()
			if err != nil || len(payload) > 0 {
				seen = append(seen, payload...)
				break
			}
			time.Sleep(time.Millisecond)
		}
	}
	r.mu.Lock()
	r.payloads = append(r.payloads, seen)
	r.mu.Unlock()
	return r.watchRecordingReader.ReadLineWithWatch(ctx, prompt, history, limit, watch)
}

// payloadAt returns the payload the prompt at index observed. The index matches
// the recorded session index, because both are appended once per prompt.
func (r *idlePollingReader) payloadAt(index int) []byte {
	r.mu.Lock()
	defer r.mu.Unlock()
	if index < 0 || index >= len(r.payloads) {
		return nil
	}
	return r.payloads[index]
}

// runIdlePollingREPL drives the REPL with a reader that polls the armed session
// before each line, so an asynchronous open is observed the way the real editor
// observes it.
func runIdlePollingREPL(t *testing.T, stub InteractiveAPI, lines []string) (string, string, *idlePollingReader) {
	t.Helper()
	reader := &idlePollingReader{watchRecordingReader: &watchRecordingReader{lines: lines}, timeout: idlePollTimeout}
	var out, diagnostics strings.Builder
	options := InteractiveOptions{
		ReadLine: func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
			return reader.ReadLineWithWatch(ctx, prompt, history, limit, nil)
		},
		WatchReader: reader,
	}
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, options); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	return out.String(), diagnostics.String(), reader
}

// assertActionFollowCount asserts how many action tails were opened, choosing the
// correct waiting discipline for the expected count.
//
// A positive count is written by the goroutine that opens the stream, so the test
// must wait for it. A zero count is an absence assertion, and reading the slice
// once cannot prove absence: the open may still be on its way. The entry
// transition's own tail is the only stream that must exist in both cases, so the
// settle waits for exactly that one and then confirms nothing else arrives.
func assertActionFollowCount(t *testing.T, stub *sendFollowStub, want int) {
	t.Helper()
	if want == 0 {
		settleFollowCount(t, stub, 1)
		if got := len(actionFollowRequests(stub)); got != 0 {
			t.Fatalf("action follow count=%d, want 0", got)
		}
		return
	}
	if got := len(waitActionFollowRequests(t, stub, want)); got != want {
		t.Fatalf("action follow count=%d, want %d", got, want)
	}
}

// slowOpenStub blocks the streaming seam until it is released, so a test can
// prove the prompt is not waiting for the transport.
type slowOpenStub struct {
	interactiveStub
	release chan struct{}
	entered chan struct{}
	once    sync.Once
}

// FollowOutput blocks until release is closed, which is what a Server that has
// not yet written its first record does to the caller.
func (s *slowOpenStub) FollowOutput(ctx context.Context, endpointID, resourceID, generation string, maxBytes, maxLines int) (<-chan protocol.OutputFollowRecord, error) {
	s.once.Do(func() { close(s.entered) })
	select {
	case <-s.release:
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	return make(chan protocol.OutputFollowRecord), nil
}

// TestStartFollowDoesNotBlockOnTheOpen proves the stream is opened off the prompt
// path. The caller is the REPL prompt, and it opens the stream before it starts
// reading keys, so a synchronous open made the terminal deaf for the whole
// provider startup window: "any key stops" waited for the provider instead of for
// the operator.
//
// The assertion is that startFollow returns while the open is still blocked, and
// that Stop returns without waiting for it. Both are properties of the prompt
// path, so a regression that restores the synchronous open fails here instead of
// only being felt by an operator.
func TestStartFollowDoesNotBlockOnTheOpen(t *testing.T) {
	stub := &slowOpenStub{release: make(chan struct{}), entered: make(chan struct{})}
	state := &interactiveState{follow: &followRequest{EndpointID: "endpoint-1", ResourceID: "res-1", ProviderGeneration: "generation-1"}}

	returned := make(chan WatchSession, 1)
	go func() {
		returned <- startFollow(context.Background(), stub, state, InteractiveOptions{WatchReader: &TerminalEditor{}})
	}()

	var session WatchSession
	select {
	case session = <-returned:
	case <-time.After(followSettleTimeout):
		t.Fatal("startFollow blocked on the open, so the prompt cannot read a keypress")
	}
	if session == nil {
		t.Fatal("startFollow returned nil")
	}
	// The open really is in flight, so the assertion above was not satisfied by a
	// seam that never ran.
	select {
	case <-stub.entered:
	case <-time.After(followSettleTimeout):
		t.Fatal("the open never started")
	}

	stopped := make(chan struct{})
	go func() {
		session.Stop()
		close(stopped)
	}()
	select {
	case <-stopped:
	case <-time.After(followSettleTimeout):
		t.Fatal("Stop blocked on the in-flight open, so a keypress would wait for the transport")
	}
	close(stub.release)
}
