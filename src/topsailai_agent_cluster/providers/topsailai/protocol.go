package main

import "encoding/json"

const (
	protocolName  = "agent-cluster-adapter"
	protocolMajor = 1
	protocolMinor = 0
)

const (
	functionDescribe     = "describe"
	functionDiscover     = "discover"
	functionInspect      = "inspect"
	functionExecute      = "execute"
	functionQuery        = "query"
	functionQueryCommand = "query_command"
	functionReadOutput   = "read_output"
	functionFollowOutput = "follow_output"
	functionWatch        = "watch"
)

const (
	resourceSession       = "session"
	resourceLaunchProfile = "launch_profile"
	resourceModelProfile  = "model_profile"

	queryLaunchOptions   = "launch.options"
	queryHistoryMessages = "history.messages"
	queryModelCatalog    = "model.catalog"
	querySessionMessages = "session.messages"

	effectNotApplied   = "not_applied"
	effectAcknowledged = "acknowledged"
	effectUnknown      = "unknown"

	deliveryNotStarted = "not_started"
	deliverySubmitted  = "submitted"

	providerVersion  = "1.0.0"
	operationVersion = "v1"
)

// Standard operation names this Provider serves.
//
// The names are the frozen Cluster contract, repeated here as literals because
// this executable is an independent module and must not import Cluster packages.
// A name that is not listed is not implemented, so an unknown operation fails
// closed instead of reaching a provider command.
const (
	operationMessageSend      = "message.send"
	operationContextInject    = "context.inject"
	operationAgentStart       = "agent.start"
	operationAgentResume      = "agent.resume"
	operationAgentStop        = "agent.stop"
	operationAgentDriveStart  = "agent.drive.start"
	operationAgentDriveStop   = "agent.drive.stop"
	operationWorkspaceClean   = "workspace.clean"
	operationAgentModelSelect = "agent.model.select"

	// controlOperationPrefix addresses the provider control family, whose action
	// names come from local configuration rather than from this list.
	controlOperationPrefix = "ctl."
)

const (
	frameStarted = "started"
	frameRecord  = "record"
	frameEnd     = "end"
)

// version identifies the public Provider CLI protocol revision.
type version struct {
	Protocol string `json:"protocol"`
	Major    int    `json:"major"`
	Minor    int    `json:"minor"`
}

// budget bounds one Provider CLI invocation.
type budget struct {
	MaxStdoutBytes int64 `json:"max_stdout_bytes"`
	MaxStderrBytes int64 `json:"max_stderr_bytes"`
	MaxRecords     int64 `json:"max_records"`
}

// target identifies one provider-private resource.
type target struct {
	ResourceKind        string `json:"resource_kind"`
	ProviderResourceKey string `json:"provider_resource_key"`
	ExpectedGeneration  string `json:"expected_generation,omitempty"`
}

// namedContract identifies one versioned standard operation or query.
type namedContract struct {
	Name    string `json:"name"`
	Version string `json:"version"`
}

// request is the public request envelope consumed from stdin.
type request struct {
	version
	RequestID    string          `json:"request_id"`
	Function     string          `json:"function"`
	AdapterID    string          `json:"adapter_id"`
	InvocationID string          `json:"invocation_id,omitempty"`
	DeadlineAtMS int64           `json:"deadline_at_ms"`
	Budget       budget          `json:"budget"`
	Target       *target         `json:"target,omitempty"`
	Operation    *namedContract  `json:"operation,omitempty"`
	Query        *namedContract  `json:"query,omitempty"`
	Payload      json.RawMessage `json:"payload"`
}

// providerError is one standard Provider CLI rejection.
type providerError struct {
	Code            string `json:"code"`
	Message         string `json:"message"`
	Retryable       bool   `json:"retryable"`
	EffectCertainty string `json:"effect_certainty"`
}

