// Package genericcli implements the provider-neutral Endpoint Adapter for an
// independently built Provider CLI executable.
package genericcli

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// Config contains local-only Generic CLI Adapter configuration.
type Config struct {
	AdapterID      string
	DisplayName    string
	Executable     string
	Args           []string
	Environment    []string
	Timeout        time.Duration
	MaxStdinBytes  int64
	MaxStdoutBytes int64
	MaxStderrBytes int64
	MaxRecords     int64
	EndpointLimits providercli.ConcurrencyLimits
	AdapterLimits  providercli.ConcurrencyLimits
	Capabilities   protocol.CapabilityDescriptor
	Mapper         adapter.ResourceMapper
	Now            func() time.Time
}

type cliRunner interface {
	invoke(context.Context, providercli.Request) (providercli.Response, error)
	invokeStream(context.Context, providercli.Request, func(providercli.StreamFrame) error) error
}

// Adapter invokes one configured Provider CLI and owns its independent scheduler.
type Adapter struct {
	config     Config
	runner     cliRunner
	scheduler  *scheduler
	descriptor providercli.Descriptor
	version    providercli.Version
	capability protocol.CapabilityDescriptor
}

// New validates the Provider descriptor and constructs one Generic CLI Adapter.
func New(ctx context.Context, config Config) (*Adapter, error) {
	if config.AdapterID == "" || config.DisplayName == "" || config.Mapper == nil {
		return nil, errors.New("adapter ID, display name and resource mapper are required")
	}
	if config.Now == nil {
		config.Now = time.Now
	}
	runner, err := newProcessRunner(runnerConfig{
		executable: config.Executable, args: config.Args, environment: config.Environment,
		timeout: config.Timeout, maxStdinBytes: config.MaxStdinBytes,
		maxStdoutBytes: config.MaxStdoutBytes, maxStderrBytes: config.MaxStderrBytes,
		maxRecords: config.MaxRecords,
	})
	if err != nil {
		return nil, err
	}
	return newWithRunner(ctx, config, runner)
}

func newWithRunner(ctx context.Context, config Config, runner cliRunner) (*Adapter, error) {
	if config.AdapterID == "" || config.DisplayName == "" || config.Mapper == nil || runner == nil {
		return nil, errors.New("adapter ID, display name, resource mapper and runner are required")
	}
	if config.Now == nil {
		config.Now = time.Now
	}
	bootstrap, err := newScheduler(config.AdapterLimits)
	if err != nil {
		return nil, fmt.Errorf("bootstrap scheduler: %w", err)
	}
	candidate := &Adapter{config: config, runner: runner, scheduler: bootstrap, version: providercli.Version{Protocol: providercli.ProtocolName, Major: providercli.ProtocolMajor, Minor: providercli.ProtocolMinor}}
	descriptor, err := candidate.describeProvider(ctx)
	if err != nil {
		return nil, err
	}
	version, err := providercli.NegotiateVersion(descriptor.ProtocolRange)
	if err != nil {
		return nil, err
	}
	limits, err := effectiveConcurrency(config.EndpointLimits, config.AdapterLimits, descriptor.Concurrency)
	if err != nil {
		return nil, err
	}
	bounded, err := newScheduler(limits)
	if err != nil {
		return nil, err
	}
	candidate.descriptor = descriptor
	candidate.version = version
	candidate.scheduler = bounded
	candidate.capability = intersectCapabilities(config.Capabilities, descriptor.Operations)
	return candidate, nil
}

// Describe returns the effective Cluster capability surface.
func (a *Adapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{
		AdapterID: a.config.AdapterID, ProviderType: a.descriptor.ProviderType,
		DisplayName: a.config.DisplayName, Version: a.descriptor.ProviderVersion,
		Capabilities: a.capability,
	}, nil
}

