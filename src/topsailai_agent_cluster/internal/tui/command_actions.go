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
	Operation          string
	OperationLabel     string
	EndpointID         string
	ResourceID         string
	ProviderGeneration string
	Payload            json.RawMessage
	Confirmed          bool
	WaitTimeoutMS      int64
	Profile            string
	ProfileRevision    string
	Folder             string
	// DisplayName is the reported session name, used only to describe the target
	// in progress output. It is presentation data: it never participates in
	// routing, authorization or the immutable intent.
	ProviderDisplayName string
	// ProviderSessionID is the provider's own key for the session, used only to
	// describe the target in progress output. Like DisplayName it is presentation
	// data and never participates in routing or the immutable intent.
	ProviderSessionID string
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
	if err := protocol.ValidateFolder(request.Folder); err != nil {
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
	// The Endpoint matches a capability on both name and version, so the intent
	// must carry the advertised version. A hardcoded default would make an
	// advertised operation such as command.exec (version "1") unreachable.
	operationVersion, err := CapabilityVersion(descriptor, request.Operation)
	if err != nil {
		return protocol.ImmutableIntent{}, err
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: id, IssuerID: "operator", Scope: "operator", EndpointID: request.EndpointID, Operation: request.Operation, OperationVersion: operationVersion, CapabilityRevision: descriptor.Revision, PayloadSchemaVersion: "v1", Folder: request.Folder, Payload: request.Payload, Budget: protocol.Budget{WaitTimeoutMS: request.WaitTimeoutMS}, ExecuteBeforeAtMS: now.UnixMilli() + 5*60*1000}
	if request.Operation != "agent.start" {
		intent.Target = &protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, ProviderGeneration: request.ProviderGeneration}
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
	return r.WaitActionWithProgress(ctx, action, budget, nil)
}

// WaitActionWithProgress polls the durable command result and reports each
// observed lifecycle stage to progress. The reporter is presentation only, so a
// nil reporter keeps the previous behaviour exactly.
func (r CommandRunner) WaitActionWithProgress(ctx context.Context, action ActionResult, budget protocol.Budget, progress *ActionProgress) (map[string]any, error) {
	waitCtx, cancel := WaitContext(context.WithoutCancel(ctx), budget)
	defer cancel()
	return WaitForTerminalWithProgress(waitCtx, r.API, action.CommandID, 100*time.Millisecond, progress)
}

// RenderAction writes the policy-specific action result.
func (r CommandRunner) RenderAction(out io.Writer, result map[string]any) error {
	if r.Policy == LegacyPolicy {
		return RenderJSON(out, result)
	}
	return RenderReceipt(out, result)
}

// RenderReceipt writes the human-readable receipt for one durable command
// result: the conservative status label, the receipt fields and the provider's
// own return document as a readable section.
//
// Both surfaces render through this function, so the standalone command and the
// interactive REPL cannot disagree about which fields are shown or how the
// provider document is presented. The document is printed as its own section
// instead of inside a JSON envelope, because an escaped document is not the
// provider's answer: the operator asked for the provider's result, not for a
// quoted copy of it. The section renders a structured document as readable text,
// while the stored document and the --json envelope keep the provider's bytes.
func RenderReceipt(out io.Writer, result map[string]any) error {
	receipt := ReceiptForStatus(result)
	if _, err := fmt.Fprintln(out, StatusLabel(protocol.CommandStatus(stringValue(result, "status")), receipt)); err != nil {
		return err
	}
	return renderReceiptDetails(out, receipt)
}

// renderReceiptDetails prints the durable receipt fields carried by a result.
// Absent fields are skipped so a minimal response keeps its previous output.
func renderReceiptDetails(out io.Writer, receipt protocol.ExecutionReceipt) error {
	pairs := [][2]string{
		{"command_id", receipt.CommandID},
		{"phase", string(receipt.Phase)},
		{"delivery_boundary", string(receipt.DeliveryBoundary)},
		{"effect_certainty", string(receipt.EffectCertainty)},
		{"outcome", receipt.Outcome},
		{"error_code", receipt.ErrorCode},
		{"error_message", receipt.ErrorMessage},
	}
	for _, pair := range pairs {
		if pair[1] == "" {
			continue
		}
		if _, err := fmt.Fprintf(out, "%s: %s\n", pair[0], pair[1]); err != nil {
			return err
		}
	}
	return renderProviderResponse(out, receipt.ProviderResponse, receipt.ProviderResponseTruncated)
}

// renderProviderResponse prints the provider's own return document as a separate
// section, so the operator can distinguish this service's receipt from the
// provider's raw answer. An absent document prints nothing, which keeps the
// previous output byte-identical for providers that return no document.
//
// A document that is one JSON object or array is rendered as readable text through
// renderStructuredBody, because raw JSON is not something an operator can read: a
// first-level value that is itself an object or a list arrives as one long line of
// braces and quotes. The rendering is generic and names no provider field, so a new
// provider needs no renderer change.
//
// The rendering is display-only. The stored document and the --json envelope keep
// the provider's own bytes, so choosing the human form never loses evidence. A
// document that is not one JSON value, such as provider stderr or a truncated
// answer, is printed verbatim: re-encoding it would either fail or drop the part
// that did not parse, and that part is the only diagnostic the operator has.
//
// Escape sequences are not stripped here: the terminal boundary already does that,
// and the stored document must stay faithful to what the provider returned.
func renderProviderResponse(out io.Writer, response string, truncated bool) error {
	if response == "" {
		return nil
	}
	if _, err := fmt.Fprintf(out, "provider_response:\n%s\n", renderStructuredBody(response)); err != nil {
		return err
	}
	if !truncated {
		return nil
	}
	_, err := fmt.Fprintf(out, "provider_response_truncated: true (limit %d bytes)\n", protocol.MaxProviderResponseBytes)
	return err
}
