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
	serverURL := flags.String("server-url", envOr(cliServerURLEnv, "http://127.0.0.1:8080"), "Server API URL")
	token := flags.String("token", cliEnvironmentValue(os.Getenv, cliServerTokenEnv), "Server bearer token")
	// --endpoint-token is the token the target Endpoint accepts. It is a separate
	// credential from --token because the two answer different questions: the
	// Server token decides whether this CLI may talk to the cluster, while the
	// Endpoint token decides whether this CLI may act on one machine. The normal
	// source is the AGENT_CLUSTER_CLI_ENDPOINT_TOKENS mapping in the CLI configuration
	// file, because a token written on a command line stays in the shell history.
	endpointToken := flags.String("endpoint-token", "", "token the target Endpoint accepts; requires --endpoint")
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
	// --limit narrows a history read. It is a separate quantity from --lines
	// because history rows are provider session records, not output lines, and
	// conflating them would let an output setting silently reshape a history table.
	historyLimit := flags.Int("limit", 0, "maximum number of history rows returned; 0 keeps the provider's own window")
	// --max-chars bounds one message body in a conversation read. It is a
	// separate quantity from --lines and --limit because a message is provider
	// prose, not an output line and not a history row, and conflating them would
	// let an unrelated setting silently reshape a conversation.
	maxChars := flags.Int("max-chars", 0, "maximum characters per message returned by messages; 0 keeps the adapter default")
	// -c is the short spelling of --max-chars. Both surfaces accept it, so an
	// operator who learned it in the interactive REPL can use it here too. It is a
	// separate flag rather than an alias entry because Go's flag package has no
	// alias mechanism, and the two spellings are reconciled after parsing so they
	// can never disagree about one quantity.
	maxCharsShort := flags.Int("c", 0, "short form of --max-chars")
	// --max-tokens bounds one message body in model tokens, which is the bound an
	// operator usually wants: a token is the unit that makes a conversation
	// expensive and noisy, while a character count says nothing about how much of
	// the model's context a message occupies. An absent value selects the cluster
	// default rather than "no bound", because an unbounded conversation is noise.
	maxTokens := flags.Int("max-tokens", 0, "maximum tokens per message returned by messages; 0 means no bound, and an absent value uses the default of 5000")
	// -t is the short spelling of --max-tokens, reconciled with it after parsing so
	// the two can never disagree about one quantity.
	maxTokensShort := flags.Int("t", 0, "short form of --max-tokens")
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
	// The Endpoint token mapping is resolved before any command runs, so a
	// malformed configuration is reported once instead of surfacing as a refusal
	// from whichever Endpoint the command happened to reach first.
	endpointTokens, err := parseEndpointTokens(cliEnvironmentValue(os.Getenv, endpointTokensEnv))
	if err != nil {
		return err
	}
	if err := applyEndpointTokenFlag(endpointTokens, resolveEndpointTokenTarget(*filter, flags.Args()), *endpointToken); err != nil {
		return err
	}
	api := client.NewAPIClient(*serverURL, *token)
	api.EndpointTokens = endpointTokens
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
		// The history store is resolved before the editor takes the terminal, so a
		// rejected bound never leaves the screen in raw mode. A nil store means no
		// path could be resolved, and the REPL keeps its in-memory behaviour.
		inputHistory, historyErr := resolveInputHistoryFromProcess(errors)
		if historyErr != nil {
			return historyErr
		}
		editor, closeEditor, editorErr := interactiveEditor(input, output, inputHistory)
		if editorErr != nil {
			return editorErr
		}
		defer closeEditor()
		// Colour follows the output boundary, so a REPL whose stdout is redirected
		// stays plain even though interactive mode requires a terminal on stdin.
		// The trigger runner is wired here, at the process boundary, because it is
		// the only place that may own a child process. The REPL receives it as an
		// injected dependency, so a test never spawns a real script.
		options := tui.InteractiveOptions{MaxBytes: *maxBytes, MaxLines: interactiveLines, WaitTimeoutMS: *waitTimeoutMS, Interrupt: interrupts, CloseInput: input == os.Stdin || interrupts != nil, Color: tui.OutputColorPolicy(output), ProgressWriter: errors, TriggerRunner: tui.NewExecTriggerRunner()}
		return tui.RunInteractive(ctx, api, input, output, errors, wireEditorReaders(options, editor))
	}
	// A negative numeric option is rejected at the boundary rather than passed
	// down, because every consumer reads a non-positive bound as "no bound". A
	// negative bound would therefore silently widen the result instead of
	// narrowing it, and the operator would see a complete conversation while
	// believing it was bounded.
	if err := rejectNegativeNumericFlags(*maxChars, *maxCharsShort, *maxTokens, *maxTokensShort, *historyLimit, *maxBytes, *lines); err != nil {
		return err
	}
	// The two spellings of the per-message bound are reconciled into one value
	// before any command reads it, so -c and --max-chars can never disagree. Two
	// different values are rejected instead of resolved by precedence, because
	// either choice would silently ignore a bound the operator stated.
	messageBound, err := reconcileMaxChars(*maxChars, *maxCharsShort)
	if err != nil {
		return err
	}
	// The token bound is reconciled the same way, and an absent value selects the
	// cluster default. The default is resolved here because this is the first layer
	// that can tell an absent flag from a stated zero: zero is a meaningful request
	// for no bound, so applying the default to it would silently override the
	// operator's own instruction.
	tokenBound, err := resolveMaxTokens(flags, *maxTokens, *maxTokensShort)
	if err != nil {
		return err
	}
	// A bound above the protocol maximum is rejected rather than clamped, so the
	// two surfaces agree about one value. The adapter clamps, which means a caller
	// who asked for 999999999 receives a 100000 bound while the command reports
	// success and prints no diagnostic; the operator then believes a bound was
	// honoured that was silently replaced. The interactive surface already rejects
	// this value, so accepting it here made the same request succeed in a script
	// and fail in the REPL.
	if messageBound > protocol.MaxMessagesMaxChars {
		return fmt.Errorf("--max-chars %d exceeds the maximum of %d", messageBound, protocol.MaxMessagesMaxChars)
	}
	if tokenBound > protocol.MaxMessagesMaxTokens {
		return fmt.Errorf("--max-tokens %d exceeds the maximum of %d", tokenBound, protocol.MaxMessagesMaxTokens)
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
	case "list", tui.ListFullAlias, tui.ListBriefAlias:
		// lf is the shorthand of "list --full" and lb is the shorthand of
		// "list --brief", so each implies its own flag instead of requiring it.
		// Resolving them here keeps one render path: a shorthand cannot drift into
		// a second implementation, and it can never silently degrade into the
		// ordinary layout that looks complete while hiding what the operator asked
		// for. The two shorthands are separate spellings rather than one spelling
		// with a mode, because they select opposite layouts and a single word
		// cannot state which one was meant.
		shorthand := listShorthand(flags.Arg(0))
		listParsed, err := parseListArgs(flags.Args()[1:], shorthand)
		if err != nil {
			return err
		}
		return list(ctx, api, output, errors, *filter, listParsed, *jsonMode, tui.OutputColorPolicy(output))
	case "refresh":
		refreshParsed, err := parseRefreshArgs(flags.Args()[1:], *filter)
		if err != nil {
			return err
		}
		return refresh(ctx, api, output, errors, refreshParsed, *jsonMode, tui.OutputColorPolicy(output))
	case "endpoints":
		endpointFilter, err := parseEndpointsArgs(flags.Args()[1:], *filter)
		if err != nil {
			return err
		}
		return endpoints(ctx, api, output, endpointFilter, *jsonMode, tui.OutputColorPolicy(output))
	case "history":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: history <endpoint-id-or-hostname> [--limit N]")
		}
		return history(ctx, api, output, errors, flags.Arg(1), *historyLimit, *jsonMode, tui.OutputColorPolicy(output))
	case "messages":
		if flags.NArg() != 3 {
			return fmt.Errorf("usage: messages <endpoint-id-or-hostname> <session-id> [-c N|--max-chars N]")
		}
		return messages(ctx, api, output, errors, flags.Arg(1), flags.Arg(2), messageBound, tokenBound, *jsonMode, tui.OutputColorPolicy(output))
	case "model":
		if flags.NArg() < 3 || flags.NArg() > 4 {
			return fmt.Errorf("usage: model <endpoint-id-or-hostname> <session-id> [profile]")
		}
		if flags.NArg() == 3 {
			return model(ctx, api, output, errors, flags.Arg(1), flags.Arg(2), *jsonMode, tui.OutputColorPolicy(output))
		}
		return modelSelectWithProgress(ctx, api, output, errors, flags.Arg(1), flags.Arg(2), flags.Arg(3), *confirmed, *jsonMode, *waitTimeoutMS, *generation)
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
	case "logs", tui.LogsFollowAlias:
		// logf is the shorthand of "logs -f", so it implies follow instead of
		// requiring the flag. Resolving it here keeps one follow path: the
		// shorthand cannot drift into a second implementation, and it can never
		// silently degrade into a one-shot snapshot that looks like a stream.
		shorthand := flags.Arg(0) == tui.LogsFollowAlias
		if flags.NArg() != 3 {
			if shorthand {
				return fmt.Errorf("usage: logf <endpoint-id> <session-id>")
			}
			return fmt.Errorf("usage: logs <endpoint-id> <session-id>")
		}
		if shorthand && (*follow || *followShort) {
			// The shorthand already states follow, so a repeated flag is a
			// contradiction rather than a harmless duplicate; the interactive
			// parser rejects the same combination.
			return fmt.Errorf("usage: logf <endpoint-id> <session-id> (follow is implied; drop --follow)")
		}
		color := tui.OutputColorPolicy(output)
		if shorthand || *follow || *followShort {
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
	case "send", "btw", "interrupt", "start", "resume", "stop", "clean":
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
	case "ctl", "control":
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

// rejectNegativeNumericFlags rejects a negative value for any numeric option.
//
// Every consumer of these options reads a non-positive value as "no bound", so a
// negative value would widen the result instead of narrowing it. The operator
// would then see a complete conversation or a complete output snapshot while
// believing the request was bounded, which is the opposite of what the flag says.
// The check lives at the boundary because the same convention is repeated in the
// adapter, the client and the Server, and a single rejected value cannot drift.
func rejectNegativeNumericFlags(maxChars, maxCharsShort, maxTokens, maxTokensShort, historyLimit, maxBytes, lines int) error {
	checks := []struct {
		name  string
		value int
	}{
		{"--max-chars", maxChars},
		{"-c", maxCharsShort},
		{"--max-tokens", maxTokens},
		{"-t", maxTokensShort},
		{"--limit", historyLimit},
		{"--max-bytes", maxBytes},
		{"--lines", lines},
	}
	for _, check := range checks {
		if check.value < 0 {
			return fmt.Errorf("%s %d is negative; a bound must be zero or a positive count", check.name, check.value)
		}
	}
	return nil
}

// reconcileMaxChars folds the two spellings of the per-message bound into one
// value, so -c and --max-chars can never disagree about one quantity.
//
// Two different non-zero values are rejected instead of resolved by precedence,
// because either choice would silently ignore a bound the operator stated. Zero
// means "not supplied" for both spellings, so "-c 0" and "--max-chars 0" agree
// and both mean "no bound", which is the meaning every consumer already applies.
func reconcileMaxChars(maxChars, maxCharsShort int) (int, error) {
	if maxChars != 0 && maxCharsShort != 0 && maxChars != maxCharsShort {
		return 0, fmt.Errorf("--max-chars %d and -c %d disagree; state the bound once", maxChars, maxCharsShort)
	}
	if maxCharsShort != 0 {
		return maxCharsShort, nil
	}
	return maxChars, nil
}

// reconcileMaxTokens folds the two spellings of the per-message token bound into
// one value, so -t and --max-tokens can never disagree about one quantity.
//
// Two different non-zero values are rejected instead of resolved by precedence,
// because either choice would silently ignore a bound the operator stated. Zero
// means "not supplied" for both spellings, so "-t 0" and "--max-tokens 0" agree and
// both mean "no bound".
func reconcileMaxTokens(maxTokens, maxTokensShort int) (int, error) {
	if maxTokens != 0 && maxTokensShort != 0 && maxTokens != maxTokensShort {
		return 0, fmt.Errorf("--max-tokens %d and -t %d disagree; state the bound once", maxTokens, maxTokensShort)
	}
	if maxTokensShort != 0 {
		return maxTokensShort, nil
	}
	return maxTokens, nil
}

// resolveMaxTokens folds the two spellings of the token bound into one value and
// applies the cluster default when neither was stated.
//
// The default is resolved here because this is the first layer that can tell an
// absent flag from a stated zero. Zero is a meaningful request for no bound, so
// applying the default to it would silently override the operator's own
// instruction, and a caller who asked for no bound would receive 5000 instead.
func resolveMaxTokens(flags *flag.FlagSet, maxTokens, maxTokensShort int) (int, error) {
	bound, err := reconcileMaxTokens(maxTokens, maxTokensShort)
	if err != nil {
		return 0, err
	}
	if !flagSupplied(flags, "max-tokens") && !flagSupplied(flags, "t") {
		return protocol.DefaultMessagesMaxTokens, nil
	}
	return bound, nil
}

// flagSupplied reports whether one option was stated on the command line.
//
// It exists because a zero value cannot distinguish "not supplied" from "supplied
// zero", and the two mean different things for a bound: an absent token bound
// selects the cluster default, while an explicit zero asks for no bound at all.
// Reading the parsed value alone would silently override the operator's own
// instruction to disable the bound.
func flagSupplied(flags *flag.FlagSet, name string) bool {
	supplied := false
	flags.Visit(func(f *flag.Flag) {
		if f.Name == name {
			supplied = true
		}
	})
	return supplied
}

// globalOptionNames lists the options the top-level flag set owns. Only these are
// hoisted, so an option a subcommand owns (for example list --clean) keeps its
// position and its meaning.
//
// Every option registered on the top-level flag set MUST appear here. A flag that
// is registered but absent from this map is accepted only before the subcommand,
// because Go's flag package stops parsing at the first positional argument. The
// operator then sees a usage error for a flag the help text documents, which reads
// as "the flag does not exist" rather than "the flag is in the wrong place".
// TestGlobalOptionNamesCoverEveryRegisteredFlag enforces this, so a new flag
// cannot be added without deciding whether it is hoistable.
var globalOptionNames = map[string]bool{
	"json": true, "endpoint": true, "yes": true, "server-url": true, "token": true,
	"endpoint-token":  true,
	"wait-timeout-ms": true, "max-bytes": true, "lines": true, "no-color": true,
	"no-progress": true, "no-truncate": true, "limit": true, "max-chars": true, "c": true,
	"max-tokens": true, "t": true,
	"profile": true, "profile-revision": true, "folder": true, "task": true,
	"generation": true, "i": true, "follow": true, "f": true,
}

// booleanGlobalOptions lists the hoisted options that take no value, so hoisting
// never swallows the following argument as if it were that option's value.
var booleanGlobalOptions = map[string]bool{
	"json": true, "yes": true, "no-color": true, "no-progress": true, "no-truncate": true,
	"i": true, "follow": true, "f": true,
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
		if !hasValue && !booleanGlobalOptions[name] && i+1 < len(args) && takesSeparateValue(args[i+1]) {
			i++
			hoisted = append(hoisted, args[i])
		}
	}
	return append(hoisted, rest...)
}

