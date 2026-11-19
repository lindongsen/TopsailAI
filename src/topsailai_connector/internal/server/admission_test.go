package server

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// testLimits builds a limit set with an explicit wait.
func testLimits(perCaller, perNode, total int, wait time.Duration) admissionLimits {
	return admissionLimits{perCaller: perCaller, perNode: perNode, total: total, wait: wait}
}

// newTestAdmission builds a controller and fails the test if construction refuses.
func newTestAdmission(t *testing.T, limits admissionLimits) *admission {
	t.Helper()
	controller, err := newAdmission(limits)
	if err != nil {
		t.Fatalf("newAdmission(%+v) = %v", limits, err)
	}
	return controller
}

// TestAdmissionBoundsOneCaller checks the per-caller dimension.
//
// The per-caller bound is what stops one caller from occupying every slot. Without
// it a single caller with a fast link fills the Server and a second caller waits
// behind work it did not cause.
func TestAdmissionBoundsOneCaller(t *testing.T) {
	controller := newTestAdmission(t, testLimits(2, 10, 10, 0))

	first, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("first acquire = %v", err)
	}
	defer first()

	second, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("second acquire = %v", err)
	}
	defer second()

	if _, err := controller.acquire("caller-a", "node-1"); !errors.Is(err, ErrOverloaded) {
		t.Fatalf("third acquire = %v, want ErrOverloaded", err)
	}

	// A different caller must still be admitted, because the bound is per caller
	// and not a global one. A test that only checked the refusal would pass with a
	// per-caller limit implemented as a total limit.
	other, err := controller.acquire("caller-b", "node-1")
	if err != nil {
		t.Fatalf("acquire for a second caller = %v, want success", err)
	}
	other()
}

// TestAdmissionBoundsOneNode checks the per-node dimension.
//
// The per-node bound protects the personal computer the Node runs on. Two callers
// with separate credentials aimed at one Node must not be able to exceed it, which
// is why the bound is keyed by node id rather than by caller.
func TestAdmissionBoundsOneNode(t *testing.T) {
	controller := newTestAdmission(t, testLimits(10, 2, 10, 0))

	first, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("first acquire = %v", err)
	}
	defer first()

	second, err := controller.acquire("caller-b", "node-1")
	if err != nil {
		t.Fatalf("second acquire = %v", err)
	}
	defer second()

	if _, err := controller.acquire("caller-c", "node-1"); !errors.Is(err, ErrOverloaded) {
		t.Fatalf("third acquire on one node = %v, want ErrOverloaded", err)
	}

	// A different Node must still be admitted, so the bound is per Node rather than
	// a second global limit.
	other, err := controller.acquire("caller-c", "node-2")
	if err != nil {
		t.Fatalf("acquire for a second node = %v, want success", err)
	}
	other()
}

// TestAdmissionBoundsTheWholeServer checks the Server-wide dimension.
//
// The total bound is the backstop. It is the only dimension that cannot be evaded
// by presenting another caller id or addressing another Node.
func TestAdmissionBoundsTheWholeServer(t *testing.T) {
	controller := newTestAdmission(t, testLimits(10, 10, 2, 0))

	first, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("first acquire = %v", err)
	}
	defer first()

	second, err := controller.acquire("caller-b", "node-2")
	if err != nil {
		t.Fatalf("second acquire = %v", err)
	}
	defer second()

	if _, err := controller.acquire("caller-c", "node-3"); !errors.Is(err, ErrOverloaded) {
		t.Fatalf("third acquire = %v, want ErrOverloaded", err)
	}
}

