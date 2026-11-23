// Package providercli defines the provider-neutral process contract between an
// Endpoint Generic CLI Adapter and an independently built Provider CLI.
package providercli

import (
	"encoding/json"

	"topsailai_agent_cluster/internal/protocol"
)

const (
	// ProtocolName is the fixed Provider CLI protocol identifier.
	ProtocolName = "agent-cluster-adapter"
	// ProtocolMajor is the only supported major version.
	ProtocolMajor = 1
	// ProtocolMinor is the highest supported minor version.
	ProtocolMinor = 0
)

const (
	// FunctionDescribe reads the Provider descriptor.
	FunctionDescribe = "describe"
	// FunctionDiscover reads provider-owned resource observations.
	FunctionDiscover = "discover"
	// FunctionInspect revalidates one provider-private target.
	FunctionInspect = "inspect"
	// FunctionResolve mints the mapping key for a provider session identifier
	// the Endpoint has not discovered yet. It is local bookkeeping and never
	// invokes the business CLI, so it cannot become an existence check.
	FunctionResolve = "resolve"
	// FunctionExecute applies one standard mutating operation.
	FunctionExecute = "execute"
	// FunctionQuery executes one registered read-only query.
	FunctionQuery = "query"
	// FunctionQueryCommand reconciles one prior provider invocation.
	FunctionQueryCommand = "query_command"
	// FunctionReadOutput reads one bounded output snapshot.
	FunctionReadOutput = "read_output"
	// FunctionFollowOutput starts one bounded output stream.
	FunctionFollowOutput = "follow_output"
	// FunctionWatch starts one optional provider observation stream.
	FunctionWatch = "watch"
)

const (
	// ResourceAgent identifies a provider agent observation.
	ResourceAgent = protocol.ResourceAgent
	// ResourceSession identifies a provider session observation.
	ResourceSession = protocol.ResourceSession
	// ResourceTask identifies a provider task observation.
	ResourceTask = protocol.ResourceTask
	// ResourceLaunchProfile identifies a provider launch preset.
	ResourceLaunchProfile = protocol.ResourceLaunchProfile
	// ResourceModelProfile identifies a provider model preset.
	ResourceModelProfile = protocol.ResourceModelProfile
	// ResourceProject identifies a provider-managed project registry entry.
	ResourceProject = protocol.ResourceProject
)

const (
	// QueryLaunchOptions reads provider launch presets and projects.
	QueryLaunchOptions = "launch.options"
	// QueryHistoryMessages reads provider history messages.
	QueryHistoryMessages = "history.messages"
	// QueryModelCatalog reads selectable model profiles.
	QueryModelCatalog = "model.catalog"
	// QueryModelRegistry reads the model configurations an Endpoint offers to
	// launches, together with the selection a launch would use. It is separate
	// from QueryModelCatalog because a catalog addresses one session while a
	// registry addresses the machine.
	QueryModelRegistry = "model.registry"
	// QueryProjectCatalog reads managed project registry entries.
	QueryProjectCatalog = "project.catalog"
	// QuerySessionMessages reads the current provider session messages.
	QuerySessionMessages = "session.messages"
	// QuerySessionMetrics reads one session's current message counts.
	QuerySessionMetrics = "session.metrics"
	// QuerySessionMetricsBatch reads the current message counts of a bounded set
	// of sessions in one provider call.
	//
	// It exists beside QuerySessionMetrics rather than replacing it, because the
	// single-session read is a published contract and a legitimate request. The
	// two are implemented by one internal function, so they cannot drift into two
	// behaviours.
	QuerySessionMetricsBatch = "session.metrics.batch"
	// QuerySessionDetail reads one session's provider metadata and runtime document.
	QuerySessionDetail = "session.detail"
)

const (
	// EffectNotApplied means the provider proves no effect was applied.
	EffectNotApplied = "not_applied"
	// EffectAcknowledged means the provider has positive effect evidence.
	EffectAcknowledged = "acknowledged"
	// EffectUnknown means the provider cannot prove whether an effect occurred.
	EffectUnknown = "unknown"
)

const (
	// DeliveryNotStarted means provider delivery did not begin.
	DeliveryNotStarted = "not_started"
	// DeliverySubmitted means the provider accepted the request.
	DeliverySubmitted = "submitted"
	// DeliverySignalSent means the provider sent a process signal.
	DeliverySignalSent = "signal_sent"
	// DeliveryPipeWritten means the provider wrote the request to its input channel.
	DeliveryPipeWritten = "pipe_written"
)

const (
	// FrameStarted begins a Provider CLI stream.
	FrameStarted = "started"
	// FrameRecord carries one operation-specific stream record.
	FrameRecord = "record"
	// FrameEnd terminates a Provider CLI stream.
	FrameEnd = "end"
)

