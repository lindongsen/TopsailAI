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
}

func (m *fakeMapper) GetOrCreateResourceID(_ context.Context, adapterID, kind, key string, _ int64) (adapter.ResourceMapping, error) {
	id := kind + "-id"
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
	if err != nil || len(result.Sessions) != 1 || result.Sessions[0].ClusterSessionID != "session-id" {
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
