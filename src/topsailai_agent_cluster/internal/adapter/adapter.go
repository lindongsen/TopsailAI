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
	// Found reports that the provider still lists the record.
	Found bool
	// Live reports that the provider also proved a process holds the record, so
	// the target is currently active. It is deliberately separate from Found: a
	// record can be listed while its liveness is unverified, and an operation that
	// authorizes on the absence of a live target must read Live, not Found.
	Live               bool
	ProviderGeneration string
	State              string
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

// HandleResolver is an optional adapter capability that turns a provider session
// handle into a durable resource mapping.
//
// It exists for the case where an operator names a session by the provider's own
// identifier before the Endpoint has ever discovered it, so no mapping exists
// yet. The Endpoint selects the single configured adapter that implements this
// interface and asks it to mint the mapping; an adapter that does not implement
// it cannot address a handle and is never asked. Minting is local bookkeeping and
// must not query the provider, because the operator already named the target and
// the Endpoint must not decide whether that session exists. The provider remains
// the only party that answers existence, when the operation reaches it.
//
// The adapter mints the mapping through the same durable mapper it uses for
// discovery, so the resolved resource ID is stable and identical to the one a
// later discovery would produce. Provider-specific spelling never leaves the
// adapter: the Endpoint only passes the handle through and receives a mapping.
type HandleResolver interface {
	ResolveProviderSessionHandle(context.Context, string) (ResourceMapping, error)
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
