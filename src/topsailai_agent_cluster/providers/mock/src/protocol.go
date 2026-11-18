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
	functionResolve      = "resolve"
	functionExecute      = "execute"
	functionQuery        = "query"
	functionQueryCommand = "query_command"
	functionReadOutput   = "read_output"
	functionFollowOutput = "follow_output"
	// functionWatch is admitted by the wire schema but deliberately not served
	// here. The Cluster's watch command is a client-side re-render loop: it
	// re-reads the inventory on a timer and never sends a provider request, so
	// no provider function is involved. The constant is kept rather than deleted
	// because the protocol does admit the name, and dropping it would erase the
	// record that the mock is silent by choice rather than by oversight.
	functionWatch = "watch"
)

const (
	resourceSession          = "session"
	queryLaunchOptions       = "launch.options"
	queryHistoryMessages     = "history.messages"
	queryModelCatalog        = "model.catalog"
	querySessionMessages     = "session.messages"
	querySessionMetrics      = "session.metrics"
	querySessionMetricsBatch = "session.metrics.batch"
	querySessionDetail       = "session.detail"
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

// namedContract identifies one versioned operation or query.
type namedContract struct {
	Name               string   `json:"name"`
	Version            string   `json:"version"`
	TargetKinds        []string `json:"target_kinds,omitempty"`
	PayloadSchema      string   `json:"payload_schema,omitempty"`
	SafetyClass        string   `json:"safety_class,omitempty"`
	RequiredPermission string   `json:"required_permission,omitempty"`
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
	Resolution  *resolutionResult `json:"resolution,omitempty"`
	Result      *operationResult  `json:"result,omitempty"`
	QueryResult json.RawMessage   `json:"query_result,omitempty"`
	Output      *outputSnapshot   `json:"output,omitempty"`
	Error       *providerError    `json:"error,omitempty"`
}

// descriptor reports the Mock Provider surface.
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

// resolutionResult is one provider-private key minted for a named handle.
//
// It carries no existence claim: resolve translates a name the operator already
// chose, and the provider answers existence only when the operation reaches it.
type resolutionResult struct {
	ProviderResourceKey string `json:"provider_resource_key"`
	ResourceKind        string `json:"resource_kind"`
}

type inspectionResult struct {
	Found       bool                 `json:"found"`
	Live        bool                 `json:"live"`
	Observation *providerObservation `json:"observation,omitempty"`
}

type operationResult struct {
	ProviderRequestRef        string `json:"provider_request_ref,omitempty"`
	DeliveryBoundary          string `json:"delivery_boundary"`
	EffectCertainty           string `json:"effect_certainty"`
	ProviderOutcome           string `json:"provider_outcome"`
	ProviderResponse          string `json:"provider_response,omitempty"`
	ProviderResponseTruncated bool   `json:"provider_response_truncated"`
	StartedAtMS               int64  `json:"started_at_ms,omitempty"`
	FinishedAtMS              int64  `json:"finished_at_ms,omitempty"`
	ExitConfirmed             bool   `json:"exit_confirmed,omitempty"`
}

type outputSnapshot struct {
	ObservedAtMS int64  `json:"observed_at_ms"`
	Content      string `json:"content"`
	Truncated    bool   `json:"truncated"`
	Complete     bool   `json:"complete"`
}

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

// currentVersion returns the single protocol revision implemented by the Mock Provider.
func currentVersion() version {
	return version{Protocol: protocolName, Major: protocolMajor, Minor: protocolMinor}
}