// TestAdmissionRefusesImmediatelyWithNoWait checks that a zero wait refuses rather
// than blocking.
//
// Zero is a meaningful setting: a Node that must not queue work refuses at once so
// the caller learns the truth instead of waiting for a slot that may not arrive.
func TestAdmissionRefusesImmediatelyWithNoWait(t *testing.T) {
	controller := newTestAdmission(t, testLimits(1, 1, 1, 0))

	held, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("first acquire = %v", err)
	}
	defer held()

	sleeps := 0
	controller.sleep = func(time.Duration) { sleeps++ }

	start := time.Now()
	if _, err := controller.acquire("caller-b", "node-1"); !errors.Is(err, ErrOverloaded) {
		t.Fatalf("acquire with no wait = %v, want ErrOverloaded", err)
	}
	if sleeps != 0 {
		t.Fatalf("acquire with no wait slept %d times, want 0", sleeps)
	}
	if elapsed := time.Since(start); elapsed > 50*time.Millisecond {
		t.Fatalf("acquire with no wait took %s, want an immediate refusal", elapsed)
	}
}

// TestAdmissionWaitsWithinTheBudgetThenRefuses checks the bounded wait.
//
// The wait exists to absorb a burst, because a refusal in the middle of a chunked
// read aborts a download that was making progress. It is bounded because an
// unbounded wait is a queue, and a queue is the thing this mechanism refuses to
// build.
//
// The clock is driven by the injected sleep so the test measures the budget rather
// than the host's scheduler.
func TestAdmissionWaitsWithinTheBudgetThenRefuses(t *testing.T) {
	controller := newTestAdmission(t, testLimits(1, 1, 1, 10*time.Millisecond))

	held, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("first acquire = %v", err)
	}
	defer held()

	clock := time.Unix(0, 0)
	controller.now = func() time.Time { return clock }
	sleeps := 0
	controller.sleep = func(d time.Duration) {
		sleeps++
		clock = clock.Add(d)
	}

	if _, err := controller.acquire("caller-b", "node-1"); !errors.Is(err, ErrOverloaded) {
		t.Fatalf("acquire past the budget = %v, want ErrOverloaded", err)
	}

	// A 10ms budget polled every 2ms is five sleeps before the deadline is reached.
	// Asserting the count proves the loop actually waited instead of refusing on the
	// first attempt, which is the difference between a burst absorber and a refusal.
	if sleeps != 5 {
		t.Fatalf("acquire slept %d times, want 5", sleeps)
	}
}

// TestAdmissionAdmitsWhenASlotFreesDuringTheWait checks that the wait is useful.
//
// A wait that never admits anything is a delay, not a burst absorber. The slot is
// released from another goroutine while the waiter polls, which is the shape of the
// real case: an in-flight read finishes and frees capacity.
func TestAdmissionAdmitsWhenASlotFreesDuringTheWait(t *testing.T) {
	controller := newTestAdmission(t, testLimits(1, 1, 1, time.Second))

	held, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("first acquire = %v", err)
	}

	clock := time.Unix(0, 0)
	controller.now = func() time.Time { return clock }
	controller.sleep = func(d time.Duration) {
		clock = clock.Add(d)
		held()
	}

	release, err := controller.acquire("caller-b", "node-1")
	if err != nil {
		t.Fatalf("acquire while a slot frees = %v, want success", err)
	}
	release()
}

// TestAdmissionReleaseIsIdempotent checks that a double release cannot widen the
// bound.
//
// A release that decremented twice would lower a counter another request owns, and
// the bound would then admit more than it states. The guard is a sync.Once, so the
// second call is a no-op rather than a silent widening.
func TestAdmissionReleaseIsIdempotent(t *testing.T) {
	controller := newTestAdmission(t, testLimits(1, 1, 1, 0))

	release, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("acquire = %v", err)
	}
	release()
	release()
	release()

	total, callers, nodes := controller.snapshot()
	if total != 0 || callers != 0 || nodes != 0 {
		t.Fatalf("snapshot after a triple release = (%d, %d, %d), want (0, 0, 0)", total, callers, nodes)
	}

	// The bound must still hold after the extra releases. A counter driven negative
	// would admit two requests here.
	first, err := controller.acquire("caller-a", "node-1")
	if err != nil {
		t.Fatalf("acquire after a triple release = %v, want success", err)
	}
	defer first()
	if _, err := controller.acquire("caller-a", "node-1"); !errors.Is(err, ErrOverloaded) {
		t.Fatalf("second acquire after a triple release = %v, want ErrOverloaded", err)
	}
}