// Discover maps provider observations into opaque Cluster Session resources.
func (a *Adapter) Discover(ctx context.Context, request adapter.DiscoverRequest) (adapter.DiscoverResult, error) {
	ctx, cancel := boundedContext(ctx, request.TimeoutMS, 0)
	defer cancel()
	response, err := a.call(ctx, classDiscovery, providercli.FunctionDiscover, nil, nil, nil, "", json.RawMessage(`{}`))
	if err != nil {
		return adapter.DiscoverResult{}, err
	}
	if err := responseError(response); err != nil {
		return adapter.DiscoverResult{}, err
	}
	if response.Discovery == nil {
		return adapter.DiscoverResult{}, errors.New("provider discovery response is missing")
	}
	result := adapter.DiscoverResult{Complete: response.Discovery.Complete, CollectionStatus: protocol.CollectionSucceeded, DataKnown: true, LastAttemptAtMS: a.config.Now().UnixMilli()}
	for _, observation := range response.Discovery.Observations {
		if observation.ResourceKind != protocol.ResourceSession {
			continue
		}
		session, mapErr := a.mapSession(ctx, observation)
		if mapErr != nil {
			return adapter.DiscoverResult{}, mapErr
		}
		result.Sessions = append(result.Sessions, session)
	}
	result.LastSuccessAtMS = result.LastAttemptAtMS
	return result, nil
}

// Inspect revalidates one exact provider-private target.
func (a *Adapter) Inspect(ctx context.Context, request adapter.InspectRequest) (adapter.InspectResult, error) {
	target, err := a.providerTarget(ctx, request.Target, false)
	if err != nil {
		return adapter.InspectResult{}, err
	}
	response, err := a.call(ctx, classDiscovery, providercli.FunctionInspect, target, nil, nil, "", json.RawMessage(`{}`))
	if err != nil {
		return adapter.InspectResult{}, err
	}
	if err := responseError(response); err != nil {
		return adapter.InspectResult{}, err
	}
	if response.Inspection == nil {
		return adapter.InspectResult{}, errors.New("provider inspection response is missing")
	}
	result := adapter.InspectResult{Found: response.Inspection.Found, Live: response.Inspection.Live}
	if response.Inspection.Observation != nil {
		result.ProviderGeneration = response.Inspection.Observation.ProviderGeneration
		result.State = response.Inspection.Observation.State
	}
	return result, nil
}

// Execute forwards one validated standard operation and returns Provider evidence only.
func (a *Adapter) Execute(ctx context.Context, request adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	ctx, cancel := boundedContext(ctx, request.Intent.Budget.CLITimeoutMS, request.Intent.ExecuteBeforeAtMS)
	defer cancel()
	intent := request.Intent
	target, err := a.executionTarget(ctx, intent)
	if err != nil {
		return adapter.ExecuteResult{}, err
	}
	operation := &providercli.NamedContract{Name: intent.Operation, Version: intent.OperationVersion}
	response, invokeErr := a.call(ctx, classMutation, providercli.FunctionExecute, target, operation, nil, intent.CommandID, intent.Payload)
	if response.Error != nil {
		result := adapter.ExecuteResult{Receipt: receiptFromProviderError(response.Error)}
		if invokeErr != nil {
			return result, invokeErr
		}
		return result, fmt.Errorf("provider rejected operation: %s", response.Error.Message)
	}
	if invokeErr != nil {
		return adapter.ExecuteResult{}, invokeErr
	}
	if response.Result == nil {
		return adapter.ExecuteResult{}, errors.New("provider operation result is missing")
	}
	return adapter.ExecuteResult{Receipt: receiptFromOperation(*response.Result)}, nil
}

