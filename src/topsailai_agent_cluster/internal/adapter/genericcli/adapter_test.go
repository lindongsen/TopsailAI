package genericcli

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

type fakeRunner struct {
	requests []providercli.Request
	invoke   func(providercli.Request) (providercli.Response, error)
	stream   []providercli.StreamFrame
}

func (f *fakeRunner) invokeRequest(request providercli.Request) (providercli.Response, error) {
	f.requests = append(f.requests, request)
	return f.invoke(request)
}

func (f *fakeRunner) invokeStream(_ context.Context, request providercli.Request, accept func(providercli.StreamFrame) error) error {
	f.requests = append(f.requests, request)
	for _, frame := range f.stream {
		if err := accept(frame); err != nil {
			return err
		}
	}
	return nil
}

type runnerAdapter struct{ *fakeRunner }

func (r runnerAdapter) invoke(ctx context.Context, request providercli.Request) (providercli.Response, error) {
	return r.invokeRequest(request)
}

type fakeMapper struct {
	mappings map[string]adapter.ResourceMapping
	failKey  string
}

func (m *fakeMapper) GetOrCreateResourceID(_ context.Context, adapterID, kind, key string, _ int64) (adapter.ResourceMapping, error) {
	if key == m.failKey {
		return adapter.ResourceMapping{}, errors.New("mapper failed")
	}
	id := kind + "-" + key
	mapping := adapter.ResourceMapping{AdapterID: adapterID, ResourceKind: kind, ProviderResourceKey: key, ResourceID: id}
	m.mappings[id] = mapping
	return mapping, nil
}
func (m *fakeMapper) LookupResourceID(_ context.Context, id string) (adapter.ResourceMapping, error) {
	mapping, ok := m.mappings[id]
	if !ok {
		return adapter.ResourceMapping{}, errors.New("mapping not found")
	}
	return mapping, nil
}

func TestAdapterMapsDiscoveryAndRejectsUnknownAttributes(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			return describeResponse(request), nil
		}
		return response(request, &providercli.DiscoveryResult{Complete: true, Observations: []providercli.ProviderObservation{{ProviderResourceKey: "native", ProviderGeneration: "g1", ResourceKind: protocol.ResourceSession, State: "running", ObservedAtMS: 10, Attributes: json.RawMessage(`{"provider_session_id":"s1"}`)}}}), nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.Discover(context.Background(), adapter.DiscoverRequest{TimeoutMS: 1000})
	if err != nil || len(result.Sessions) != 1 || result.Sessions[0].ClusterSessionID != "session-native" {
		t.Fatalf("discover = %+v, %v", result, err)
	}
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		return response(request, &providercli.DiscoveryResult{Complete: true, Observations: []providercli.ProviderObservation{{ProviderResourceKey: "native", ResourceKind: protocol.ResourceSession, State: "running", ObservedAtMS: 10, Attributes: json.RawMessage(`{"cluster_session_id":"forged"}`)}}}), nil
	}
	if _, err := binding.Discover(context.Background(), adapter.DiscoverRequest{}); err == nil {
		t.Fatal("unknown authoritative attribute was accepted")
	}
}

func TestAdapterUsesLaunchProfileAndPreservesProviderFailure(t *testing.T) {
	provider := newFakeProvider(t)
	binding := mustAdapter(t, provider)
	binding.config.Mapper.(*fakeMapper).mappings["profile-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceLaunchProfile, ProviderResourceKey: "native-profile", ResourceID: "profile-id"}
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		failure := &providercli.ProviderError{Code: "denied", Message: "no", EffectCertainty: providercli.EffectNotApplied}
		return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: false, Error: failure}, &invocationError{response: providercli.Response{}, cause: errors.New("exit 2")}
	}
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c", Operation: "agent.start", OperationVersion: "v1", LaunchProfileID: "profile-id", ProfileRevision: "r1", Payload: json.RawMessage(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli()}})
	if err == nil || result.Receipt.ErrorCode != "denied" {
		t.Fatalf("execute = %+v, %v", result, err)
	}
	request := provider.requests[len(provider.requests)-1]
	if request.Target.ProviderResourceKey != "native-profile" || request.Target.ExpectedGeneration != "r1" {
		t.Fatalf("target = %+v", request.Target)
	}
}

