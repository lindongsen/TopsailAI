package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strconv"
	"strings"

	"github.com/mattn/go-isatty"

	"topsailai_agent_cluster/internal/client"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

func main() {
	if err := prepareExecutableEnv(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	os.Exit(runExitCode(os.Args[1:], os.Stdin, os.Stdout, os.Stderr, defaultTerminalDetector))
}

func run(args []string) error {
	_, err := runWithExitCode(args, os.Stdin, os.Stdout, os.Stderr, defaultTerminalDetector)
	return err
}

func runExitCode(args []string, input io.Reader, output, errors io.Writer, terminal TerminalDetector) int {
	interrupts := make(chan os.Signal, 1)
	signal.Notify(interrupts, os.Interrupt)
	defer signal.Stop(interrupts)
	code, _ := runWithSignals(args, input, output, errors, terminal, interrupts)
	return code
}

type TerminalDetector func() bool

func defaultTerminalDetector() bool {
	fd := os.Stdin.Fd()
	return isatty.IsTerminal(fd) || isatty.IsCygwinTerminal(fd)
}

func runWithExitCode(args []string, input io.Reader, output, errors io.Writer, terminal TerminalDetector) (int, error) {
	return runWithSignals(args, input, output, errors, terminal, nil)
}

func runWithSignals(args []string, input io.Reader, output, errorOutput io.Writer, terminal TerminalDetector, interrupts <-chan os.Signal) (int, error) {
	if terminal == nil {
		terminal = func() bool { return false }
	}
	err := runWithIO(args, input, output, errorOutput, terminal(), interrupts)
	if err != nil {
		if errors.Is(err, tui.ErrInteractiveInterrupt) {
			return 130, err
		}
		if _, writeErr := fmt.Fprintln(errorOutput, err); writeErr != nil {
			return 2, writeErr
		}
		return 2, err
	}
	return 0, nil
}

func runWithIO(args []string, input io.Reader, output, errors io.Writer, terminal bool, interrupts <-chan os.Signal) error {
	flags := flag.NewFlagSet("agent-cluster-cli", flag.ContinueOnError)
	flags.SetOutput(errors)
	flags.Usage = func() {
		writeUsage(errors, flags)
	}
	jsonMode := flags.Bool("json", false, "write structured JSON")
	filter := flags.String("endpoint", "", "filter by endpoint ID")
	confirmed := flags.Bool("yes", false, "confirm a mutating action")
	serverURL := flags.String("server-url", envOr("AGENT_CLUSTER_SERVER_URL", "http://127.0.0.1:8080"), "Server API URL")
	token := flags.String("token", os.Getenv("AGENT_CLUSTER_TOKEN"), "Server bearer token")
	waitTimeoutMS := flags.Int64("wait-timeout-ms", 0, "maximum local wait for command completion in milliseconds")
	maxBytes := flags.Int("max-bytes", 64<<10, "maximum output snapshot size in bytes")
	// --lines is one quantity with one meaning: how many trailing output lines a
	// read returns. Its default depends on the surface, because a script that
	// asks for a snapshot is not the same as an operator who deliberately
	// selected a session, so the interactive default is resolved after parsing
	// instead of being baked into the flag.
	lines := flags.Int("lines", 100, "maximum number of output lines returned by logs; interactive mode defaults to 300 and accepts 100-1000")
	follow := flags.Bool("follow", false, "stream output records until interrupted; logs only")
	// -f is the short spelling of --follow. Both surfaces accept it, so an
	// operator who learned it in the interactive REPL can use it here too.
	followShort := flags.Bool("f", false, "short form of --follow")
	noColor := flags.Bool("no-color", false, "disable terminal colors")
	noTruncate := flags.Bool("no-truncate", false, "disable table truncation; a narrow terminal wraps instead of clipping")
	noProgress := flags.Bool("no-progress", false, "disable progress lines for long-running commands")
	profile := flags.String("profile", "", "launch profile ID for start")
	profileRevision := flags.String("profile-revision", "", "launch profile revision for start")
	folder := flags.String("folder", "", "working folder for start")
	task := flags.String("task", "", "literal initial task text for start; no JSON is required")
	generation := flags.String("generation", "", "target generation; alternative to the positional generation argument")
	interactiveShort := flags.Bool("i", false, "start the interactive REPL (same as the interactive command)")
	// A help request is a successful request, so it is answered before flag
	// parsing: Go's flag package reports --help as flag.ErrHelp, which the caller
	// would otherwise turn into exit code 2 on stderr. The request is detected on
	// the raw arguments because flag.Parse stops at the first positional, so a
	// command-level --help would never reach the flag set at all.
	if requested, target := helpRequest(args); requested {
		if target == "" {
			writeUsage(output, flags)
			return nil
		}
		return tui.PrintNonInteractiveCommandHelp(output, target)
	}
	if err := flags.Parse(hoistTrailingFlags(args)); err != nil {
		return err
	}
	// The output boundary owns the truncation and colour policy, so every render
	// path inherits the flags without threading them through each command.
	// Colour eligibility follows the output stream: a redirected stdout cannot
	// render escape sequences even when stdin is an interactive terminal.
	output = terminalOutput{Writer: output, full: *noTruncate, color: resolveOutputColor(output, *noColor)}
	// The diagnostics boundary owns the progress decision, so a redirected stderr
	// stays silent and --no-progress disables the lines without touching colour.
	errors = resolveProgressOutput(errors, *noColor, *noProgress)
	interactiveSelected, err := resolveInteractiveSelection(*interactiveShort, flags.Args())
	if err != nil {
		return err
	}
	if !interactiveSelected && flags.NArg() == 0 {
		return fmt.Errorf("a command is required: list, show, logs, send, stop")
	}
	api := client.NewAPIClient(*serverURL, *token)
	ctx := context.Background()
	if interactiveSelected {
		if *jsonMode || *confirmed {
			return fmt.Errorf("interactive does not support --json or --yes")
		}
		if !terminal {
			return fmt.Errorf("interactive mode requires a terminal on stdin")
		}
		// The budget is validated before the editor takes the terminal, so a
		// rejected startup value never leaves the screen in raw mode.
		interactiveLines, err := resolveInteractiveLines(flags, *lines)
		if err != nil {
			return err
		}
		editor, closeEditor, editorErr := interactiveEditor(input, output)
		if editorErr != nil {
			return editorErr
		}
		defer closeEditor()
		// Colour follows the output boundary, so a REPL whose stdout is redirected
		// stays plain even though interactive mode requires a terminal on stdin.
		options := tui.InteractiveOptions{MaxBytes: *maxBytes, MaxLines: interactiveLines, WaitTimeoutMS: *waitTimeoutMS, Interrupt: interrupts, CloseInput: input == os.Stdin || interrupts != nil, Color: tui.OutputColorPolicy(output), ProgressWriter: errors}
		return tui.RunInteractive(ctx, api, input, output, errors, wireEditorReaders(options, editor))
	}
	switch flags.Arg(0) {
	case "help":
		if flags.NArg() > 2 {
			return fmt.Errorf("usage: help [command]")
		}
		target := ""
		if flags.NArg() == 2 {
			target = flags.Arg(1)
		}
		return tui.PrintNonInteractiveCommandHelp(output, target)
	case "list":
		listClean, err := parseListArgs(flags.Args()[1:], false)
		if err != nil {
			return err
		}
		return list(ctx, api, output, errors, *filter, listClean, *jsonMode, tui.OutputColorPolicy(output))
	case "refresh":
		if err := parseRefreshArgs(flags.Args()[1:]); err != nil {
			return err
		}
		return refresh(ctx, api, output, errors, *filter, *jsonMode, tui.OutputColorPolicy(output))
	case "endpoints":
		endpointFilter, err := parseEndpointsArgs(flags.Args()[1:], *filter)
		if err != nil {
			return err
		}
		return endpoints(ctx, api, output, endpointFilter, *jsonMode, tui.OutputColorPolicy(output))
	case "history":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: history <endpoint-id-or-hostname>")
		}
		return history(ctx, api, output, errors, flags.Arg(1), *jsonMode, tui.OutputColorPolicy(output))
	case "table":
		return fmt.Errorf(`"table" has been removed; use "list --clean" for the previous behavior`)
	case "show":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: show <endpoint-id-or-session-id>")
		}
		return show(ctx, api, output, flags.Arg(1), *jsonMode)
	case "info":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: info <session-id>")
		}
		return legacyRunner(api).Info(ctx, output, flags.Arg(1), *jsonMode)
	case "logs":
		if flags.NArg() != 3 {
			return fmt.Errorf("usage: logs <endpoint-id> <session-id>")
		}
		color := tui.OutputColorPolicy(output)
		if *follow || *followShort {
			// The process installs a SIGINT handler, so the default termination is
			// disabled. A standalone follow therefore has to observe the interrupt
			// itself, or Ctrl-C would be swallowed and the stream would never end.
			followCtx, stopFollow := interruptContext(ctx, interrupts)
			defer stopFollow()
			return followLogs(followCtx, api, output, flags.Arg(1), flags.Arg(2), *generation, *maxBytes, *lines, *jsonMode, color)
		}
		return logs(ctx, api, output, flags.Arg(1), flags.Arg(2), *maxBytes, *lines, *jsonMode, color)
	case "status":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: status <command-id>")
		}
		return status(ctx, api, output, flags.Arg(1), *jsonMode)
	case "drive":
		return driveWithProgress(ctx, api, output, errors, flags.Args()[1:], *confirmed, *jsonMode, *waitTimeoutMS, *generation)
	case "send", "btw", "interrupt", "control", "start", "resume", "stop":
		// A bare send, btw or start reads a multi-line block from the
		// command input. On a terminal nothing else would prompt, so the
		// operator would face a silent wait; the hint goes to the diagnostics
		// stream to keep the machine-readable output clean.
		if hint := multiLineHint(flags.Arg(0), flags.NArg(), *task, terminal); hint != "" {
			if _, err := fmt.Fprintln(errors, hint); err != nil {
				return err
			}
		}
		// Colour follows the output boundary, so a redirected stdout stays plain
		// even when stdin is an interactive terminal.
		color := tui.OutputColorPolicy(output)
		return action(ctx, api, output, input, errors, color, flags.Args(), *confirmed, *jsonMode, *waitTimeoutMS, *profile, *profileRevision, *folder, *task, *generation)
	case "ctl":
		return ctlCommandWithProgress(ctx, api, output, errors, flags.Args(), *confirmed, *jsonMode, *waitTimeoutMS, *generation)
	case "exec":
		return execCommandWithProgress(ctx, api, output, errors, flags.Args(), *confirmed, *jsonMode, *waitTimeoutMS, *generation)
	default:
		return fmt.Errorf("unknown command %q", flags.Arg(0))
	}
}

