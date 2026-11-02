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
	jsonMode := flags.Bool("json", false, "write structured JSON")
	filter := flags.String("endpoint", "", "filter by endpoint ID")
	confirmed := flags.Bool("yes", false, "confirm a mutating action")
	serverURL := flags.String("server-url", envOr("AGENT_CLUSTER_SERVER_URL", "http://127.0.0.1:8080"), "Server API URL")
	token := flags.String("token", os.Getenv("AGENT_CLUSTER_TOKEN"), "Server bearer token")
	waitTimeoutMS := flags.Int64("wait-timeout-ms", 0, "maximum local wait for command completion in milliseconds")
	maxBytes := flags.Int("max-bytes", 64<<10, "maximum output snapshot size in bytes")
	noColor := flags.Bool("no-color", false, "disable terminal colors")
	profile := flags.String("profile", "", "launch profile ID for start")
	profileRevision := flags.String("profile-revision", "", "launch profile revision for start")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() == 0 {
		return fmt.Errorf("a command is required: list, show, logs, send, stop")
	}
	api := client.NewAPIClient(*serverURL, *token)
	ctx := context.Background()
	if flags.Arg(0) == "interactive" {
		if flags.NArg() != 1 {
			return fmt.Errorf("usage: interactive")
		}
		if *jsonMode || *confirmed {
			return fmt.Errorf("interactive does not support --json or --yes")
		}
		if !terminal {
			return fmt.Errorf("interactive mode requires a terminal on stdin")
		}
		return tui.RunInteractive(ctx, api, input, output, errors, tui.InteractiveOptions{MaxBytes: *maxBytes, WaitTimeoutMS: *waitTimeoutMS, Interrupt: interrupts, CloseInput: input == os.Stdin || interrupts != nil, Color: tui.ResolveColorPolicy(terminal, noColorPresent(), *noColor, strings.EqualFold(os.Getenv("TERM"), "dumb"), true)})
	}
	switch flags.Arg(0) {
	case "list":
		return list(ctx, api, output, errors, *filter, *jsonMode, tui.ResolveColorPolicy(terminal, noColorPresent(), *noColor, strings.EqualFold(os.Getenv("TERM"), "dumb"), true))
	case "table":
		return table(ctx, api, output, errors, *filter, *jsonMode, tui.ResolveColorPolicy(terminal, noColorPresent(), *noColor, strings.EqualFold(os.Getenv("TERM"), "dumb"), true))
	case "show":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: show <endpoint-id-or-session-id>")
		}
		return show(ctx, api, output, flags.Arg(1), *jsonMode)
	case "logs":
		if flags.NArg() != 3 {
			return fmt.Errorf("usage: logs <endpoint-id> <session-id>")
		}
		return logs(ctx, api, output, flags.Arg(1), flags.Arg(2), *maxBytes, *jsonMode)
	case "status":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: status <command-id>")
		}
		return status(ctx, api, output, flags.Arg(1), *jsonMode)
	case "send", "btw", "control", "start", "resume", "stop":
		return action(ctx, api, output, flags.Args(), *confirmed, *jsonMode, *waitTimeoutMS, *profile, *profileRevision)
	default:
		return fmt.Errorf("unknown command %q", flags.Arg(0))
	}
}

func legacyRunner(api tui.CommandAPI) tui.CommandRunner {
	return tui.CommandRunner{API: api, Policy: tui.LegacyPolicy}
}

func table(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, filter string, jsonMode bool, color tui.ColorPolicy) error {
	return legacyRunner(api).Table(ctx, output, errors, filter, jsonMode, tui.TableOptions{Color: color})
}

func list(ctx context.Context, api tui.CommandAPI, output, errors io.Writer, filter string, jsonMode bool, color tui.ColorPolicy) error {
	return legacyRunner(api).ListWithOptions(ctx, output, errors, filter, jsonMode, tui.TableOptions{Color: color})
}

func show(ctx context.Context, api tui.CommandAPI, output io.Writer, id string, jsonMode bool) error {
	return legacyRunner(api).Show(ctx, output, id, jsonMode)
}

// status renders one durable command result with conservative evidence wording.
func status(ctx context.Context, api tui.CommandAPI, output io.Writer, commandID string, jsonMode bool) error {
	return legacyRunner(api).Status(ctx, output, commandID, jsonMode)
}

func logs(ctx context.Context, api tui.CommandAPI, output io.Writer, endpointID, resourceID string, maxBytes int, jsonMode bool) error {
	return legacyRunner(api).Logs(ctx, output, endpointID, resourceID, maxBytes, jsonMode)
}

func action(ctx context.Context, api tui.CommandAPI, output io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, profile, profileRevision string) error {
	operation := args[0]
	if operation == "stop" && len(args) < 4 {
		return fmt.Errorf("usage: stop <endpoint-id> <resource-id> <generation>")
	}
	if operation != "stop" && len(args) < 3 {
		return fmt.Errorf("usage: %s <endpoint-id> <resource-id> [payload] [generation]", operation)
	}
	endpointID, resourceID := args[1], args[2]
	generation := ""
	payload := json.RawMessage(`{}`)
	if operation == "stop" {
		generation = args[3]
	} else {
		if len(args) >= 4 {
			payload = json.RawMessage(args[3])
		}
		if len(args) >= 5 {
			generation = args[4]
		}
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
	request := tui.ActionRequest{Operation: operationValue, OperationLabel: operation, EndpointID: endpointID, ResourceID: resourceID, Generation: generation, Payload: payload, Confirmed: confirmed, WaitTimeoutMS: waitTimeoutMS, Profile: profile, ProfileRevision: profileRevision}
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
	if value == "btw" {
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
