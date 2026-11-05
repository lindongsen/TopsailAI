package protocol

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"
	"unicode"
)

// ImmutableIntent contains the versioned, deduplicated command meaning.
type ImmutableIntent struct {
	HashVersion          string          `json:"hash_version"`
	CommandID            string          `json:"command_id"`
	IssuerID             string          `json:"issuer_id"`
	Scope                string          `json:"scope"`
	EndpointID           string          `json:"endpoint_id"`
	Target               *CommandTarget  `json:"target,omitempty"`
	LaunchProfileID      string          `json:"launch_profile_id,omitempty"`
	ProfileRevision      string          `json:"profile_revision,omitempty"`
	Folder               string          `json:"folder,omitempty"`
	Operation            string          `json:"operation"`
	OperationVersion     string          `json:"operation_version"`
	CapabilityRevision   string          `json:"capability_revision"`
	PayloadSchemaVersion string          `json:"payload_schema_version"`
	Payload              json.RawMessage `json:"payload"`
	ExecuteBeforeAtMS    int64           `json:"execute_before_at_ms"`
	ExpectedRevision     int64           `json:"expected_resource_revision,omitempty"`
	Budget               Budget          `json:"budget,omitempty"`
}

// CommandTarget identifies a resource and its expected execution generation.
type CommandTarget struct {
	Kind       string `json:"kind"`
	ResourceID string `json:"resource_id"`
	Generation string `json:"generation"`
}

// ValidateFolder accepts an omitted folder and rejects unsafe supplied values.
func ValidateFolder(folder string) error {
	if folder == "" {
		return nil
	}
	if strings.TrimSpace(folder) != folder {
		return fmt.Errorf("folder must not have leading or trailing whitespace")
	}
	for _, character := range folder {
		if unicode.IsControl(character) {
			return fmt.Errorf("folder must not contain control characters")
		}
	}
	return nil
}

// TransportEnvelope carries immutable intent over a particular connection.
type TransportEnvelope struct {
	ProtocolVersion      string          `json:"protocol_version"`
	FrameID              string          `json:"frame_id"`
	ConnectionGeneration string          `json:"connection_generation"`
	EndpointInstanceID   string          `json:"endpoint_instance_id"`
	RequestID            string          `json:"request_id"`
	Intent               ImmutableIntent `json:"intent"`
}

// CommandPhase describes durable Endpoint execution progress.
type CommandPhase string

const (
	PhaseAccepted          CommandPhase = "accepted"
	PhaseInvocationStarted CommandPhase = "invocation_started"
	PhaseEndpointAdmitted  CommandPhase = "endpoint_admitted"
	PhaseReceiptRecorded   CommandPhase = "receipt_recorded"
)

// DeliveryBoundary describes the strongest known provider handoff.
type DeliveryBoundary string

const (
	DeliveryNotStarted  DeliveryBoundary = "not_started"
	DeliverySubmitted   DeliveryBoundary = "submitted"
	DeliverySignalSent  DeliveryBoundary = "signal_sent"
	DeliveryPipeWritten DeliveryBoundary = "pipe_written"
)

// EffectCertainty describes whether an external effect is known.
type EffectCertainty string

const (
	EffectNotApplied   EffectCertainty = "not_applied"
	EffectAcknowledged EffectCertainty = "acknowledged"
	EffectUnknown      EffectCertainty = "unknown"
)

// CommandStatus describes Server-side command lifecycle.
type CommandStatus string

const (
	StatusAdmitted         CommandStatus = "admitted"
	StatusDispatched       CommandStatus = "dispatched"
	StatusEndpointAdmitted CommandStatus = "endpoint_admitted"
	StatusExecuting        CommandStatus = "executing"
	StatusFinished         CommandStatus = "finished"
	StatusRejected         CommandStatus = "rejected"
	StatusFailed           CommandStatus = "failed"
	StatusExpired          CommandStatus = "expired"
	StatusCancelled        CommandStatus = "cancelled_before_execution"
	// StatusUnconfirmed is terminal: delivery happened but the exit was never confirmed
	// before the immutable deadline, so the external effect stays unknown.
	StatusUnconfirmed CommandStatus = "unconfirmed"
)