// writeUsage renders the global usage block. The flag set's own Usage hook and
// an explicit help request share it, so the two can never drift. The flag set
// writes its defaults to its configured output, so that output is redirected for
// the duration of the call; otherwise a help request answered on stdout would
// still print its options on stderr.
func writeUsage(out io.Writer, flags *flag.FlagSet) {
	previous := flags.Output()
	flags.SetOutput(out)
	defer flags.SetOutput(previous)
	fmt.Fprintln(out, "Usage: agent-cluster-cli [options] <command>")
	fmt.Fprintln(out, "Global options may also be written after the command.")
	// The help option is documented once here instead of on every command, so
	// the command list stays a list of commands rather than a list of options.
	fmt.Fprintln(out, "Every command accepts --help (or -h) for its detailed help, equivalent to help <command>.")
	fmt.Fprintln(out, "Commands:")
	for _, line := range tui.NonInteractiveCommandHelpLines() {
		fmt.Fprintln(out, "  "+line)
	}
	fmt.Fprintln(out, "Options:")
	flags.PrintDefaults()
}

// helpRequest reports whether the raw arguments ask for help and which command
// the request names. It scans the raw arguments because flag.Parse stops at the
// first positional argument, so a command-level --help would never reach the
// flag set. A "--" terminator ends the scan: after it every token is data, so
// "exec <endpoint> <resource> <generation> -- ls --help" still passes --help to
// ls instead of answering it here.
func helpRequest(args []string) (bool, string) {
	target := ""
	for index := 0; index < len(args); index++ {
		arg := args[index]
		if arg == "--" {
			return false, ""
		}
		if arg == "--help" || arg == "-h" {
			return true, target
		}
		if !strings.HasPrefix(arg, "-") || arg == "-" {
			if target == "" {
				target = arg
			}
			continue
		}
		// A value-taking global option written as a separate pair owns the next
		// argument, so a value that happens to look like an option is not
		// misread as a help request.
		name, hasValue := splitOptionName(arg)
		if !hasValue && globalOptionNames[name] && !booleanGlobalOptions[name] && index+1 < len(args) && !strings.HasPrefix(args[index+1], "-") {
			index++
		}
	}
	return false, ""
}

