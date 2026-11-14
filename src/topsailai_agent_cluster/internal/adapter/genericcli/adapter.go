// Package genericcli implements the provider-neutral Endpoint Adapter for an
// independently built Provider CLI executable.
package genericcli

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"
	"unicode/utf8"

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
	candidate.capability = intersectCapabilities(config.Capabilities, descriptor.Operations, descriptor.ControlActions)
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
	payload, err := a.executionPayload(ctx, intent)
	if err != nil {
		return adapter.ExecuteResult{}, err
	}
	operation := &providercli.NamedContract{Name: intent.Operation, Version: intent.OperationVersion}
	response, invokeErr := a.call(ctx, classMutation, providercli.FunctionExecute, target, operation, nil, intent.CommandID, payload)
	if response.Error != nil {
		result := adapter.ExecuteResult{Receipt: receiptFromProviderError(response.Error, invokeErr)}
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
		return adapter.OutputResult{}, outputError(response, err)
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

// LaunchProfile reads and maps this Adapter instance's provider-private launch profile.
func (a *Adapter) LaunchProfile(ctx context.Context) (protocol.LaunchHandler, error) {
	result, err := a.launchOptions(ctx, false)
	if err != nil {
		return protocol.LaunchHandler{}, err
	}
	mapping, err := a.config.Mapper.GetOrCreateResourceID(ctx, a.config.AdapterID, protocol.ResourceLaunchProfile, result.Profile.ProviderResourceKey, a.config.Now().UnixMilli())
	if err != nil {
		return protocol.LaunchHandler{}, err
	}
	return protocol.LaunchHandler{AdapterID: a.config.AdapterID, LaunchProfileID: mapping.ResourceID, DisplayName: result.Profile.DisplayName, Revision: result.Profile.Revision}, nil
}

// Projects returns provider-managed launch projects without exposing the launch profile key.
func (a *Adapter) Projects(ctx context.Context) ([]protocol.Project, error) {
	result, err := a.launchOptions(ctx, true)
	if err != nil {
		return nil, err
	}
	projects := make([]protocol.Project, 0, len(result.Projects))
	for _, project := range result.Projects {
		projects = append(projects, protocol.Project{Name: project.Name, Path: project.Path})
	}
	return projects, nil
}

// History maps provider-private session keys to opaque Cluster resource IDs.
func (a *Adapter) History(ctx context.Context, query protocol.HistoryQuery) (protocol.HistoryResult, error) {
	payload, _ := json.Marshal(providercli.HistoryMessagesPayload{Limit: query.Limit})
	value, err := a.typedQuery(ctx, providercli.QueryHistoryMessages, nil, payload)
	if err != nil {
		return protocol.HistoryResult{}, err
	}
	providerResult := value.(providercli.HistoryMessagesResult)
	result := protocol.HistoryResult{Rows: make([]protocol.HistoryRow, 0, len(providerResult.Rows)), ObservedAtMS: providerResult.ObservedAtMS, Truncated: providerResult.Truncated}
	for _, row := range providerResult.Rows {
		mapping, mapErr := a.config.Mapper.GetOrCreateResourceID(ctx, a.config.AdapterID, protocol.ResourceSession, row.ProviderResourceKey, providerResult.ObservedAtMS)
		if mapErr != nil {
			return protocol.HistoryResult{}, mapErr
		}
		result.Rows = append(result.Rows, protocol.HistoryRow{ProviderSessionID: row.ProviderSessionID, ResourceID: mapping.ResourceID, ProviderDisplayName: row.ProviderDisplayName, ProviderProjectWorkspace: row.ProviderProjectWorkspace, Task: row.Task, ProviderStatus: row.ProviderStatus, CreatedAtMS: row.CreatedAtMS, ModifiedAtMS: row.ModifiedAtMS, ProviderNo: row.ProviderNo, Resumable: row.Resumable, ResumeBlockedReason: row.ResumeBlockedReason})
	}
	return result, nil
}

// ModelCatalog maps provider-private profile keys to opaque Cluster profile IDs.
func (a *Adapter) ModelCatalog(ctx context.Context, query protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	target, err := a.providerTarget(ctx, query.Target, false)
	if err != nil {
		return protocol.ModelCatalog{}, err
	}
	value, err := a.typedQuery(ctx, providercli.QueryModelCatalog, target, json.RawMessage(`{}`))
	if err != nil {
		return protocol.ModelCatalog{}, err
	}
	providerResult := value.(providercli.ModelCatalogResult)
	result := protocol.ModelCatalog{Profiles: make([]protocol.ModelProfile, 0, len(providerResult.Profiles)), ObservedAtMS: providerResult.ObservedAtMS, Truncated: providerResult.Truncated}
	for _, profile := range providerResult.Profiles {
		mapping, mapErr := a.config.Mapper.GetOrCreateResourceID(ctx, a.config.AdapterID, protocol.ResourceModelProfile, profile.ProviderResourceKey, providerResult.ObservedAtMS)
		if mapErr != nil {
			return protocol.ModelCatalog{}, mapErr
		}
		result.Profiles = append(result.Profiles, protocol.ModelProfile{ModelProfileID: mapping.ResourceID, ProviderDisplayName: profile.ProviderDisplayName, CurrentState: profile.CurrentState, Available: profile.Available, UnavailableReason: profile.UnavailableReason})
		if profile.ProviderResourceKey == providerResult.CurrentProviderResourceKey {
			result.CurrentProfileID = mapping.ResourceID
		}
	}
	return result, nil
}

// Messages converts one typed provider conversation result without creating a new Cluster identity.
func (a *Adapter) Messages(ctx context.Context, query protocol.MessagesQuery) (protocol.MessagesResult, error) {
	target := &providercli.Target{ResourceKind: protocol.ResourceSession, ProviderResourceKey: query.ProviderSessionID}
	payload, _ := json.Marshal(providercli.SessionMessagesPayload{MaxChars: query.MaxChars, MaxTokens: query.MaxTokens})
	value, err := a.typedQuery(ctx, providercli.QuerySessionMessages, target, payload)
	if err != nil {
		// A provider that does not know the session is reported as a missing
		// session, not as a provider failure. The distinction is the whole point
		// of the read: "this session recorded nothing" and "this session does not
		// exist" send the operator to different places, and the Server maps the
		// two to different HTTP statuses.
		var coded interface{ ErrorCode() string }
		if errors.As(err, &coded) && coded.ErrorCode() == providerSessionNotFoundCode {
			return protocol.MessagesResult{ErrorCode: protocol.MessagesSessionNotFound, ProviderSessionID: query.ProviderSessionID}, err
		}
		return protocol.MessagesResult{}, err
	}
	providerResult := value.(providercli.SessionMessagesResult)
	result := protocol.MessagesResult{ProviderSessionID: providerResult.ProviderSessionID, Messages: make([]protocol.Message, 0, len(providerResult.Messages)), MessageCount: providerResult.MessageCount, ObservedAtMS: providerResult.ObservedAtMS, Truncated: providerResult.Truncated}
	for _, message := range providerResult.Messages {
		result.Messages = append(result.Messages, protocol.Message{Role: message.Role, Content: message.Content, CreatedAtMS: message.CreatedAtMS, WordCount: message.WordCount, TokenCount: message.TokenCount})
	}
	return result, nil
}

func (a *Adapter) launchOptions(ctx context.Context, includeProjects bool) (providercli.LaunchOptionsResult, error) {
	payload, _ := json.Marshal(providercli.LaunchOptionsPayload{IncludeProjects: includeProjects})
	value, err := a.typedQuery(ctx, providercli.QueryLaunchOptions, nil, payload)
	if err != nil {
		return providercli.LaunchOptionsResult{}, err
	}
	return value.(providercli.LaunchOptionsResult), nil
}

func (a *Adapter) typedQuery(ctx context.Context, name string, target *providercli.Target, payload json.RawMessage) (any, error) {
	query := providercli.NamedContract{Name: name, Version: "v1"}
	if !a.supportsQuery(query) {
		return nil, adapter.ErrUnsupported
	}
	if _, err := providercli.DecodeQueryPayload(query, target, payload); err != nil {
		return nil, fmt.Errorf("validate provider query request: %w", err)
	}
	response, err := a.call(ctx, classDiscovery, providercli.FunctionQuery, target, nil, &query, "", payload)
	if err != nil {
		return nil, err
	}
	if err := responseError(response); err != nil {
		return nil, err
	}
	value, err := providercli.DecodeQueryResult(query, response.QueryResult)
	if err != nil {
		return nil, fmt.Errorf("decode provider query result: %w", err)
	}
	return value, nil
}

func (a *Adapter) supportsQuery(query providercli.NamedContract) bool {
	for _, candidate := range a.descriptor.Queries {
		if candidate == query {
			return true
		}
	}
	return false
}

// QueryCommand reconciles one prior Provider invocation when supported.
func (a *Adapter) QueryCommand(ctx context.Context, query adapter.CommandQuery) (adapter.CommandResult, error) {
	response, err := a.call(ctx, classMutation, providercli.FunctionQueryCommand, nil, nil, nil, query.ProviderRequestRef, json.RawMessage(`{}`))
	if err != nil {
		return adapter.CommandResult{}, err
	}
	if response.Error != nil {
		return adapter.CommandResult{Receipt: receiptFromProviderError(response.Error, err)}, fmt.Errorf("provider command query failed: %s", response.Error.Message)
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

func (a *Adapter) executionPayload(ctx context.Context, intent protocol.ImmutableIntent) (json.RawMessage, error) {
	switch intent.Operation {
	case protocol.OperationAgentStart:
		return agentStartExecutionPayload(intent)
	case protocol.OperationAgentModelSelect:
		selection, err := protocol.ValidateModelSelectPayload(intent.Payload)
		if err != nil {
			return nil, err
		}
		mapping, err := a.config.Mapper.LookupResourceID(ctx, selection.ModelProfileID)
		if err != nil {
			return nil, fmt.Errorf("resolve model profile: %w", err)
		}
		if mapping.AdapterID != a.config.AdapterID {
			return nil, errors.New("model profile is not owned by this adapter")
		}
		if mapping.ResourceKind != protocol.ResourceModelProfile {
			return nil, errors.New("model profile mapping has the wrong resource kind")
		}
		return providercli.MarshalModelSelectPayload(providercli.ModelSelectPayload{ProviderResourceKey: mapping.ProviderResourceKey})
	default:
		return intent.Payload, nil
	}
}

func agentStartExecutionPayload(intent protocol.ImmutableIntent) (json.RawMessage, error) {
	if !utf8.Valid(intent.Payload) {
		return nil, errors.New("Cluster agent.start payload must be valid UTF-8")
	}
	var source struct {
		Task json.RawMessage `json:"task"`
	}
	decoder := json.NewDecoder(bytes.NewReader(intent.Payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&source); err != nil {
		return nil, fmt.Errorf("decode Cluster agent.start payload: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return nil, errors.New("Cluster agent.start payload contains an extra JSON document")
		}
		return nil, fmt.Errorf("decode Cluster agent.start payload trailer: %w", err)
	}
	var task string
	if len(source.Task) > 0 {
		if bytes.Equal(bytes.TrimSpace(source.Task), []byte("null")) {
			return nil, errors.New("Cluster agent.start task must not be null")
		}
		if err := json.Unmarshal(source.Task, &task); err != nil {
			return nil, fmt.Errorf("decode Cluster agent.start task: %w", err)
		}
		if task == "" {
			return nil, errors.New("Cluster agent.start task must not be empty")
		}
	}
	return providercli.MarshalAgentStartPayload(providercli.AgentStartPayload{Folder: intent.Folder, Task: task})
}

func (a *Adapter) executionTarget(ctx context.Context, intent protocol.ImmutableIntent) (*providercli.Target, error) {
	if intent.Target != nil {
		return a.providerTarget(ctx, *intent.Target, providercli.OperationNeedsLiveGeneration(intent.Operation))
	}
	if intent.Operation != protocol.OperationAgentStart || intent.LaunchProfileID == "" || intent.ProfileRevision == "" {
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

// intersectCapabilities keeps only the configured capabilities the provider
// actually offers.
//
// The provider advertises two separate contract lists, and both are offers: the
// fixed operation list and the control action family. Reading only the operation
// list made every ctl. capability unreachable, because a provider reports its
// control actions in their own field rather than as operations. The Endpoint then
// advertised no ctl. capability at all and refused every control command as
// unsupported before the policy hook could authorize it, so a configured catalog
// had no effect.
//
// The revision is carried through unchanged, which is what makes a published
// effective revision meaningful.
func intersectCapabilities(configured protocol.CapabilityDescriptor, offered []providercli.NamedContract, controlActions []providercli.NamedContract) protocol.CapabilityDescriptor {
	allowed := make(map[string]struct{}, len(offered)+len(controlActions))
	for _, item := range offered {
		allowed[item.Name+"\x00"+item.Version] = struct{}{}
	}
	for _, item := range controlActions {
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
		// The provider is the only side that can observe the exit, so its answer
		// is the sole source of this field. Leaving it unset made every
		// signal_sent operation non-terminal in the Cluster journal, because
		// storage keeps signal_sent && !exit_confirmed at "executing".
		ExitConfirmed: result.ExitConfirmed,
	}
}

// receiptFromProviderError builds the receipt for a rejected invocation.
//
// The provider's own error document is carried as ProviderResponse, because it
// is the only evidence of why the call failed and the operator surface renders
// that field as a separate section. Leaving it empty made the section disappear
// entirely: renderProviderResponse prints nothing for an empty document, so a
// failed invocation looked like a receipt with no provider answer at all.
//
// invokeErr is the transport-level failure, and its captured stderr is the
// fallback when the provider produced no structured document. A provider that
// dies before writing a document still has a diagnostic, and discarding it would
// leave the operator with a bare error code.
func receiptFromProviderError(providerError *providercli.ProviderError, invokeErr error) protocol.ExecutionReceipt {
	document := providerErrorDocument(providerError)
	if document == "" {
		document = adapter.ProviderFailureText(invokeErr)
	}
	bounded, truncated := adapter.BoundedProviderResponse(document)
	return protocol.ExecutionReceipt{
		DeliveryBoundary: protocol.DeliveryNotStarted,
		EffectCertainty:  protocol.EffectCertainty(providerError.EffectCertainty), Outcome: "rejected",
		ErrorCode: providerError.Code, ErrorMessage: providerError.Message,
		ProviderResponse: bounded, ProviderResponseTruncated: truncated,
	}
}

// providerErrorDocument renders one provider error document as JSON.
//
// The field order is fixed by the struct, so the rendered document is stable and
// a scenario can assert its content without depending on map iteration order. An
// empty document is returned when the provider supplied no code and no message,
// which is the case where the stderr fallback is the only evidence available.
func providerErrorDocument(providerError *providercli.ProviderError) string {
	if providerError == nil || (providerError.Code == "" && providerError.Message == "") {
		return ""
	}
	document, err := json.Marshal(providerError)
	if err != nil {
		return ""
	}
	return string(document)
}

// outputError classifies a provider output rejection.
//
// A provider that answers "unsupported" is reporting a capability gap, not a
// failure: the Endpoint maps adapter.ErrUnsupported onto the standard
// "unsupported" error code and every other error onto "provider_error". Returning
// the plain error made a provider capability gap indistinguishable from a broken
// provider, so the operator was told the read failed instead of being told the
// provider cannot do it.
func outputError(response providercli.Response, err error) error {
	if response.Error != nil && response.Error.Code == providerUnsupportedCode {
		return fmt.Errorf("%w: %s", adapter.ErrUnsupported, response.Error.Message)
	}
	return err
}

// providerUnsupportedCode is the provider's own code for an unsupported
// capability. It is a provider protocol value, not a Cluster error code.
const providerUnsupportedCode = "unsupported"

// providerSessionNotFoundCode is the provider's own code for a session it does
// not know. It is a provider protocol value, not a Cluster error code, so it is
// declared here beside the other provider codes rather than in the protocol.
const providerSessionNotFoundCode = "session_not_found"

// providerError preserves the provider's own error code.
//
// The code is kept as a field rather than flattened into the message because a
// caller has to act on it: a provider that cannot find a session and a provider
// that failed to read one are different outcomes for the operator, and a single
// formatted string makes them indistinguishable once the error leaves this
// package. The message keeps the original wording so existing logs still read the
// same.
type providerError struct {
	Code    string
	Message string
}

// Error renders the provider code and message in the historical format.
func (e *providerError) Error() string {
	return fmt.Sprintf("provider %s: %s", e.Code, e.Message)
}

// ErrorCode reports the provider's own code so a caller can classify the failure.
func (e *providerError) ErrorCode() string {
	return e.Code
}

func responseError(response providercli.Response) error {
	if response.Error == nil {
		return nil
	}
	return &providerError{Code: response.Error.Code, Message: response.Error.Message}
}

func randomID() (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", fmt.Errorf("generate provider request ID: %w", err)
	}
	return hex.EncodeToString(value[:]), nil
}