// ExecutionReceipt records bounded evidence without claiming provider success.
type ExecutionReceipt struct {
	CommandID          string           `json:"command_id"`
	RequestHash        string           `json:"request_hash"`
	CommandRevision    int64            `json:"command_revision"`
	EndpointInstanceID string           `json:"endpoint_instance_id"`
	Phase              CommandPhase     `json:"phase"`
	DeliveryBoundary   DeliveryBoundary `json:"delivery_boundary"`
	EffectCertainty    EffectCertainty  `json:"effect_certainty"`
	Outcome            string           `json:"outcome"`
	ErrorCode          string           `json:"error_code,omitempty"`
	ErrorMessage       string           `json:"error_message,omitempty"`
	StartedAtMS        int64            `json:"started_at_ms,omitempty"`
	FinishedAtMS       int64            `json:"finished_at_ms,omitempty"`
	ProviderRequestRef string           `json:"provider_request_ref,omitempty"`
	ExitConfirmed      bool             `json:"exit_confirmed"`
}

// Budget separates execution, local CLI, and caller wait limits.
type Budget struct {
	ExecuteBeforeAtMS int64 `json:"execute_before_at_ms"`
	CLITimeoutMS      int64 `json:"cli_timeout_ms"`
	WaitTimeoutMS     int64 `json:"wait_timeout_ms"`
}

// OutputSnapshotRequest requests a bounded output snapshot from an Endpoint.
type OutputSnapshotRequest struct {
	EndpointID string `json:"endpoint_id"`
	ResourceID string `json:"resource_id"`
	Generation string `json:"generation"`
	MaxBytes   int    `json:"max_bytes"`
}

// OutputSnapshotResponse contains a bounded output snapshot or an error code.
type OutputSnapshotResponse struct {
	Data         string `json:"data"`
	Truncated    bool   `json:"truncated"`
	ObservedAtMS int64  `json:"observed_at_ms"`
	ErrorCode    string `json:"error_code,omitempty"`
}

// CanonicalHash computes a versioned digest of the immutable intent fields.
func CanonicalHash(intent ImmutableIntent) (string, error) {
	if intent.HashVersion == "" || intent.CommandID == "" || intent.EndpointID == "" || intent.Operation == "" || intent.OperationVersion == "" || intent.CapabilityRevision == "" || intent.PayloadSchemaVersion == "" {
		return "", fmt.Errorf("required immutable intent field is missing")
	}
	if !json.Valid(intent.Payload) {
		return "", fmt.Errorf("payload is not valid JSON")
	}
	canonical := struct {
		HashVersion, CommandID, IssuerID, Scope, EndpointID                                                             string
		Target                                                                                                          *CommandTarget
		LaunchProfileID, ProfileRevision, Folder, Operation, OperationVersion, CapabilityRevision, PayloadSchemaVersion string
		Payload                                                                                                         json.RawMessage
		ExecuteBeforeAtMS, ExpectedRevision                                                                             int64
		Budget                                                                                                          Budget
	}{intent.HashVersion, intent.CommandID, intent.IssuerID, intent.Scope, intent.EndpointID, intent.Target, intent.LaunchProfileID, intent.ProfileRevision, intent.Folder, intent.Operation, intent.OperationVersion, intent.CapabilityRevision, intent.PayloadSchemaVersion, intent.Payload, intent.ExecuteBeforeAtMS, intent.ExpectedRevision, intent.Budget}
	data, err := json.Marshal(canonical)
	if err != nil {
		return "", fmt.Errorf("marshal canonical intent: %w", err)
	}
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:]), nil
}