// resolveInteractiveSelection decides whether the invocation enters the REPL.
// The -i flag and the interactive command are interchangeable, but -i must not
// silently discard a different command.
func resolveInteractiveSelection(shortFlag bool, args []string) (bool, error) {
	if len(args) == 0 {
		return shortFlag, nil
	}
	if args[0] != "interactive" {
		if shortFlag {
			return false, fmt.Errorf("-i cannot be combined with the %q command", args[0])
		}
		return false, nil
	}
	if len(args) != 1 {
		return false, fmt.Errorf("usage: interactive")
	}
	return true, nil
}

// resolveInteractiveLines resolves the REPL output line budget from the startup
// flags. An absent --lines selects the interactive default, and an explicit value
// outside the supported window is rejected instead of being clamped: an operator
// who asked for more lines than the REPL will render must not be shown a shorter
// tail that looks complete.
//
// The standalone surface keeps its own default, so this resolver is only called
// once the invocation is known to enter the REPL.
func resolveInteractiveLines(flags *flag.FlagSet, value int) (int, error) {
	explicit := false
	flags.Visit(func(f *flag.Flag) {
		if f.Name == "lines" {
			explicit = true
		}
	})
	if !explicit {
		return tui.DefaultInteractiveMaxLines, nil
	}
	if value < tui.MinInteractiveMaxLines || value > tui.MaxInteractiveMaxLines {
		return 0, fmt.Errorf("--lines %d is outside the interactive range %d-%d; the standalone logs command accepts any positive count", value, tui.MinInteractiveMaxLines, tui.MaxInteractiveMaxLines)
	}
	return value, nil
}