// takesSeparateValue reports whether the argument after a value-taking option is
// that option's value rather than another option.
//
// A following option is never a value, but a negative number is: "--max-chars -5"
// states one option and one value, while "--max-chars --json" states two options.
// Treating every leading dash as an option made a negative value fall through to
// the positional list, so the flag then consumed the subcommand name and reported
// `invalid value "messages" for flag -max-chars`, which names neither the real
// problem nor the real argument.
func takesSeparateValue(next string) bool {
	if next == "--" {
		return false
	}
	if !strings.HasPrefix(next, "-") {
		return true
	}
	return isNegativeNumber(next)
}

// isNegativeNumber reports whether the argument is a negative number rather than
// an option. The first character after the dash must be a digit or a decimal
// point, so a word such as "-inf" is never mistaken for a value.
func isNegativeNumber(arg string) bool {
	if len(arg) < 2 || arg[0] != '-' {
		return false
	}
	rest := arg[1:]
	if (rest[0] < '0' || rest[0] > '9') && rest[0] != '.' {
		return false
	}
	_, err := strconv.ParseFloat(rest, 64)
	return err == nil
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

// listShorthand names the list spelling the operator typed, so a usage error can
// answer with that spelling and the implied flag can be derived from it. It is a
// type rather than a bool because there are now two shorthands that imply
// opposite layouts, and a bool could only express "some shorthand".
type listShorthand string

const (
	// listShorthandNone is the canonical "list" spelling, which implies nothing.
	listShorthandNone listShorthand = ""
	// listShorthandFull is "lf", which implies --full.
	listShorthandFull listShorthand = tui.ListFullAlias
	// listShorthandBrief is "lb", which implies --brief.
	listShorthandBrief listShorthand = tui.ListBriefAlias
)

// listShorthandFor classifies the command word the operator typed.
func listShorthandFor(spelling string) listShorthand {
	switch spelling {
	case tui.ListFullAlias:
		return listShorthandFull
	case tui.ListBriefAlias:
		return listShorthandBrief
	default:
		return listShorthandNone
	}
}

// parseListArgs parses the standalone list tail. --full is the per-command
// request to render without truncation and --brief is the per-command request to
// render only the identifying columns; the two are independent axes, so they
// combine. shorthand states which spelling the operator typed, because that
// spelling already implies one of the two flags.
//
// A repeated flag is a usage error rather than a harmless duplicate, because the
// operator who typed it twice cannot tell which one took effect. A shorthand
// rejects the flag it already implies for the same reason logf rejects a repeated
// follow flag: the combination is a contradiction. It accepts the other flag,
// because that one states something the shorthand did not.
func parseListArgs(args []string, shorthand listShorthand) (listFlags, error) {
	parsed := listFlags{
		Full:  shorthand == listShorthandFull,
		Brief: shorthand == listShorthandBrief,
	}
	for _, arg := range args {
		switch arg {
		case "--clean":
			if parsed.Clean {
				return listFlags{}, listUsageError(shorthand)
			}
			parsed.Clean = true
		case "-a", "--all":
			// -a and --all are one flag in two spellings, so a second spelling of
			// either is a usage error. The default omits endpoints that are not
			// online, because querying one can only produce a failure that describes
			// the endpoint rather than a defect.
			if parsed.All {
				return listFlags{}, listUsageError(shorthand)
			}
			parsed.All = true
		case "--full":
			if parsed.Full {
				if shorthand == listShorthandFull {
					return listFlags{}, fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] lf [--clean] [-a|--all] [--brief] (full is implied; drop --full)")
				}
				return listFlags{}, listUsageError(shorthand)
			}
			parsed.Full = true
		case "--brief":
			if parsed.Brief {
				if shorthand == listShorthandBrief {
					return listFlags{}, fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] lb [--clean] [-a|--all] [--full] (brief is implied; drop --brief)")
				}
				return listFlags{}, listUsageError(shorthand)
			}
			parsed.Brief = true
		default:
			return listFlags{}, listUsageError(shorthand)
		}
	}
	return parsed, nil
}

