package tui

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"sort"
	"strings"
	"sync"
	"time"
)

// Watch intervals. The projection mode only re-reads the persisted Server
// inventory, so it may run at the operator's five-second default. A forced
// collection launches one provider discovery per endpoint, so it keeps the
// ten-second floor documented in the architecture cost model instead of
// amplifying discovery.
const (
	defaultWatchInterval  = 5 * time.Second
	minWatchInterval      = time.Second
	defaultForcedInterval = 10 * time.Second
	minForcedInterval     = 10 * time.Second
)

// watchRequest is the parsed intent of one watch command.
type watchRequest struct {
	Interval time.Duration
	Force    bool
}

// WatchTicker supplies the tick source for one loop and releases it on stop.
// Tests inject a manual source, so no test depends on wall-clock sleeps.
type WatchTicker func(time.Duration) (<-chan time.Time, func())

// WatchSession is the auto-refresh loop the line editor observes while idle.
// The editor owns the terminal, so a session never writes while a key is being
// decoded; it only publishes already-sanitized bytes for the editor to place.
type WatchSession interface {
	// Idle applies one pending refresh and returns the bytes to print, or nil
	// when nothing changed. It never blocks, so a keypress is never delayed.
	Idle() ([]byte, error)
	// Stop ends the loop. It is idempotent and cancels an in-flight collection.
	Stop()
}

// WatchLineReader is a line reader that can observe an auto-refresh loop while
// it waits for a key. A reader without this capability cannot run watch, because
// a blocking read cannot be interrupted from outside.
type WatchLineReader interface {
	ReadLineWithWatch(context.Context, string, bool, int, WatchSession) (string, bool, error)
}

// parseWatchArguments decodes the interactive watch grammar.
// Accepted forms are "watch", "watch <interval>", "watch --force" and
// "watch <interval> --force".
func parseWatchArguments(rest string) (watchRequest, error) {
	request := watchRequest{Interval: defaultWatchInterval}
	intervalSet := false
	for _, token := range strings.Fields(rest) {
		switch {
		case token == "--force":
			if request.Force {
				return watchRequest{}, fmt.Errorf("usage: watch [interval] [--force]")
			}
			request.Force = true
		case strings.HasPrefix(token, "-"):
			return watchRequest{}, fmt.Errorf("option %q is available only in non-interactive mode; JSON output is available only with the standalone command", token)
		default:
			if intervalSet {
				return watchRequest{}, fmt.Errorf("usage: watch [interval] [--force]")
			}
			parsed, err := time.ParseDuration(token)
			if err != nil || parsed <= 0 {
				return watchRequest{}, fmt.Errorf("usage: watch [interval] [--force]")
			}
			request.Interval = parsed
			intervalSet = true
		}
	}
	if request.Force {
		if !intervalSet {
			request.Interval = defaultForcedInterval
		}
		if request.Interval < minForcedInterval {
			return watchRequest{}, fmt.Errorf("watch --force requires an interval of at least %s, because every tick launches one provider discovery per endpoint", minForcedInterval)
		}
		return request, nil
	}
	if request.Interval < minWatchInterval {
		return watchRequest{}, fmt.Errorf("watch requires an interval of at least %s", minWatchInterval)
	}
	return request, nil
}

// watchResult is one completed collection, already rendered to sanitized bytes.
type watchResult struct {
	rows   []SessionRow
	output []byte
	err    error
}

// watchController collects on a tick and publishes rendered output for the
// editor thread. It never touches interactiveState or the terminal, so the
// editor stays the only writer and REPL state needs no lock.
type watchController struct {
	api     InteractiveAPI
	filter  string
	request watchRequest
	ticks   <-chan time.Time
	release func()
	color   ColorPolicy
	ctx     context.Context
	cancel  context.CancelFunc

	mu      sync.Mutex
	pending *watchResult
	lastErr string

	stopOnce sync.Once
	done     chan struct{}
}

// newWatchController starts one loop. The ticker is injected so tests can drive
// ticks deterministically; nil selects the real ticker.
func newWatchController(parent context.Context, api InteractiveAPI, filter string, request watchRequest, ticker WatchTicker, color ColorPolicy) *watchController {
	if ticker == nil {
		ticker = realWatchTicker
	}
	ticks, release := ticker(request.Interval)
	ctx, cancel := context.WithCancel(parent)
	controller := &watchController{
		api:     api,
		filter:  filter,
		request: request,
		ticks:   ticks,
		release: release,
		color:   color,
		ctx:     ctx,
		cancel:  cancel,
		done:    make(chan struct{}),
	}
	go controller.run()
	return controller
}