// globalOptionNames lists the options the top-level flag set owns. Only these are
// hoisted, so an option a subcommand owns (for example list --clean) keeps its
// position and its meaning.
var globalOptionNames = map[string]bool{
	"json": true, "endpoint": true, "yes": true, "server-url": true, "token": true,
	"wait-timeout-ms": true, "max-bytes": true, "lines": true, "no-color": true,
	"no-progress": true,
	"profile": true, "profile-revision": true, "folder": true, "task": true,
	"generation": true, "i": true, "follow": true, "f": true,
}

// booleanGlobalOptions lists the hoisted options that take no value, so hoisting
// never swallows the following argument as if it were that option's value.
var booleanGlobalOptions = map[string]bool{
	"json": true, "yes": true, "no-color": true, "no-progress": true, "i": true, "follow": true, "f": true,
}

// hoistTrailingFlags moves recognized global options that appear after the
// subcommand in front of it. Go's flag package stops parsing at the first
// positional argument, so without this an operator who follows the tool's own
// advice ("rerun with --yes") has the option silently swallowed as data, and a
// filter such as --endpoint is dropped instead of narrowing the scope. A "--"
// terminator still ends option parsing, so a literal value beginning with a dash
// stays expressible.
func hoistTrailingFlags(args []string) []string {
	split := -1
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			break
		}
		if !strings.HasPrefix(arg, "-") || arg == "-" {
			split = i
			break
		}
		// A leading value-taking option written as a separate pair owns the next
		// argument, so that value is not the first positional. Skipping it keeps
		// the boundary at the real subcommand instead of at an option's value.
		name, hasValue := splitOptionName(arg)
		if !hasValue && globalOptionNames[name] && !booleanGlobalOptions[name] && i+1 < len(args) {
			i++
		}
	}
	if split < 0 {
		return args
	}
	hoisted := make([]string, 0, len(args))
	hoisted = append(hoisted, args[:split]...)
	rest := make([]string, 0, len(args)-split)
	for i := split; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			rest = append(rest, args[i:]...)
			break
		}
		name, hasValue := splitOptionName(arg)
		if !globalOptionNames[name] {
			rest = append(rest, arg)
			continue
		}
		hoisted = append(hoisted, arg)
		// A value-taking option written as a separate pair takes its value with
		// it, otherwise hoisting would leave the value behind as a positional.
		// A boolean option never consumes the next argument.
		if !hasValue && !booleanGlobalOptions[name] && i+1 < len(args) && !strings.HasPrefix(args[i+1], "-") {
			i++
			hoisted = append(hoisted, args[i])
		}
	}
	return append(hoisted, rest...)
}

// splitOptionName reports the option name without its leading dashes and whether
// the value was attached with "=".
func splitOptionName(arg string) (string, bool) {
	name := strings.TrimLeft(arg, "-")
	if idx := strings.Index(name, "="); idx >= 0 {
		return name[:idx], true
	}
	return name, false
}

func parseListArgs(args []string, clean bool) (bool, error) {
	for _, arg := range args {
		if arg != "--clean" {
			return false, fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] list [--clean]")
		}
		if clean {
			return false, fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] list [--clean]")
		}
		clean = true
	}
	return clean, nil
}

// parseRefreshArgs rejects every positional argument, so a typo cannot silently
// refresh a different scope than the operator intended.
func parseRefreshArgs(args []string) error {
	if len(args) != 0 {
		return fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] refresh")
	}
	return nil
}

// parseEndpointsArgs accepts at most one endpoint ID filter and rejects any
// other argument, so a typo cannot silently list every endpoint.
func parseEndpointsArgs(args []string, flagFilter string) (string, error) {
	filter := flagFilter
	for _, arg := range args {
		if strings.HasPrefix(arg, "-") {
			return "", fmt.Errorf("usage: agent-cluster-cli [options] endpoints [endpoint-id]")
		}
		if filter != "" {
			return "", fmt.Errorf("usage: agent-cluster-cli [options] endpoints [endpoint-id]")
		}
		filter = arg
	}
	return filter, nil
}