// listFlags is the parsed list tail. It is a struct rather than a tuple of
// positional booleans because clean, all, full and brief are all booleans: a
// positional signature would let a caller swap two of them and still compile,
// which is a silent layout bug rather than a type error.
type listFlags struct {
	Clean bool
	All   bool
	Full  bool
	Brief bool
}

// listUsageError names the spelling the operator typed, so a usage error never
// answers with a command they did not run.
func listUsageError(shorthand listShorthand) error {
	switch shorthand {
	case listShorthandFull:
		return fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] lf [--clean] [-a|--all] [--brief]")
	case listShorthandBrief:
		return fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] lb [--clean] [-a|--all] [--full]")
	default:
		return fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] list [--clean] [-a|--all] [--full] [--brief]")
	}
}

// refreshFlags is the parsed standalone refresh tail. Filter includes the
// existing global --endpoint value, so a positional Endpoint cannot silently
// override it.
type refreshFlags struct {
	Filter string
	All    bool
}

// parseRefreshArgs accepts one optional Endpoint and one spelling of --all. An
// explicit Endpoint wins over the online-only default, while --all restores the
// complete fleet collection. A repeated spelling is a usage error.
func parseRefreshArgs(args []string, flagFilter string) (refreshFlags, error) {
	parsed := refreshFlags{Filter: flagFilter}
	for _, arg := range args {
		switch arg {
		case "-a", "--all":
			if parsed.All {
				return refreshFlags{}, fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] refresh [endpoint] [-a|--all]")
			}
			parsed.All = true
		default:
			if strings.HasPrefix(arg, "-") || parsed.Filter != "" {
				return refreshFlags{}, fmt.Errorf("usage: agent-cluster-cli [options] [--endpoint <id>] refresh [endpoint] [-a|--all]")
			}
			parsed.Filter = arg
		}
	}
	return parsed, nil
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
func history(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, target string, limit int, jsonMode bool, color tui.ColorPolicy) error {
	options := tui.TableOptionsFor(output)
	options.Color = color
	return legacyRunner(api).History(ctx, output, errors, target, limit, jsonMode, options)
}

