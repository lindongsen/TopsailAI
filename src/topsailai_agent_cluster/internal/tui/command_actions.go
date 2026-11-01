package tui

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// ActionRequest describes one immutable operator action.
type ActionRequest struct {
	Operation       string
	OperationLabel  string
	EndpointID      string
	ResourceID      string
	Generation      string
	Payload         json.RawMessage
	Confirmed       bool
	WaitTimeoutMS   int64
	Profile         string
	ProfileRevision string
}

// ActionResult contains the durable result and command identifier.
type ActionResult struct {
	CommandID string
	Value     map[string]any
}

// PrepareAction validates and constructs an immutable intent.
func (r CommandRunner) PrepareAction(ctx context.Context, request ActionRequest) (protocol.ImmutableIntent, error) {
	label := request.OperationLabel
	if label == "" {
		label = request.Operation
	}
	if err := RequireConfirmation(request.Confirmed, label, request.ResourceID, string(request.Payload)); err != nil {
		return protocol.ImmutableIntent{}, err
	}
	descriptor, err := PreflightCapability(ctx, r.API, request.EndpointID, request.Operation)
	if err != nil {
		return protocol.ImmutableIntent{}, err
	}
	if !json.Valid(request.Payload) {
		return protocol.ImmutableIntent{}, fmt.Errorf("payload must be valid JSON")
	}
	now := time.Now()
	if r.Now != nil {
		now = r.Now()
	}
	id := fmt.Sprintf("tui-%d", now.UnixNano())
	if r.NewID != nil {
		id = r.NewID()
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: id, IssuerID: "operator", Scope: "operator", EndpointID: request.EndpointID, Operation: request.Operation, OperationVersion: "v1", CapabilityRevision: descriptor.Revision, PayloadSchemaVersion: "v1", Payload: request.Payload, Budget: protocol.Budget{WaitTimeoutMS: request.WaitTimeoutMS}, ExecuteBeforeAtMS: now.UnixMilli() + 5*60*1000}
	if request.Operation != "agent.start" {
		intent.Target = &protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, Generation: request.Generation}
	}
	if request.Operation == "agent.start" {
		if request.Profile == "" || request.ProfileRevision == "" {
			return protocol.ImmutableIntent{}, fmt.Errorf("start requires --profile and --profile-revision")
		}
		intent.LaunchProfileID, intent.ProfileRevision = request.Profile, request.ProfileRevision
	}
	return intent, nil
}

// SubmitAction admits one immutable intent without retrying ambiguous failures.
func (r CommandRunner) SubmitAction(ctx context.Context, intent protocol.ImmutableIntent) (ActionResult, error) {
	result, err := r.API.AdmitCommand(ctx, intent)
	if err != nil {
		return ActionResult{CommandID: intent.CommandID}, err
	}
	commandID, _ := result["command_id"].(string)
	if commandID == "" {
		commandID = intent.CommandID
	}
	return ActionResult{CommandID: commandID, Value: result}, nil
}

// WaitAction polls the durable command result within the requested local budget.
func (r CommandRunner) WaitAction(ctx context.Context, action ActionResult, budget protocol.Budget) (map[string]any, error) {
	waitCtx, cancel := WaitContext(ctx, budget)
	defer cancel()
	return WaitForTerminal(waitCtx, r.API, action.CommandID, 100*time.Millisecond)
}

// RenderAction writes the policy-specific action result.
func (r CommandRunner) RenderAction(out io.Writer, result map[string]any) error {
	if r.Policy == LegacyPolicy {
		return RenderJSON(out, result)
	}
	_, err := fmt.Fprintln(out, StatusLabel(protocol.CommandStatus(stringValue(result, "status")), ReceiptForStatus(result)))
	return err
}