func TestFollowRejectsUndeclaredFunctionWithoutInvocation(t *testing.T) {
	provider := newFakeProvider(t)
	binding := mustAdapter(t, provider)
	binding.config.Mapper.(*fakeMapper).mappings["session-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "native", ResourceID: "session-id"}
	requestCount := len(provider.requests)

	err := binding.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "session-id", ProviderGeneration: "g", MaxBytes: 10}, func(protocol.OutputChunk) error { return nil })
	if !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("follow error = %v, want %v", err, adapter.ErrUnsupported)
	}
	if len(provider.requests) != requestCount {
		t.Fatalf("provider requests = %d, want %d", len(provider.requests), requestCount)
	}
}

func TestFollowReturnsConsumerStopUnchanged(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		return describeResponseWithFunctions(request, providercli.FunctionFollowOutput), nil
	}
	binding := mustAdapter(t, provider)
	binding.config.Mapper.(*fakeMapper).mappings["session-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "native", ResourceID: "session-id"}
	provider.stream = []providercli.StreamFrame{{Version: binding.version, RequestID: "ignored", Type: providercli.FrameRecord, Sequence: 2, ObservedAtMS: 1, Record: json.RawMessage(`{"lines":["x"]}`)}}
	err := binding.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "session-id", ProviderGeneration: "g", MaxBytes: 10}, func(protocol.OutputChunk) error { return adapter.ErrFollowStopped })
	if !errors.Is(err, adapter.ErrFollowStopped) {
		t.Fatalf("follow error = %v", err)
	}
}

func newFakeProvider(t *testing.T) *fakeRunner {
	t.Helper()
	provider := &fakeRunner{}
	provider.invoke = func(request providercli.Request) (providercli.Response, error) { return describeResponse(request), nil }
	return provider
}

func mustAdapter(t *testing.T, provider *fakeRunner) *Adapter {
	t.Helper()
	limits := providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1}
	config := Config{AdapterID: "a", DisplayName: "A", Timeout: time.Second, MaxStdinBytes: 65536, MaxStdoutBytes: 65536, MaxStderrBytes: 4096, MaxRecords: 10, EndpointLimits: limits, AdapterLimits: limits, Mapper: &fakeMapper{mappings: map[string]adapter.ResourceMapping{}}, Capabilities: protocol.CapabilityDescriptor{Revision: "r", Capabilities: []protocol.Capability{{Name: "agent.start", Version: "v1"}}}}
	binding, err := newWithRunner(context.Background(), config, runnerAdapter{provider})
	if err != nil {
		t.Fatalf("new adapter: %v", err)
	}
	return binding
}

func describeResponse(request providercli.Request) providercli.Response {
	return describeResponseWithFunctions(request)
}

func describeResponseWithFunctions(request providercli.Request, additional ...string) providercli.Response {
	functions := []string{providercli.FunctionDescribe, providercli.FunctionDiscover, providercli.FunctionExecute}
	functions = append(functions, additional...)
	descriptor := &providercli.Descriptor{ProviderType: "mock", ProviderVersion: "1", DescriptorRevision: "r", ProtocolRange: providercli.ProtocolRange{Protocol: providercli.ProtocolName, Major: 1, Minimum: 0, Maximum: 0}, Functions: functions, Operations: []providercli.NamedContract{{Name: "agent.start", Version: "v1"}}, Limits: providercli.Budget{MaxStdoutBytes: 65536, MaxStderrBytes: 4096, MaxRecords: 10}, Concurrency: providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1}}
	return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true, Descriptor: descriptor}
}

func response(request providercli.Request, discovery *providercli.DiscoveryResult) providercli.Response {
	return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true, Discovery: discovery}
}