// realWatchTicker is the production tick source.
func realWatchTicker(interval time.Duration) (<-chan time.Time, func()) {
	ticker := time.NewTicker(interval)
	return ticker.C, ticker.Stop
}

// run collects on every tick until the loop is stopped. A tick that arrives
// while a collection is in flight is dropped by the ticker channel, so a slow
// collection never queues a backlog of overlapping scans.
func (c *watchController) run() {
	defer close(c.done)
	defer c.release()
	for {
		select {
		case <-c.ctx.Done():
			return
		case <-c.ticks:
			c.collect()
		}
	}
}

// collect performs one bounded collection and publishes its rendered result.
func (c *watchController) collect() {
	ctx, cancel := c.collectionContext()
	defer cancel()
	loaded, err := c.load(ctx)
	if err != nil {
		c.publishFailure(err)
		return
	}
	rows, output, err := c.render(loaded)
	if err != nil {
		c.publishFailure(err)
		return
	}
	c.mu.Lock()
	c.lastErr = ""
	c.pending = &watchResult{rows: rows, output: output}
	c.mu.Unlock()
}

// collectionContext bounds one collection. A forced collection inherits the
// forced-collection budget so the Server reports its own failure first.
func (c *watchController) collectionContext() (context.Context, context.CancelFunc) {
	if c.request.Force {
		return context.WithTimeout(c.ctx, refreshCommandTimeout)
	}
	return context.WithTimeout(c.ctx, 10*time.Second)
}

// load reads the inventory for the current scope. A partially failed refresh is
// rejected instead of rendered, because replacing the table with an incomplete
// row set would rebind row numbers from data the operator cannot see.
func (c *watchController) load(ctx context.Context) (reportLoad, error) {
	var loaded reportLoad
	var err error
	if c.request.Force {
		loaded, err = forceCollection(ctx, c.api, c.filter)
	} else {
		loaded, err = loadReports(ctx, c.api, c.filter)
	}
	if err != nil {
		return reportLoad{}, err
	}
	// The failing endpoint IDs are sorted before the message is built, because a
	// map iteration order would alternate the message between ticks and defeat
	// the repeated-failure de-duplication in publishFailure.
	failed := make([]string, 0, len(loaded.errors))
	for endpointID := range loaded.errors {
		failed = append(failed, endpointID)
	}
	if len(failed) == 0 {
		return loaded, nil
	}
	sort.Strings(failed)
	if len(failed) == 1 {
		return reportLoad{}, fmt.Errorf("endpoint %q failed to report", failed[0])
	}
	return reportLoad{}, fmt.Errorf("endpoints %q failed to report", strings.Join(failed, `", "`))
}

// render produces the table bytes through the shared renderer, so sanitization
// and layout stay identical to a manual list.
func (c *watchController) render(loaded reportLoad) ([]SessionRow, []byte, error) {
	var buffer bytes.Buffer
	safe := newSafeWriter(&buffer)
	var rows []SessionRow
	options := tableOptionsFor(safe, c.color, false, func(rendered []SessionRow) {
		rows = append(rows, rendered...)
	})
	if err := renderListRows(safe, io.Discard, loaded, c.filter, false, options); err != nil {
		return nil, nil, err
	}
	if err := safe.Flush(); err != nil {
		return nil, nil, err
	}
	return rows, buffer.Bytes(), nil
}

// publishFailure records one failure. A repeated identical failure is reported
// once, so a permanently unreachable endpoint cannot flood the terminal.
func (c *watchController) publishFailure(err error) {
	message := err.Error()
	c.mu.Lock()
	defer c.mu.Unlock()
	if message == c.lastErr {
		return
	}
	c.lastErr = message
	c.pending = &watchResult{err: err}
}

// take removes the pending result, so one collection is applied exactly once.
func (c *watchController) take() (watchResult, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.pending == nil {
		return watchResult{}, false
	}
	result := *c.pending
	c.pending = nil
	return result, true
}

