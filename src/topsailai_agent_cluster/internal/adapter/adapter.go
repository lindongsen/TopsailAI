// Package adapter defines the Endpoint-private provider adapter contract.
package adapter

import (
	"context"
	"errors"

	"topsailai_agent_cluster/internal/protocol"
)

// ErrUnsupported indicates that an adapter does not implement a requested capability.
var ErrUnsupported = errors.New("adapter capability unsupported")

// Descriptor identifies one configured adapter instance and its capabilities.
type Descriptor struct {
	AdapterID    string
	ProviderType string
	DisplayName  string
	Version      string
	Capabilities protocol.CapabilityDescriptor
}

// DiscoverRequest bounds one provider inventory operation.
type DiscoverRequest struct {
	TimeoutMS int64
}

// DiscoverResult contains provider-neutral session observations.
type DiscoverResult struct {
	Sessions         []protocol.Session
	Complete         bool
	CollectionStatus string
	ErrorCode        string
	ErrorMessage     string
	LastAttemptAtMS  int64
	LastSuccessAtMS  int64
	DataKnown        bool
	Stale            bool
}

// InspectRequest identifies a resource for provider verification.
type InspectRequest struct {
	Target protocol.CommandTarget
}

// InspectResult contains bounded provider-neutral target evidence.
type InspectResult struct {
	Found      bool
	Generation string
	State      string
}

// ExecuteRequest carries a validated standard operation.
type ExecuteRequest struct {
	Intent protocol.ImmutableIntent
}

// ExecuteResult contains the strongest provider handoff evidence available.
type ExecuteResult struct {
	Receipt protocol.ExecutionReceipt
}

// OutputRequest requests a bounded output snapshot.
// MaxBytes bounds the returned payload; MaxLines bounds the provider line count
// and zero keeps the provider default.
type OutputRequest struct {
	Target   protocol.CommandTarget
	MaxBytes int
	MaxLines int
}

// OutputResult contains a bounded output snapshot.
type OutputResult struct {
	Lines        []string
	Truncated    bool
	ScanLimited  bool
	ObservedAtMS int64
}

// ErrFollowStopped reports that the consumer ended the follow on purpose, for
// example because the operator pressed a key. It is a normal termination, not a
// provider failure, so a caller must not report it as an error.
var ErrFollowStopped = errors.New("output follow stopped by consumer")

// OutputFollower is an optional adapter capability that streams output records.
//
// It is deliberately separate from Adapter rather than a method on it: a
// provider that cannot stream keeps compiling and reports the capability as
// unsupported, instead of silently degrading a follow request into a snapshot
// that never updates. The callback receives each chunk as it arrives and returns
// ErrFollowStopped to end the stream early; any other returned error is a real
// failure. FollowOutput returns only after the stream ended, so the caller knows
// the provider child has been reaped.
//
// The request and chunk types are the protocol types rather than adapter-local
// copies, so the Endpoint can forward a frame to this method without translating
// it and without the adapter package depending on the Endpoint.
type OutputFollower interface {
	FollowOutput(context.Context, protocol.OutputFollowRequest, func(protocol.OutputChunk) error) error
}

// CommandQuery requests provider-side status for an opaque request reference.
type CommandQuery struct {
	ProviderRequestRef string
}

// CommandResult contains a provider command status when supported.
type CommandResult struct {
	Receipt protocol.ExecutionReceipt
}

// Event is a provider event delivered by an optional watch stream.
type Event struct {
	Name string
	Data []byte
}

// ResourceMapping binds a provider-native key to a durable opaque resource ID.
type ResourceMapping struct {
	AdapterID   string
	ProviderKey string
	ResourceID  string
}

// ResourceMapper persists and resolves Endpoint resource ownership.
type ResourceMapper interface {
	GetOrCreateResourceID(context.Context, string, string, int64) (ResourceMapping, error)
	LookupResourceID(context.Context, string) (ResourceMapping, error)
}

// Adapter is the Endpoint-private interface implemented by provider bindings.
type Adapter interface {
	Describe(context.Context) (Descriptor, error)
	Discover(context.Context, DiscoverRequest) (DiscoverResult, error)
	Inspect(context.Context, InspectRequest) (InspectResult, error)
	Execute(context.Context, ExecuteRequest) (ExecuteResult, error)
	ReadOutput(context.Context, OutputRequest) (OutputResult, error)
	QueryCommand(context.Context, CommandQuery) (CommandResult, error)
	Watch(context.Context) (<-chan Event, error)
	Close() error
}
