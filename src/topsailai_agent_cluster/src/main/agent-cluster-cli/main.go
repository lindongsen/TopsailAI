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
	output = terminalOutput{Writer: output}
	flags := flag.NewFlagSet("agent-cluster-cli", flag.ContinueOnError)
	flags.SetOutput(errors)
	flags.Usage = func() {
		fmt.Fprintln(errors, "Usage: agent-cluster-cli [options] <command>")
		fmt.Fprintln(errors, "Global options may also be written after the command.")
		fmt.Fprintln(errors, "Commands:")
		for _, line := range tui.NonInteractiveCommandHelpLines() {
			fmt.Fprintln(errors, "  "+line)
		}
		fmt.Fprintln(errors, "  interactive        start the interactive REPL (equivalent to -i)")
		fmt.Fprintln(errors, "Options:")
		flags.PrintDefaults()
	}
	jsonMode := flags.Bool("json", false, "write structured JSON")
	filter := flags.String("endpoint", "", "filter by endpoint ID")
	confirmed := flags.Bool("yes", false, "confirm a mutating action")
	serverURL := flags.String("server-url", envOr("AGENT_CLUSTER_SERVER_URL", "http://127.0.0.1:8080"), "Server API URL")
	token := flags.String("token", os.Getenv("AGENT_CLUSTER_TOKEN"), "Server bearer token")
	waitTimeoutMS := flags.Int64("wait-timeout-ms", 0, "maximum local wait for command completion in milliseconds")
	maxBytes := flags.Int("max-bytes", 64<<10, "maximum output snapshot size in bytes")
	lines := flags.Int("lines", 100, "maximum number of output lines returned by logs")
	noColor := flags.Bool("no-color", false, "disable terminal colors")
	profile := flags.String("profile", "", "launch profile ID for start")
	profileRevision := flags.String("profile-revision", "", "launch profile revision for start")
	folder := flags.String("folder", "", "working folder for start")
	task := flags.String("task", "", "literal initial task text for start; no JSON is required")
	generation := flags.String("generation", "", "target generation; alternative to the positional generation argument")
	interactiveShort := flags.Bool("i", false, "start the interactive REPL (same as the interactive command)")
	if err := flags.Parse(hoistTrailingFlags(args)); err != nil {
		return err
	}
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
		readLine, closeEditor, editorErr := interactiveEditor(input, output)
		if editorErr != nil {
			return editorErr
		}
		defer closeEditor()
		return tui.RunInteractive(ctx, api, input, output, errors, tui.InteractiveOptions{ReadLine: readLine, MaxBytes: *maxBytes, MaxLines: *lines, WaitTimeoutMS: *waitTimeoutMS, Interrupt: interrupts, CloseInput: input == os.Stdin || interrupts != nil, Color: tui.ResolveColorPolicy(terminal, noColorPresent(), *noColor, strings.EqualFold(os.Getenv("TERM"), "dumb"), true)})
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
		return list(ctx, api, output, errors, *filter, listClean, *jsonMode, tui.ResolveColorPolicy(terminal, noColorPresent(), *noColor, strings.EqualFold(os.Getenv("TERM"), "dumb"), true))
	case "refresh":
		if err := parseRefreshArgs(flags.Args()[1:]); err != nil {
			return err
		}
		return refresh(ctx, api, output, errors, *filter, *jsonMode, tui.ResolveColorPolicy(terminal, noColorPresent(), *noColor, strings.EqualFold(os.Getenv("TERM"), "dumb"), true))
	case "endpoints":
		endpointFilter, err := parseEndpointsArgs(flags.Args()[1:], *filter)
		if err != nil {
			return err
		}
		return endpoints(ctx, api, output, endpointFilter, *jsonMode, tui.ResolveColorPolicy(terminal, noColorPresent(), *noColor, strings.EqualFold(os.Getenv("TERM"), "dumb"), true))
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
		return logs(ctx, api, output, flags.Arg(1), flags.Arg(2), *maxBytes, *lines, *jsonMode)
	case "status":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: status <command-id>")
		}
		return status(ctx, api, output, flags.Arg(1), *jsonMode)
	case "send", "btw", "inject", "control", "start", "resume", "stop":
		// A bare send or start reads a multi-line block from the command input.
		// On a terminal nothing else would prompt, so the operator would face a
		// silent wait; the hint goes to the diagnostics stream to keep the
		// machine-readable output clean.
		if hint := multiLineHint(flags.Arg(0), flags.NArg(), *task, terminal); hint != "" {
			if _, err := fmt.Fprintln(errors, hint); err != nil {
				return err
			}
		}
		color := tui.ResolveColorPolicy(terminal, noColorPresent(), *noColor, strings.EqualFold(os.Getenv("TERM"), "dumb"), true)
		return action(ctx, api, output, input, errors, color, flags.Args(), *confirmed, *jsonMode, *waitTimeoutMS, *profile, *profileRevision, *folder, *task, *generation)
	default:
		return fmt.Errorf("unknown command %q", flags.Arg(0))
	}
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