// Stop cancels an in-flight collection and waits for the loop to exit.
func (c *watchController) Stop() {
	c.stopOnce.Do(c.cancel)
	<-c.done
}

// replWatch applies a controller result to REPL state. It runs only on the
// editor thread, so it can mutate state without a lock.
type replWatch struct {
	controller *watchController
	state      *interactiveState
	// lastPayload is the table last printed by this loop, so an unchanged
	// inventory does not reprint on every tick. It lives here because Idle runs
	// only on the editor thread, so no lock is needed.
	lastPayload []byte
	hasPayload  bool
}

// Idle applies one pending refresh and returns the bytes the editor must print.
// A collection failure becomes one diagnostic line instead of an error, because
// a failed refresh must never end the operator's session.
func (w *replWatch) Idle() ([]byte, error) {
	result, ok := w.controller.take()
	if !ok {
		return nil, nil
	}
	if result.err != nil {
		return []byte("auto-refresh: " + sanitizeInlineText(result.err.Error()) + "\n"), nil
	}
	rebound := w.rebind(result.rows)
	payload := result.output
	if rebound {
		payload = append(payload, []byte("auto-refresh: row numbers rebound; run list to review the new order\n")...)
	}
	// Suppress an unchanged table, so a static inventory does not reprint on
	// every tick. Rendered bytes alone are not sufficient evidence: a generation
	// change can render identical text, so a rebinding must always print even
	// when the table looks the same.
	if !rebound && w.hasPayload && bytes.Equal(payload, w.lastPayload) {
		return nil, nil
	}
	w.lastPayload = append(w.lastPayload[:0], payload...)
	w.hasPayload = true
	return payload, nil
}

// rebind replaces the row bindings and reports whether the row set changed, so
// a moving table is never silent about a changed row number.
func (w *replWatch) rebind(rows []SessionRow) bool {
	changed := !sameRowIdentity(w.state.Rows, rows)
	w.state.setRows(rows)
	return changed
}

// Stop ends the loop.
func (w *replWatch) Stop() { w.controller.Stop() }

// sameRowIdentity compares row bindings by identity, not by display text, so a
// status change alone does not count as a rebinding.
func sameRowIdentity(current map[int]SessionRow, rows []SessionRow) bool {
	if len(current) != len(rows) {
		return false
	}
	for _, row := range rows {
		existing, ok := current[row.No]
		if !ok || existing.SessionID != row.SessionID || existing.Generation != row.Generation || existing.EndpointID != row.EndpointID {
			return false
		}
	}
	return true
}

// interactiveWatch arms the auto-refresh loop for the next prompt. The loop
// itself starts before the next read, because a blocking read cannot be
// interrupted from outside.
func interactiveWatch(api InteractiveAPI, state *interactiveState, rest string, out io.Writer, options InteractiveOptions) error {
	request, err := parseWatchArguments(rest)
	if err != nil {
		return err
	}
	if options.WatchReader == nil {
		return fmt.Errorf("auto-refresh requires a terminal that can observe keypresses; it is unavailable in this input mode")
	}
	if request.Force {
		if _, ok := api.(InventoryRefresher); !ok {
			return fmt.Errorf("auto-refresh --force is unavailable: the API client does not support forced collection")
		}
	}
	state.watch = &request
	mode := "projection"
	if request.Force {
		mode = "forced collection"
	}
	_, err = fmt.Fprintf(out, "auto-refresh: %s %s (any key stops)\n", request.Interval, mode)
	return err
}

// startWatch activates the armed auto-refresh intent for the next prompt.
// It consumes the intent, so a keypress that stops the loop cannot silently
// re-arm it on the following prompt. It returns nil when no watch was requested
// or the reader cannot observe one, so the plain read path stays byte-identical.
func startWatch(parent context.Context, api InteractiveAPI, state *interactiveState, options InteractiveOptions) WatchSession {
	if state.watch == nil {
		return nil
	}
	request := *state.watch
	state.watch = nil
	if options.WatchReader == nil {
		return nil
	}
	filter, err := scopedListFilter(state, "")
	if err != nil {
		return nil
	}
	controller := newWatchController(parent, api, filter, request, options.Ticks, options.Color)
	return &replWatch{controller: controller, state: state}
}
