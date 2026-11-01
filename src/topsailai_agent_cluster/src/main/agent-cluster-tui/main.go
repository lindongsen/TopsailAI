package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

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
	flags := flag.NewFlagSet("agent-cluster-tui", flag.ContinueOnError)
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
	switch flags.Arg(0) {
	case "list":
		return list(ctx, api, *filter, *jsonMode)
	case "show":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: show <endpoint-id-or-session-id>")
		}
		return show(ctx, api, flags.Arg(1), *jsonMode)
	case "logs":
		if flags.NArg() != 3 {
			return fmt.Errorf("usage: logs <endpoint-id> <session-id>")
		}
		return logs(ctx, api, flags.Arg(1), flags.Arg(2), *maxBytes, *jsonMode)
	case "status":
		if flags.NArg() != 2 {
			return fmt.Errorf("usage: status <command-id>")
		}
		return status(ctx, api, flags.Arg(1), *jsonMode)
	case "send", "btw", "control", "start", "resume", "stop":
		return action(ctx, api, flags.Args(), *confirmed, *jsonMode, *waitTimeoutMS, *profile, *profileRevision)
	default:
		return fmt.Errorf("unknown command %q", flags.Arg(0))
	}
}

func list(ctx context.Context, api *client.APIClient, filter string, jsonMode bool) error {
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
		return tui.RenderJSON(os.Stdout, rows)
	}
	tui.RenderRows(os.Stdout, rows)
	return nil
}

func show(ctx context.Context, api *client.APIClient, id string, jsonMode bool) error {
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
		return tui.RenderJSON(os.Stdout, detail)
	}
	tui.RenderDetail(os.Stdout, detail)
	return nil
}

// status renders one durable command result with conservative evidence wording.
func status(ctx context.Context, api *client.APIClient, commandID string, jsonMode bool) error {
	result, err := api.GetCommand(ctx, commandID)
	if err != nil {
		return err
	}
	if jsonMode {
		return tui.RenderJSON(os.Stdout, result)
	}
	label := tui.StatusLabel(protocol.CommandStatus(stringValue(result, "status")), tui.ReceiptForStatus(result))
	fmt.Fprintln(os.Stdout, label)
	return nil
}

func stringValue(values map[string]any, key string) string {
	value, _ := values[key].(string)
	return value
}

func logs(ctx context.Context, api *client.APIClient, endpointID, resourceID string, maxBytes int, jsonMode bool) error {
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
			return tui.RenderJSON(os.Stdout, snapshot)
		}
		fmt.Fprintln(os.Stdout, snapshot.ErrorCode)
		return nil
	}
	if jsonMode {
		return tui.RenderJSON(os.Stdout, snapshot)
	}
	tui.RenderSnapshot(os.Stdout, snapshot.ObservedAtMS, snapshot.Data, snapshot.Truncated)
	return nil
}

func action(ctx context.Context, api *client.APIClient, args []string, confirmed, jsonMode bool, waitTimeoutMS int64, profile, profileRevision string) error {
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
		return tui.RenderJSON(os.Stdout, result)
	}
	return tui.RenderJSON(os.Stdout, result)
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
