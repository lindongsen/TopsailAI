package tui

import (
	"bufio"
	"context"
	stderrors "errors"
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
	ReadLine      InteractiveLineReader
	MaxBytes      int
	MaxLines      int
	WaitTimeoutMS int64
	LineLimit     int
	Color         ColorPolicy
	Interrupt     <-chan os.Signal
	CloseInput    bool
	// WatchReader is the tick-capable reader used by the auto-refresh loop. It is
	// a separate seam because ReadLine is a function value and cannot be type
	// asserted, and because a reader without it must refuse watch explicitly.
	WatchReader WatchLineReader
	// ProgressWriter receives progress lines for long-running commands. It is a
	// separate seam because the REPL diagnostics writer sanitizes untrusted text
	// and therefore cannot report a progress boundary itself. A nil writer keeps
	// the REPL silent, so a caller that supplies none loses nothing.
	ProgressWriter io.Writer
	// Ticks injects the auto-refresh tick source; nil selects the real ticker.
	Ticks             WatchTicker
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
	Scope     ScopeState
	commandID string
	// watch is the armed auto-refresh intent; it is consumed by the next prompt.
	watch *watchRequest
	// history is the row-number namespace produced by the most recent history
	// render. It is nil until history renders, and rendering a list clears it, so
	// a number always means the row of the table the operator last saw.
	history *historyNamespace
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
	if options.MaxLines <= 0 {
		options.MaxLines = 100
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
	if err := parent.Err(); err != nil {
		return err
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
	var lineResults <-chan lineReadResult
	var inputReaderDone *sync.WaitGroup
	stopInputReader := func() {}
	if options.ReadLine == nil {
		lineResults, inputReaderDone, stopInputReader = startInputReader(input, options.LineLimit)
	}
	waitForInputReader := input != os.Stdin
	defer func() {
		stopInputReader()
		if options.CloseInput && controller.input != nil {
			_ = controller.input.Close()
		}
		if waitForInputReader && inputReaderDone != nil {
			inputReaderDone.Wait()
		}
	}()
	state := interactiveState{}
	// The workspace inventory is rendered once before the first prompt.
	if err := runStartupList(parent, api, &state, controller, output, errOut, options.Color); err != nil {
		return err
	}
	if err := parent.Err(); err != nil {
		return err
	}
	consecutivePromptFailures := 0
	for {
		if err := parent.Err(); err != nil {
			return err
		}
		if controller.promptWasInterrupted() {
			return ErrInteractiveInterrupt
		}
		if err := writePrompt(output, state, options.Color); err != nil {
			return err
		}
		var line string
		var overflow bool
		var err error
		if options.ReadLine != nil {
			var prompt strings.Builder
			if promptErr := writePrompt(&prompt, state, options.Color); promptErr != nil {
				return promptErr
			}
			readCtx, cancelRead := context.WithCancel(parent)
			stopPrompt := context.AfterFunc(promptContext(controller.promptDone), cancelRead)
			// An armed auto-refresh loop starts before the read, because a blocking
			// read cannot be interrupted from outside. The reader stops it on the
			// first keypress, so the loop never outlives the prompt it serves.
			watch := startWatch(readCtx, api, &state, output, options)
			if watch != nil && options.WatchReader != nil {
				line, overflow, err = options.WatchReader.ReadLineWithWatch(readCtx, prompt.String(), true, options.LineLimit, watch)
			} else {
				line, overflow, err = options.ReadLine(readCtx, prompt.String(), true, options.LineLimit)
			}
			if watch != nil {
				watch.Stop()
			}
			stopPrompt()
			cancelRead()
			if controller.promptWasInterrupted() {
				return ErrInteractiveInterrupt
			}
		} else {
			select {
			case <-parent.Done():
				return parent.Err()
			case result, ok := <-lineResults:
				if !ok {
					return nil
				}
				line, overflow, err = result.line, result.overflow, result.err
			case <-controller.promptDone:
				return ErrInteractiveInterrupt
			}
		}
		if overflow {
			if writeErr := writeInteractiveError(errOut, "", fmt.Errorf("input line exceeds the maximum length")); writeErr != nil {
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
		if parentErr := parent.Err(); parentErr != nil {
			return parentErr
		}
		line = strings.TrimSpace(strings.TrimSuffix(line, "\r"))
		if line == "" {
			if err == io.EOF {
				return nil
			}
			continue
		}
		var promptFailure error
		var promptRecoverable bool
		commandCtx, cancel := context.WithCancel(parent)
		if options.ReadLine != nil {
			commandCtx = context.WithValue(commandCtx, promptReaderKey{}, promptReaderConfig{read: options.ReadLine, limit: options.LineLimit, color: options.Color, failure: &promptFailure, recoverable: &promptRecoverable})
		}
		controller.setCancel(cancel)
		exit, execErr := executeInteractiveLine(commandCtx, api, &state, line, lineResults, out, output, errOut, options)
		controller.clearCancel()
		cancel()
		if parentErr := parent.Err(); options.ReadLine != nil && parentErr != nil {
			return parentErr
		}
		if options.ReadLine != nil && controller.takeCommandInterrupted() {
			if _, writeErr := fmt.Fprintln(errOut, "interrupted"); writeErr != nil {
				return writeErr
			}
			continue
		}
		if promptFailure != nil {
			if stderrors.Is(promptFailure, ErrInteractiveInterrupt) {
				execErr = promptFailure
			} else if promptFailure == io.EOF {
				return nil
			} else if promptRecoverable {
				// A failed human answer cancels only the current operation; the REPL
				// stays alive so the operator can retry. Repeated failures mean the
				// input source is unusable, so the third one terminates the session.
				consecutivePromptFailures++
				if consecutivePromptFailures >= maxConsecutivePromptFailures {
					return promptFailure
				}
				if writeErr := writeInteractiveError(errOut, diagnosticCommandName(line), promptFailure); writeErr != nil {
					return writeErr
				}
				continue
			} else {
				// Wizard prompts are not recoverable: an unusable answer stream must
				// abort the command instead of silently continuing.
				return promptFailure
			}
		}
		consecutivePromptFailures = 0
		if stderrors.Is(execErr, ErrInteractiveInterrupt) {
			if _, writeErr := fmt.Fprintln(errOut, "interrupted"); writeErr != nil {
				return writeErr
			}
			continue
		}
		if fatal := unwrapStartTermination(execErr); fatal != nil {
			return fatal
		}
		if parentErr := parent.Err(); parentErr != nil {
			return parentErr
		}
		if controller.takeCommandInterrupted() {
			if _, writeErr := fmt.Fprintln(errOut, "interrupted"); writeErr != nil {
				return writeErr
			}
			continue
		}
		if isStartPromptEOF(execErr) {
			return nil
		}
		if execErr != nil {
			commandName := diagnosticCommandName(line)
			if writeErr := writeInteractiveError(errOut, commandName, execErr); writeErr != nil {
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

// maxConsecutivePromptFailures bounds tolerated prompt read failures before the REPL exits.
const maxConsecutivePromptFailures = 3

func executeInteractiveLine(ctx context.Context, api InteractiveAPI, state *interactiveState, line string, lineResults <-chan lineReadResult, out, trustedOut, errOut io.Writer, options InteractiveOptions) (bool, error) {
	// The allowlisted-command prefix is recognised before the command word is
	// split. commandAllowed returns true for an unknown name, so a later position
	// would let "!git status" reach the dispatcher as a command named "!git" and
	// report an unknown command instead of running the command.
	if isShellLine(line) {
		return false, runShellCommand(ctx, api, state, line, trustedOut, options)
	}
	rawName, rest := commandToken(line)
	// The send prefix is resolved before tokenisation: splitCommand splits on the
	// first literal space, so ">hello world" would otherwise yield the token
	// ">hello". The prefix is disjoint from every command word, so this branch can
	// never reinterpret a command or a typo as a message.
	if strings.HasPrefix(line, sendPrefix) {
		rawName, rest = sendPrefix, strings.TrimPrefix(line, sendPrefix)
	} else if candidate, token, surplus := numericInput(line); candidate {
		if surplus {
			return false, fmt.Errorf("usage: cd [target]")
		}
		rawName, rest = "cd", token
	}
	name := canonicalCommandName(rawName)
	// Scope availability is enforced once, before any command-specific parsing.
	if err := requireCommandScope(rawName, state.Scope.Kind); err != nil {
		return false, err
	}
	// "quit" outside workspace scope navigates back to workspace scope instead of
	// leaving the REPL, and "q" is only an alias of "quit", so both spellings share
	// this one rule rather than carrying separate behaviour. It reuses the bare-cd
	// path, so the pinned session selection is cleared and the workspace table is
	// re-rendered exactly like "cd". A surplus argument stays a usage error, so
	// "quit foo" can never be read as a navigation target. "exit" is a separate
	// canonical command and is not affected, so it always leaves the process.
	if quitReturnsToWorkspace(name, state.Scope.Kind) {
		if strings.TrimSpace(rest) != "" {
			return false, fmt.Errorf("usage: %s", name)
		}
		return false, interactiveCD(ctx, api, state, "", lineResults, out, trustedOut, options.Color, options)
	}
	switch name {
	case "help":
		return false, printHelp(out, strings.TrimSpace(rest), state.Scope.Kind)
	case "quit":
		if strings.TrimSpace(rest) != "" {
			return false, fmt.Errorf("usage: %s", name)
		}
		return true, nil
	case "exit":
		// "exit" always leaves the process from every scope, so it never navigates
		// and never inherits the scope-aware "quit" behaviour.
		if strings.TrimSpace(rest) != "" {
			return false, fmt.Errorf("usage: %s", name)
		}
		return true, nil
	case "list":
		filter, clean, err := parseListArguments(rest)
		if err != nil {
			return false, err
		}
		return false, interactiveList(ctx, api, state, filter, clean, trustedOut, errOut, options.Color)
	case "endpoints":
		// The endpoint table is trusted application styling over sanitized cells,
		// so it renders through the trusted writer like list and refresh.
		return false, interactiveEndpoints(ctx, api, rest, trustedOut, options.Color)
	case "history":
		// The history table is trusted application styling over sanitized cells,
		// so it renders through the trusted writer like list and endpoints.
		return false, interactiveHistory(ctx, api, state, rest, trustedOut, errOut, options.Color)
	case "table":
		return false, fmt.Errorf(`"table" has been removed; use "list --clean" for the previous behavior`)
	case "use":
		return false, fmt.Errorf(`"use" has been removed; use "cd" to navigate`)
	case "cd":
		return false, interactiveCD(ctx, api, state, rest, lineResults, out, trustedOut, options.Color, options)
	case "show":
		if err := rejectInteractiveOption("show", rest); err != nil {
			return false, err
		}
		return false, interactiveShow(ctx, api, state, strings.TrimSpace(rest), out)
	case "info":
		if err := rejectInteractiveOption("info", rest); err != nil {
			return false, err
		}
		return false, interactiveInfo(ctx, api, state, rest, out)
	case "logs":
		return false, interactiveLogs(ctx, api, state, strings.TrimSpace(rest), options.MaxBytes, options.MaxLines, trustedOut, options.Color)
	case "status":
		return false, interactiveStatus(ctx, api, state, strings.TrimSpace(rest), out)
	case "refresh":
		return false, interactiveRefresh(ctx, api, state, trustedOut, errOut, options.Color)
	case "watch":
		return false, interactiveWatch(api, state, rest, trustedOut, options)
	case "start":
		if query, ok := api.(LaunchQuerier); ok && !strings.Contains(rest, "--") {
			recorder := &startOutputRecorder{}
			startOut := newRecordingWriter(out, recorder)
			startTrustedOut := newRecordingWriter(trustedOut, recorder)
			err := projectLaunch(ctx, api, query, state, rest, lineResults, startOut, startTrustedOut, options)
			if stderrors.Is(err, errLaunchQuit) {
				return true, startOutputError(nil, recorder, startOut)
			}
			if stderrors.Is(err, errLaunchRefresh) {
				if _, writeErr := fmt.Fprintln(startOut, "start cancelled"); writeErr != nil {
					return false, startOutputError(writeErr, recorder, startOut)
				}
				return false, startOutputError(interactiveRefresh(ctx, api, state, trustedOut, errOut, options.Color), recorder, startOut)
			}
			return false, startOutputError(err, recorder, startOut)
		}
		draft, err := parseInteractiveStartDraft(rest)
		if err != nil {
			return false, err
		}
		recorder := &startOutputRecorder{}
		startOut := newRecordingWriter(out, recorder)
		startTrustedOut := newRecordingWriter(trustedOut, recorder)
		startErrOut := newRecordingWriter(errOut, recorder)
		outcome, request, promptErr := runStartPrompt(ctx, *state, draft, lineResults, startOut, startErrOut, options.Color)
		if promptErr != nil {
			return false, startOutputError(promptErr, recorder, startOut, startTrustedOut, startErrOut)
		}
		var commandErr error
		switch outcome {
		case startPromptQuit:
			return true, startOutputError(nil, recorder, startOut, startTrustedOut, startErrOut)
		case startPromptRefresh:
			if _, writeErr := fmt.Fprintln(startOut, "start cancelled"); writeErr != nil {
				commandErr = writeErr
				break
			}
			commandErr = interactiveRefresh(ctx, api, state, startTrustedOut, startErrOut, options.Color)
		case startPromptCancel:
			commandErr = nil
		default:
			if err := ctx.Err(); err != nil {
				return false, err
			}
			commandErr = interactiveStart(ctx, api, state, request, startOut, startTrustedOut, options)
		}
		return false, startOutputError(commandErr, recorder, startOut, startTrustedOut, startErrOut)
	case "resume":
		// Resume authorizes on the provider session being absent, so it is
		// dispatched from the history namespace rather than the live one.
		return false, interactiveResume(ctx, api, state, rest, lineResults, out, trustedOut, options)
	case "stop":
		return false, interactiveStop(ctx, api, state, rest, lineResults, out, trustedOut, options)
	case "inject", "btw":
		return false, interactiveSessionPayload(ctx, api, state, protocol.OperationContextInject, name, rest, lineResults, out, trustedOut, options)
	case "interrupt", "control":
		return false, interactiveSessionPayload(ctx, api, state, protocol.OperationExecutionInterrupt, name, rest, lineResults, out, trustedOut, options)
	case "drive":
		return false, interactiveDrive(ctx, api, state, rest, lineResults, out, trustedOut, options)
	case "send":
		return false, interactiveSend(ctx, api, state, rest, lineResults, out, trustedOut, options)
	case "ctl":
		return false, interactiveCtl(ctx, api, state, rest, lineResults, out, trustedOut, options)
	default:
		return false, offerSendForUnknownInput(ctx, api, state, line, name, lineResults, out, trustedOut, options)
	}
}

// numericInput classifies only a whole-line ASCII decimal first token.
func numericInput(line string) (candidate bool, token string, surplus bool) {
	fields := strings.Fields(line)
	if len(fields) == 0 || !isASCIIDecimal(fields[0]) {
		return false, "", false
	}
	return true, fields[0], len(fields) > 1
}

// diagnosticCommandName keeps numeric shorthand errors on the cd help path.
func diagnosticCommandName(line string) string {
	if candidate, _, _ := numericInput(line); candidate {
		return "cd"
	}
	name, _ := commandToken(line)
	return name
}

// commandToken splits a REPL line and strips the optional leading command
// prefix from the command word only. The prefix is a form, not an alias: it is
// removed before alias and scope resolution, and never from the argument text,
// so a payload such as "send /help" keeps its literal slash.
func commandToken(line string) (string, string) {
	name, rest := splitCommand(line)
	return trimCommandPrefix(name), rest
}

// trimCommandPrefix removes one leading slash from a non-empty command word.
// A bare "/" is left intact so it stays an unknown command instead of silently
// becoming an empty line.
func trimCommandPrefix(name string) string {
	if len(name) > 1 && strings.HasPrefix(name, "/") {
		return name[1:]
	}
	return name
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
	return RenderPrompt(out, state.Scope, state.Invalidated, policy)
}

func printHelp(out io.Writer, target string, kind ScopeKind) error {
	return PrintScopedCommandHelp(out, target, kind)
}

// nonSyntaxError marks a failure that is not an argument-syntax problem, so the
// diagnostic omits the usage line instead of telling the operator to fix syntax.
// The optional next hint replaces the generic syntax advice.
type nonSyntaxError struct {
	message string
	next    string
}

// Error implements error.
func (e nonSyntaxError) Error() string { return e.message }

// writeInteractiveError renders one actionable three-line diagnostic.
func writeInteractiveError(out io.Writer, command string, err error) error {
	canonical := canonicalCommandName(command)
	cause := err.Error()
	usage := ""
	if strings.HasPrefix(cause, "usage: ") {
		usage = strings.TrimPrefix(cause, "usage: ")
		cause = "invalid arguments"
	}
	if usage == "" {
		if entry, ok := commandHelpCatalog[canonical]; ok {
			usage = entry.syntax
		} else {
			usage = "help"
		}
	}
	next := "Run help " + canonical + " for valid syntax."
	if _, known := commandHelpCatalog[canonical]; !known {
		next = "Run help or help all to see valid commands."
	}
	if marker := "use status "; strings.Contains(cause, marker) {
		statusPart := strings.SplitN(strings.SplitN(cause, marker, 2)[1], ";", 2)[0]
		commandID := strings.Fields(statusPart)[0]
		next = "Run status " + commandID + " to query the existing command."
	}
	if strings.HasPrefix(cause, "input line exceeds") {
		usage = "interactive command"
		next = "Shorten the input line and retry."
	}
	// A non-syntax failure keeps the cause and the remedy but drops the usage
	// line, because the operator's command shape was already valid.
	var notSyntax nonSyntaxError
	if stderrors.As(err, &notSyntax) {
		usage = ""
		if notSyntax.next != "" {
			next = notSyntax.next
		} else {
			next = "Run endpoints to list valid endpoint identifiers."
		}
	}
	if _, writeErr := fmt.Fprintln(out, "error:", cause); writeErr != nil {
		return writeErr
	}
	if usage != "" {
		if _, writeErr := fmt.Fprintln(out, "usage:", usage); writeErr != nil {
			return writeErr
		}
	}
	_, writeErr := fmt.Fprintln(out, "next:", next)
	return writeErr
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

func interactiveList(parent context.Context, api InteractiveAPI, state *interactiveState, filter string, clean bool, out, errors io.Writer, color ColorPolicy) error {
	scoped, err := scopedListFilter(state, filter)
	if err != nil {
		return err
	}
	state.Rows = nil
	// A list render restores the live namespace, so a history row number can
	// never survive into a table that no longer shows history rows.
	state.history = nil
	staged := make([]SessionRow, 0)
	ctx, cancel := commandContext(parent)
	defer cancel()
	err = (CommandRunner{API: api, Policy: InteractivePolicy}).ListWithOptions(ctx, out, errors, scoped, false, tableOptionsFor(out, color, clean, func(rows []SessionRow) { staged = append(staged, rows...) }))
	if err != nil {
		state.Rows = nil
		return err
	}
	state.setRows(staged)
	return nil
}

func parseListArguments(rest string) (string, bool, error) {
	parts := strings.Fields(rest)
	filter := ""
	clean := false
	for _, part := range parts {
		if part == "--clean" {
			if clean {
				return "", false, fmt.Errorf("usage: list [endpoint] [--clean]")
			}
			clean = true
			continue
		}
		if strings.HasPrefix(part, "-") {
			return "", false, fmt.Errorf("option %q is available only in non-interactive mode; JSON output is available only with the standalone command", part)
		}
		if filter != "" {
			return "", false, fmt.Errorf("usage: list [endpoint] [--clean]")
		}
		filter = part
	}
	return filter, clean, nil
}

func rejectInteractiveOption(command, rest string) error {
	for _, part := range strings.Fields(rest) {
		if strings.HasPrefix(part, "-") {
			return fmt.Errorf("option %q is available only in non-interactive mode; JSON output is available only with the standalone command", part)
		}
	}
	return nil
}

func findSelected(ctx context.Context, api InteractiveAPI, state *interactiveState) (protocol.Endpoint, protocol.InventoryReport, *protocol.Session, error) {
	if err := state.requireUsable(); err != nil {
		return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
	}
	loaded, err := loadReports(ctx, api, state.EndpointID)
	if err != nil {
		return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
	}
	return findSelectedIn(loaded, state)
}

// findSelectedIn revalidates the pinned selection against an already loaded
// inventory, so a caller that also renders that load performs one API round trip.
func findSelectedIn(loaded reportLoad, state *interactiveState) (protocol.Endpoint, protocol.InventoryReport, *protocol.Session, error) {
	if err := state.requireUsable(); err != nil {
		return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
	}
	for _, endpoint := range loaded.endpoints {
		if endpoint.EndpointID != state.EndpointID {
			continue
		}
		if err := validateEndpointOnline(endpoint); err != nil {
			return protocol.Endpoint{}, protocol.InventoryReport{}, nil, err
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
	// The endpoint no longer reports the pinned session, so the selection can never be
	// resolved again; name the recovery step instead of leaving the operator to guess.
	return protocol.Endpoint{}, protocol.InventoryReport{}, nil, fmt.Errorf("selected session %q was not found; use cd .. to leave the session scope", state.SessionID)
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

// interactiveRefresh forces one fresh Endpoint collection in the current scope and
// renders the committed inventory, so the operator sees fresh data rather than a
// cached Server projection. In session scope it revalidates the pinned selection
// against that same committed document, so a changed generation still invalidates
// the selection instead of silently retargeting it.
func interactiveRefresh(parent context.Context, api InteractiveAPI, state *interactiveState, out, errors io.Writer, color ColorPolicy) error {
	ctx, cancel := context.WithTimeout(parent, refreshCommandTimeout)
	defer cancel()
	scoped, err := scopedListFilter(state, "")
	if err != nil {
		return err
	}
	state.Rows = nil
	staged := make([]SessionRow, 0)
	loaded, err := forceCollection(ctx, api, scoped)
	if err != nil {
		state.Rows = nil
		return err
	}
	// Endpoint and session scope name one exact Endpoint, so its failure is the
	// operator's answer; workspace scope reports per-Endpoint failures as
	// diagnostics while still rendering the healthy Endpoints.
	if state.Scope.Kind != ScopeWorkspace {
		if refreshErr, failed := loaded.errors[state.Scope.EndpointID]; failed {
			state.Rows = nil
			return refreshErr
		}
	}
	if state.Scope.Kind == ScopeSession {
		if _, _, _, err := findSelectedIn(loaded, state); err != nil {
			state.Rows = nil
			return err
		}
	}
	err = renderListRows(out, errors, loaded, scoped, false, tableOptionsFor(out, color, false, func(rows []SessionRow) { staged = append(staged, rows...) }))
	if err != nil {
		state.Rows = nil
		return err
	}
	state.setRows(staged)
	return nil
}

// interactiveShow renders the current scope target or an explicit target.
// A bare ASCII row number selects the session from the most recently rendered
// list, so the operator never has to type a provider session identifier.
func interactiveShow(parent context.Context, api InteractiveAPI, state *interactiveState, id string, out io.Writer) error {
	if state.Invalidated {
		return state.requireUsable()
	}
	ctx, cancel := commandContext(parent)
	defer cancel()
	if id == "" {
		switch state.Scope.Kind {
		case ScopeWorkspace:
			return fmt.Errorf("show requires an endpoint or session in workspace scope; use show <number> for a session row or show <endpoint-id>")
		case ScopeEndpoint:
			id = state.Scope.EndpointID
		default:
			_, _, session, err := findSelected(ctx, api, state)
			if err != nil {
				return err
			}
			id = session.SessionID
		}
	} else {
		row, resolved, err := resolveSessionToken(state, id)
		if err != nil {
			return err
		}
		if resolved {
			id = row.SessionID
		}
	}
	if err := (CommandRunner{API: api, Policy: InteractivePolicy}).Show(ctx, out, id, false); err != nil {
		return numericTokenHint(id, err)
	}
	return nil
}