// ReadOutput reads one bounded Provider output snapshot.
func (a *Adapter) ReadOutput(ctx context.Context, request adapter.OutputRequest) (adapter.OutputResult, error) {
	target, err := a.providerTarget(ctx, request.Target, true)
	if err != nil {
		return adapter.OutputResult{}, err
	}
	payload, _ := json.Marshal(struct {
		MaxBytes int `json:"max_bytes"`
		MaxLines int `json:"max_lines"`
	}{request.MaxBytes, request.MaxLines})
	response, err := a.call(ctx, classDiscovery, providercli.FunctionReadOutput, target, nil, nil, "", payload)
	if err != nil {
		return adapter.OutputResult{}, err
	}
	if err := responseError(response); err != nil {
		return adapter.OutputResult{}, err
	}
	if response.Output == nil {
		return adapter.OutputResult{}, errors.New("provider output response is missing")
	}
	return adapter.OutputResult{Lines: splitOutput(response.Output.Content), Truncated: response.Output.Truncated, ObservedAtMS: response.Output.ObservedAtMS}, nil
}

// FollowOutput streams bounded Provider output records.
func (a *Adapter) FollowOutput(ctx context.Context, request protocol.OutputFollowRequest, emit func(protocol.OutputChunk) error) error {
	if !a.supportsFunction(providercli.FunctionFollowOutput) {
		return adapter.ErrUnsupported
	}
	mapping, err := a.config.Mapper.LookupResourceID(ctx, request.ResourceID)
	if err != nil {
		return err
	}
	if mapping.AdapterID != a.config.AdapterID || mapping.ResourceKind != protocol.ResourceSession {
		return errors.New("output resource is not owned by this adapter")
	}
	target := &providercli.Target{ResourceKind: mapping.ResourceKind, ProviderResourceKey: mapping.ProviderResourceKey, ExpectedGeneration: request.ProviderGeneration}
	payload, _ := json.Marshal(struct {
		MaxBytes int `json:"max_bytes"`
		MaxLines int `json:"max_lines"`
	}{request.MaxBytes, request.MaxLines})
	release, err := a.scheduler.acquire(classFollow)
	if err != nil {
		return err
	}
	defer release()
	providerRequest, err := a.request(ctx, providercli.FunctionFollowOutput, target, nil, nil, "", payload)
	if err != nil {
		return err
	}
	return a.runner.invokeStream(ctx, providerRequest, func(frame providercli.StreamFrame) error {
		if frame.Type != providercli.FrameRecord {
			if frame.Type == providercli.FrameEnd && frame.Error != nil {
				return fmt.Errorf("provider stream ended: %s", frame.Error.Message)
			}
			return nil
		}
		var record struct {
			Lines []string `json:"lines"`
		}
		if err := decodeStrictJSON(frame.Record, &record); err != nil {
			return fmt.Errorf("decode output record: %w", err)
		}
		return emit(protocol.OutputChunk{Lines: record.Lines, ObservedAtMS: frame.ObservedAtMS, Truncated: frame.Truncated})
	})
}

// QueryCommand reconciles one prior Provider invocation when supported.
func (a *Adapter) QueryCommand(ctx context.Context, query adapter.CommandQuery) (adapter.CommandResult, error) {
	response, err := a.call(ctx, classMutation, providercli.FunctionQueryCommand, nil, nil, nil, query.ProviderRequestRef, json.RawMessage(`{}`))
	if err != nil {
		return adapter.CommandResult{}, err
	}
	if response.Error != nil {
		return adapter.CommandResult{Receipt: receiptFromProviderError(response.Error)}, fmt.Errorf("provider command query failed: %s", response.Error.Message)
	}
	if response.Result == nil {
		return adapter.CommandResult{}, errors.New("provider command result is missing")
	}
	return adapter.CommandResult{Receipt: receiptFromOperation(*response.Result)}, nil
}

// Watch is not exposed until a typed Cluster event contract exists.
func (a *Adapter) Watch(context.Context) (<-chan adapter.Event, error) {
	return nil, adapter.ErrUnsupported
}

// Close releases no long-lived process; each invocation owns and reaps its child.
func (a *Adapter) Close() error { return nil }