func legacyRunner(api tui.CommandAPI) tui.CommandRunner {
	return tui.CommandRunner{API: api, Policy: tui.LegacyPolicy}
}

// history renders bounded provider session history for one endpoint.
//
// The endpoint argument is mandatory because a history query is endpoint-scoped:
// provider session IDs may collide across endpoints, so a fleet-wide merge could
// not be joined to the persisted inventory unambiguously.
func history(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, target string, jsonMode bool, color tui.ColorPolicy) error {
	options := tui.TableOptionsFor(output)
	options.Color = color
	return legacyRunner(api).History(ctx, output, errors, target, jsonMode, options)
}

func list(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, filter string, clean, jsonMode bool, color tui.ColorPolicy) error {
	options := tui.TableOptionsFor(output)
	options.Color = color
	options.Clean = clean
	return legacyRunner(api).ListWithOptions(ctx, output, errors, filter, jsonMode, options)
}

// refresh forces one fresh Endpoint collection and renders the committed
// inventory, so the operator's next view is fresh rather than a cached projection.
func refresh(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, filter string, jsonMode bool, color tui.ColorPolicy) error {
	refreshCtx, cancel := context.WithTimeout(ctx, tui.RefreshCommandTimeout())
	defer cancel()
	options := tui.TableOptionsFor(output)
	options.Color = color
	// A forced collection is the longest silent wait on the read surface, so it
	// reports progress like a command does. The reporter is built from the
	// diagnostics stream, so a redirected stream stays silent.
	progress := tui.NewProgress(errors, refreshProgressHeader(filter))
	return legacyRunner(api).RefreshWithProgress(refreshCtx, output, errors, filter, jsonMode, options, progress)
}

// refreshProgressHeader describes the forced collection in flight. A scoped
// refresh names its Endpoint, because the operator asked for that exact one.
func refreshProgressHeader(filter string) string {
	if filter == "" {
		return "refreshing all endpoints..."
	}
	return "refreshing endpoint " + tui.SanitizeInlineText(filter) + "..."
}

// endpoints renders the endpoint projection for the standalone CLI.
func endpoints(ctx context.Context, api tui.CommandAPI, output io.Writer, filter string, jsonMode bool, color tui.ColorPolicy) error {
	options := tui.TableOptionsFor(output)
	options.Color = color
	return legacyRunner(api).Endpoints(ctx, output, filter, jsonMode, options)
}

func show(ctx context.Context, api tui.CommandAPI, output io.Writer, id string, jsonMode bool) error {
	return legacyRunner(api).Show(ctx, output, id, jsonMode)
}

// status renders one durable command result with conservative evidence wording.
func status(ctx context.Context, api tui.CommandAPI, output io.Writer, commandID string, jsonMode bool) error {
	return legacyRunner(api).Status(ctx, output, commandID, jsonMode)
}

func logs(ctx context.Context, api tui.CommandAPI, output io.Writer, endpointID, resourceID string, maxBytes, maxLines int, jsonMode bool, color tui.ColorPolicy) error {
	return legacyRunner(api).Logs(ctx, output, endpointID, resourceID, maxBytes, maxLines, jsonMode, color)
}

// interruptContext derives a cancellable context that ends on the first
// interrupt signal. The returned stop function releases the watcher, so a
// completed stream never leaves a goroutine behind.
func interruptContext(parent context.Context, interrupts <-chan os.Signal) (context.Context, func()) {
	if interrupts == nil {
		return parent, func() {}
	}
	ctx, cancel := context.WithCancel(parent)
	done := make(chan struct{})
	go func() {
		defer close(done)
		select {
		case <-interrupts:
			cancel()
		case <-ctx.Done():
		}
	}()
	return ctx, func() {
		cancel()
		<-done
	}
}

// followLogs streams output records for one session. The generation is resolved
// from the committed inventory first, so the stream is bound to the exact
// session the operator named rather than to whatever the provider reports later.
// The standalone surface has no terminal to observe a keypress, so the operator
// stops the stream with an interrupt signal.
func followLogs(ctx context.Context, api tui.CommandAPI, output io.Writer, endpointID, resourceID, generation string, maxBytes, maxLines int, jsonMode bool, color tui.ColorPolicy) error {
	runner := legacyRunner(api)
	if generation == "" {
		report, err := api.GetInventory(ctx, endpointID)
		if err != nil {
			return err
		}
		for _, session := range report.Sessions {
			if session.SessionID == resourceID {
				generation = session.Generation
				break
			}
		}
	}
	return runner.FollowLogs(ctx, output, endpointID, resourceID, generation, maxBytes, maxLines, jsonMode, color)
}

