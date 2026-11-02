package tui

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"strings"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// InteractiveAPI is defined as the shared CommandAPI alias in commands.go.

// InteractiveOptions controls bounded REPL behavior.
type InteractiveOptions struct {
	MaxBytes          int
	WaitTimeoutMS     int64
	LineLimit         int
	Color             ColorPolicy
	Interrupt         <-chan os.Signal
	CloseInput        bool
	watcherExit       func(bool)
	watcherBeforeDone func()
}

type reportLoad struct {
	endpoints []protocol.Endpoint
	reports   map[string]protocol.InventoryReport
	errors    map[string]error
}

type interactiveState struct {
	interactiveSelection
	commandID string
}

type interruptController struct {
	mu                 sync.Mutex
	cancel             context.CancelFunc
	promptInterrupted  bool
	commandInterrupted bool
	input              io.Closer
	promptDone         chan struct{}
	promptOnce         sync.Once
}

func (c *interruptController) setCancel(cancel context.CancelFunc) {
	c.mu.Lock()
	c.cancel = cancel
	c.mu.Unlock()
}

func (c *interruptController) clearCancel() {
	c.mu.Lock()
	c.cancel = nil
	c.mu.Unlock()
}

func (c *interruptController) interrupt() {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.cancel != nil {
		c.commandInterrupted = true
		c.cancel()
		return
	}
	c.promptInterrupted = true
	c.promptOnce.Do(func() { close(c.promptDone) })
	if c.input != nil {
		_ = c.input.Close()
	}
}

func (c *interruptController) takeCommandInterrupted() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	interrupted := c.commandInterrupted
	c.commandInterrupted = false
	return interrupted
}

func (c *interruptController) promptWasInterrupted() bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.promptInterrupted
}

type lineReadResult struct {
	line     string
	overflow bool
	err      error
}

func startInputReader(input io.Reader, limit int) (<-chan lineReadResult, *sync.WaitGroup, func()) {
	reader := bufio.NewReaderSize(input, 4096)
	results := make(chan lineReadResult, 1)
	stop := make(chan struct{})
	var stopOnce sync.Once
	var done sync.WaitGroup
	done.Add(1)
	go func() {
		defer done.Done()
		defer close(results)
		for {
			line, overflow, err := readLine(reader, limit)
			result := lineReadResult{line: line, overflow: overflow, err: err}
			select {
			case results <- result:
			case <-stop:
				return
			}
			if err != nil {
				return
			}
		}
	}()
	return results, &done, func() { stopOnce.Do(func() { close(stop) }) }
}

// RunInteractive executes the stream-driven operator REPL.
func RunInteractive(parent context.Context, api InteractiveAPI, input io.Reader, output, errors io.Writer, options InteractiveOptions) error {
	if api == nil {
		return fmt.Errorf("interactive API is unavailable")
	}
	if input == nil || output == nil || errors == nil {
		return fmt.Errorf("interactive streams are unavailable")
	}
	if options.MaxBytes <= 0 {
		options.MaxBytes = 64 << 10
	}
	if options.LineLimit <= 0 {
		options.LineLimit = 8192
	}
	controller := &interruptController{promptDone: make(chan struct{})}
	if options.CloseInput {
		if closer, ok := input.(io.Closer); ok {
			controller.input = closer
		}
	}
	stopWatcher := make(chan struct{})
	var watcher sync.WaitGroup
	watcherDone := make(chan struct{})
	if options.Interrupt != nil {
		watcher.Add(1)
		go func() {
			defer close(watcherDone)
			defer watcher.Done()
			select {
			case <-options.Interrupt:
				controller.interrupt()
			case <-stopWatcher:
			}
			if options.watcherBeforeDone != nil {
				options.watcherBeforeDone()
			}
		}()
	}
	defer func() {
		close(stopWatcher)
		watcher.Wait()
		if options.watcherExit != nil {
			joined := false
			select {
			case <-watcherDone:
				joined = true
			default:
			}
			options.watcherExit(joined)
		}
	}()
	out := newSafeWriter(output)
	errOut := newSafeWriter(errors)
	lineResults, inputReaderDone, stopInputReader := startInputReader(input, options.LineLimit)
	waitForInputReader := input != os.Stdin
	defer func() {
		stopInputReader()
		if options.CloseInput && controller.input != nil {
			_ = controller.input.Close()
		}
		if waitForInputReader {
			inputReaderDone.Wait()
		}
	}()
	state := interactiveState{}
	for {
		if controller.promptWasInterrupted() {
			return ErrInteractiveInterrupt
		}
		if err := writePrompt(output, state, options.Color); err != nil {
			return err
		}
		var line string
		var overflow bool
		var err error
		select {
		case result, ok := <-lineResults:
			if !ok {
				return nil
			}
			line, overflow, err = result.line, result.overflow, result.err
		case <-controller.promptDone:
			return ErrInteractiveInterrupt
		}
		if overflow {
			if _, writeErr := fmt.Fprintln(errOut, "input line exceeds the maximum length"); writeErr != nil {
				return writeErr
			}
			if err == io.EOF {
				return nil
			}
			continue
		}
		if err != nil && err != io.EOF {
			return err
		}
		line = strings.TrimSpace(strings.TrimSuffix(line, "\r"))
		if line == "" {
			if err == io.EOF {
				return nil
			}
			continue
		}
		commandCtx, cancel := context.WithCancel(parent)
		controller.setCancel(cancel)
		exit, execErr := executeInteractiveLine(commandCtx, api, &state, line, lineResults, out, output, errOut, options)
		controller.clearCancel()
		cancel()
		if controller.takeCommandInterrupted() {
			if _, writeErr := fmt.Fprintln(errOut, "interrupted"); writeErr != nil {
				return writeErr
			}
			continue
		}
		if execErr != nil {
			if _, writeErr := fmt.Fprintln(errOut, "error:", execErr); writeErr != nil {
				return writeErr
			}
		}
		if exit || err == io.EOF {
			return nil
		}
	}
}

