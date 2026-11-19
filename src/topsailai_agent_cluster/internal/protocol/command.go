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

// CommandTarget identifies a resource and its expected provider generation.
//
// ProviderSessionHandle is an optional cluster-level selector for a target the
// operator named by its provider session identifier instead of its opaque
// cluster resource ID. It exists because the operator may know the provider's
// own identifier while the Endpoint has never discovered that session, so no
// durable mapping exists yet. The Endpoint resolves the handle through the
// owning adapter before it inspects or invokes anything, and the resolved
// mapping then supplies ResourceID for the rest of the command. Exactly one of
// ResourceID and ProviderSessionHandle is required; a target that carries both
// is ambiguous and is rejected rather than silently preferring one.
type CommandTarget struct {
	Kind                  string `json:"kind"`
	ResourceID            string `json:"resource_id"`
	ProviderGeneration    string `json:"provider_generation"`
	ProviderSessionHandle string `json:"provider_session_handle,omitempty"`
	// ProviderTarget is optional Provider-owned exact-target evidence copied from
	// the reported resource. It supplements, and never replaces, Cluster identity
	// and generation checks.
	ProviderTarget string `json:"provider_target,omitempty"`
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

// ReceiptRejection names why a Server refused a receipt it could not apply.
//
// The vocabulary is closed and shared by both sides, because the Endpoint must
// decide from the reason alone whether the receipt can be forgotten. A free-form
// message would force the Endpoint to parse prose, and a reason it does not
// recognise must leave the receipt pending rather than discard evidence.
type ReceiptRejection string

const (
	// ReceiptRejectedUnknownCommand means the Server holds no intent matching the
	// receipt's command ID and request hash. This is the normal outcome after an
	// Endpoint is re-homed to a different Server, which never admitted the
	// command. The receipt is settled because no future retry can make the Server
	// recognise it.
	ReceiptRejectedUnknownCommand ReceiptRejection = "unknown_command"
	// ReceiptRejectedRevisionStale means the Server already stores a newer
	// revision of the same receipt. The submitted revision is represented by that
	// newer one, so the receipt is settled rather than retried forever.
	ReceiptRejectedRevisionStale ReceiptRejection = "revision_stale"
	// ReceiptRejectedRevisionConflict means the Server stores a different receipt
	// at the same revision. This is a real integrity disagreement, not a
	// re-homing artefact, so it is never settled: discarding it would erase the
	// only evidence that two sides disagree about one command.
	ReceiptRejectedRevisionConflict ReceiptRejection = "revision_conflict"
)

// Settles reports whether a rejection reason authorises the Endpoint to forget
// the receipt.
//
// Only the two reasons that prove the receipt can never be applied settle. An
// unrecognised reason returns false, so a newer Server that introduces a reason
// this Endpoint does not understand keeps the receipt pending instead of
// silently dropping it.
func (r ReceiptRejection) Settles() bool {
	return r == ReceiptRejectedUnknownCommand || r == ReceiptRejectedRevisionStale
}

// SettlementOrigin names which terminal outcome ended a receipt's resend
// obligation.
//
// It is a separate axis from ReceiptRejection on purpose. A rejection reason
// answers "why can this receipt never be applied", and only some rejections
// settle. An acknowledgement answers "the Server already holds this receipt",
// which is a different fact and carries no rejection reason at all. Storing both
// in one column would force the reason column to describe two unrelated events,
// and a reader could no longer tell an integrity conflict from a delivery
// confirmation.
type SettlementOrigin string

const (
	// SettlementOriginRejection means the Server refused the receipt and named a
	// reason that proves it can never be applied.
	SettlementOriginRejection SettlementOrigin = "rejection"
	// SettlementOriginAcknowledgement means the Server durably stored the receipt
	// and acknowledged it, so the Endpoint must stop re-sending it.
	SettlementOriginAcknowledgement SettlementOrigin = "acknowledgement"
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

// MaxProviderResponseBytes bounds the opaque provider return document carried in
// one receipt. The bound is applied at the adapter boundary, so an oversized
// provider document is truncated and labelled before it can reach storage.
const MaxProviderResponseBytes = 64 << 10

// ExecutionReceipt records bounded evidence without claiming provider success.
// ProviderResponse carries the provider's own return document verbatim. It is an
// opaque bounded string, never a provider schema: Server stores and returns it
// without interpreting any field, so the Server/Endpoint abstraction boundary is
// unchanged. ProviderResponseTruncated reports that the bound was reached, so a
// shortened document is never presented as complete.
type ExecutionReceipt struct {
	CommandID                 string           `json:"command_id"`
	RequestHash               string           `json:"request_hash"`
	CommandRevision           int64            `json:"command_revision"`
	EndpointInstanceID        string           `json:"endpoint_instance_id"`
	Phase                     CommandPhase     `json:"phase"`
	DeliveryBoundary          DeliveryBoundary `json:"delivery_boundary"`
	EffectCertainty           EffectCertainty  `json:"effect_certainty"`
	Outcome                   string           `json:"outcome"`
	ErrorCode                 string           `json:"error_code,omitempty"`
	ErrorMessage              string           `json:"error_message,omitempty"`
	StartedAtMS               int64            `json:"started_at_ms,omitempty"`
	FinishedAtMS              int64            `json:"finished_at_ms,omitempty"`
	ProviderRequestRef        string           `json:"provider_request_ref,omitempty"`
	ProviderResponse          string           `json:"provider_response,omitempty"`
	ProviderResponseTruncated bool             `json:"provider_response_truncated,omitempty"`
	ExitConfirmed             bool             `json:"exit_confirmed"`
}

// Budget separates execution, local CLI, and caller wait limits.
type Budget struct {
	ExecuteBeforeAtMS int64 `json:"execute_before_at_ms"`
	CLITimeoutMS      int64 `json:"cli_timeout_ms"`
	WaitTimeoutMS     int64 `json:"wait_timeout_ms"`
}

// OutputSnapshotRequest requests a bounded output snapshot from an Endpoint.
// MaxBytes bounds the returned payload; MaxLines bounds the provider line count
// and zero keeps the provider default.
type OutputSnapshotRequest struct {
	EndpointID         string `json:"endpoint_id"`
	ResourceID         string `json:"resource_id"`
	ProviderGeneration string `json:"provider_generation"`
	ProviderTarget     string `json:"provider_target,omitempty"`
	MaxBytes           int    `json:"max_bytes"`
	MaxLines           int    `json:"max_lines"`
}

// OutputSnapshotResponse contains a bounded output snapshot or an error code.
type OutputSnapshotResponse struct {
	Data         string `json:"data"`
	Truncated    bool   `json:"truncated"`
	ObservedAtMS int64  `json:"observed_at_ms"`
	ErrorCode    string `json:"error_code,omitempty"`
}

// OutputFollowRequest starts one streaming output follow for an exact resource
// generation. It is a distinct capability from OutputSnapshotRequest: a snapshot
// is one bounded read, while a follow stays open and delivers records as they are
// written. MaxLines bounds the initial tail and MaxBytes bounds one chunk.
type OutputFollowRequest struct {
	EndpointID         string `json:"endpoint_id"`
	ResourceID         string `json:"resource_id"`
	ProviderGeneration string `json:"provider_generation"`
	ProviderTarget     string `json:"provider_target,omitempty"`
	MaxLines           int    `json:"max_lines"`
	MaxBytes           int    `json:"max_bytes"`
}

// OutputChunk carries one bounded batch of followed output lines. Lines are
// already complete records, so a consumer never has to reassemble a partial line.
// Truncated reports that a record exceeded the byte budget and was shortened, so a
// consumer never presents a shortened record as complete.
type OutputChunk struct {
	Lines        []string `json:"lines"`
	ObservedAtMS int64    `json:"observed_at_ms"`
	Truncated    bool     `json:"truncated,omitempty"`
}

// OutputEnd terminates one follow stream. It is always the last frame for a
// request, so a consumer that stops receiving chunks without it must treat the
// stream as interrupted rather than complete. ErrorCode is empty for a normal
// termination.
type OutputEnd struct {
	ErrorCode    string `json:"error_code,omitempty"`
	ObservedAtMS int64  `json:"observed_at_ms"`
	Truncated    bool   `json:"truncated,omitempty"`
}

// OutputFollowRecord is one streamed output record delivered to a consumer.
//
// Exactly one record carries End, and it is always the last one, so a consumer
// that stops receiving records without End must treat the stream as interrupted
// rather than complete. The type lives in the protocol package because both the
// API client and the terminal surfaces consume it, and the terminal package must
// not depend on the HTTP client.
type OutputFollowRecord struct {
	Lines        []string
	ObservedAtMS int64
	Truncated    bool
	End          bool
	ErrorCode    string
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