// drive dispatches the standalone drive surface. status is a read projection of
// the persisted inventory; start and stop admit one durable command through the
// same runner the interactive surface uses, so the two cannot diverge.
func drive(ctx context.Context, api tui.CommandAPI, output io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, generationFlag string) error {
	return driveWithProgress(ctx, api, output, nil, args, confirmed, jsonMode, waitTimeoutMS, generationFlag)
}

// driveWithProgress is drive with a diagnostics stream for progress lines. A nil
// diagnostics stream keeps the previous silent behaviour.
func driveWithProgress(ctx context.Context, api tui.CommandAPI, output, diagnostics io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, generationFlag string) error {
	if len(args) < 1 {
		return fmt.Errorf("usage: drive <start|stop|status> <endpoint> <session> [generation]")
	}
	action := strings.ToLower(args[0])
	if _, known := driveOperation(action); !known {
		return fmt.Errorf("usage: drive <start|stop|status> <endpoint> <session> [generation]")
	}
	if len(args) < 3 {
		return fmt.Errorf("usage: drive %s <endpoint> <session> [generation]", action)
	}
	if err := rejectMisplacedFlags("drive", args); err != nil {
		return err
	}
	if len(args) > 4 {
		return fmt.Errorf("unexpected arguments %q; run help drive for valid syntax", strings.Join(args[4:], " "))
	}
	endpointID, resourceID := args[1], args[2]
	operation, _ := driveOperation(action)
	if operation == "" {
		if generationFlag != "" || len(args) == 4 {
			return fmt.Errorf("drive status takes no generation; it reads the persisted inventory")
		}
		return legacyRunner(api).DriveStatus(ctx, output, endpointID, resourceID, jsonMode)
	}
	generation := generationFlag
	if generation == "" && len(args) == 4 {
		generation = args[3]
	}
	if generation == "" {
		return fmt.Errorf("drive %s requires a generation", action)
	}
	request := tui.ActionRequest{Operation: operation, OperationLabel: "drive " + action, EndpointID: endpointID, ResourceID: resourceID, Generation: generation, Payload: json.RawMessage(`{}`), Confirmed: confirmed, WaitTimeoutMS: waitTimeoutMS}
	runner := legacyRunner(api)
	progress := tui.NewActionProgress(diagnostics, request)
	intent, err := runner.PrepareAction(ctx, request)
	if err != nil {
		return err
	}
	actionResult, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return err
	}
	result, err := runner.WaitActionWithProgress(ctx, actionResult, intent.Budget, progress)
	if err != nil {
		return err
	}
	return runner.RenderAction(output, result)
}

// driveOperation maps one accepted drive action onto the standard operation.
// An empty operation means the action is a read, which is why the caller must
// check the known flag before treating the result as a command.
func driveOperation(action string) (string, bool) {
	switch action {
	case "start":
		return protocol.OperationAgentDriveStart, true
	case "stop":
		return protocol.OperationAgentDriveStop, true
	case "status":
		return "", true
	}
	return "", false
}

// resolveActionPayload converts one positional payload argument into the
// standard operation payload. Plain text is accepted for every operation that
// carries user text, so no caller has to write JSON; a JSON object is still
// forwarded unchanged as the advanced form.
func resolveActionPayload(operation, value string) (json.RawMessage, error) {
	switch operation {
	case "send", "btw":
		return tui.MessagePayload(value)
	case "interrupt", "control":
		return tui.InterruptPayload(operation, value)
	case "start":
		return tui.TaskPayload(value)
	}
	return json.RawMessage(`{}`), nil
}

