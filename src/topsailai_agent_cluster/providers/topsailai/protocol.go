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
	effectNotApplied = "not_applied"
	providerVersion  = "1.0.0"
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
	RequestID  string         `json:"request_id"`
	OK         bool           `json:"ok"`
	Descriptor *descriptor    `json:"descriptor,omitempty"`
	Error      *providerError `json:"error,omitempty"`
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
