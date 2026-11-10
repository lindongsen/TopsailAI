package endpoint

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// Executor executes validated commands through one Endpoint-local adapter registry.
type Executor struct {
	store            *endpointstorage.Store
	registry         *adapter.Registry
	mu               sync.Mutex
	locks            map[string]*sync.Mutex
	now              func() time.Time
	BeforeInvocation func()
	AdmissionHook    func(context.Context, protocol.ImmutableIntent, string) error
	// PolicyHook authorizes an intent before the journal records an invocation.
	// It must run before MarkInvocationStarted, because a rejection recorded after
	// that point would be indistinguishable from a crash mid-invocation and would
	// surface as a false "unknown" effect for a command that was never applied.
	PolicyHook func(context.Context, protocol.ImmutableIntent) error
}

// NewExecutor constructs an Endpoint command executor.
func NewExecutor(store *endpointstorage.Store, registry *adapter.Registry, hooks ...func()) (*Executor, error) {
	if store == nil || registry == nil {
		return nil, errors.New("store and registry are required")
	}
	var beforeInvocation func()
	if len(hooks) > 0 {
		beforeInvocation = hooks[0]
	}
	return &Executor{store: store, registry: registry, locks: make(map[string]*sync.Mutex), now: time.Now, BeforeInvocation: beforeInvocation}, nil
}