// TestAdmissionForgetsIdleKeys checks that the maps do not grow without bound.
//
// Both maps are keyed by a value that arrives from outside: a caller key id and a
// node id. Leaving a zero entry behind would let an authenticated caller grow the
// map by presenting many key ids, which is a memory leak reachable with a
// credential.
func TestAdmissionForgetsIdleKeys(t *testing.T) {
	controller := newTestAdmission(t, testLimits(1, 1, 100, 0))

	for _, caller := range []string{"caller-a", "caller-b", "caller-c"} {
		release, err := controller.acquire(caller, "node-"+caller)
		if err != nil {
			t.Fatalf("acquire for %s = %v", caller, err)
		}
		release()
	}

	total, callers, nodes := controller.snapshot()
	if total != 0 {
		t.Fatalf("total after every release = %d, want 0", total)
	}
	if callers != 0 {
		t.Fatalf("caller entries after every release = %d, want 0", callers)
	}
	if nodes != 0 {
		t.Fatalf("node entries after every release = %d, want 0", nodes)
	}
}

// TestAdmissionRefusesUnusableLimits checks that a zero limit is refused rather
// than substituted.
//
// A zero limit refuses every request, and a Server that refuses everything looks
// like a working Server that denies. Refusing construction makes the mistake
// visible at startup instead of at the first request.
func TestAdmissionRefusesUnusableLimits(t *testing.T) {
	cases := []struct {
		name   string
		limits admissionLimits
	}{
		{"per-caller zero", testLimits(0, 1, 1, 0)},
		{"per-node zero", testLimits(1, 0, 1, 0)},
		{"total zero", testLimits(1, 1, 0, 0)},
		{"negative wait", testLimits(1, 1, 1, -time.Millisecond)},
		{"wait over the cap", testLimits(1, 1, 1, MaxAdmissionWait+time.Millisecond)},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if _, err := newAdmission(testCase.limits); err == nil {
				t.Fatalf("newAdmission(%+v) = nil error, want a refusal", testCase.limits)
			}
		})
	}
}

// TestAdmissionIsSafeUnderConcurrency checks the counters under parallel use.
//
// The three dimensions are reserved under one lock, so a request cannot take a
// caller slot and then discover the Node is full while holding it. A partial
// reservation would leak capacity permanently, and the leak would only appear under
// load.
func TestAdmissionIsSafeUnderConcurrency(t *testing.T) {
	controller := newTestAdmission(t, testLimits(4, 4, 8, 0))

	var waitGroup sync.WaitGroup
	var mutex sync.Mutex
	admitted := 0
	refused := 0

	for index := 0; index < 40; index++ {
		waitGroup.Add(1)
		go func(index int) {
			defer waitGroup.Done()
			caller := "caller-" + string(rune('a'+index%4))
			node := "node-" + string(rune('a'+index%2))
			release, err := controller.acquire(caller, node)
			if err != nil {
				mutex.Lock()
				refused++
				mutex.Unlock()
				return
			}
			mutex.Lock()
			admitted++
			mutex.Unlock()
			release()
		}(index)
	}
	waitGroup.Wait()

	if admitted+refused != 40 {
		t.Fatalf("admitted %d plus refused %d = %d, want 40", admitted, refused, admitted+refused)
	}
	if admitted == 0 {
		t.Fatal("no request was admitted, so the test measured nothing")
	}
	total, callers, nodes := controller.snapshot()
	if total != 0 || callers != 0 || nodes != 0 {
		t.Fatalf("snapshot after the run = (%d, %d, %d), want (0, 0, 0)", total, callers, nodes)
	}
}