// messages renders one session's bounded conversation for one endpoint.
//
// The endpoint argument is mandatory because a conversation read is
// endpoint-scoped: provider session IDs may collide across endpoints, so a
// fleet-wide merge could not identify the session the operator asked for.
//
// The session argument is the provider's own session key rather than a cluster
// resource ID, because a stopped session is absent from the inventory and has no
// resource ID. That is also why this read needs no generation: it addresses
// persisted provider data, not a live process.
func messages(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, target, sessionID string, maxChars, maxTokens int, jsonMode bool, color tui.ColorPolicy) error {
	return legacyRunner(api).Messages(ctx, output, errors, target, sessionID, maxChars, maxTokens, jsonMode, color)
}

// model renders the model profiles one session can select.
//
// The endpoint argument is mandatory because a catalog read is endpoint-scoped:
// provider session IDs may collide across endpoints, so a fleet-wide merge could
// not identify the session the operator asked for.
//
// The generation is empty on purpose. A catalog read is read-only and addresses
// the provider's configuration rather than a live process, so it needs no
// generation proof; requiring one would refuse to list profiles for exactly the
// stopped sessions an operator may want to inspect before resuming.
func model(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, target, sessionID string, jsonMode bool, color tui.ColorPolicy) error {
	options := tui.TableOptionsFor(output)
	options.Color = color
	return legacyRunner(api).ModelCatalog(ctx, output, errors, target, sessionID, "", jsonMode, options)
}