const (
	// MaxIdentifierBytes bounds opaque protocol identifiers.
	MaxIdentifierBytes = 256
	// MaxProviderTargetBytes bounds one opaque Provider-owned exact-target slot.
	MaxProviderTargetBytes = 4096
	// MaxProviderResponseBytes bounds one opaque provider response.
	MaxProviderResponseBytes = 64 << 10
	// MaxWarningBytes bounds one provider warning, and MaxWarnings bounds how many
	// a single result may carry. Both are needed because a warning is rendered to
	// the operator: an unbounded list of unbounded strings would let a provider
	// flood a terminal, which is the same reason provider_response is bounded.
	MaxWarningBytes = 512
	MaxWarnings     = 8
	// MaxErrorMessageBytes bounds one provider error message.
	MaxErrorMessageBytes = 4 << 10
)

// Version identifies one Provider CLI protocol version.
type Version struct {
	Protocol string `json:"protocol"`
	Major    int    `json:"major"`
	Minor    int    `json:"minor"`
}

// ProtocolRange declares the compatible minor versions for one protocol major.
type ProtocolRange struct {
	Protocol string `json:"protocol"`
	Major    int    `json:"major"`
	Minimum  int    `json:"minimum_minor"`
	Maximum  int    `json:"maximum_minor"`
}

// Budget bounds one Provider CLI invocation.
type Budget struct {
	MaxStdoutBytes int64 `json:"max_stdout_bytes"`
	MaxStderrBytes int64 `json:"max_stderr_bytes"`
	MaxRecords     int64 `json:"max_records"`
}

// Target identifies one provider-private resource and expected generation.
type Target struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	ExpectedGeneration  string `json:"expected_generation,omitempty"`
	// ProviderTarget is an opaque Provider-owned exact-target slot. The Generic
	// CLI Adapter validates only its bound and forwards it unchanged.
	ProviderTarget string `json:"provider_target,omitempty"`
}

// NamedContract identifies one versioned standard operation, query or control
// action.
//
// A control action also describes the capability it becomes, so the provider that
// implements the action is the source of what the action is: which resource kinds
// it addresses, the JSON Schema of its payload, and whether it changes provider
// state. Those three fields are empty for an operation or a query, because an
// operation's capability metadata is an Endpoint decision rather than a provider
// one.
//
// RequiredPermission is carried so the wire contract is complete, but the
// Endpoint never adopts it for a control action: who may invoke an action is an
// operator decision, and a provider that could declare its own permission could
// downgrade a control action to a read scope. See capabilityFromContract.
type NamedContract struct {
	Name    string `json:"name"`
	Version string `json:"version"`
	// TargetKinds are the resource kinds the action addresses.
	TargetKinds []string `json:"target_kinds,omitempty"`
	// PayloadSchema is the JSON Schema document of the action payload.
	PayloadSchema string `json:"payload_schema,omitempty"`
	// SafetyClass is read_only or mutating.
	SafetyClass string `json:"safety_class,omitempty"`
	// RequiredPermission is the operator scope the action needs. The Endpoint
	// keeps its own configured value and ignores a provider-declared one.
	RequiredPermission string `json:"required_permission,omitempty"`
}

// Request is one non-authoritative request sent to a Provider CLI.
type Request struct {
	Version
	RequestID    string          `json:"request_id"`
	Function     string          `json:"function"`
	AdapterID    string          `json:"adapter_id"`
	InvocationID string          `json:"invocation_id,omitempty"`
	DeadlineAtMS int64           `json:"deadline_at_ms"`
	Budget       Budget          `json:"budget"`
	Target       *Target         `json:"target,omitempty"`
	Operation    *NamedContract  `json:"operation,omitempty"`
	Query        *NamedContract  `json:"query,omitempty"`
	Payload      json.RawMessage `json:"payload"`
}

// ProviderObservation is one provider-owned resource fact before Cluster mapping.
type ProviderObservation struct {
	ProviderResourceKey string          `json:"provider_resource_key"`
	ProviderGeneration  string          `json:"provider_generation,omitempty"`
	ResourceKind        string          `json:"resource_kind"`
	State               string          `json:"state"`
	StateReason         string          `json:"state_reason,omitempty"`
	ObservedAtMS        int64           `json:"observed_at_ms"`
	Attributes          json.RawMessage `json:"attributes,omitempty"`
	ProviderTarget      string          `json:"provider_target,omitempty"`
}

// DiscoveryResult carries a bounded provider scan and its completeness evidence.
type DiscoveryResult struct {
	Observations []ProviderObservation `json:"observations"`
	Complete     bool                  `json:"complete"`
	Checkpoint   string                `json:"checkpoint,omitempty"`
}