// ErrInteractiveInterrupt marks an interrupt received while reading the prompt.
var ErrInteractiveInterrupt = fmt.Errorf("interactive interrupted")

func executeInteractiveLine(ctx context.Context, api InteractiveAPI, state *interactiveState, line string, lineResults <-chan lineReadResult, out, trustedOut, errOut io.Writer, options InteractiveOptions) (bool, error) {
	name, rest := splitCommand(line)
	switch name {
	case "help", "?":
		return false, printHelp(out)
	case "quit", "exit":
		if strings.TrimSpace(rest) != "" {
			return false, fmt.Errorf("usage: %s", name)
		}
		return true, nil
	case "list":
		return false, interactiveList(ctx, api, strings.TrimSpace(rest), out)
	case "table":
		return false, interactiveTable(ctx, api, strings.TrimSpace(rest), trustedOut, errOut, options.Color)
	case "use":
		return false, interactiveUse(ctx, api, state, rest)
	case "show":
		return false, interactiveShow(ctx, api, state, strings.TrimSpace(rest), out)
	case "logs":
		return false, interactiveLogs(ctx, api, state, strings.TrimSpace(rest), options.MaxBytes, out)
	case "status":
		return false, interactiveStatus(ctx, api, state, strings.TrimSpace(rest), out)
	case "refresh":
		return false, interactiveRefresh(ctx, api, state, out)
	case "send":
		return false, interactiveSend(ctx, api, state, rest, lineResults, out, options)
	default:
		return false, fmt.Errorf("unknown command %q (try help)", name)
	}
}

func splitCommand(line string) (string, string) {
	parts := strings.SplitN(strings.TrimSpace(line), " ", 2)
	name := parts[0]
	if len(parts) == 1 {
		return name, ""
	}
	return name, parts[1]
}

func readLine(reader *bufio.Reader, limit int) (string, bool, error) {
	var line strings.Builder
	for {
		fragment, err := reader.ReadSlice('\n')
		if line.Len()+len(fragment) > limit {
			for err == bufio.ErrBufferFull {
				fragment, err = reader.ReadSlice('\n')
				if strings.HasSuffix(string(fragment), "\n") {
					break
				}
			}
			return "", true, err
		}
		line.Write(fragment)
		if err == nil || err == io.EOF {
			return strings.TrimSuffix(line.String(), "\n"), false, err
		}
		if err != bufio.ErrBufferFull {
			return "", false, err
		}
	}
}

func writePrompt(out io.Writer, state interactiveState, policy ColorPolicy) error {
	return RenderPrompt(out, state.EndpointID, state.SessionID, state.Invalidated, policy)
}

func printHelp(out io.Writer) error {
	_, err := fmt.Fprintln(out, "commands: list [endpoint], table [endpoint], use <endpoint> <session>, show, logs, send <json>, status, refresh, help, quit")
	return err
}

func commandContext(parent context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(parent, 10*time.Second)
}

func loadReports(ctx context.Context, api InteractiveAPI, endpointFilter string) (reportLoad, error) {
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return reportLoad{}, err
	}
	loaded := reportLoad{endpoints: endpoints, reports: make(map[string]protocol.InventoryReport), errors: make(map[string]error)}
	for _, endpoint := range endpoints {
		if endpointFilter != "" && endpoint.EndpointID != endpointFilter {
			continue
		}
		report, fetchErr := api.GetInventory(ctx, endpoint.EndpointID)
		if fetchErr != nil {
			loaded.errors[endpoint.EndpointID] = fetchErr
			continue
		}
		loaded.reports[endpoint.EndpointID] = report
	}
	return loaded, nil
}

func interactiveTable(parent context.Context, api InteractiveAPI, filter string, out, errors io.Writer, color ColorPolicy) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	return (CommandRunner{API: api, Policy: InteractivePolicy}).Table(ctx, out, errors, filter, false, TableOptions{Color: color})
}