func (a *Adapter) describeProvider(ctx context.Context) (providercli.Descriptor, error) {
	response, err := a.call(ctx, classDiscovery, providercli.FunctionDescribe, nil, nil, nil, "", json.RawMessage(`{}`))
	if err != nil {
		return providercli.Descriptor{}, err
	}
	if err := responseError(response); err != nil {
		return providercli.Descriptor{}, err
	}
	if response.Descriptor == nil {
		return providercli.Descriptor{}, errors.New("provider descriptor is missing")
	}
	return *response.Descriptor, nil
}

func (a *Adapter) call(ctx context.Context, class invocationClass, function string, target *providercli.Target, operation, query *providercli.NamedContract, invocationID string, payload json.RawMessage) (providercli.Response, error) {
	if function != providercli.FunctionDescribe && !a.supportsFunction(function) {
		return providercli.Response{}, adapter.ErrUnsupported
	}
	release, err := a.scheduler.acquire(class)
	if err != nil {
		return providercli.Response{}, err
	}
	defer release()
	request, err := a.request(ctx, function, target, operation, query, invocationID, payload)
	if err != nil {
		return providercli.Response{}, err
	}
	return a.runner.invoke(ctx, request)
}

func (a *Adapter) supportsFunction(function string) bool {
	for _, candidate := range a.descriptor.Functions {
		if candidate == function {
			return true
		}
	}
	return false
}

func (a *Adapter) request(ctx context.Context, function string, target *providercli.Target, operation, query *providercli.NamedContract, invocationID string, payload json.RawMessage) (providercli.Request, error) {
	requestID, err := randomID()
	if err != nil {
		return providercli.Request{}, err
	}
	deadline := a.config.Now().Add(a.config.Timeout)
	if contextDeadline, ok := ctx.Deadline(); ok && contextDeadline.Before(deadline) {
		deadline = contextDeadline
	}
	return providercli.Request{
		Version: a.version, RequestID: requestID, Function: function, AdapterID: a.config.AdapterID,
		InvocationID: invocationID, DeadlineAtMS: deadline.UnixMilli(),
		Budget: providercli.Budget{MaxStdoutBytes: a.config.MaxStdoutBytes, MaxStderrBytes: a.config.MaxStderrBytes, MaxRecords: a.config.MaxRecords},
		Target: target, Operation: operation, Query: query, Payload: payload,
	}, nil
}

func (a *Adapter) executionTarget(ctx context.Context, intent protocol.ImmutableIntent) (*providercli.Target, error) {
	if intent.Target != nil {
		return a.providerTarget(ctx, *intent.Target, true)
	}
	if intent.Operation != "agent.start" || intent.LaunchProfileID == "" || intent.ProfileRevision == "" {
		return nil, errors.New("operation requires a target or launch profile")
	}
	mapping, err := a.config.Mapper.LookupResourceID(ctx, intent.LaunchProfileID)
	if err != nil {
		return nil, err
	}
	if mapping.AdapterID != a.config.AdapterID || mapping.ResourceKind != protocol.ResourceLaunchProfile {
		return nil, errors.New("launch profile is not owned by this adapter")
	}
	return &providercli.Target{ResourceKind: mapping.ResourceKind, ProviderResourceKey: mapping.ProviderResourceKey, ExpectedGeneration: intent.ProfileRevision}, nil
}

func (a *Adapter) providerTarget(ctx context.Context, target protocol.CommandTarget, requireGeneration bool) (*providercli.Target, error) {
	mapping, err := a.config.Mapper.LookupResourceID(ctx, target.ResourceID)
	if err != nil {
		return nil, err
	}
	if mapping.AdapterID != a.config.AdapterID || mapping.ResourceKind != target.Kind {
		return nil, errors.New("target resource is not owned by this adapter")
	}
	if requireGeneration && target.ProviderGeneration == "" {
		return nil, errors.New("target generation is required")
	}
	return &providercli.Target{ResourceKind: mapping.ResourceKind, ProviderResourceKey: mapping.ProviderResourceKey, ExpectedGeneration: target.ProviderGeneration}, nil
}