// Execute admits and executes one command, preserving durable uncertainty on crashes.
func (e *Executor) Execute(ctx context.Context, intent protocol.ImmutableIntent, requestHash string) (protocol.ExecutionReceipt, error) {
	entry, _, err := e.store.AdmitJournal(ctx, intent, requestHash, e.now().UnixMilli())
	if err != nil {
		return protocol.ExecutionReceipt{}, err
	}
	if entry.Phase == protocol.PhaseReceiptRecorded {
		return decodeReceipt(entry.ReceiptJSON)
	}
	if entry.Phase == protocol.PhaseInvocationStarted || entry.Phase == protocol.PhaseEndpointAdmitted {
		return unknownReceipt(intent, requestHash, "invocation_recovery_unknown"), nil
	}
	lock := e.lockFor(targetKey(intent))
	lock.Lock()
	defer lock.Unlock()
	entry, _, err = e.store.AdmitJournal(ctx, intent, requestHash, e.now().UnixMilli())
	if err != nil {
		return protocol.ExecutionReceipt{}, err
	}
	if entry.Phase == protocol.PhaseReceiptRecorded {
		return decodeReceipt(entry.ReceiptJSON)
	}
	if entry.Phase == protocol.PhaseInvocationStarted || entry.Phase == protocol.PhaseEndpointAdmitted {
		return unknownReceipt(intent, requestHash, "invocation_recovery_unknown"), nil
	}
	if intent.ExecuteBeforeAtMS > 0 && e.now().UnixMilli() > intent.ExecuteBeforeAtMS {
		receipt := unknownReceipt(intent, requestHash, "expired_before_execution")
		receipt.EffectCertainty = protocol.EffectNotApplied
		receipt.Outcome = "expired"
		return e.recordEarlyRejection(ctx, intent, receipt)
	}
	instance, adapterID, err := e.adapterForIntent(ctx, intent)
	if err != nil {
		// A coded resolution failure is a decision about the target, so it must
		// become a durable terminal rejection. Returning a bare error here left
		// the command looking in-flight forever, because no receipt was recorded
		// and the Server therefore never learned the outcome.
		var coded *resolutionError
		if errors.As(err, &coded) {
			receipt := rejectedReceipt(intent, requestHash, coded.code)
			receipt.ErrorMessage = coded.message
			return e.recordEarlyRejection(ctx, intent, receipt)
		}
		return protocol.ExecutionReceipt{}, err
	}
	descriptor, err := instance.Describe(ctx)
	if err != nil {
		// The adapter is configured but cannot describe itself, so no capability
		// can be validated and nothing was invoked: the effect is provably not
		// applied and the command is terminally rejected.
		receipt := rejectedReceipt(intent, requestHash, "capability_unavailable")
		receipt.ErrorMessage = err.Error()
		return e.recordEarlyRejection(ctx, intent, receipt)
	}
	if intent.Operation == "agent.start" {
		if intent.LaunchProfileID == "" || intent.ProfileRevision == "" {
			return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "profile_required"))
		}
		if descriptor.Capabilities.Revision != intent.ProfileRevision {
			return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "profile_revision_mismatch"))
		}
	}
	if !supports(descriptor.Capabilities, intent.Operation, intent.OperationVersion) {
		return e.recordEarlyRejection(ctx, intent, unsupportedReceipt(intent, requestHash))
	}
	if intent.Target != nil {
		if intent.Operation == protocol.OperationAgentResume {
			// Resume authorizes on the absence of a live target, and that absence
			// must come from the authoritative provider observation: a cached
			// snapshot can lag one collection cycle behind and would let a resume
			// target a session that is already active again. The check reads Live
			// rather than Found, because a record whose process is gone is still
			// listed by the provider; refusing on Found would reject exactly the
			// sessions resume exists for.
			inspection, inspectErr := instance.Inspect(ctx, adapter.InspectRequest{Target: *intent.Target})
			if inspectErr != nil {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_observation_failed"))
			}
			if inspection.Live {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_still_active"))
			}
		} else if intent.Target.ProviderGeneration == "" {
			// Every other operation addresses a live process, so an empty
			// generation cannot prove which process it would reach. This is
			// rejected before revalidation, because revalidation compares the
			// requested generation with the observed one and two empty strings
			// compare equal: without this guard an unverified session would pass
			// the comparison and reach the provider as if it were live.
			return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "generation_required"))
		} else if err := e.revalidateGeneration(ctx, instance, adapterID, *intent.Target); err != nil {
			return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_generation_mismatch"))
		}
	}
	if e.PolicyHook != nil {
		if policyErr := e.PolicyHook(ctx, intent); policyErr != nil {
			return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "policy_denied"))
		}
	}
	if e.BeforeInvocation != nil {
		e.BeforeInvocation()
	}
	if err := e.store.MarkInvocationStarted(ctx, intent.CommandID, e.now().UnixMilli()); err != nil {
		return protocol.ExecutionReceipt{}, err
	}
	if err := e.store.MarkEndpointAdmitted(ctx, intent.CommandID, e.now().UnixMilli()); err != nil {
		return protocol.ExecutionReceipt{}, err
	}
	admitted, err := e.store.GetJournal(ctx, intent.CommandID)
	if err != nil {
		return protocol.ExecutionReceipt{}, fmt.Errorf("confirm endpoint admission: %w", err)
	}
	if admitted.Phase != protocol.PhaseEndpointAdmitted {
		return protocol.ExecutionReceipt{}, fmt.Errorf("confirm endpoint admission: phase=%s", admitted.Phase)
	}
	if e.AdmissionHook != nil {
		if err := e.AdmissionHook(ctx, intent, requestHash); err != nil {
			return protocol.ExecutionReceipt{}, err
		}
	}
	deadlineBudget := intent.ExecuteBeforeAtMS - e.now().UnixMilli()
	if deadlineBudget <= 0 {
		return unknownReceipt(intent, requestHash, "expired_after_validation"), nil
	}
	callBudget := deadlineBudget
	if intent.Budget.CLITimeoutMS > 0 && intent.Budget.CLITimeoutMS < callBudget {
		callBudget = intent.Budget.CLITimeoutMS
	}
	callCtx, cancel := context.WithTimeout(ctx, time.Duration(callBudget)*time.Millisecond)
	defer cancel()
	result, executeErr := instance.Execute(callCtx, adapter.ExecuteRequest{Intent: intent})
	receipt := result.Receipt
	if receipt.CommandID == "" {
		receipt.CommandID = intent.CommandID
	}
	receipt.RequestHash = requestHash
	if receipt.CommandRevision == 0 {
		receipt.CommandRevision = 1
	}
	receipt.Phase = protocol.PhaseReceiptRecorded
	if executeErr != nil {
		// An adapter may return a decoded provider document together with the error,
		// for example a rejected or unconfirmed outcome reported on a non-zero exit.
		// Only fill in what the adapter did not determine, so that evidence is not
		// flattened into a generic failure.
		if receipt.Outcome == "" {
			receipt.Outcome = "failed"
		}
		if receipt.EffectCertainty == "" {
			receipt.EffectCertainty = protocol.EffectUnknown
		}
		receipt.ErrorMessage = executeErr.Error()
		if receipt.DeliveryBoundary == "" {
			receipt.DeliveryBoundary = protocol.DeliveryNotStarted
		}
	}
	if err := e.store.RecordReceipt(ctx, intent.CommandID, receipt, e.now().UnixMilli()); err != nil {
		return protocol.ExecutionReceipt{}, err
	}
	return receipt, executeErr
}

