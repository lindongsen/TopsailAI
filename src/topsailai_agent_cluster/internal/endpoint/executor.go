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
	instance, err := e.adapterForIntent(ctx, intent)
	if err != nil {
		return protocol.ExecutionReceipt{}, err
	}
	descriptor, err := instance.Describe(ctx)
	if err != nil {
		return protocol.ExecutionReceipt{}, err
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
		inspection, inspectErr := instance.Inspect(ctx, adapter.InspectRequest{Target: *intent.Target})
		if intent.Operation == protocol.OperationAgentResume {
			if inspectErr != nil {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_observation_failed"))
			}
			if inspection.Found {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_still_active"))
			}
		} else if inspectErr != nil || !inspection.Found || inspection.Generation != intent.Target.Generation {
			return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_generation_mismatch"))
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
		receipt.Outcome = "failed"
		receipt.EffectCertainty = protocol.EffectUnknown
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
	if request.ResourceID == "" || request.Generation == "" {
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
	if err := e.revalidateGeneration(ctx, instance, mapping.AdapterID, request); err != nil {
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
	result, err := instance.ReadOutput(ctx, adapter.OutputRequest{Target: protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, Generation: request.Generation}, MaxBytes: limit, MaxLines: lines})
	if errors.Is(err, adapter.ErrUnsupported) {
		return protocol.OutputSnapshotResponse{ErrorCode: "unsupported"}, nil
	}
	if err != nil {
		return protocol.OutputSnapshotResponse{ErrorCode: "provider_error"}, err
	}
	data := strings.Join(result.Lines, "\n")
	response := protocol.OutputSnapshotResponse{Data: data, Truncated: result.Truncated, ObservedAtMS: result.ObservedAtMS}
	if len(response.Data) > limit {
		response.Data = response.Data[:limit]
		response.Truncated = true
	}
	return response, nil
}

// revalidateGeneration confirms the requested generation without paying for a full
// provider discovery on every read. It trusts only a known, non-stale snapshot that
// actually contains the resource; anything else falls back to a live inspection so
// an unknown observation is never mistaken for a match.
func (e *Executor) revalidateGeneration(ctx context.Context, instance adapter.Adapter, adapterID string, request protocol.OutputSnapshotRequest) error {
	snapshot, found, err := e.store.SourceSnapshot(ctx, adapterID)
	if err == nil && found && snapshot.DataKnown && !snapshot.Stale {
		for _, session := range snapshot.Sessions {
			if session.SessionID != request.ResourceID {
				continue
			}
			if session.Generation != request.Generation {
				return fmt.Errorf("resource generation does not match")
			}
			return nil
		}
	}
	inspection, inspectErr := instance.Inspect(ctx, adapter.InspectRequest{Target: protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, Generation: request.Generation}})
	if inspectErr != nil || !inspection.Found || inspection.Generation != request.Generation {
		return fmt.Errorf("resource generation does not match")
	}
	return nil
}

func (e *Executor) adapterForIntent(ctx context.Context, intent protocol.ImmutableIntent) (adapter.Adapter, error) {
	if intent.Target != nil {
		mapping, err := e.store.LookupResourceID(ctx, intent.Target.ResourceID)
		if err != nil {
			return nil, fmt.Errorf("resource_id %q mapping lookup failed: %w", intent.Target.ResourceID, err)
		}
		instance, ok := e.registry.Get(mapping.AdapterID)
		if !ok {
			return nil, fmt.Errorf("resource_id %q adapter %q is not configured", intent.Target.ResourceID, mapping.AdapterID)
		}
		return instance, nil
	}
	if intent.Operation != "agent.start" {
		return nil, fmt.Errorf("resource_id is required for operation %q", intent.Operation)
	}
	instance, ok := e.registry.Get(intent.LaunchProfileID)
	if !ok {
		return nil, fmt.Errorf("launch profile adapter %q is not configured", intent.LaunchProfileID)
	}
	return instance, nil
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