func (a *Adapter) mapSession(ctx context.Context, observation providercli.ProviderObservation) (protocol.Session, error) {
	mapping, err := a.config.Mapper.GetOrCreateResourceID(ctx, a.config.AdapterID, protocol.ResourceSession, observation.ProviderResourceKey, observation.ObservedAtMS)
	if err != nil {
		return protocol.Session{}, err
	}
	var attributes sessionAttributes
	if len(observation.Attributes) > 0 {
		if err := decodeStrictJSON(observation.Attributes, &attributes); err != nil {
			return protocol.Session{}, fmt.Errorf("decode session attributes: %w", err)
		}
	}
	return protocol.Session{
		ClusterSessionID: mapping.ResourceID, ProviderSessionID: attributes.ProviderSessionID,
		ProviderPID: attributes.ProviderPID, ProviderDisplayName: attributes.ProviderDisplayName,
		ProviderSessionQualifier: attributes.ProviderSessionQualifier,
		ProviderProjectWorkspace: attributes.ProviderProjectWorkspace,
		ProviderAgentID:          attributes.ProviderAgentID, ProviderGeneration: observation.ProviderGeneration,
		AdapterID: a.config.AdapterID, State: observation.State, StateReason: observation.StateReason,
		ObservedAtMS: observation.ObservedAtMS, Drive: attributes.Drive,
	}, nil
}

type sessionAttributes struct {
	ProviderSessionID        string                 `json:"provider_session_id,omitempty"`
	ProviderPID              int64                  `json:"provider_pid,omitempty"`
	ProviderDisplayName      string                 `json:"provider_display_name,omitempty"`
	ProviderSessionQualifier string                 `json:"provider_session_qualifier,omitempty"`
	ProviderProjectWorkspace string                 `json:"provider_project_workspace,omitempty"`
	ProviderAgentID          string                 `json:"provider_agent_id,omitempty"`
	Drive                    *protocol.DriveSummary `json:"drive,omitempty"`
}

func intersectCapabilities(configured protocol.CapabilityDescriptor, offered []providercli.NamedContract) protocol.CapabilityDescriptor {
	allowed := make(map[string]struct{}, len(offered))
	for _, item := range offered {
		allowed[item.Name+"\x00"+item.Version] = struct{}{}
	}
	result := protocol.CapabilityDescriptor{Revision: configured.Revision}
	for _, capability := range configured.Capabilities {
		if _, ok := allowed[capability.Name+"\x00"+capability.Version]; ok {
			result.Capabilities = append(result.Capabilities, capability)
		}
	}
	return result
}

func receiptFromOperation(result providercli.OperationResult) protocol.ExecutionReceipt {
	return protocol.ExecutionReceipt{
		DeliveryBoundary: protocol.DeliveryBoundary(result.DeliveryBoundary),
		EffectCertainty:  protocol.EffectCertainty(result.EffectCertainty), Outcome: result.ProviderOutcome,
		StartedAtMS: result.StartedAtMS, FinishedAtMS: result.FinishedAtMS,
		ProviderRequestRef: result.ProviderRequestRef, ProviderResponse: result.ProviderResponse,
		ProviderResponseTruncated: result.ProviderResponseTruncated,
	}
}

func receiptFromProviderError(providerError *providercli.ProviderError) protocol.ExecutionReceipt {
	return protocol.ExecutionReceipt{
		DeliveryBoundary: protocol.DeliveryNotStarted,
		EffectCertainty:  protocol.EffectCertainty(providerError.EffectCertainty), Outcome: "rejected",
		ErrorCode: providerError.Code, ErrorMessage: providerError.Message,
	}
}

func responseError(response providercli.Response) error {
	if response.Error == nil {
		return nil
	}
	return fmt.Errorf("provider %s: %s", response.Error.Code, response.Error.Message)
}

func randomID() (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", fmt.Errorf("generate provider request ID: %w", err)
	}
	return hex.EncodeToString(value[:]), nil
}