// blockingForwarder holds a request until the test releases it.
//
// It exists so a handler test can observe a request that is genuinely in flight.
// A delay-based forwarder would make the test depend on the host's scheduler, and a
// test that is only usually correct is worse than no test.
type blockingForwarder struct {
	entered chan struct{}
	release chan struct{}
	once    sync.Once
}

// Forward signals entry and waits for the test to release it.
func (f *blockingForwarder) Forward(ctx context.Context, nodeID string, request protocol.Request) (protocol.Response, error) {
	f.once.Do(func() { close(f.entered) })
	select {
	case <-f.release:
		return protocol.Success([]byte(`{"ok":true}`)), nil
	case <-ctx.Done():
		return protocol.Response{}, ctx.Err()
	}
}

// TestHandlerRefusesAtAdmissionWhenSaturated checks the end-to-end refusal.
//
// The test proves three things at once: the gate is wired into the request path,
// the refusal carries the retryable overloaded code rather than internal, and the
// slot is released when the in-flight request finishes.
func TestHandlerRefusesAtAdmissionWhenSaturated(t *testing.T) {
	registry := NewRegistry()
	if _, _, err := registry.Register(&fakeChannel{nodeID: testNodeID}); err != nil {
		t.Fatalf("Register: %v", err)
	}

	forwarder := &blockingForwarder{entered: make(chan struct{}), release: make(chan struct{})}
	config := testConfig(t)
	config.MaxInFlightPerCaller = 1
	config.MaxInFlightPerNode = 1
	config.MaxInFlight = 1
	config.AdmissionWait = 0

	handler, err := NewHandler(config, registry, forwarder, nil)
	if err != nil {
		t.Fatalf("NewHandler() = %v", err)
	}

	// The first request occupies the only slot and blocks inside the forwarder.
	firstDone := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		firstDone <- serve(handler, signedRequest(t, testNodeID, validBody))
	}()
	<-forwarder.entered

	// The second request must be refused at admission, before it reaches the
	// forwarder. A refusal that happened after forwarding would have spent the
	// resource the bound exists to protect.
	second := serve(handler, signedRequest(t, testNodeID, validBody))
	body := decodeEnvelope(t, second)
	if body.Code != protocol.CodeOverloaded {
		t.Fatalf("saturated request code = %d (%s), want %d (overloaded)", body.Code, body.Message, protocol.CodeOverloaded)
	}
	if second.Code != http.StatusServiceUnavailable {
		t.Fatalf("saturated request status = %d, want %d", second.Code, http.StatusServiceUnavailable)
	}

	close(forwarder.release)
	first := <-firstDone
	if first.Code != http.StatusOK {
		t.Fatalf("in-flight request status = %d, want 200", first.Code)
	}

	// The slot must be free again, so the next request succeeds. A leaked slot would
	// reduce capacity permanently and only show up as a Server that slowly stops
	// answering.
	third := serve(handler, signedRequest(t, testNodeID, validBody))
	if third.Code != http.StatusOK {
		t.Fatalf("request after the slot was released status = %d, want 200", third.Code)
	}
}

// TestHandlerReleasesTheSlotOnARefusedForward checks that a failed forward returns
// its slot.
//
// The release is deferred, so every path below the gate returns the slot. A path
// that forgot would leak one slot per failure, and a Node that is offline for a
// while would drain the Server's capacity without any request succeeding.
func TestHandlerReleasesTheSlotOnARefusedForward(t *testing.T) {
	registry := NewRegistry()
	if _, _, err := registry.Register(&fakeChannel{nodeID: testNodeID}); err != nil {
		t.Fatalf("Register: %v", err)
	}

	forwarder := &fakeForwarder{err: ErrNodeOffline}
	config := testConfig(t)
	config.MaxInFlightPerCaller = 1
	config.MaxInFlightPerNode = 1
	config.MaxInFlight = 1
	config.AdmissionWait = 0

	handler, err := NewHandler(config, registry, forwarder, nil)
	if err != nil {
		t.Fatalf("NewHandler() = %v", err)
	}

	for attempt := 0; attempt < 3; attempt++ {
		recorder := serve(handler, signedRequest(t, testNodeID, validBody))
		body := decodeEnvelope(t, recorder)
		if body.Code != protocol.CodeNodeOffline {
			t.Fatalf("attempt %d code = %d (%s), want %d (node_offline)", attempt, body.Code, body.Message, protocol.CodeNodeOffline)
		}
	}

	total, callers, nodes := handler.admission.snapshot()
	if total != 0 || callers != 0 || nodes != 0 {
		t.Fatalf("snapshot after three refused forwards = (%d, %d, %d), want (0, 0, 0)", total, callers, nodes)
	}
}