// response is one non-streaming Provider CLI result.
type response struct {
	version
	RequestID   string            `json:"request_id"`
	OK          bool              `json:"ok"`
	Descriptor  *descriptor       `json:"descriptor,omitempty"`
	Discovery   *discoveryResult  `json:"discovery,omitempty"`
	Inspection  *inspectionResult `json:"inspection,omitempty"`
	Result      *operationResult  `json:"result,omitempty"`
	QueryResult json.RawMessage   `json:"query_result,omitempty"`
	Output      *outputSnapshot   `json:"output,omitempty"`
	Error       *providerError    `json:"error,omitempty"`
}

// streamFrame is one strict JSON Lines lifecycle frame.
type streamFrame struct {
	version
	RequestID    string          `json:"request_id"`
	Type         string          `json:"type"`
	Sequence     int64           `json:"sequence"`
	ObservedAtMS int64           `json:"observed_at_ms,omitempty"`
	Record       json.RawMessage `json:"record,omitempty"`
	Truncated    bool            `json:"truncated,omitempty"`
	Error        *providerError  `json:"error,omitempty"`
}

// providerObservation is one provider-owned fact before Endpoint ID mapping.
type providerObservation struct {
	ProviderResourceKey string          `json:"provider_resource_key"`
	ProviderGeneration  string          `json:"provider_generation,omitempty"`
	ResourceKind        string          `json:"resource_kind"`
	State               string          `json:"state"`
	StateReason         string          `json:"state_reason,omitempty"`
	ObservedAtMS        int64           `json:"observed_at_ms"`
	Attributes          json.RawMessage `json:"attributes,omitempty"`
}

type discoveryResult struct {
	Observations []providerObservation `json:"observations"`
	Complete     bool                  `json:"complete"`
	Checkpoint   string                `json:"checkpoint,omitempty"`
}

type inspectionResult struct {
	Found       bool                 `json:"found"`
	Live        bool                 `json:"live"`
	Observation *providerObservation `json:"observation,omitempty"`
}

// operationResult carries Provider evidence for one mutation.
//
// It deliberately holds no Cluster identity, journal state or receipt: the
// Endpoint owns those, and a Provider that reported them would be a second source
// of truth for facts it cannot observe.
type operationResult struct {
	ProviderRequestRef        string `json:"provider_request_ref,omitempty"`
	DeliveryBoundary          string `json:"delivery_boundary"`
	EffectCertainty           string `json:"effect_certainty"`
	ProviderOutcome           string `json:"provider_outcome"`
	ProviderResponse          string `json:"provider_response,omitempty"`
	ProviderResponseTruncated bool   `json:"provider_response_truncated"`
	StartedAtMS               int64  `json:"started_at_ms,omitempty"`
	FinishedAtMS              int64  `json:"finished_at_ms,omitempty"`
}

type outputSnapshot struct {
	ObservedAtMS int64  `json:"observed_at_ms"`
	Content      string `json:"content"`
	Truncated    bool   `json:"truncated"`
	Complete     bool   `json:"complete"`
}

// descriptor reports the independently built TopsailAI Provider surface.
type descriptor struct {
	ProviderType       string            `json:"provider_type"`
	ProviderVersion    string            `json:"provider_version"`
	DescriptorRevision string            `json:"descriptor_revision"`
	ProtocolRange      protocolRange     `json:"protocol_range"`
	Functions          []string          `json:"functions"`
	Operations         []namedContract   `json:"operations"`
	Queries            []namedContract   `json:"queries"`
	ControlActions     []namedContract   `json:"control_actions"`
	Limits             budget            `json:"limits"`
	Concurrency        concurrencyLimits `json:"concurrency"`
}

type protocolRange struct {
	Protocol string `json:"protocol"`
	Major    int    `json:"major"`
	Minimum  int    `json:"minimum_minor"`
	Maximum  int    `json:"maximum_minor"`
}

type concurrencyLimits struct {
	Total     int `json:"total"`
	Discovery int `json:"discovery"`
	Mutation  int `json:"mutation"`
	Follow    int `json:"follow"`
}

// currentVersion returns the single protocol revision implemented here.
func currentVersion() version {
	return version{Protocol: protocolName, Major: protocolMajor, Minor: protocolMinor}
}
