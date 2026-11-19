package server

import (
	"errors"
	"sync"
	"time"
)

// ErrOverloaded reports that admission refused a request because a limit was
// reached and the bounded wait expired.
//
// It is a distinct error rather than a generic failure because the caller can act
// on it: the condition is temporary, the same request will work later, and the
// answer is a retryable code rather than "the server failed".
var ErrOverloaded = errors.New("server is at its concurrency limit")

// Default admission limits.
//
// The three limits answer three different questions, and one limit cannot answer
// all of them. A single Server-wide bound stops unbounded growth but lets one
// caller occupy every slot, so a second caller waits behind work it did not cause.
// A per-caller bound alone lets one caller with many credentials, or many callers
// aimed at one Node, saturate a single Node.
//
// The values are deliberately small. A read is a stream of 256 KiB chunks, so a
// caller needs very few concurrent requests to keep a link busy; a large bound
// would mostly admit work that queues behind the Node's own disk anyway.
const (
	// DefaultMaxInFlightPerCaller bounds one caller's concurrent requests. Two is
	// enough for a caller that pipelines a read and a stat, and small enough that
	// one caller cannot fill the Server.
	DefaultMaxInFlightPerCaller = 2
	// DefaultMaxInFlightPerNode bounds one Node's concurrent requests. A Node runs
	// on a personal computer, so the bound protects the machine the operator is
	// using rather than the Server.
	DefaultMaxInFlightPerNode = 4
	// DefaultMaxInFlight bounds the whole process. It matches the per-channel
	// bound, so the Server-wide limit and the channel backstop agree instead of one
	// silently shadowing the other.
	DefaultMaxInFlight = 64
	// DefaultAdmissionWait is how long a request may wait for a slot before it is
	// refused. A short wait absorbs a burst, which matters because a refusal in the
	// middle of a chunked read aborts a download that was making progress. A long
	// wait would turn saturation into latency, which is the failure the bound exists
	// to prevent.
	DefaultAdmissionWait = 200 * time.Millisecond
	// MaxAdmissionWait bounds the configured wait. A wait measured in seconds is a
	// queue with a timeout, and a queue is what this mechanism refuses to build.
	MaxAdmissionWait = 5 * time.Second
	// admissionPollInterval is how often a waiting request re-checks for a slot.
	//
	// Polling is used instead of a condition variable because a condition variable
	// has no timeout, and adding one means a timer goroutine per waiter. The
	// interval is short enough that a freed slot is noticed promptly and long enough
	// that a waiter costs almost no CPU: a request waiting the full default budget
	// wakes about a hundred times, and each wake is a mutex acquisition.
	admissionPollInterval = 2 * time.Millisecond
)

// admissionLimits is the resolved set of limits.
type admissionLimits struct {
	perCaller int
	perNode   int
	total     int
	wait      time.Duration
}

// admission bounds concurrent requests on three dimensions at once.
//
// It holds counters and nothing else. It never holds a request, a response, a
// proof or a secret: a waiter is a goroutine that already exists because net/http
// started it, so waiting adds no queue and no per-waiter allocation beyond the
// stack it already had. That is what keeps the bound a bound rather than a buffer.
type admission struct {
	limits admissionLimits

	mutex    sync.Mutex
	total    int
	byCaller map[string]int
	byNode   map[string]int

	// now and sleep are fields so a test can drive the wait budget without
	// sleeping for real. They are not configuration.
	now   func() time.Time
	sleep func(time.Duration)
}

// newAdmission builds the admission controller from resolved limits.
//
// A limit below one is refused rather than substituted, because a zero limit would
// refuse every request and look like a working Server that denies everything.
func newAdmission(limits admissionLimits) (*admission, error) {
	if limits.perCaller < 1 {
		return nil, errors.New("per-caller admission limit must be at least 1")
	}
	if limits.perNode < 1 {
		return nil, errors.New("per-node admission limit must be at least 1")
	}
	if limits.total < 1 {
		return nil, errors.New("server-wide admission limit must be at least 1")
	}
	if limits.wait < 0 || limits.wait > MaxAdmissionWait {
		return nil, errors.New("admission wait is outside the accepted range")
	}
	return &admission{
		limits:   limits,
		byCaller: make(map[string]int),
		byNode:   make(map[string]int),
		now:      time.Now,
		sleep:    time.Sleep,
	}, nil
}

// acquire reserves a slot for one request, waiting within the configured budget.
//
// The returned function releases the slot and must be called exactly once. It is
// safe to call more than once, because a double release would decrement a counter
// another request owns and quietly widen the bound.
func (a *admission) acquire(callerKeyID, nodeID string) (func(), error) {
	deadline := a.now().Add(a.limits.wait)

	for {
		if release, ok := a.tryAcquire(callerKeyID, nodeID); ok {
			return release, nil
		}
		if !a.now().Before(deadline) {
			return nil, ErrOverloaded
		}
		a.sleep(admissionPollInterval)
	}
}

// tryAcquire reserves a slot if all three dimensions have room.
//
// All three are checked and incremented under one lock, so a request cannot take a
// caller slot and then discover the Node is full while holding it. A partial
// reservation would leak capacity: the caller slot would stay taken by a request
// that never ran.
func (a *admission) tryAcquire(callerKeyID, nodeID string) (func(), bool) {
	a.mutex.Lock()
	defer a.mutex.Unlock()

	if a.total >= a.limits.total {
		return nil, false
	}
	if a.byCaller[callerKeyID] >= a.limits.perCaller {
		return nil, false
	}
	if a.byNode[nodeID] >= a.limits.perNode {
		return nil, false
	}

	a.total++
	a.byCaller[callerKeyID]++
	a.byNode[nodeID]++

	var once sync.Once
	return func() {
		once.Do(func() {
			a.mutex.Lock()
			defer a.mutex.Unlock()
			a.total--
			a.decrement(a.byCaller, callerKeyID)
			a.decrement(a.byNode, nodeID)
		})
	}, true
}

// decrement lowers one counter and removes the entry at zero.
//
// The entry is removed rather than left at zero because the maps are keyed by a
// caller id and a node id, both of which arrive from outside. Keeping a zero entry
// would let a caller grow the map without bound by presenting many key ids, which
// is a memory leak reachable by an authenticated caller.
func (a *admission) decrement(counters map[string]int, key string) {
	remaining := counters[key] - 1
	if remaining <= 0 {
		delete(counters, key)
		return
	}
	counters[key] = remaining
}

// snapshot reports the current occupancy. It exists for tests and for a future
// observability unit, and it takes the lock so a caller never reads a torn value.
func (a *admission) snapshot() (total int, callers int, nodes int) {
	a.mutex.Lock()
	defer a.mutex.Unlock()
	return a.total, len(a.byCaller), len(a.byNode)
}