// modelSelectWithProgress applies one model profile to one session.
//
// The standalone surface has no rendered table, so a row number is rejected: a row
// number is a position in a table the operator saw, and no table was rendered here.
// The selector is resolved against a live catalog read instead, so an unknown or
// unavailable profile is refused before anything is submitted rather than being sent
// to the provider as an opaque value.
//
// The catalog carries no generation, so the generation a model change needs is
// resolved from the committed inventory instead. A model change addresses a live
// process, and the Endpoint rejects an empty generation with generation_required
// (internal/endpoint/executor.go:126-133), which would otherwise surface only after
// the operator had already answered the confirmation question. Resolving it here
// turns that late failure into an immediate one that names the real reason.
func modelSelectWithProgress(ctx context.Context, api tui.CommandAPI, output, diagnostics io.Writer, target, sessionID, profile string, confirmed, jsonMode bool, waitTimeoutMS int64, generationFlag string) error {
	if tui.IsRowNumber(profile) {
		return fmt.Errorf("model profile %q is a row number, which only exists after an interactive render; name the profile by model_profile_id or display name", profile)
	}
	querier, ok := api.(tui.ModelCatalogQuerier)
	if !ok {
		return fmt.Errorf("model profiles are unavailable: this client cannot query model profiles")
	}
	endpoint, err := tui.ResolveEndpointTarget(ctx, api, target)
	if err != nil {
		return err
	}
	// The label is resolved once and reused by every message below, so one command
	// performs one inventory read instead of one per failure path.
	label := tui.SessionIdentityLabelFromInventory(ctx, api, endpoint.EndpointID, sessionID)
	if generationFlag == "" {
		generationFlag, err = resolveSessionGeneration(ctx, api, endpoint.EndpointID, sessionID)
		if err != nil {
			return err
		}
		if generationFlag == "" {
			return fmt.Errorf("session %s has no verified generation in the committed inventory, so a model change cannot address it; pass --generation explicitly or refresh the inventory", label)
		}
	}
	catalog, err := querier.GetModelCatalog(ctx, endpoint.EndpointID, sessionID, generationFlag)
	if err != nil {
		return err
	}
	if catalog.ErrorCode != "" {
		return tui.ModelCatalogError(label, catalog.ErrorCode)
	}
	view := tui.NewModelCatalogView(endpoint.EndpointID, sessionID, catalog)
	row, err := tui.ResolveModelProfileSelector(view, profile, label)
	if err != nil {
		return err
	}
	if !row.Available {
		reason := row.UnavailableReason
		if reason == "" {
			reason = "unavailable"
		}
		return fmt.Errorf("model profile %q is unavailable (%s)", tui.ModelProfileLabel(row), reason)
	}
	payload, err := json.Marshal(protocol.ModelSelectRequest{ModelProfileID: row.ModelProfileID})
	if err != nil {
		return err
	}
	request := tui.ActionRequest{Operation: protocol.OperationAgentModelSelect, OperationLabel: "model select", EndpointID: endpoint.EndpointID, ResourceID: sessionID, ProviderGeneration: generationFlag, Payload: payload, Confirmed: confirmed, WaitTimeoutMS: waitTimeoutMS}
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
	return renderActionResult(output, result, jsonMode)
}