// InspectionResult separates record existence from verified process liveness.
type InspectionResult struct {
	Found       bool                 `json:"found"`
	Live        bool                 `json:"live"`
	Observation *ProviderObservation `json:"observation,omitempty"`
}

// ResolutionResult reports the mapping key a Provider minted for a named
// session. It carries no existence, liveness or generation evidence.
type ResolutionResult struct {
	ProviderResourceKey string `json:"provider_resource_key"`
	ResourceKind        string `json:"resource_kind"`
}

// OutputSnapshot is one bounded, non-streaming provider output observation.
type OutputSnapshot struct {
	ObservedAtMS int64  `json:"observed_at_ms"`
	Content      string `json:"content"`
	Truncated    bool   `json:"truncated"`
	Complete     bool   `json:"complete"`
}

// ConcurrencyLimits are truthful Provider limits applied below Endpoint limits.
type ConcurrencyLimits struct {
	Total     int `json:"total"`
	Discovery int `json:"discovery"`
	Mutation  int `json:"mutation"`
	Follow    int `json:"follow"`
}

// Descriptor reports one Provider CLI implementation and its standard surface.
type Descriptor struct {
	ProviderType       string            `json:"provider_type"`
	ProviderVersion    string            `json:"provider_version"`
	DescriptorRevision string            `json:"descriptor_revision"`
	ProtocolRange      ProtocolRange     `json:"protocol_range"`
	Functions          []string          `json:"functions"`
	Operations         []NamedContract   `json:"operations"`
	Queries            []NamedContract   `json:"queries"`
	ControlActions     []NamedContract   `json:"control_actions"`
	Limits             Budget            `json:"limits"`
	Concurrency        ConcurrencyLimits `json:"concurrency"`
}

// OperationResult carries provider evidence without Cluster journal authority.
type OperationResult struct {
	ProviderRequestRef        string `json:"provider_request_ref,omitempty"`
	DeliveryBoundary          string `json:"delivery_boundary"`
	EffectCertainty           string `json:"effect_certainty"`
	ProviderOutcome           string `json:"provider_outcome"`
	ProviderResponse          string `json:"provider_response,omitempty"`
	ProviderResponseTruncated bool   `json:"provider_response_truncated"`
	StartedAtMS               int64  `json:"started_at_ms,omitempty"`
	FinishedAtMS              int64  `json:"finished_at_ms,omitempty"`
	// ExitConfirmed reports whether the provider confirmed that the signalled
	// process actually exited. It is separate from the delivery boundary because
	// a signal can be delivered without the exit being observed: the Cluster
	// keeps such a command at "executing" until the exit is confirmed, so a
	// provider that never reports this field leaves every signal_sent operation
	// permanently non-terminal.
	ExitConfirmed bool `json:"exit_confirmed,omitempty"`
	// Warnings carries bounded, non-fatal findings the provider reports about a
	// request it still executed. A warning is never a rejection: the operation
	// ran, and the warning explains what the provider could not honour. It is a
	// separate field rather than prose inside ProviderResponse because
	// ProviderResponse is the provider's own document, forwarded verbatim, and
	// prefixing a Cluster-facing sentence into it would make the Cluster a second
	// author of that document.
	Warnings []string `json:"warnings,omitempty"`
}

// ProviderError is one standard Provider CLI error document.
type ProviderError struct {
	Code            string `json:"code"`
	Message         string `json:"message"`
	Retryable       bool   `json:"retryable"`
	EffectCertainty string `json:"effect_certainty"`
}

// Response is one correlated non-streaming Provider CLI result.
type Response struct {
	Version
	RequestID   string            `json:"request_id"`
	OK          bool              `json:"ok"`
	Descriptor  *Descriptor       `json:"descriptor,omitempty"`
	Discovery   *DiscoveryResult  `json:"discovery,omitempty"`
	Inspection  *InspectionResult `json:"inspection,omitempty"`
	Resolution  *ResolutionResult `json:"resolution,omitempty"`
	Result      *OperationResult  `json:"result,omitempty"`
	QueryResult json.RawMessage   `json:"query_result,omitempty"`
	Output      *OutputSnapshot   `json:"output,omitempty"`
	Error       *ProviderError    `json:"error,omitempty"`
}

// StreamFrame is one correlated JSON Lines frame.
type StreamFrame struct {
	Version
	RequestID    string          `json:"request_id"`
	Type         string          `json:"type"`
	Sequence     int64           `json:"sequence"`
	ObservedAtMS int64           `json:"observed_at_ms,omitempty"`
	Record       json.RawMessage `json:"record,omitempty"`
	Truncated    bool            `json:"truncated,omitempty"`
	Error        *ProviderError  `json:"error,omitempty"`
}