// action executes one non-interactive command. The diagnostics stream carries
// operator-facing guidance and the verbatim multi-line task echo, so the
// machine-readable output stream stays clean under --json. The colour policy is
// resolved by the caller, because only it knows whether the output is a terminal.
func action(ctx context.Context, api tui.CommandAPI, output io.Writer, input io.Reader, diagnostics io.Writer, color tui.ColorPolicy, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, profile, profileRevision, folder, task, generationFlag string) error {
	operation := args[0]
	// A "--" after the command word ends option parsing, so everything after it is
	// literal data. The head is still checked for misplaced flags, because a flag
	// written before the terminator would silently become a payload or a target
	// generation; the tail is never inspected, so a message that begins with a dash
	// can be sent without escaping it.
	head, tail := splitTerminator(args)
	if err := rejectMisplacedFlags(args[0], head); err != nil {
		return err
	}
	args = append(append([]string{}, head...), tail...)
	if operation == "stop" && len(args) < 4 && generationFlag == "" {
		return fmt.Errorf("usage: stop <endpoint-id> <resource-id> <generation>")
	}
	if operation != "stop" && len(args) < 3 {
		return fmt.Errorf("usage: %s <endpoint-id> <resource-id> [text] [generation]", operation)
	}
	endpointID, resourceID := args[1], args[2]
	// The documented syntax accepts at most one text and one generation positional. A
	// value supplied by a flag removes its positional slot, so an unquoted multi-word
	// message is rejected instead of being silently truncated to its first word.
	positionalLimit := 5
	textStart := 3
	if operation == "stop" {
		positionalLimit = 4
		textStart = 0
	}
	if generationFlag != "" {
		positionalLimit--
	}
	if operation == "start" && task != "" {
		positionalLimit--
		textStart = 0
	}
	if err := rejectExtraPositionals(operation, args, positionalLimit, textStart); err != nil {
		return err
	}
	generation := generationFlag
	payload := json.RawMessage(`{}`)
	if operation == "stop" {
		if generation == "" {
			generation = args[3]
		}
	} else {
		if len(args) >= 4 {
			resolved, err := resolveActionPayload(operation, args[3])
			if err != nil {
				return err
			}
			payload = resolved
		} else if operation == "send" {
			// A send without a text argument reads a multi-line block from the
			// command input, so a message never has to be quoted into one line.
			block, err := tui.ReadMultiLineBlock(input, 0)
			if err != nil {
				return err
			}
			resolved, err := resolveActionPayload(operation, block.Text)
			if err != nil {
				return err
			}
			payload = resolved
		} else if operation == "btw" {
			// A btw without a text argument reads a multi-line context
			// block from the command input, so context text never has to be
			// quoted into one line. The block keeps the message payload bound,
			// because context injection carries the same text field as send.
			block, err := tui.ReadContextMultiLineBlock(input, 0)
			if err != nil {
				return err
			}
			resolved, err := resolveActionPayload(operation, block.Text)
			if err != nil {
				return err
			}
			payload = resolved
		} else if operation == "interrupt" {
			// A bare interrupt submits the hard default, so the operator does not
			// have to spell the action word. A message without an explicit action
			// word is rejected by InterruptPayload instead of being guessed.
			resolved, err := resolveActionPayload(operation, "")
			if err != nil {
				return err
			}
			payload = resolved
		} else if operation == "start" && task == "" {
			// A start without a task reads a multi-line task block, so a task
			// never has to be quoted into one line. The accepted task is echoed
			// verbatim with colour, so the operator can verify exactly what will
			// be sent before the command is admitted. The launch profile is
			// validated first, because reading a whole task block only to reject
			// the invocation would waste the operator's input.
			if profile == "" || profileRevision == "" {
				return fmt.Errorf("start requires --profile and --profile-revision")
			}
			block, err := tui.ReadTaskMultiLineBlock(input, 0)
			if err != nil {
				return err
			}
			if err := tui.WriteTaskEcho(taskEchoWriter(output, diagnostics, jsonMode), block.Text, color); err != nil {
				return err
			}
			resolved, err := resolveActionPayload(operation, block.Text)
			if err != nil {
				return err
			}
			payload = resolved
		}
		if generation == "" && len(args) >= 5 {
			generation = args[4]
		}
	}
	if operation == "start" && task != "" {
		resolved, err := tui.TaskPayload(task)
		if err != nil {
			return err
		}
		payload = resolved
	}
	target := protocol.CommandTarget{Kind: "session", ResourceID: resourceID, Generation: generation}
	if operation == "start" {
		target = protocol.CommandTarget{}
	}
	if operation == "stop" {
		if err := tui.ValidateStopTarget(target); err != nil {
			return err
		}
	}
	operationValue := operationName(operation)
	request := tui.ActionRequest{Operation: operationValue, OperationLabel: operation, EndpointID: endpointID, ResourceID: resourceID, Generation: generation, Payload: payload, Confirmed: confirmed, WaitTimeoutMS: waitTimeoutMS, Profile: profile, ProfileRevision: profileRevision, Folder: folder}
	runner := legacyRunner(api)
	// Progress is created before the capability preflight, because that preflight
	// is itself a network round trip the operator would otherwise wait through
	// silently. The reporter is nil when the diagnostics stream cannot render it,
	// so a redirected or disabled stream costs nothing.
	progress := tui.NewActionProgress(diagnostics, request)
	intent, err := runner.PrepareAction(ctx, request)
	if err != nil {
		return err
	}
	actionResult, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return err
	}
	result, err := runner.WaitActionWithProgress(ctx, actionResult, intent.Budget, progress)
	if err != nil {
		return err
	}
	if err := runner.RenderAction(output, result); err != nil {
		return err
	}
	if operation != "start" {
		return nil
	}
	// A successful start forces one fresh collection for the Endpoint that accepted
	// it, so the operator's next list already contains the launched session instead
	// of waiting for the periodic collection. The refresh is scoped to that single
	// Endpoint, and its failure is reported on stderr without changing the exit
	// status, because the admission already succeeded.
	refreshCtx, cancel := context.WithTimeout(ctx, tui.RefreshCommandTimeout())
	defer cancel()
	options := tui.TableOptionsFor(output)
	options.Color = color
	return runner.RefreshAfterStart(refreshCtx, output, diagnostics, endpointID, result, jsonMode, options)
}

