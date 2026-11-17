package endpoint

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
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
	// Logger receives the policy refusal line. It is optional, because the
	// executor is constructed without one on every existing path; a nil logger
	// means the refusal is recorded in the journal only, which is the previous
	// behaviour rather than a crash.
	Logger *slog.Logger
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
	// A target named by its provider session handle has no durable mapping yet,
	// so it must be resolved before the lock is chosen: the lock key is the
	// resolved resource, and locking on an empty resource ID would let two
	// commands for the same session run concurrently. Resolution rewrites the
	// intent's target to the resolved opaque resource ID, so every later step
	// sees exactly the target a discovery would have produced and the liveness
	// gate below still runs.
	resolvedIntent, resolveErr := e.resolveProviderSessionHandle(ctx, intent)
	if resolveErr != nil {
		var coded *resolutionError
		if errors.As(resolveErr, &coded) {
			receipt := rejectedReceipt(intent, requestHash, coded.code)
			receipt.ErrorMessage = coded.message
			return e.recordEarlyRejection(ctx, intent, receipt)
		}
		return protocol.ExecutionReceipt{}, resolveErr
	}
	intent = resolvedIntent
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
	instance, adapterID, release, err := e.adapterForIntent(ctx, intent)
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
	// Hold the instance for the whole command. A Provider CLI version replacement
	// retires the previous instance instead of closing it, so this command finishes
	// on the version it validated against and the instance is closed only after
	// this release runs.
	defer release()
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
		profileRevision := descriptor.Capabilities.Revision
		if profileReader, ok := instance.(adapter.LaunchProfileHandler); ok {
			profile, profileErr := profileReader.LaunchProfile(ctx)
			if profileErr != nil {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "profile_unavailable"))
			}
			if profile.LaunchProfileID != intent.LaunchProfileID {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "profile_not_found"))
			}
			profileRevision = profile.Revision
		}
		if profileRevision != intent.ProfileRevision {
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
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, observationFailureCode(inspectErr)))
			}
			if inspection.Live {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_still_active"))
			}
		} else if intent.Operation == protocol.OperationAgentDriveStop {
			// Drive stop addresses the recorded controller, including a residual
			// record whose process is already gone, so it authorizes on the exact
			// provider record rather than on a live process generation. A session
			// process generation is not controller generation, so it is never
			// compared here: doing so would reject the residual-record case this
			// operation exists for.
			inspection, inspectErr := instance.Inspect(ctx, adapter.InspectRequest{Target: *intent.Target})
			if inspectErr != nil {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, observationFailureCode(inspectErr)))
			}
			if !inspection.Found {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_not_found"))
			}
		} else if intent.Operation == protocol.OperationWorkspaceClean && intent.Target.ProviderGeneration == "" {
			// Cleanup addresses provider-owned expired artifacts by the exact
			// session/PID mapping rather than a live process generation. Require
			// the provider to still report that exact row before dispatch.
			inspection, inspectErr := instance.Inspect(ctx, adapter.InspectRequest{Target: *intent.Target})
			if inspectErr != nil {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, observationFailureCode(inspectErr)))
			}
			if !inspection.Found {
				return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, "target_not_found"))
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
			return e.recordEarlyRejection(ctx, intent, rejectedReceipt(intent, requestHash, revalidationFailureCode(err, "target_generation_mismatch")))
		}
	}
	if e.PolicyHook != nil {
		if policyErr := e.PolicyHook(ctx, intent); policyErr != nil {
			// The refusal is logged where it is decided, not where the receipt is
			// stored. recordEarlyRejection also records unsupported, profile and
			// generation rejections, and reporting those as policy refusals would
			// send an operator to a policy file that is correct. The message
			// matches the read path's wording so one grep finds both, and the
			// token is never logged because a log reader must not become a
			// credential holder.
			e.logPolicyRefusal(intent, policyErr)
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
//
// A generation is not required. A generation proves liveness, which is what a
// mutation needs to know which process it would reach; a read needs identity,
// which record's output to return. Identity is already proven without it: the
// resource ID resolves through the durable mapping, and the provider proves the
// row by digest or refuses an ambiguous or absent match. Requiring a generation
// here made the output of an unverified session unreadable, which is exactly the
// session an operator most needs to inspect.
//
// The liveness comparison is skipped rather than merely tolerated when the
// generation is empty. revalidateGeneration compares with !=, so an empty
// requested generation would compare equal to an empty observed one and pass
// while proving nothing; skipping states the intent instead of relying on that
// coincidence.
func (e *Executor) ReadOutput(ctx context.Context, request protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	if request.ResourceID == "" {
		return protocol.OutputSnapshotResponse{ErrorCode: "invalid_target"}, fmt.Errorf("resource ID is required")
	}
	mapping, err := e.store.LookupResourceID(ctx, request.ResourceID)
	if err != nil {
		return protocol.OutputSnapshotResponse{ErrorCode: "unknown_resource"}, err
	}
	instance, release, ok := e.registry.Acquire(mapping.AdapterID)
	if !ok {
		return protocol.OutputSnapshotResponse{ErrorCode: "unknown_adapter"}, fmt.Errorf("adapter %q is not configured", mapping.AdapterID)
	}
	defer release()
	// Revalidate the target generation from the Endpoint's own latest accepted
	// collection snapshot. A live inspection re-runs the provider's full discovery,
	// which costs seconds per read, so it is reserved for the cases the snapshot
	// cannot answer: unknown data, stale data, or a resource absent from it.
	if request.ProviderGeneration != "" {
		if err := e.revalidateGeneration(ctx, instance, mapping.AdapterID, protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, ProviderGeneration: request.ProviderGeneration}); err != nil {
			return protocol.OutputSnapshotResponse{ErrorCode: revalidationFailureCode(err, "generation_mismatch")}, err
		}
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
	if request.ResourceID == "" {
		return fmt.Errorf("resource ID is required")
	}
	mapping, err := e.store.LookupResourceID(ctx, request.ResourceID)
	if err != nil {
		return err
	}
	instance, release, ok := e.registry.Acquire(mapping.AdapterID)
	if !ok {
		return fmt.Errorf("adapter %q is not configured", mapping.AdapterID)
	}
	// A follow is long-lived, so this reference is what pins the stream to the
	// version it started on. Releasing it after the stream ends lets a replacement
	// close the retired instance at that point instead of interrupting the stream.
	defer release()
	// A generation is optional for the same reason it is optional in ReadOutput:
	// it proves liveness, while a follow needs identity, which the mapping and the
	// provider's own row proof already establish. The comparison is skipped rather
	// than tolerated, because an empty generation would compare equal to an empty
	// observed one and pass while proving nothing.
	if request.ProviderGeneration != "" {
		if err := e.revalidateGeneration(ctx, instance, mapping.AdapterID, protocol.CommandTarget{Kind: "session", ResourceID: request.ResourceID, ProviderGeneration: request.ProviderGeneration}); err != nil {
			return err
		}
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
	if inspectErr != nil {
		// A capacity refusal means the adapter was never invoked, so it proves
		// nothing about the target. Flattening it into the mismatch message
		// reported a busy adapter as a stale generation and sent the operator to
		// inspect a session that was never the problem. The cause is preserved so
		// each caller can classify it, and errors.Is(err, adapter.ErrBusy) holds.
		if errors.Is(inspectErr, adapter.ErrBusy) {
			return fmt.Errorf("resource generation could not be revalidated: %w", inspectErr)
		}
		return fmt.Errorf("resource generation does not match")
	}
	if !inspection.Found || inspection.ProviderGeneration != target.ProviderGeneration {
		return fmt.Errorf("resource generation does not match")
	}
	return nil
}

// resolveProviderSessionHandle rewrites a handle-named target into the opaque
// resource ID the rest of the command path requires.
//
// The operator may name a session by the provider's own identifier before the
// Endpoint has ever discovered it, so no durable mapping exists and the ordinary
// resource-ID lookup would reject the command as target_not_found. That rejection
// is exactly what this path removes: the operator named the target, so the
// Endpoint must not decide whether the session exists. Minting the mapping is a
// local bookkeeping step and never asks the provider, so no existence judgement
// happens here. Whether the session really exists is decided by the provider when
// the operation reaches it, which is the only party that can answer.
//
// The mapping is minted by the single configured adapter that can address a
// provider session handle. Zero such adapters means no configured provider can
// accept a handle, and more than one means the handle cannot be attributed to a
// provider without guessing, so both are rejected instead of picking one. A target
// that carries both a resource ID and a handle is rejected rather than silently
// preferring one, because the two could name different sessions.
//
// A target without a handle is returned unchanged, so every existing command path
// keeps its current behaviour and pays no extra work.
func (e *Executor) resolveProviderSessionHandle(ctx context.Context, intent protocol.ImmutableIntent) (protocol.ImmutableIntent, error) {
	if intent.Target == nil || intent.Target.ProviderSessionHandle == "" {
		return intent, nil
	}
	if intent.Target.ResourceID != "" {
		return protocol.ImmutableIntent{}, resolutionFailure("target_ambiguous", fmt.Errorf("target carries both resource_id %q and provider_session_handle %q", intent.Target.ResourceID, intent.Target.ProviderSessionHandle))
	}
	handle := intent.Target.ProviderSessionHandle
	var owner adapter.HandleResolver
	owners := 0
	for _, instance := range e.registry.All() {
		resolver, ok := instance.(adapter.HandleResolver)
		if !ok {
			continue
		}
		owner = resolver
		owners++
	}
	switch owners {
	case 0:
		return protocol.ImmutableIntent{}, resolutionFailure("target_not_found", fmt.Errorf("no configured adapter accepts a provider session handle, so %q cannot be addressed", handle))
	case 1:
	default:
		return protocol.ImmutableIntent{}, resolutionFailure("target_ambiguous", fmt.Errorf("%d configured adapters accept a provider session handle, so %q cannot be attributed", owners, handle))
	}
	mapping, err := owner.ResolveProviderSessionHandle(ctx, handle)
	if err != nil {
		return protocol.ImmutableIntent{}, fmt.Errorf("resolve provider session handle %q: %w", handle, err)
	}
	// The resolved mapping is authoritative from here on: the handle is cleared so
	// a later step cannot resolve it a second time, and the resource ID is the same
	// opaque value a discovery would have minted for this session.
	target := *intent.Target
	target.ResourceID = mapping.ResourceID
	target.ProviderSessionHandle = ""
	intent.Target = &target
	return intent, nil
}

// adapterForIntent resolves the adapter instance that owns the intent target and
// returns its configured adapter ID so callers can read that adapter's own persisted
// collection snapshot without repeating the mapping lookup. A target that cannot be
// resolved to a configured adapter is reported as a coded resolution error so the
// caller can record a terminal rejection; a storage failure stays a plain error
// because it says nothing about the target's validity.
func (e *Executor) adapterForIntent(ctx context.Context, intent protocol.ImmutableIntent) (adapter.Adapter, string, func(), error) {
	if intent.Target != nil {
		mapping, err := e.store.LookupResourceID(ctx, intent.Target.ResourceID)
		if err != nil {
			if errors.Is(err, endpointstorage.ErrResourceNotFound) {
				return nil, "", nil, resolutionFailure("target_not_found", err)
			}
			return nil, "", nil, fmt.Errorf("resource_id %q mapping lookup failed: %w", intent.Target.ResourceID, err)
		}
		instance, release, ok := e.registry.Acquire(mapping.AdapterID)
		if !ok {
			return nil, "", nil, resolutionFailure("adapter_not_configured", fmt.Errorf("resource_id %q adapter %q is not configured", intent.Target.ResourceID, mapping.AdapterID))
		}
		return instance, mapping.AdapterID, release, nil
	}
	if intent.Operation != "agent.start" {
		return nil, "", nil, resolutionFailure("target_required", fmt.Errorf("resource_id is required for operation %q", intent.Operation))
	}
	mapping, err := e.store.LookupResourceID(ctx, intent.LaunchProfileID)
	if err == nil {
		if mapping.ResourceKind != protocol.ResourceLaunchProfile {
			return nil, "", nil, resolutionFailure("profile_not_found", fmt.Errorf("resource_id %q is not a launch profile", intent.LaunchProfileID))
		}
		instance, release, ok := e.registry.Acquire(mapping.AdapterID)
		if !ok {
			return nil, "", nil, resolutionFailure("adapter_not_configured", fmt.Errorf("launch profile %q adapter %q is not configured", intent.LaunchProfileID, mapping.AdapterID))
		}
		return instance, mapping.AdapterID, release, nil
	}
	if !errors.Is(err, endpointstorage.ErrResourceNotFound) {
		return nil, "", nil, fmt.Errorf("launch profile %q mapping lookup failed: %w", intent.LaunchProfileID, err)
	}
	instance, release, ok := e.registry.Acquire(intent.LaunchProfileID)
	if !ok {
		return nil, "", nil, resolutionFailure("adapter_not_configured", fmt.Errorf("launch profile %q is not configured", intent.LaunchProfileID))
	}
	return instance, intent.LaunchProfileID, release, nil
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

// logPolicyRefusal emits the audit line for a refused command.
//
// The read path logs its refusal where the decision is made, so the two paths
// must log in the same place and with the same message: an operator greps one
// phrase and finds every refused attempt on the machine. Logging inside
// recordEarlyRejection instead would report unsupported operations, missing
// profiles and generation mismatches as policy refusals, which is a different
// decision and would send the operator to a policy file that is correct.
//
// The token is deliberately absent. It is a secret, and a log that records it
// turns every log reader into a credential holder; the command ID is enough to
// correlate the refusal with the caller's own record and with the stored receipt.
func (e *Executor) logPolicyRefusal(intent protocol.ImmutableIntent, err error) {
	if e.Logger == nil {
		return
	}
	e.Logger.Warn("endpoint access policy refused operation", "operation", intent.Operation, "command_id", intent.CommandID, "error", err.Error())
}

func rejectedReceipt(intent protocol.ImmutableIntent, hash, code string) protocol.ExecutionReceipt {
	receipt := unsupportedReceipt(intent, hash)
	receipt.ErrorCode = code
	return receipt
}

// observationFailureCode names why a preflight observation did not happen.
//
// A busy adapter and a broken provider are different facts and must not share one
// code. Capacity is a transient collision with another invocation of the same
// Adapter instance, so the same intent may succeed unchanged once that invocation
// finishes; reporting it as target_observation_failed told the operator the target
// could not be observed, which sent them to inspect a session that was never the
// problem. The provider-failure code is kept for every other error, because only a
// capacity condition is provably unrelated to the target.
func observationFailureCode(err error) string {
	if code, busy := capacityCode(err); busy {
		return code
	}
	return "target_observation_failed"
}

// readFailureCode names why a read-only provider call did not happen.
//
// A busy adapter and a broken provider are different facts and must not share one
// code. Capacity is a transient collision with another invocation of the same
// Adapter instance, so the same read may succeed unchanged once that invocation
// finishes; reporting it as a provider failure told the operator to investigate a
// provider that was never invoked. The provider code is kept for every other
// error, because only a capacity condition is provably unrelated to the provider.
//
// A capacity condition outranks whatever the adapter reported, because the adapter
// never reached the provider and so has no provider evidence to report. Otherwise
// the adapter's own code is preserved and providerCode is only the fallback for an
// adapter that reported nothing, which keeps the original precedence intact.
//
// Every read path calls this one helper rather than repeating the check, because
// the defect this replaces existed precisely because one path was updated and its
// siblings were not.
func readFailureCode(err error, reported, providerCode string) string {
	if code, busy := capacityCode(err); busy {
		return code
	}
	if reported != "" {
		return reported
	}
	return providerCode
}

// revalidationFailureCode names why a target generation could not be confirmed.
//
// A capacity refusal means the adapter was never invoked, so it proves nothing
// about the target and must not be reported as a mismatch. Reporting it as one
// told the operator the generation had changed, which sent them to re-inspect a
// session that was never the problem, and the same intent may succeed unchanged
// once the competing invocation finishes. A genuine mismatch keeps the caller's
// own mismatch code, because that vocabulary differs per surface and is already
// part of each surface's contract.
func revalidationFailureCode(err error, mismatchCode string) string {
	if code, busy := capacityCode(err); busy {
		return code
	}
	return mismatchCode
}

// capacityCode reports the retryable capacity code when err is a capacity
// refusal, so every surface classifies that one fact identically.
//
// It exists as one primitive rather than a repeated check because the defect it
// replaces existed precisely because one path was updated and its siblings were
// not. A second spelling of "capacity" is a future divergence, not a local
// convenience.
func capacityCode(err error) (string, bool) {
	if errors.Is(err, adapter.ErrBusy) {
		return protocol.AdapterBusy, true
	}
	return "", false
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