// ReadOutput reads a bounded snapshot through the mapped resource adapter.
func (e *Executor) ReadOutput(ctx context.Context, request protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	if request.ResourceID == "" || request.ProviderGeneration == "" {
		return protocol.OutputSnapshotResponse{ErrorCode: "invalid_target"}, fmt.Errorf("resource ID and generation are required")
	}
	mapping, err := e.store.LookupResourceID(ctx, request.ResourceID)
	if err != nil {
		return protocol.OutputSnapshotResponse{ErrorCode: "unknown_resource"}, err
	}
	instance, ok := e.registry.Get(mapping.AdapterID)
	if !ok {
		return protocol.OutputSnapshotResponse{ErrorCode: "unknown_adapter"}, fmt.Errorf("adapter %q is not configured", mapping.AdapterID)
	}
	// Revalidate the target generation from the Endpoint's own latest accepted
	// collection snapshot. A live inspection re-runs the provider's full discovery,
	// which costs seconds per read, so it is reserved for the cases the snapshot
	// cannot answer: unknown data, stale data, or a resource absent from it.
	if err := e.revalidateGeneration(ctx, instance, mapping.AdapterID, protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, ProviderGeneration: request.ProviderGeneration}); err != nil {
		return protocol.OutputSnapshotResponse{ErrorCode: "generation_mismatch"}, err
	}
	limit := request.MaxBytes
	if limit <= 0 {
		limit = 64 << 10
	}
	if limit > 1<<20 {
		limit = 1 << 20
	}
	lines := request.MaxLines
	if lines < 0 {
		lines = 0
	}
	if lines > 10000 {
		lines = 10000
	}
	result, err := instance.ReadOutput(ctx, adapter.OutputRequest{Target: protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, ProviderGeneration: request.ProviderGeneration}, MaxBytes: limit, MaxLines: lines})
	if errors.Is(err, adapter.ErrUnsupported) {
		return protocol.OutputSnapshotResponse{ErrorCode: "unsupported"}, nil
	}
	if err != nil {
		return protocol.OutputSnapshotResponse{ErrorCode: "provider_error"}, err
	}
	data := strings.Join(result.Lines, "\n")
	response := protocol.OutputSnapshotResponse{Data: data, Truncated: result.Truncated, ObservedAtMS: result.ObservedAtMS}
	// Truncate on a rune boundary rather than at a raw byte offset: a byte slice
	// would cut a multi-byte character in half and hand the caller bytes that no
	// longer decode. The follow path shares the same helper so the two output
	// routes cannot disagree about what a truncated payload looks like.
	if len(response.Data) > limit {
		response.Data = string(adapter.TruncateUTF8([]byte(response.Data), limit))
		response.Truncated = true
	}
	return response, nil
}

// FollowOutput streams output records through the mapped resource adapter.
//
// It resolves the target exactly like ReadOutput so a follow can never reach an
// adapter that does not own the resource, and it revalidates the generation from
// the same snapshot before the provider child is started. The adapter capability
// is asserted separately from Adapter because streaming is optional: an adapter
// that cannot stream reports ErrUnsupported, which the Endpoint turns into an
// honest "unsupported" end frame instead of a provider failure.
func (e *Executor) FollowOutput(ctx context.Context, request protocol.OutputFollowRequest, emit func(protocol.OutputChunk) error) error {
	if request.ResourceID == "" || request.ProviderGeneration == "" {
		return fmt.Errorf("resource ID and generation are required")
	}
	mapping, err := e.store.LookupResourceID(ctx, request.ResourceID)
	if err != nil {
		return err
	}
	instance, ok := e.registry.Get(mapping.AdapterID)
	if !ok {
		return fmt.Errorf("adapter %q is not configured", mapping.AdapterID)
	}
	if err := e.revalidateGeneration(ctx, instance, mapping.AdapterID, protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, ProviderGeneration: request.ProviderGeneration}); err != nil {
		return err
	}
	follower, ok := instance.(adapter.OutputFollower)
	if !ok {
		return adapter.ErrUnsupported
	}
	return follower.FollowOutput(ctx, request, emit)
}

// revalidateGeneration confirms the requested target generation without paying for a
// full provider discovery on every command. It trusts only a known, non-stale snapshot
// that actually contains the resource; anything else falls back to a live inspection so
// an unknown observation is never mistaken for a match.
func (e *Executor) revalidateGeneration(ctx context.Context, instance adapter.Adapter, adapterID string, target protocol.CommandTarget) error {
	snapshot, found, err := e.store.SourceSnapshot(ctx, adapterID)
	if err == nil && found && snapshot.DataKnown && !snapshot.Stale {
		for _, session := range snapshot.Sessions {
			if session.ClusterSessionID != target.ResourceID {
				continue
			}
			if session.ProviderGeneration != target.ProviderGeneration {
				return fmt.Errorf("resource generation does not match")
			}
			return nil
		}
	}
	inspection, inspectErr := instance.Inspect(ctx, adapter.InspectRequest{Target: target})
	if inspectErr != nil || !inspection.Found || inspection.ProviderGeneration != target.ProviderGeneration {
		return fmt.Errorf("resource generation does not match")
	}
	return nil
}

