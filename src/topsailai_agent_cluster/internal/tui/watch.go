package tui

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/protocol"
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
	// TriggerSet records that the operator asked for a trigger script. It is
	// separate from TriggerPath because a bare --trigger means "use the default
	// location", which is a different request from naming a path.
	TriggerSet bool
	// TriggerPath is the path the operator named, or empty for the default.
	TriggerPath string
	// TriggerScript is the resolved absolute path, filled in once at arm time so
	// the loop never re-resolves a path on every tick. An empty value with
	// TriggerSet means no usable script was found, and the reason was reported
	// when the command was armed.
	TriggerScript string
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

// watchUsage is the interactive usage line. One constant keeps every rejection
// message identical, so an operator never has to compare two spellings of the
// same grammar.
const watchUsage = "usage: watch [interval] [--force] [-t|--trigger[=<path>]]"

// parseWatchArguments decodes the interactive watch grammar.
// Accepted forms are "watch", "watch <interval>", "watch --force",
// "watch <interval> --force", and either of those with "-t", "--trigger",
// "-t=<path>" or "--trigger=<path>" appended.
//
// --trigger is a flag with an optional value rather than a positional argument,
// because the interval is already positional and a bare path would be
// indistinguishable from it. A bare --trigger selects the default script
// location, so the operator never has to spell a path that the convention
// already defines.
//
// -t is a spelling of the same flag rather than a second flag, so it accepts
// exactly the two forms --trigger accepts and shares the same duplicate guard.
// A repeated spelling in any combination is a usage error, because resolving it
// by precedence would silently ignore something the operator stated.
func parseWatchArguments(rest string) (watchRequest, error) {
	request := watchRequest{Interval: defaultWatchInterval}
	intervalSet := false
	for _, token := range strings.Fields(rest) {
		switch {
		case token == "--force":
			if request.Force {
				return watchRequest{}, fmt.Errorf("%s", watchUsage)
			}
			request.Force = true
		case token == "--trigger" || token == "-t":
			if request.TriggerSet {
				return watchRequest{}, fmt.Errorf("%s", watchUsage)
			}
			request.TriggerSet = true
		case strings.HasPrefix(token, "--trigger=") || strings.HasPrefix(token, "-t="):
			if request.TriggerSet {
				return watchRequest{}, fmt.Errorf("%s", watchUsage)
			}
			// Both spellings carry the value after the same separator, so the
			// value is taken from the token instead of from a second prefix.
			_, path, _ := strings.Cut(token, "=")
			if path == "" {
				return watchRequest{}, fmt.Errorf("%s", watchUsage)
			}
			request.TriggerSet = true
			request.TriggerPath = path
		case strings.HasPrefix(token, "-"):
			return watchRequest{}, fmt.Errorf("option %q is available only in non-interactive mode; JSON output is available only with the standalone command", token)
		default:
			if intervalSet {
				return watchRequest{}, fmt.Errorf("%s", watchUsage)
			}
			parsed, err := time.ParseDuration(token)
			if err != nil || parsed <= 0 {
				return watchRequest{}, fmt.Errorf("%s", watchUsage)
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

// watchWriter sanitizes trusted table output while reporting the real output
// boundary's layout. The auto-refresh table is rendered into a buffer, so
// without this seam the renderer would see no terminal width and never fit the
// table to the terminal the operator is actually watching.
type watchWriter struct {
	*safeWriter
	layout TableLayout
}

// TableLayout reports the layout of the real output boundary, not the buffer.
func (w *watchWriter) TableLayout() TableLayout { return w.layout }

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
	// layoutSource re-reads the real output boundary's presentation policy on
	// every render, so a rendered table is fitted to the terminal instead of to
	// the internal buffer, and a terminal resize during the loop is honoured
	// rather than frozen at the moment the loop started.
	layoutSource func() TableLayout
	ctx          context.Context
	cancel       context.CancelFunc
	// runner executes the trigger script. A nil runner with a resolved script is
	// a wiring defect, so the loop reports it instead of silently skipping the
	// script the operator asked for.
	runner TriggerRunner
	// tracker remembers the last observed state per session identity, so the
	// trigger fires on a transition rather than on a state.
	tracker triggerTracker

	mu      sync.Mutex
	pending *watchResult
	lastErr string
	// triggerBusy marks a script still running. A transition that arrives while
	// one is in flight is dropped rather than queued, because a notification
	// script that cannot keep up must not accumulate a backlog of stale events.
	triggerBusy bool
	// triggerDone is closed when the in-flight script finishes, so Stop can wait
	// for it instead of leaving an orphan process behind.
	triggerDone chan struct{}

	stopOnce sync.Once
	done     chan struct{}
}

// newWatchController starts one loop. The ticker is injected so tests can drive
// ticks deterministically; nil selects the real ticker. layoutSource is queried
// on every render, so the caller passes a live read of the output boundary
// rather than a snapshot of it. runner executes the trigger script and is
// injected for the same reason as the ticker: a test must observe the invocation
// without starting a real process.
func newWatchController(parent context.Context, api InteractiveAPI, filter string, request watchRequest, ticker WatchTicker, color ColorPolicy, layoutSource func() TableLayout, runner TriggerRunner) *watchController {
	if ticker == nil {
		ticker = realWatchTicker
	}
	ticks, release := ticker(request.Interval)
	ctx, cancel := context.WithCancel(parent)
	controller := &watchController{
		api:          api,
		filter:       filter,
		request:      request,
		ticks:        ticks,
		release:      release,
		color:        color,
		layoutSource: layoutSource,
		ctx:          ctx,
		cancel:       cancel,
		runner:       runner,
		done:         make(chan struct{}),
	}
	go controller.run()
	return controller
}

// realWatchTicker is the production tick source.
func realWatchTicker(interval time.Duration) (<-chan time.Time, func()) {
	ticker := time.NewTicker(interval)
	return ticker.C, ticker.Stop
}

// run collects once immediately, then on every tick until the loop is stopped.
// The immediate collection means the operator sees the current inventory at
// once instead of waiting a whole interval for a table that is already
// available. A tick that arrives while a collection is in flight is dropped by
// the ticker channel, so a slow collection never queues a backlog of
// overlapping scans.
func (c *watchController) run() {
	defer close(c.done)
	defer c.release()
	c.collect()
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
	// The trigger runs after the table is published, so a slow script can never
	// delay the render the operator is waiting for. It runs on this goroutine
	// rather than the editor thread, so a script that blocks cannot delay a
	// keypress.
	c.fireTriggers(rows)
}

// fireTriggers runs the trigger script for every transition this collection
// observed. It is a no-op when no script was resolved, so a watch without
// --trigger keeps its previous behaviour exactly.
func (c *watchController) fireTriggers(rows []SessionRow) {
	if c.request.TriggerScript == "" {
		return
	}
	events := c.tracker.observe(rows)
	if len(events) == 0 {
		return
	}
	if c.runner == nil {
		c.publishFailure(fmt.Errorf("trigger script %q cannot run: no runner is configured", filepath.Base(c.request.TriggerScript)))
		return
	}
	for _, event := range events {
		if !c.beginTrigger() {
			// A script is still running, so this transition is dropped instead of
			// queued. A notification that cannot keep up must not accumulate a
			// backlog of events that describe a state the operator already saw.
			c.publishFailure(fmt.Errorf("trigger script %q is still running, so one %s transition was dropped", filepath.Base(c.request.TriggerScript), event.State))
			continue
		}
		c.runTrigger(event)
	}
}

// beginTrigger claims the single in-flight slot and reports whether it was free.
func (c *watchController) beginTrigger() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.triggerBusy {
		return false
	}
	c.triggerBusy = true
	c.triggerDone = make(chan struct{})
	return true
}

// runTrigger executes one script on its own goroutine and releases the in-flight
// slot when it finishes. It must not run on the collection goroutine: a script
// that blocks for its whole lifetime would otherwise stall the next collection
// and freeze the table the operator is watching. A failure is reported once
// through the same de-duplicating path as a collection failure, so a script that
// fails on every transition cannot flood the terminal.
func (c *watchController) runTrigger(event TriggerEvent) {
	path := c.request.TriggerScript
	runner := c.runner
	go func() {
		err := runner.RunTrigger(c.ctx, path, triggerEnvironment(event))
		c.mu.Lock()
		done := c.triggerDone
		c.triggerBusy = false
		c.triggerDone = nil
		c.mu.Unlock()
		if done != nil {
			close(done)
		}
		if err != nil {
			c.publishFailure(err)
		}
	}()
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
// and layout stay identical to a manual list. The writer keeps trusted SGR when
// the colour policy allows it, because the table renderer's styling is trusted
// application output; provider-derived cell text is already sanitized by
// escapeCell, so no untrusted escape can survive this seam. The layout is read
// here rather than stored, so a terminal resize during the loop is honoured on
// the next render.
func (c *watchController) render(loaded reportLoad) ([]SessionRow, []byte, error) {
	var buffer bytes.Buffer
	safe := &watchWriter{safeWriter: &safeWriter{target: &buffer, keepSGR: c.color.Enabled}, layout: c.layoutSource()}
	var rows []SessionRow
	options := tableOptionsFor(safe, c.color, listArguments{}, func(rendered []SessionRow) {
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

// Stop cancels an in-flight collection and any running trigger script, then
// waits for the loop to exit. Waiting for the script matters because the script
// is a child process: returning while it still runs would leave an orphan that
// outlives the prompt it was armed for.
func (c *watchController) Stop() {
	c.stopOnce.Do(c.cancel)
	<-c.done
	c.mu.Lock()
	done := c.triggerDone
	c.mu.Unlock()
	if done != nil {
		<-done
	}
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
	var marker bytes.Buffer
	if err := RenderWatchingPrompt(&marker, w.state.Scope, w.state.Invalidated, w.controller.color); err != nil {
		return nil, err
	}
	payload := append(marker.Bytes(), result.output...)
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
		if !ok || existing.ClusterSessionID != row.ClusterSessionID || existing.ProviderGeneration != row.ProviderGeneration || existing.EndpointID != row.EndpointID {
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
	// The script is resolved once here, at arm time, so the loop never stats a
	// path on every tick and an unusable path is reported before the operator
	// starts watching instead of after the first transition.
	script, note, err := resolveTriggerScript(request)
	if err != nil {
		return err
	}
	request.TriggerScript = script
	state.watch = &request
	mode := "projection"
	if request.Force {
		mode = "forced collection"
	}
	if _, err = fmt.Fprintf(out, "auto-refresh: %s %s (any key stops)\n", request.Interval, mode); err != nil {
		return err
	}
	if !request.TriggerSet {
		return nil
	}
	// The trigger line names the script and the transition it watches, so the
	// operator never has to guess which script is armed or when it fires. A
	// missing default script is reported as a note rather than an error, because
	// the operator asked for the convention rather than for one exact file.
	if note != "" {
		_, err = fmt.Fprintln(out, note)
		return err
	}
	_, err = fmt.Fprintf(out, "trigger: %s on %s -> %s\n", script, protocol.SessionStateRunning, protocol.SessionStateWaitingInput)
	return err
}

// startWatch activates the armed auto-refresh intent for the next prompt.
// It consumes the intent, so a keypress that stops the loop cannot silently
// re-arm it on the following prompt. It returns nil when no watch was requested
// or the reader cannot observe one, so the plain read path stays byte-identical.
// out is the real output boundary, so the rendered table is fitted to the
// terminal the operator is watching instead of to the internal buffer.
func startWatch(parent context.Context, api InteractiveAPI, state *interactiveState, out io.Writer, options InteractiveOptions) WatchSession {
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
	// The layout is passed as a live read, not a snapshot, so a terminal resize
	// during the loop is honoured on the next render. The trigger runner is
	// injected rather than constructed here, so a test can observe the script
	// invocation without spawning a real process.
	controller := newWatchController(parent, api, filter, request, options.Ticks, options.Color, func() TableLayout {
		return OutputLayout(out)
	}, options.TriggerRunner)
	return &replWatch{controller: controller, state: state}
}