// rejectMisplacedFlags fails when a flag appears after the command name. flag.Parse stops
// at the first positional, so a flag written after the command stays positional and would
// silently become a payload or a target generation. The caller passes the command name
// explicitly because a command with an action word keeps that word in args[0].
func rejectMisplacedFlags(command string, args []string) error {
	for _, arg := range args[1:] {
		if !strings.HasPrefix(arg, "-") || arg == "-" {
			continue
		}
		if _, err := strconv.ParseFloat(arg, 64); err == nil {
			continue
		}
		return fmt.Errorf("option %q must be written before the command; run help %s for valid syntax", arg, command)
	}
	return nil
}

// splitTerminator separates the option-bearing head of a command line from the
// literal tail written after "--". args[0] is the command word, so a "--" at
// index 0 is not a terminator. Everything after the first "--" is data: it is
// never inspected for flags, so a payload that begins with a dash can be sent
// without the operator escaping it. The tail is returned separately because the
// caller must still apply its positional rules to it.
func splitTerminator(args []string) (head, tail []string) {
	for index := 1; index < len(args); index++ {
		if args[index] == "--" {
			return args[:index], args[index+1:]
		}
	}
	return args, nil
}

// rejectExtraPositionals fails when more positional arguments are supplied than the
// documented syntax accepts. Without this check an unquoted multi-word message is silently
// truncated: only the first word becomes the payload and the next word becomes the target
// generation, so the operator believes the whole message was sent. The caller passes the
// exact accepted count because it depends on the operation and on which flags were used,
// and the index where the message text begins so the error can echo the whole intended
// message instead of only the words that overflowed. A zero textStart means the operation
// has no positional text slot, so the message must not suggest quoting text.
func rejectExtraPositionals(operation string, args []string, limit, textStart int) error {
	if len(args) <= limit {
		return nil
	}
	overflow := args[limit:]
	if textStart > 0 && textStart < len(args) {
		return fmt.Errorf("unexpected arguments %q; quote the message text so it stays one argument, or run help %s for valid syntax", strings.Join(args[textStart:], " "), operation)
	}
	return fmt.Errorf("unexpected arguments %q; run help %s for valid syntax", strings.Join(overflow, " "), operation)
}

func operationName(value string) string {
	if value == "btw" {
		return "context.inject"
	}
	if value == "interrupt" || value == "control" {
		return "execution.interrupt"
	}
	if value == "start" {
		return "agent.start"
	}
	if value == "resume" {
		return "agent.resume"
	}
	if value == "stop" {
		return "agent.stop"
	}
	return "message.send"
}

func envOr(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func noColorPresent() bool { _, ok := os.LookupEnv("NO_COLOR"); return ok }

// multiLineHint reports how to finish a multi-line block, or an empty string
// when the invocation carries its text explicitly. Only a terminal needs the
// hint, because a piped stream already ends at the end of input.
func multiLineHint(operation string, narg int, task string, terminal bool) string {
	if !terminal {
		return ""
	}
	switch operation {
	case "send":
		if narg == 3 {
			return tui.MultiLineHint
		}
	case "btw":
		// A positional text supplies the context, so no block is read.
		if narg == 3 {
			return tui.MultiLineContextHint
		}
	case "start":
		// A positional task or --task supplies the text, so no block is read.
		if narg == 3 && task == "" {
			return tui.MultiLineTaskHint
		}
	}
	return ""
}

// taskEchoWriter selects the stream that carries the verbatim task echo. Under
// --json the output stream must stay machine-readable, so the echo goes to the
// diagnostics stream instead of corrupting the JSON document.
func taskEchoWriter(output, diagnostics io.Writer, jsonMode bool) io.Writer {
	if jsonMode {
		return diagnostics
	}
	return output
}
