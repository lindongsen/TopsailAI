package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/mattn/go-isatty"

	"topsailai_agent_cluster/internal/client"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

func run(args []string) error {
	terminal := isatty.IsTerminal(os.Stdin.Fd()) || isatty.IsCygwinTerminal(os.Stdin.Fd())
	return runWithIO(args, os.Stdin, os.Stdout, os.Stderr, terminal)
}

func runWithIO(args []string, input io.Reader, output, errors io.Writer, terminal bool) error {
	flags := flag.NewFlagSet("agent-cluster-cli", flag.ContinueOnError)
	flags.SetOutput(errors)
	jsonMode := flags.Bool("json", false, "write structured JSON")
	filter := flags.String("endpoint", "", "filter by endpoint ID")
	confirmed := flags.Bool("yes", false, "confirm a mutating action")
	serverURL := flags.String("server-url", envOr("AGENT_CLUSTER_SERVER_URL", "http://127.0.0.1:8080"), "Server API URL")
	token := flags.String("token", os.Getenv("AGENT_CLUSTER_TOKEN"), "Server bearer token")
	waitTimeoutMS := flags.Int64("wait-timeout-ms", 0, "maximum local wait for command completion in milliseconds")
	maxBytes := flags.Int("max-bytes", 64<<10, "maximum output snapshot size in bytes")
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
		return tui.RunInteractive(ctx, api, input, output, errors, tui.InteractiveOptions{MaxBytes: *maxBytes, WaitTimeoutMS: *waitTimeoutMS})
	}
	switch flags.Arg(0) {
	case "list":
		return list(ctx, api, output, *filter, *jsonMode)
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

func list(ctx context.Context, api *client.APIClient, output io.Writer, filter string, jsonMode bool) error {
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return err
	}
	reports := make(map[string]protocol.InventoryReport, len(endpoints))
	for _, endpoint := range endpoints {
		report, fetchErr := api.GetInventory(ctx, endpoint.EndpointID)
		if fetchErr == nil {
			reports[endpoint.EndpointID] = report
		}
	}
	rows := tui.ListRows(endpoints, reports, filter)
	if jsonMode {
		return tui.RenderJSON(output, rows)
	}
	tui.RenderRows(output, rows)
	return nil
}

func show(ctx context.Context, api *client.APIClient, output io.Writer, id string, jsonMode bool) error {
	endpoints, err := api.ListEndpoints(ctx)
	if err != nil {
		return err
	}
	reports := make(map[string]protocol.InventoryReport, len(endpoints))
	for _, endpoint := range endpoints {
		report, fetchErr := api.GetInventory(ctx, endpoint.EndpointID)
		if fetchErr == nil {
			reports[endpoint.EndpointID] = report
		}
	}
	endpoint, report, session, err := tui.FindSession(id, endpoints, reports)
	if err != nil {
		return err
	}
	capabilities, capabilityErr := api.GetCapabilities(ctx, endpoint.EndpointID)
	detail := tui.Detail{Endpoint: endpoint, Session: session, Inventory: report, Capabilities: capabilities}
	resourceID := ""
	if session != nil {
		resourceID = session.SessionID
	}
	if commands, commandErr := api.ListCommands(ctx, endpoint.EndpointID, resourceID, 20); commandErr == nil {
		detail.CommandHistory = commands
	} else {
		detail.Unavailable = append(detail.Unavailable, "commands: "+commandErr.Error())
	}
	if capabilityErr != nil {
		detail.Unavailable = append(detail.Unavailable, "capabilities: "+capabilityErr.Error())
	}
	if jsonMode {
		return tui.RenderJSON(output, detail)
	}
	tui.RenderDetail(output, detail)
	return nil
}

// status renders one durable command result with conservative evidence wording.
func status(ctx context.Context, api *client.APIClient, output io.Writer, commandID string, jsonMode bool) error {
	result, err := api.GetCommand(ctx, commandID)
	if err != nil {
		return err
	}
	if jsonMode {
		return tui.RenderJSON(output, result)
	}
	label := tui.StatusLabel(protocol.CommandStatus(stringValue(result, "status")), tui.ReceiptForStatus(result))
	fmt.Fprintln(output, label)
	return nil
}

func stringValue(values map[string]any, key string) string {
	value, _ := values[key].(string)
	return value
}

func logs(ctx context.Context, api *client.APIClient, output io.Writer, endpointID, resourceID string, maxBytes int, jsonMode bool) error {
	report, err := api.GetInventory(ctx, endpointID)
	if err != nil {
		return err
	}
	generation := ""
	for _, session := range report.Sessions {
		if session.SessionID == resourceID {
			generation = session.Generation
			break
		}
	}
	snapshot, err := api.GetOutput(ctx, endpointID, resourceID, generation, maxBytes)
	if err != nil {
		return err
	}
	if snapshot.ErrorCode != "" {
		if jsonMode {
			return tui.RenderJSON(output, snapshot)
		}
		fmt.Fprintln(output, snapshot.ErrorCode)
		return nil
	}
	if jsonMode {
		return tui.RenderJSON(output, snapshot)
	}
	tui.RenderSnapshot(output, snapshot.ObservedAtMS, snapshot.Data, snapshot.Truncated)
	return nil
}

func action(ctx context.Context, api *client.APIClient, output io.Writer, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, profile, profileRevision string) error {
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
	parameters := string(payload)
	if err := tui.RequireConfirmation(confirmed, operation, resourceID, parameters); err != nil {
		return err
	}
	operationName := operationName(operation)
	descriptor, err := tui.PreflightCapability(ctx, api, endpointID, operationName)
	if err != nil {
		return err
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: fmt.Sprintf("tui-%d", time.Now().UnixNano()), IssuerID: "operator", Scope: "operator", EndpointID: endpointID, Operation: operationName, OperationVersion: "v1", CapabilityRevision: descriptor.Revision, PayloadSchemaVersion: "v1", Payload: payload, Budget: protocol.Budget{WaitTimeoutMS: waitTimeoutMS}, ExecuteBeforeAtMS: time.Now().Add(5 * time.Minute).UnixMilli()}
	if operationName != "agent.start" {
		intent.Target = &target
	}
	if operationName == "agent.start" {
		intent.LaunchProfileID, intent.ProfileRevision = profile, profileRevision
		if intent.LaunchProfileID == "" || intent.ProfileRevision == "" {
			return fmt.Errorf("start requires --profile and --profile-revision")
		}
	}
	if !json.Valid(payload) {
		return fmt.Errorf("payload must be valid JSON")
	}
	result, err := api.AdmitCommand(ctx, intent)
	if err != nil {
		return err
	}
	commandID, _ := result["command_id"].(string)
	if commandID == "" {
		commandID = intent.CommandID
	}
	waitCtx, waitCancel := tui.WaitContext(ctx, intent.Budget)
	defer waitCancel()
	result, err = tui.WaitForTerminal(waitCtx, api, commandID, 100*time.Millisecond)
	if err != nil {
		return err
	}
	if jsonMode {
		return tui.RenderJSON(output, result)
	}
	return tui.RenderJSON(output, result)
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