// list renders the session table. full is the per-command request to disable
// truncation, and it is ORed with the boundary value rather than replacing it,
// so the startup --no-truncate option survives a command that did not repeat it.
// brief selects the identifying column set; it is a separate axis from full, so
// the two combine instead of overriding each other.
func list(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, filter string, parsed listFlags, jsonMode bool, color tui.ColorPolicy) error {
	options := tui.TableOptionsFor(output)
	options.Color = color
	options.Clean = parsed.Clean
	options.All = parsed.All
	options.Full = options.Full || parsed.Full
	options.Brief = parsed.Brief
	return legacyRunner(api).ListWithOptions(ctx, output, errors, filter, jsonMode, options)
}

// refresh forces one fresh Endpoint collection and renders the committed
// inventory, so the operator's next view is fresh rather than a cached projection.
func refresh(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, parsed refreshFlags, jsonMode bool, color tui.ColorPolicy) error {
	refreshCtx, cancel := context.WithTimeout(ctx, tui.RefreshCommandTimeout())
	defer cancel()
	options := tui.TableOptionsFor(output)
	options.Color = color
	options.All = parsed.All
	// A forced collection is the longest silent wait on the read surface, so it
	// reports progress like a command does. The reporter is built from the
	// diagnostics stream, so a redirected stream stays silent.
	progress := tui.NewProgress(errors, refreshProgressHeader(parsed.Filter, parsed.All))
	return legacyRunner(api).RefreshWithProgress(refreshCtx, output, errors, parsed.Filter, jsonMode, options, progress)
}