// adapterForIntent resolves the adapter instance that owns the intent target and
// returns its configured adapter ID so callers can read that adapter's own persisted
// collection snapshot without repeating the mapping lookup. A target that cannot be
// resolved to a configured adapter is reported as a coded resolution error so the
// caller can record a terminal rejection; a storage failure stays a plain error
// because it says nothing about the target's validity.
func (e *Executor) adapterForIntent(ctx context.Context, intent protocol.ImmutableIntent) (adapter.Adapter, string, error) {
	if intent.Target != nil {
		mapping, err := e.store.LookupResourceID(ctx, intent.Target.ResourceID)
		if err != nil {
			if errors.Is(err, endpointstorage.ErrResourceNotFound) {
				return nil, "", resolutionFailure("target_not_found", err)
			}
			return nil, "", fmt.Errorf("resource_id %q mapping lookup failed: %w", intent.Target.ResourceID, err)
		}
		instance, ok := e.registry.Get(mapping.AdapterID)
		if !ok {
			return nil, "", resolutionFailure("adapter_not_configured", fmt.Errorf("resource_id %q adapter %q is not configured", intent.Target.ResourceID, mapping.AdapterID))
		}
		return instance, mapping.AdapterID, nil
	}
	if intent.Operation != "agent.start" {
		return nil, "", resolutionFailure("target_required", fmt.Errorf("resource_id is required for operation %q", intent.Operation))
	}
	instance, ok := e.registry.Get(intent.LaunchProfileID)
	if !ok {
		return nil, "", resolutionFailure("adapter_not_configured", fmt.Errorf("launch profile adapter %q is not configured", intent.LaunchProfileID))
	}
	return instance, intent.LaunchProfileID, nil
}

func (e *Executor) lockFor(key string) *sync.Mutex {
	e.mu.Lock()
	defer e.mu.Unlock()
	if lock, ok := e.locks[key]; ok {
		return lock
	}
	lock := &sync.Mutex{}
	e.locks[key] = lock
	return lock
}

func targetKey(intent protocol.ImmutableIntent) string {
	if intent.Target == nil {
		return intent.LaunchProfileID
	}
	return intent.EndpointID + ":" + intent.Target.Kind + ":" + intent.Target.ResourceID
}

func supports(descriptor protocol.CapabilityDescriptor, operation, version string) bool {
	for _, capability := range descriptor.Capabilities {
		if capability.Name == operation && capability.Version == version {
			return true
		}
	}
	return false
}

// resolutionError reports why an intent could not be mapped to a configured
// adapter. It carries a bounded standard error code so the caller can record a
// terminal rejection instead of returning a bare error that leaves the command
// looking in-flight forever.
type resolutionError struct {
	code    string
	message string
}

func (e *resolutionError) Error() string { return e.message }

// resolutionFailure builds a coded resolution error from an underlying cause.
func resolutionFailure(code string, cause error) error {
	return &resolutionError{code: code, message: cause.Error()}
}

func unknownReceipt(intent protocol.ImmutableIntent, hash, code string) protocol.ExecutionReceipt {
	return protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: hash, Phase: protocol.PhaseReceiptRecorded, DeliveryBoundary: protocol.DeliveryNotStarted, EffectCertainty: protocol.EffectUnknown, Outcome: "unknown", ErrorCode: code}
}
func unsupportedReceipt(intent protocol.ImmutableIntent, hash string) protocol.ExecutionReceipt {
	receipt := unknownReceipt(intent, hash, "unsupported")
	receipt.EffectCertainty = protocol.EffectNotApplied
	receipt.Outcome = "rejected"
	return receipt
}
func (e *Executor) recordEarlyRejection(ctx context.Context, intent protocol.ImmutableIntent, receipt protocol.ExecutionReceipt) (protocol.ExecutionReceipt, error) {
	receipt.Phase = protocol.PhaseReceiptRecorded
	receipt.EffectCertainty = protocol.EffectNotApplied
	receipt.FinishedAtMS = e.now().UnixMilli()
	if err := e.store.RecordReceipt(ctx, intent.CommandID, receipt, receipt.FinishedAtMS); err != nil {
		return protocol.ExecutionReceipt{}, err
	}
	return receipt, nil
}

func rejectedReceipt(intent protocol.ImmutableIntent, hash, code string) protocol.ExecutionReceipt {
	receipt := unsupportedReceipt(intent, hash)
	receipt.ErrorCode = code
	return receipt
}
func decodeReceipt(value string) (protocol.ExecutionReceipt, error) {
	var receipt protocol.ExecutionReceipt
	if value == "" {
		return receipt, fmt.Errorf("receipt is empty")
	}
	if err := json.Unmarshal([]byte(value), &receipt); err != nil {
		return receipt, err
	}
	return receipt, nil
}