// globalOptionNames lists the options the top-level flag set owns. Only these are
// hoisted, so an option a subcommand owns (for example list --clean) keeps its
// position and its meaning.
var globalOptionNames = map[string]bool{
	"json": true, "endpoint": true, "yes": true, "server-url": true, "token": true,
	"wait-timeout-ms": true, "max-bytes": true, "lines": true, "no-color": true,
	"profile": true, "profile-revision": true, "folder": true, "task": true,
	"generation": true, "i": true,
}

// booleanGlobalOptions lists the hoisted options that take no value, so hoisting
// never swallows the following argument as if it were that option's value.
var booleanGlobalOptions = map[string]bool{
	"json": true, "yes": true, "no-color": true, "i": true,
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

func list(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, filter string, clean, jsonMode bool, color tui.ColorPolicy) error {
	return legacyRunner(api).ListWithOptions(ctx, output, errors, filter, jsonMode, tui.TableOptions{Width: tui.OutputWidth(output), Color: color, Clean: clean})
}

// refresh forces one fresh Endpoint collection and renders the committed
// inventory, so the operator's next view is fresh rather than a cached projection.
func refresh(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, filter string, jsonMode bool, color tui.ColorPolicy) error {
	refreshCtx, cancel := context.WithTimeout(ctx, tui.RefreshCommandTimeout())
	defer cancel()
	return legacyRunner(api).Refresh(refreshCtx, output, errors, filter, jsonMode, tui.TableOptions{Width: tui.OutputWidth(output), Color: color})
}

// endpoints renders the endpoint projection for the standalone CLI.
func endpoints(ctx context.Context, api tui.CommandAPI, output io.Writer, filter string, jsonMode bool, color tui.ColorPolicy) error {
	return legacyRunner(api).Endpoints(ctx, output, filter, jsonMode, tui.TableOptions{Width: tui.OutputWidth(output), Color: color})
}

func show(ctx context.Context, api tui.CommandAPI, output io.Writer, id string, jsonMode bool) error {
	return legacyRunner(api).Show(ctx, output, id, jsonMode)
}

// status renders one durable command result with conservative evidence wording.
func status(ctx context.Context, api tui.CommandAPI, output io.Writer, commandID string, jsonMode bool) error {
	return legacyRunner(api).Status(ctx, output, commandID, jsonMode)
}

func logs(ctx context.Context, api tui.CommandAPI, output io.Writer, endpointID, resourceID string, maxBytes, maxLines int, jsonMode bool) error {
	return legacyRunner(api).Logs(ctx, output, endpointID, resourceID, maxBytes, maxLines, jsonMode)
}

// resolveActionPayload converts one positional payload argument into the
// standard operation payload. Plain text is accepted for every operation that
// carries user text, so no caller has to write JSON; a JSON object is still
// forwarded unchanged as the advanced form.
func resolveActionPayload(operation, value string) (json.RawMessage, error) {
	switch operation {
	case "send", "btw", "inject":
		return tui.MessagePayload(value)
	case "control":
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
	if operation == "stop" && len(args) < 4 && generationFlag == "" {
		return fmt.Errorf("usage: stop <endpoint-id> <resource-id> <generation>")
	}
	if operation != "stop" && len(args) < 3 {
		return fmt.Errorf("usage: %s <endpoint-id> <resource-id> [text] [generation]", operation)
	}
	endpointID, resourceID := args[1], args[2]
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
	intent, err := runner.PrepareAction(ctx, request)
	if err != nil {
		return err
	}
	actionResult, err := runner.SubmitAction(ctx, intent)
	if err != nil {
		return err
	}
	result, err := runner.WaitAction(ctx, actionResult, intent.Budget)
	if err != nil {
		return err
	}
	return runner.RenderAction(output, result)
}

func operationName(value string) string {
	if value == "btw" || value == "inject" {
		return "context.inject"
	}
	if value == "control" {
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