// blockingBody is a request body that blocks until the test releases it.
//
// It exists so a test can observe a request that is still being read. The body is
// read before the client proof is verified, so a gate placed before authentication
// would hold a slot for the whole duration of a slow upload, which is a denial of
// service reachable without a credential.
type blockingBody struct {
	entered chan struct{}
	release chan struct{}
	once    sync.Once
	payload []byte
}

// Read signals entry once, waits for the release, then returns the payload.
func (b *blockingBody) Read(buffer []byte) (int, error) {
	b.once.Do(func() { close(b.entered) })
	<-b.release
	if len(b.payload) == 0 {
		return 0, io.EOF
	}
	count := copy(buffer, b.payload)
	b.payload = b.payload[count:]
	return count, nil
}

// Close satisfies io.ReadCloser.
func (b *blockingBody) Close() error { return nil }

// TestHandlerDoesNotHoldASlotWhileReadingAnUnauthenticatedBody checks the gate's
// position by measuring the slot, not by observing a refusal.
//
// The earlier version of this test sent an unauthenticated request and then checked
// that an authenticated one succeeded. That test passed with the gate moved before
// authentication, because the unauthenticated request had already finished and
// released its slot by the time the second request ran. It proved release, not
// ordering.
//
// This version holds the body open, so the unauthenticated request is still inside
// the handler while the slot is inspected. With the gate after authentication the
// slot is free; with the gate before it the slot is taken, and the test fails.
func TestHandlerDoesNotHoldASlotWhileReadingAnUnauthenticatedBody(t *testing.T) {
	registry := NewRegistry()
	if _, _, err := registry.Register(&fakeChannel{nodeID: testNodeID}); err != nil {
		t.Fatalf("Register: %v", err)
	}

	forwarder := &fakeForwarder{response: protocol.Success([]byte(`{"ok":true}`))}
	config := testConfig(t)
	config.MaxInFlightPerCaller = 1
	config.MaxInFlightPerNode = 1
	config.MaxInFlight = 1
	config.AdmissionWait = 0

	handler, err := NewHandler(config, registry, forwarder, nil)
	if err != nil {
		t.Fatalf("NewHandler() = %v", err)
	}

	body := &blockingBody{entered: make(chan struct{}), release: make(chan struct{}), payload: []byte(validBody)}
	request := httptest.NewRequest(http.MethodPost, OperationPathPrefix+testNodeID+OperationPathSuffix, body)
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(security.NodeAuthHeader, nodeProofFor(t, testNodeID, "req_slow_body", validBody))

	done := make(chan struct{})
	go func() {
		defer close(done)
		serve(handler, request)
	}()
	<-body.entered

	// The request is now blocked inside readBody, before any proof was verified. The
	// slot must still be free, because no authenticated work has been admitted.
	total, callers, nodes := handler.admission.snapshot()
	if total != 0 || callers != 0 || nodes != 0 {
		t.Fatalf("snapshot while an unauthenticated body is being read = (%d, %d, %d), want (0, 0, 0); the gate runs before authentication", total, callers, nodes)
	}

	close(body.release)
	<-done
}