func TestTypedQueriesMapProviderKeysWithoutPublishingThem(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			for _, query := range providercli.StandardQueries() {
				response.Descriptor.Queries = append(response.Descriptor.Queries, providercli.NamedContract{Name: query.Name, Version: query.Version})
			}
			return response, nil
		}
		result := json.RawMessage(`{}`)
		switch request.Query.Name {
		case providercli.QueryLaunchOptions:
			result = json.RawMessage(`{"profile":{"resource_kind":"launch_profile","provider_resource_key":"provider-launch","display_name":"default","revision":"launch-r1"},"projects":[{"name":"work","path":"/work"}]}`)
		case providercli.QueryHistoryMessages:
			result = json.RawMessage(`{"rows":[{"resource_kind":"session","provider_resource_key":"provider-history","provider_session_id":"session-1","resumable":true}],"observed_at_ms":10,"truncated":false}`)
		case providercli.QueryModelCatalog:
			result = json.RawMessage(`{"profiles":[{"resource_kind":"model_profile","provider_resource_key":"provider-model","provider_display_name":"Model","current_state":"yes","available":true}],"current_provider_resource_key":"provider-model","observed_at_ms":11,"truncated":false}`)
		case providercli.QuerySessionMessages:
			result = json.RawMessage(`{"provider_session_id":"session-1","messages":[{"role":"user","content":"hello"}],"message_count":1,"observed_at_ms":12,"truncated":false}`)
		}
		return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true, QueryResult: result}, nil
	}
	binding := mustAdapter(t, provider)
	profile, err := binding.LaunchProfile(context.Background())
	if err != nil || profile.AdapterID != "a" || profile.LaunchProfileID != "launch_profile-provider-launch" || profile.Revision != "launch-r1" {
		t.Fatalf("launch profile = %+v, %v", profile, err)
	}
	history, err := binding.History(context.Background(), protocol.HistoryQuery{Limit: 10})
	if err != nil || len(history.Rows) != 1 || history.Rows[0].ResourceID != "session-provider-history" {
		t.Fatalf("history = %+v, %v", history, err)
	}
	mapper := binding.config.Mapper.(*fakeMapper)
	mapper.mappings["session-live"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "provider-live", ResourceID: "session-live"}
	catalog, err := binding.ModelCatalog(context.Background(), protocol.ModelCatalogQuery{Target: protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: "session-live"}})
	if err != nil || len(catalog.Profiles) != 1 || catalog.Profiles[0].ModelProfileID != "model_profile-provider-model" || catalog.CurrentProfileID != catalog.Profiles[0].ModelProfileID {
		t.Fatalf("catalog = %+v, %v", catalog, err)
	}
	messages, err := binding.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "session-1", MaxChars: 100, MaxTokens: 100})
	if err != nil || len(messages.Messages) != 1 || messages.Messages[0].Content != "hello" {
		t.Fatalf("messages = %+v, %v", messages, err)
	}
}

func TestTypedQueryMapperFailurePublishesNoPartialResult(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			response.Descriptor.Queries = []providercli.NamedContract{{Name: providercli.QueryHistoryMessages, Version: "v1"}}
			return response, nil
		}
		return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true, QueryResult: json.RawMessage(`{"rows":[{"resource_kind":"session","provider_resource_key":"good","provider_session_id":"s1","resumable":true},{"resource_kind":"session","provider_resource_key":"bad","provider_session_id":"s2","resumable":true}],"observed_at_ms":10,"truncated":false}`)}, nil
	}
	binding := mustAdapter(t, provider)
	binding.config.Mapper.(*fakeMapper).failKey = "bad"
	result, err := binding.History(context.Background(), protocol.HistoryQuery{})
	if err == nil || len(result.Rows) != 0 {
		t.Fatalf("history = %+v, %v", result, err)
	}
}

func TestTypedQueryRejectsUnadvertisedContractWithoutInvocation(t *testing.T) {
	provider := newFakeProvider(t)
	binding := mustAdapter(t, provider)
	before := len(provider.requests)
	_, err := binding.History(context.Background(), protocol.HistoryQuery{})
	if !errors.Is(err, adapter.ErrUnsupported) || len(provider.requests) != before {
		t.Fatalf("history error = %v requests = %d, want unsupported and %d", err, len(provider.requests), before)
	}
}