// refreshProgressHeader describes the forced collection in flight. A scoped
// refresh names its Endpoint, because the operator asked for that exact one.
func refreshProgressHeader(filter string, all bool) string {
	if filter != "" {
		return "refreshing endpoint " + tui.SanitizeInlineText(filter) + "..."
	}
	if all {
		return "refreshing all endpoints..."
	}
	return "refreshing online endpoints..."
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

// resolveSessionGeneration looks up the generation the committed inventory reports
// for one session. An empty result means the inventory reports no verified
// generation for that session, which is a fact the caller must interpret: a model
// change refuses it, while a follow stream passes it through and lets the Endpoint
// decide. The lookup is shared so the two surfaces cannot drift apart.
func resolveSessionGeneration(ctx context.Context, api tui.CommandAPI, endpointID, sessionID string) (string, error) {
	report, err := api.GetInventory(ctx, endpointID)
	if err != nil {
		return "", err
	}
	for _, session := range report.Sessions {
		if session.ClusterSessionID == sessionID {
			return session.ProviderGeneration, nil
		}
	}
	return "", nil
}

// followLogs streams output records for one session. The generation is resolved
// from the committed inventory first, so the stream is bound to the exact
// session the operator named rather than to whatever the provider reports later.
// The standalone surface has no terminal to observe a keypress, so the operator
// stops the stream with an interrupt signal.
func followLogs(ctx context.Context, api tui.CommandAPI, output io.Writer, endpointID, resourceID, generation string, maxBytes, maxLines int, jsonMode bool, color tui.ColorPolicy) error {
	runner := legacyRunner(api)
	if generation == "" {
		resolved, err := resolveSessionGeneration(ctx, api, endpointID, resourceID)
		if err != nil {
			return err
		}
		generation = resolved
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
	request := tui.ActionRequest{Operation: operation, OperationLabel: "drive " + action, EndpointID: endpointID, ResourceID: resourceID, ProviderGeneration: generation, Payload: json.RawMessage(`{}`), Confirmed: confirmed, WaitTimeoutMS: waitTimeoutMS}
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
	return renderActionResult(output, result, jsonMode)
}

// renderActionResult writes one durable command result for the standalone
// surface. --json keeps the machine-readable envelope, because a script parses
// that document; every other invocation renders the receipt, so the provider's
// own return document is printed verbatim instead of being escaped inside a JSON
// string. Both branches share the same receipt renderer the interactive REPL
// uses, so the two surfaces cannot disagree about the provider section.
func renderActionResult(output io.Writer, result map[string]any, jsonMode bool) error {
	if jsonMode {
		return tui.RenderJSON(output, result)
	}
	return tui.RenderReceipt(output, result)
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
	case "interrupt":
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
	if operation == "stop" || operation == "clean" {
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
	if operation == "stop" || operation == "clean" {
		if generation == "" && len(args) >= 4 {
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
	target := protocol.CommandTarget{Kind: "session", ResourceID: resourceID, ProviderGeneration: generation}
	if operation == "start" {
		target = protocol.CommandTarget{}
	}
	if operation == "stop" {
		if err := tui.ValidateStopTarget(target); err != nil {
			return err
		}
	}
	operationValue := operationName(operation)
	request := tui.ActionRequest{Operation: operationValue, OperationLabel: operation, EndpointID: endpointID, ResourceID: resourceID, ProviderGeneration: generation, Payload: payload, Confirmed: confirmed, WaitTimeoutMS: waitTimeoutMS, Profile: profile, ProfileRevision: profileRevision, Folder: folder}
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
	if err := renderActionResult(output, result, jsonMode); err != nil {
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
	if value == "interrupt" {
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
	if value == "clean" {
		return protocol.OperationWorkspaceClean
	}
	return "message.send"
}

func envOr(name, fallback string) string {
	if value := cliEnvironmentValue(os.Getenv, name); value != "" {
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