func interactiveList(parent context.Context, api InteractiveAPI, filter string, out io.Writer) error {
	ctx, cancel := commandContext(parent)
	defer cancel()
	return (CommandRunner{API: api, Policy: InteractivePolicy}).List(ctx, out, filter, false)
}

func findSelected(ctx context.Context, api InteractiveAPI, state *interactiveState) (protocol.Endpoint, protocol.InventoryReport, *protocol.Session, error) {
	if err := state.requireUsable(); err != nil {
		return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
	}
	loaded, err := loadReports(ctx, api, state.EndpointID)
	if err != nil {
		return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
	}
	for _, endpoint := range loaded.endpoints {
		if endpoint.EndpointID != state.EndpointID {
			continue
		}
		report, ok := loaded.reports[endpoint.EndpointID]
		if !ok || !report.ReportComplete {
			return protocol.Endpoint{}, protocol.InventoryReport{}, nil, fmt.Errorf("endpoint %q inventory is unavailable", state.EndpointID)
		}
		for index := range report.Sessions {
			if report.Sessions[index].SessionID != state.SessionID {
				continue
			}
			session := &report.Sessions[index]
			if err := validateSessionFreshness(report, *session); err != nil {
				return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
			}
			if err := validateAdapterFreshness(report, session.AdapterID); err != nil {
				return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
			}
			if session.Generation == "" || session.Generation != state.Generation {
				state.invalidate("selected session generation changed")
				return protocol.Endpoint{}, protocol.InventoryReport{}, nil, fmt.Errorf("selected session generation changed; use the session again")
			}
			return endpoint, report, session, nil
		}
	}
	return protocol.Endpoint{}, protocol.InventoryReport{}, nil, fmt.Errorf("selected session %q was not found", state.SessionID)
}

func interactiveUse(parent context.Context, api InteractiveAPI, state *interactiveState, rest string) error {
	args := strings.Fields(rest)
	if len(args) == 1 && args[0] == "clear" {
		*state = interactiveState{}
		return nil
	}
	if len(args) != 2 {
		return fmt.Errorf("usage: use <endpoint> <session>")
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	loaded, err := loadReports(ctx, api, args[0])
	if err != nil {
		return err
	}
	for _, endpoint := range loaded.endpoints {
		report, ok := loaded.reports[endpoint.EndpointID]
		if endpoint.EndpointID != args[0] || !ok || !report.ReportComplete {
			continue
		}
		for _, session := range report.Sessions {
			if session.SessionID != args[1] || session.Generation == "" {
				continue
			}
			if freshnessErr := validateSessionFreshness(report, session); freshnessErr != nil {
				return freshnessErr
			}
			if freshnessErr := validateAdapterFreshness(report, session.AdapterID); freshnessErr != nil {
				return freshnessErr
			}
			state.reset(args[0], args[1], session.Generation)
			return nil
		}
	}
	return fmt.Errorf("session %q was not found on endpoint %q", args[1], args[0])
}

func validateSessionFreshness(report protocol.InventoryReport, session protocol.Session) error {
	collectionStatus := session.CollectionStatus
	if collectionStatus == "" {
		collectionStatus = report.CollectionStatus
	}
	if session.Stale || session.Unknown || collectionStatus != protocol.CollectionSucceeded {
		return fmt.Errorf("session %q is not fresh: stale=%t unknown=%t collection_status=%s", session.SessionID, session.Stale, session.Unknown, collectionStatus)
	}
	return nil
}

func validateAdapterFreshness(report protocol.InventoryReport, adapterID string) error {
	for _, adapter := range report.Adapters {
		if adapter.AdapterID != adapterID {
			continue
		}
		if adapter.Stale || !adapter.DataKnown || adapter.CollectionStatus != protocol.CollectionSucceeded {
			return fmt.Errorf("adapter %q is not fresh: stale=%t unknown=%t collection_status=%s", adapterID, adapter.Stale, !adapter.DataKnown, adapter.CollectionStatus)
		}
		return nil
	}
	// Adapter freshness is optional when no matching summary is present.
	return nil
}

func interactiveRefresh(parent context.Context, api InteractiveAPI, state *interactiveState, out io.Writer) error {
	if state.EndpointID == "" {
		return interactiveList(parent, api, "", out)
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	_, _, session, err := findSelected(ctx, api, state)
	if err != nil {
		return err
	}
	_ = session
	return nil
}

func interactiveShow(parent context.Context, api InteractiveAPI, state *interactiveState, id string, out io.Writer) error {
	if state.Invalidated {
		return state.requireUsable()
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	if id == "" {
		if err := state.requireUsable(); err != nil {
			return err
		}
		_, _, session, err := findSelected(ctx, api, state)
		if err != nil {
			return err
		}
		id = session.SessionID
	}
	return (CommandRunner{API: api, Policy: InteractivePolicy}).Show(ctx, out, id, false)
}
