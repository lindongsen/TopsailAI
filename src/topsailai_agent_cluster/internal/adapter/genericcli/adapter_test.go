package genericcli

import (
	"context"
	"encoding/json"
	"errors"
	"os/exec"
	"strconv"
	"strings"
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
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c", Operation: "agent.start", OperationVersion: "v1", LaunchProfileID: "profile-id", ProfileRevision: "r1", Folder: "/work/project", Payload: json.RawMessage(`{"task":"initial task"}`), ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli()}})
	if err == nil || result.Receipt.ErrorCode != "denied" {
		t.Fatalf("execute = %+v, %v", result, err)
	}
	request := provider.requests[len(provider.requests)-1]
	if request.Target.ResourceKind != protocol.ResourceLaunchProfile || request.Target.ProviderResourceKey != "native-profile" || request.Target.ExpectedGeneration != "r1" {
		t.Fatalf("target = %+v", request.Target)
	}
	payload, decodeErr := providercli.DecodeAgentStartPayload(request.Payload)
	if decodeErr != nil {
		t.Fatalf("decode Provider start payload: %v", decodeErr)
	}
	if payload.Folder != "/work/project" || payload.Task != "initial task" {
		t.Fatalf("Provider start payload = %+v", payload)
	}
}

func TestAdapterRejectsInvalidAgentStartPayloadBeforeProviderInvocation(t *testing.T) {
	tests := []struct {
		name    string
		folder  string
		payload json.RawMessage
	}{
		{name: "missing folder", payload: json.RawMessage(`{}`)},
		{name: "null task", folder: "/work", payload: json.RawMessage(`{"task":null}`)},
		{name: "empty task", folder: "/work", payload: json.RawMessage(`{"task":""}`)},
		{name: "unknown field", folder: "/work", payload: json.RawMessage(`{"task":"work","resource_id":"cluster-id"}`)},
		{name: "invalid UTF-8", folder: "/work", payload: json.RawMessage{'{', '"', 't', 'a', 's', 'k', '"', ':', '"', 0xff, '"', '}'}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			provider := newFakeProvider(t)
			binding := mustAdapter(t, provider)
			binding.config.Mapper.(*fakeMapper).mappings["profile-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceLaunchProfile, ProviderResourceKey: "native-profile", ResourceID: "profile-id"}
			before := len(provider.requests)
			_, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "c", Operation: protocol.OperationAgentStart, OperationVersion: "v1", LaunchProfileID: "profile-id", ProfileRevision: "r1", Folder: test.folder, Payload: test.payload, ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli()}})
			if err == nil {
				t.Fatal("invalid start payload was accepted")
			}
			if len(provider.requests) != before {
				t.Fatalf("Provider requests = %d, want %d", len(provider.requests), before)
			}
		})
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

// TestFollowPreservesProviderErrorCode proves a Provider-reported stream failure
// keeps its own code across the adapter boundary.
//
// The Endpoint classifies a stream failure by matching sentinel errors, so an
// adapter that reduced every Provider failure to one formatted string made all of
// them indistinguishable: a Provider that correctly reported `cancelled` was
// reported to the operator as `provider_error`, which sent the investigation to a
// Provider that had behaved correctly. This test fails when the code is folded
// back into a message, because the extracted code is then absent.
func TestFollowPreservesProviderErrorCode(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		return describeResponseWithFunctions(request, providercli.FunctionFollowOutput), nil
	}
	binding := mustAdapter(t, provider)
	binding.config.Mapper.(*fakeMapper).mappings["session-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "native", ResourceID: "session-id"}
	provider.stream = []providercli.StreamFrame{{
		Version:   binding.version,
		RequestID: "ignored",
		Type:      providercli.FrameEnd,
		Sequence:  2,
		Error:     &providercli.ProviderError{Code: "cancelled", Message: "provider stopped the stream"},
	}}
	err := binding.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "session-id", ProviderGeneration: "g", MaxBytes: 10}, func(protocol.OutputChunk) error { return nil })
	var streamErr *adapter.StreamError
	if !errors.As(err, &streamErr) {
		t.Fatalf("follow error = %v, want a StreamError carrying the provider code", err)
	}
	if streamErr.Code != "cancelled" {
		t.Fatalf("stream error code = %q, want cancelled", streamErr.Code)
	}
	if streamErr.Message != "provider stopped the stream" {
		t.Fatalf("stream error message = %q, want the provider message", streamErr.Message)
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

// TestFollowForwardsTheConfiguredRecordBudget proves the record budget in the
// provider request is the configured value rather than a literal invented on the
// follow path.
//
// The budget is not a bound the Endpoint enforces, so nothing fails when it is
// dropped or replaced: the follow still works, and the only symptom is a provider
// receiving a different number than the operator configured. Asserting the
// forwarded value is what keeps the wire budget a configuration decision instead
// of a constant that drifts away from the one the factory declares.
func TestFollowForwardsTheConfiguredRecordBudget(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		return describeResponseWithFunctions(request, providercli.FunctionFollowOutput), nil
	}
	binding := mustAdapter(t, provider)
	binding.config.Mapper.(*fakeMapper).mappings["session-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "native", ResourceID: "session-id"}

	if err := binding.FollowOutput(context.Background(), protocol.OutputFollowRequest{ResourceID: "session-id", ProviderGeneration: "g", MaxBytes: 10, MaxLines: 300}, func(protocol.OutputChunk) error { return nil }); err != nil {
		t.Fatalf("follow: %v", err)
	}
	request := provider.requests[len(provider.requests)-1]
	if request.Budget.MaxRecords != binding.config.MaxRecords {
		t.Fatalf("follow request budget MaxRecords = %d, want the configured %d", request.Budget.MaxRecords, binding.config.MaxRecords)
	}
	// The line budget is the caller's own, and it is the value a record count used
	// to truncate: the REPL asks for a 300-line tail while the Endpoint allowed 128
	// records. Both numbers must survive to the provider unchanged.
	var payload struct {
		MaxLines int `json:"max_lines"`
	}
	if err := json.Unmarshal(request.Payload, &payload); err != nil {
		t.Fatalf("decode follow payload: %v", err)
	}
	if payload.MaxLines != 300 {
		t.Fatalf("follow payload max_lines = %d, want the caller's 300", payload.MaxLines)
	}
}

func TestAdapterMapsModelSelectPayloadToProviderKey(t *testing.T) {
	provider := newFakeProvider(t)
	binding := mustAdapter(t, provider)
	mapper := binding.config.Mapper.(*fakeMapper)
	mapper.mappings["session-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "provider-session", ResourceID: "session-id"}
	mapper.mappings["model-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceModelProfile, ProviderResourceKey: "provider-model", ResourceID: "model-id"}
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true, Result: &providercli.OperationResult{DeliveryBoundary: providercli.DeliverySubmitted, EffectCertainty: providercli.EffectAcknowledged, ProviderOutcome: "selected"}}, nil
	}

	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "command-1", Operation: protocol.OperationAgentModelSelect, OperationVersion: "v1",
		Target:  &protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: "session-id", ProviderGeneration: "generation-1"},
		Payload: json.RawMessage(`{"model_profile_id":"model-id"}`), ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli(),
	}})
	if err != nil || result.Receipt.Outcome != "selected" {
		t.Fatalf("execute = %+v, %v", result, err)
	}
	request := provider.requests[len(provider.requests)-1]
	if request.Target.ResourceKind != protocol.ResourceSession || request.Target.ProviderResourceKey != "provider-session" || request.Target.ExpectedGeneration != "generation-1" {
		t.Fatalf("target = %+v", request.Target)
	}
	payload, err := providercli.DecodeModelSelectPayload(request.Payload)
	if err != nil {
		t.Fatalf("decode Provider model-select payload: %v", err)
	}
	if payload.ProviderResourceKey != "provider-model" {
		t.Fatalf("Provider model key = %q", payload.ProviderResourceKey)
	}
	if string(request.Payload) == `{"model_profile_id":"model-id"}` {
		t.Fatal("Cluster model_profile_id reached Provider unchanged")
	}
}

func TestAdapterRejectsInvalidModelSelectMappingBeforeProviderInvocation(t *testing.T) {
	tests := []struct {
		name    string
		mapping *adapter.ResourceMapping
		payload json.RawMessage
	}{
		{name: "unknown Cluster ID", payload: json.RawMessage(`{"model_profile_id":"missing"}`)},
		{name: "wrong adapter", mapping: &adapter.ResourceMapping{AdapterID: "other", ResourceKind: protocol.ResourceModelProfile, ProviderResourceKey: "provider-model", ResourceID: "model-id"}, payload: json.RawMessage(`{"model_profile_id":"model-id"}`)},
		{name: "wrong resource kind", mapping: &adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "provider-model", ResourceID: "model-id"}, payload: json.RawMessage(`{"model_profile_id":"model-id"}`)},
		{name: "empty Provider key", mapping: &adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceModelProfile, ResourceID: "model-id"}, payload: json.RawMessage(`{"model_profile_id":"model-id"}`)},
		{name: "invalid Provider key", mapping: &adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceModelProfile, ProviderResourceKey: " provider-model", ResourceID: "model-id"}, payload: json.RawMessage(`{"model_profile_id":"model-id"}`)},
		{name: "unknown public field", payload: json.RawMessage(`{"model_profile_id":"model-id","provider_resource_key":"provider-model"}`)},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			provider := newFakeProvider(t)
			binding := mustAdapter(t, provider)
			mapper := binding.config.Mapper.(*fakeMapper)
			mapper.mappings["session-id"] = adapter.ResourceMapping{AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "provider-session", ResourceID: "session-id"}
			if test.mapping != nil {
				mapper.mappings[test.mapping.ResourceID] = *test.mapping
			}
			before := len(provider.requests)
			_, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "command-1", Operation: protocol.OperationAgentModelSelect, OperationVersion: "v1",
				Target:  &protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: "session-id", ProviderGeneration: "generation-1"},
				Payload: test.payload, ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli(),
			}})
			if err == nil {
				t.Fatal("invalid model selection was accepted")
			}
			if len(provider.requests) != before {
				t.Fatalf("Provider requests = %d, want %d", len(provider.requests), before)
			}
		})
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

// TestReadOutputMapsProviderUnsupportedToAdapterUnsupported proves a provider
// capability gap is reported as unsupported rather than as a provider failure.
//
// The Endpoint maps adapter.ErrUnsupported onto the standard "unsupported" error
// code and every other error onto "provider_error". Returning the plain provider
// error therefore told the operator the read had failed when the provider had
// actually said it cannot do it, and the two conditions need different operator
// responses: one is a capability gap, the other is a fault.
func TestReadOutputMapsProviderUnsupportedToAdapterUnsupported(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			return describeResponseWithFunctions(request, providercli.FunctionReadOutput), nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: false,
			Error: &providercli.ProviderError{Code: "unsupported", Message: "output is unsupported", EffectCertainty: providercli.EffectNotApplied},
		}, nil
	}
	binding := mustAdapter(t, provider)
	mapping, err := binding.config.Mapper.GetOrCreateResourceID(context.Background(), "a", protocol.ResourceSession, "session:stable", 1)
	if err != nil {
		t.Fatalf("map session: %v", err)
	}
	_, err = binding.ReadOutput(context.Background(), adapter.OutputRequest{
		Target: protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: mapping.ResourceID, ProviderGeneration: "generation-1"},
	})
	if !errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("read output error = %v, want %v", err, adapter.ErrUnsupported)
	}
}

// TestReadOutputKeepsOtherProviderErrorsAsFailures proves the mapping is narrow.
//
// Only the provider's own "unsupported" code is a capability gap. A provider that
// reports any other failure must still surface as a failure, otherwise a broken
// provider would be reported as a missing capability and the operator would stop
// looking for the fault.
func TestReadOutputKeepsOtherProviderErrorsAsFailures(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			return describeResponseWithFunctions(request, providercli.FunctionReadOutput), nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: false,
			Error: &providercli.ProviderError{Code: "provider_error", Message: "output read failed", EffectCertainty: providercli.EffectNotApplied},
		}, nil
	}
	binding := mustAdapter(t, provider)
	mapping, err := binding.config.Mapper.GetOrCreateResourceID(context.Background(), "a", protocol.ResourceSession, "session:stable", 1)
	if err != nil {
		t.Fatalf("map session: %v", err)
	}
	_, err = binding.ReadOutput(context.Background(), adapter.OutputRequest{
		Target: protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: mapping.ResourceID, ProviderGeneration: "generation-1"},
	})
	if err == nil || errors.Is(err, adapter.ErrUnsupported) {
		t.Fatalf("read output error = %v, want a plain failure", err)
	}
}

// TestMessagesMapsProviderMissingSessionToClusterMissingSession proves a
// provider that does not know the session is reported as a missing session.
//
// The two outcomes are different claims: "this session does not exist" and "the
// provider failed to read this session" send the operator to different places,
// and the Server maps them to different HTTP statuses. Flattening the provider
// code into a message made the distinction unrecoverable, so this test asserts
// the code survives the trip.
func TestMessagesMapsProviderMissingSessionToClusterMissingSession(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			response.Descriptor.Queries = []providercli.NamedContract{{Name: providercli.QuerySessionMessages, Version: "v1"}}
			return response, nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: false,
			Error: &providercli.ProviderError{Code: "session_not_found", Message: "provider session does not exist", EffectCertainty: providercli.EffectNotApplied},
		}, nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "never-recorded"})
	if err == nil {
		t.Fatal("messages error = nil, want a missing-session failure")
	}
	if result.ErrorCode != protocol.MessagesSessionNotFound {
		t.Fatalf("messages error code = %q, want %q", result.ErrorCode, protocol.MessagesSessionNotFound)
	}
	if result.ProviderSessionID != "never-recorded" {
		t.Fatalf("messages provider session id = %q, want the requested session", result.ProviderSessionID)
	}
}

// TestMessagesKeepsOtherProviderErrorsAsProviderFailures proves the mapping is
// narrow.
//
// Only the provider's own missing-session code is a missing session. Any other
// provider failure must stay a provider failure, otherwise a broken provider
// would be reported as a deleted session and the operator would stop looking for
// data that still exists.
func TestMessagesKeepsOtherProviderErrorsAsProviderFailures(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			response.Descriptor.Queries = []providercli.NamedContract{{Name: providercli.QuerySessionMessages, Version: "v1"}}
			return response, nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: false,
			Error: &providercli.ProviderError{Code: "provider_error", Message: "history read failed", EffectCertainty: providercli.EffectNotApplied},
		}, nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.Messages(context.Background(), protocol.MessagesQuery{ProviderSessionID: "session-1"})
	if err == nil {
		t.Fatal("messages error = nil, want a provider failure")
	}
	if result.ErrorCode == protocol.MessagesSessionNotFound {
		t.Fatalf("messages error code = %q, want a provider failure", result.ErrorCode)
	}
}

// TestMetricsMapsProviderCountsOntoTheTwoClusterPositions proves the two counts
// reach the cluster fields the surface renders as data1/data2.
//
// The values are deliberately distinct and neither is zero, because a mapping
// that swapped the two positions or hardcoded one of them would pass a test
// whose fixture used equal or zero counts. The provider's own layer names are
// asserted nowhere: the cluster contract names the roles, so this test would
// still be correct for a provider that called its layers something else.
func TestMetricsMapsProviderCountsOntoTheTwoClusterPositions(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			response.Descriptor.Queries = []providercli.NamedContract{{Name: providercli.QuerySessionMetrics, Version: "v1"}}
			return response, nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: true,
			QueryResult: json.RawMessage(`{"provider_session_id":"session-1","messages":{"inbound":7,"outbound":3},"observed_at_ms":99}`),
		}, nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.Metrics(context.Background(), protocol.SessionMetricsQuery{ProviderSessionID: "session-1"})
	if err != nil {
		t.Fatalf("metrics error = %v, want success", err)
	}
	if result.Messages.Inbound != 7 || result.Messages.Outbound != 3 {
		t.Fatalf("metrics messages = %+v, want inbound=7 outbound=3", result.Messages)
	}
	if result.ProviderSessionID != "session-1" || result.ObservedAtMS != 99 {
		t.Fatalf("metrics identity = %q observed=%d, want session-1 observed=99", result.ProviderSessionID, result.ObservedAtMS)
	}
	if result.ErrorCode != "" {
		t.Fatalf("metrics error code = %q, want empty on success", result.ErrorCode)
	}
}

// TestMetricsMapsProviderMissingSessionToClusterMissingSession proves a deleted
// session is reported as absent rather than as a provider fault.
//
// The distinction decides what the operator does next: an absent session is a
// row that no longer exists, while a provider fault is a machine to investigate.
// Reporting one as the other sends the investigation to the wrong place.
func TestMetricsMapsProviderMissingSessionToClusterMissingSession(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			response.Descriptor.Queries = []providercli.NamedContract{{Name: providercli.QuerySessionMetrics, Version: "v1"}}
			return response, nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: false,
			Error: &providercli.ProviderError{Code: "session_not_found", Message: "provider session does not exist", EffectCertainty: providercli.EffectNotApplied},
		}, nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.Metrics(context.Background(), protocol.SessionMetricsQuery{ProviderSessionID: "never-recorded"})
	if err == nil {
		t.Fatal("metrics error = nil, want a missing-session failure")
	}
	if result.ErrorCode != protocol.MetricsSessionNotFound {
		t.Fatalf("metrics error code = %q, want %q", result.ErrorCode, protocol.MetricsSessionNotFound)
	}
	if result.ProviderSessionID != "never-recorded" {
		t.Fatalf("metrics provider session id = %q, want the requested session", result.ProviderSessionID)
	}
}

// TestDetailForwardsProviderMetadataVerbatimAndLeavesRuntimeEmpty proves the
// provider record reaches the surface unchanged and the runtime seam stays empty.
//
// The metadata fixture carries a field the cluster does not model, because a
// re-encoding adapter would drop exactly that field while still passing any
// assertion that checked only the fields it knew about. Comparing the whole
// document is the only assertion that distinguishes forwarding from rebuilding.
//
// The runtime assertion is the other half: an empty runtime must stay empty, so a
// placeholder invented by the adapter would fail here instead of being presented
// to the operator as an observation nobody made.
func TestDetailForwardsProviderMetadataVerbatimAndLeavesRuntimeEmpty(t *testing.T) {
	const providerRecord = `{"session_id":"s-1","task":"work","unmodelled_field":{"nested":true}}`
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			response.Descriptor.Queries = []providercli.NamedContract{{Name: providercli.QuerySessionDetail, Version: "v1"}}
			return response, nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: true,
			QueryResult: json.RawMessage(`{"provider_session_id":"s-1","provider_metadata":` + strconv.Quote(providerRecord) + `,"observed_at_ms":42}`),
		}, nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.Detail(context.Background(), protocol.SessionDetailQuery{ProviderSessionID: "s-1"})
	if err != nil {
		t.Fatalf("detail error = %v, want success", err)
	}
	if result.ProviderMetadata != providerRecord {
		t.Fatalf("detail provider_metadata = %q, want the provider record verbatim", result.ProviderMetadata)
	}
	if result.ProviderRuntime != "" {
		t.Fatalf("detail provider_runtime = %q, want empty because the provider reported none", result.ProviderRuntime)
	}
	if result.ProviderSessionID != "s-1" || result.ObservedAtMS != 42 {
		t.Fatalf("detail identity = %q observed=%d, want s-1 observed=42", result.ProviderSessionID, result.ObservedAtMS)
	}
}

// TestDetailMapsProviderMissingSessionToClusterMissingSession proves detail uses
// the same narrow mapping as metrics.
//
// Detail is the read an operator performs on a session that may have no live
// process, so a missing record is a normal answer here rather than an error path
// nobody exercises. It must still be reported as absent, not as a fault.
func TestDetailMapsProviderMissingSessionToClusterMissingSession(t *testing.T) {
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			response.Descriptor.Queries = []providercli.NamedContract{{Name: providercli.QuerySessionDetail, Version: "v1"}}
			return response, nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: false,
			Error: &providercli.ProviderError{Code: "session_not_found", Message: "provider session does not exist", EffectCertainty: providercli.EffectNotApplied},
		}, nil
	}
	binding := mustAdapter(t, provider)
	result, err := binding.Detail(context.Background(), protocol.SessionDetailQuery{ProviderSessionID: "never-recorded"})
	if err == nil {
		t.Fatal("detail error = nil, want a missing-session failure")
	}
	if result.ErrorCode != protocol.DetailSessionNotFound {
		t.Fatalf("detail error code = %q, want %q", result.ErrorCode, protocol.DetailSessionNotFound)
	}
	if result.ProviderSessionID != "never-recorded" {
		t.Fatalf("detail provider session id = %q, want the requested session", result.ProviderSessionID)
	}
}

// TestReceiptFromOperationCarriesExitConfirmation proves the provider's exit
// observation reaches the Cluster receipt.
//
// The field is load-bearing rather than informational: storage keeps a
// signal_sent receipt at "executing" while exit_confirmed is false, so a
// provider that confirms an exit and an adapter that drops the confirmation
// together produce a command that can never reach a terminal state. The false
// case is asserted in the same table because a mapping that hardcodes true
// would pass a true-only test while silently claiming every signal exited.
func TestReceiptFromOperationCarriesExitConfirmation(t *testing.T) {
	cases := []struct {
		name string
		exit bool
	}{
		{name: "confirmed", exit: true},
		{name: "unconfirmed", exit: false},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			receipt := receiptFromOperation(providercli.OperationResult{
				DeliveryBoundary: providercli.DeliverySignalSent,
				EffectCertainty:  providercli.EffectAcknowledged,
				ProviderOutcome:  "submitted",
				ExitConfirmed:    testCase.exit,
			})
			if receipt.ExitConfirmed != testCase.exit {
				t.Fatalf("receipt exit confirmed = %t, want %t", receipt.ExitConfirmed, testCase.exit)
			}
			if receipt.DeliveryBoundary != protocol.DeliverySignalSent {
				t.Fatalf("receipt delivery boundary = %q, want signal_sent", receipt.DeliveryBoundary)
			}
		})
	}
}

// TestReceiptFromProviderErrorCarriesTheProviderDiagnostic proves a rejected
// invocation still carries the provider's own evidence.
//
// The operator surface renders ProviderResponse as a separate section and prints
// nothing for an empty document, so an unset field silently removed the whole
// section: the operator saw a receipt with an error code and no provider answer.
// The stderr case is asserted separately because a provider that dies before
// writing a document has no structured evidence, and its stderr is then the only
// diagnostic available.
// TestIntersectCapabilitiesAcceptsTheControlActionFamily proves a control action
// the provider advertises is reachable.
//
// The provider reports its control actions in their own contract list rather than
// as operations, so reading only the operation list dropped every ctl. capability
// the operator had configured. The Endpoint then advertised no control surface at
// all and refused every control command as unsupported before the policy hook, so
// a configured catalog had no effect.
func TestIntersectCapabilitiesAcceptsTheControlActionFamily(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: "ctl.fixture_probe", Version: "v1", TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassMutating, RequiredPermission: "control"},
			{Name: "message.send", Version: "v1", TargetKinds: []string{"session"}},
		},
	}
	offered := []providercli.NamedContract{{Name: "message.send", Version: "v1"}}
	controlActions := []providercli.NamedContract{{Name: "ctl.fixture_probe", Version: "v1"}}

	effective := intersectCapabilities(configured, providercli.Descriptor{DescriptorRevision: "provider-r1", Operations: offered, ControlActions: controlActions})
	if effective.Revision != "provider-r1" {
		t.Fatalf("effective revision = %q, want the Provider's descriptor revision", effective.Revision)
	}
	names := make([]string, 0, len(effective.Capabilities))
	for _, capability := range effective.Capabilities {
		names = append(names, capability.Name)
	}
	if len(names) != 2 {
		t.Fatalf("effective capabilities = %v, want both the operation and the control action", names)
	}
}

// TestIntersectCapabilitiesDropsAnUnadvertisedControlAction is the reverse case.
//
// Without it, treating every configured ctl. capability as reachable would pass
// the positive test while advertising an action the provider cannot serve, and
// the operator would see a provider error instead of a capability gap.
func TestIntersectCapabilitiesDropsAnUnadvertisedControlAction(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: "ctl.fixture_probe", Version: "v1", TargetKinds: []string{"session"}},
		},
	}
	effective := intersectCapabilities(configured, providercli.Descriptor{ControlActions: []providercli.NamedContract{{Name: "ctl.other_action", Version: "v1"}}})
	if len(effective.Capabilities) != 0 {
		t.Fatalf("effective capabilities = %v, want none because the provider does not advertise the configured action", effective.Capabilities)
	}
}

// TestIntersectCapabilitiesKeepsCommandExecWithoutAProviderOffer proves the one
// configured capability that is not intersected stays reachable.
//
// command.exec is Endpoint-native: the Endpoint owns the allowlist, the working
// directory, the confinement decision, the environment, the timeout and the
// process cleanup, and Execute returns before any provider call. A provider that
// reports only what it implements therefore cannot advertise it, and requiring an
// offer made the operator's own allowlisted command unreachable on every such
// provider. The configured entry is the operator's allowlist, so it is kept even
// though nothing offered it.
func TestIntersectCapabilitiesKeepsCommandExecWithoutAProviderOffer(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion, TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassMutating, RequiredPermission: "control"},
			{Name: "message.send", Version: "v1", TargetKinds: []string{"session"}},
		},
	}
	// The provider offers one unrelated operation and nothing else, which is the
	// shape a provider that reports only its own handlers produces.
	offered := []providercli.NamedContract{{Name: "message.send", Version: "v1"}}

	effective := intersectCapabilities(configured, providercli.Descriptor{Operations: offered})
	if len(effective.Capabilities) != 2 {
		t.Fatalf("effective capabilities = %v, want command.exec kept beside the offered operation", effective.Capabilities)
	}
	var found bool
	for _, capability := range effective.Capabilities {
		if capability.Name != protocol.OperationCommandExec {
			continue
		}
		found = true
		if capability.Version != protocol.CommandExecPayloadVersion {
			t.Fatalf("command.exec version = %q, want %q", capability.Version, protocol.CommandExecPayloadVersion)
		}
		if capability.RequiredPermission != "control" {
			t.Fatalf("command.exec permission = %q, want the configured control permission", capability.RequiredPermission)
		}
	}
	if !found {
		t.Fatalf("effective capabilities = %v, want command.exec present", effective.Capabilities)
	}
}

// TestIntersectCapabilitiesStillDropsAnUnadvertisedOperation is the reverse case
// for the command.exec exemption.
//
// The exemption must be exactly one operation. If it widened into "keep every
// configured capability", an operation the provider cannot serve would be
// advertised and the operator would see a provider error instead of a capability
// gap, which is the defect the intersection exists to prevent.
func TestIntersectCapabilitiesStillDropsAnUnadvertisedOperation(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: "agent.stop", Version: "v1", TargetKinds: []string{"session"}},
		},
	}
	effective := intersectCapabilities(configured, providercli.Descriptor{})
	if len(effective.Capabilities) != 0 {
		t.Fatalf("effective capabilities = %v, want none because the provider does not offer agent.stop", effective.Capabilities)
	}
}

// TestIntersectCapabilitiesTakesTheActionMetadataFromTheProvider proves the
// provider is the source of what an allowed control action is.
//
// The catalog decides which actions are allowed, because it is the operator's
// allowlist. It cannot decide what an action addresses or whether it changes
// state: only the provider that implements the action knows that. Reading the
// metadata from the configured side instead would let an operator's stale copy
// describe an action the provider has since changed.
func TestIntersectCapabilitiesTakesTheActionMetadataFromTheProvider(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: "ctl.heartbeat", Version: "v1", TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassMutating, RequiredPermission: "control"},
		},
	}
	controlActions := []providercli.NamedContract{{
		Name:          "ctl.heartbeat",
		Version:       "v1",
		TargetKinds:   []string{"session"},
		PayloadSchema: `{"type":"object"}`,
		SafetyClass:   protocol.SafetyClassReadOnly,
	}}

	effective := intersectCapabilities(configured, providercli.Descriptor{ControlActions: controlActions})
	if len(effective.Capabilities) != 1 {
		t.Fatalf("effective capabilities = %v, want the configured action", effective.Capabilities)
	}
	got := effective.Capabilities[0]
	if got.PayloadSchema != `{"type":"object"}` {
		t.Fatalf("payload schema = %q, want the provider-declared schema", got.PayloadSchema)
	}
	if got.SafetyClass != protocol.SafetyClassReadOnly {
		t.Fatalf("safety class = %q, want the provider-declared class", got.SafetyClass)
	}
}

// TestIntersectCapabilitiesKeepsTheConfiguredPermission is the security case.
//
// Who may invoke a control action is an operator decision. A provider that could
// declare its own permission could downgrade a mutating action to a read scope
// and hand it to a caller the operator never authorized, so the configured value
// must always win even when the provider disagrees.
func TestIntersectCapabilitiesKeepsTheConfiguredPermission(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: "ctl.heartbeat", Version: "v1", TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassMutating, RequiredPermission: "control"},
		},
	}
	controlActions := []providercli.NamedContract{{
		Name:               "ctl.heartbeat",
		Version:            "v1",
		TargetKinds:        []string{"session"},
		SafetyClass:        protocol.SafetyClassMutating,
		RequiredPermission: "view",
	}}

	effective := intersectCapabilities(configured, providercli.Descriptor{ControlActions: controlActions})
	if len(effective.Capabilities) != 1 {
		t.Fatalf("effective capabilities = %v, want the configured action", effective.Capabilities)
	}
	if got := effective.Capabilities[0].RequiredPermission; got != "control" {
		t.Fatalf("required permission = %q, want the configured scope, because a provider must not widen its own access", got)
	}
}

// TestIntersectCapabilitiesKeepsConfiguredMetadataWhenTheProviderOmitsIt proves
// an older provider cannot strip a capability description.
//
// A provider that declares only a name and a version is still a valid provider.
// Treating its silence as "no target kinds, no safety class" would advertise a
// capability the Endpoint cannot describe, so an omitted field keeps the
// configured value.
func TestIntersectCapabilitiesKeepsConfiguredMetadataWhenTheProviderOmitsIt(t *testing.T) {
	configured := protocol.CapabilityDescriptor{
		Revision: "rev-1",
		Capabilities: []protocol.Capability{
			{Name: "ctl.heartbeat", Version: "v1", TargetKinds: []string{"session"}, SafetyClass: protocol.SafetyClassMutating, RequiredPermission: "control"},
		},
	}
	controlActions := []providercli.NamedContract{{Name: "ctl.heartbeat", Version: "v1"}}

	effective := intersectCapabilities(configured, providercli.Descriptor{ControlActions: controlActions})
	if len(effective.Capabilities) != 1 {
		t.Fatalf("effective capabilities = %v, want the configured action", effective.Capabilities)
	}
	got := effective.Capabilities[0]
	if len(got.TargetKinds) != 1 || got.TargetKinds[0] != "session" {
		t.Fatalf("target kinds = %v, want the configured kinds", got.TargetKinds)
	}
	if got.SafetyClass != protocol.SafetyClassMutating {
		t.Fatalf("safety class = %q, want the configured class", got.SafetyClass)
	}
}

func TestReceiptFromProviderErrorCarriesTheProviderDiagnostic(t *testing.T) {
	t.Run("structured document", func(t *testing.T) {
		receipt := receiptFromProviderError(&providercli.ProviderError{
			Code: "provider_error", Message: "mock execution failure", EffectCertainty: providercli.EffectNotApplied,
		}, nil)
		if receipt.ProviderResponse == "" {
			t.Fatal("receipt provider response is empty, want the provider error document")
		}
		if !strings.Contains(receipt.ProviderResponse, "mock execution failure") {
			t.Fatalf("receipt provider response = %q, want it to carry the provider message", receipt.ProviderResponse)
		}
		if receipt.ProviderResponseTruncated {
			t.Fatal("receipt provider response is truncated, want it complete")
		}
	})

	t.Run("stderr fallback", func(t *testing.T) {
		receipt := receiptFromProviderError(&providercli.ProviderError{EffectCertainty: providercli.EffectNotApplied}, &exec.ExitError{Stderr: []byte("provider died before answering")})
		if !strings.Contains(receipt.ProviderResponse, "provider died before answering") {
			t.Fatalf("receipt provider response = %q, want the provider stderr", receipt.ProviderResponse)
		}
	})

	t.Run("no evidence at all", func(t *testing.T) {
		receipt := receiptFromProviderError(&providercli.ProviderError{EffectCertainty: providercli.EffectNotApplied}, nil)
		if receipt.ProviderResponse != "" {
			t.Fatalf("receipt provider response = %q, want empty when the provider supplied nothing", receipt.ProviderResponse)
		}
	})
}

// TestDetailHonoursTheConfiguredBound proves the configured detail bound is the
// bound the adapter actually enforces.
//
// The same provider document is read twice through two adapters that differ only
// in MaxDetailBytes. A test that asserted only the rejection would pass with the
// bound hardcoded, and a test that asserted only the acceptance would pass with
// the bound ignored. Both halves are required because the defect this guards is a
// configured value that is parsed, validated and then never read: every layer
// forwards it faithfully and the behaviour never changes.
func TestDetailHonoursTheConfiguredBound(t *testing.T) {
	// The document is larger than the small bound and smaller than the large one,
	// so the two adapters must disagree about it. A fixture that fits both bounds
	// could not express the failure mode.
	document := strings.Repeat("x", 4096)
	provider := newFakeProvider(t)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionDescribe {
			response := describeResponseWithFunctions(request, providercli.FunctionQuery)
			response.Descriptor.Queries = []providercli.NamedContract{{Name: providercli.QuerySessionDetail, Version: "v1"}}
			return response, nil
		}
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: true,
			QueryResult: json.RawMessage(`{"provider_session_id":"s-1","provider_metadata":` + strconv.Quote(document) + `,"observed_at_ms":42}`),
		}, nil
	}
	limits := providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1}
	build := func(t *testing.T, maxDetailBytes int) *Adapter {
		t.Helper()
		config := Config{
			AdapterID: "a", DisplayName: "A", Timeout: time.Second,
			MaxStdinBytes: 65536, MaxStdoutBytes: 65536, MaxStderrBytes: 4096, MaxRecords: 10,
			MaxDetailBytes: maxDetailBytes,
			EndpointLimits: limits, AdapterLimits: limits,
			Mapper:       &fakeMapper{mappings: map[string]adapter.ResourceMapping{}},
			Capabilities: protocol.CapabilityDescriptor{Revision: "r", Capabilities: []protocol.Capability{{Name: "agent.start", Version: "v1"}}},
		}
		binding, err := newWithRunner(context.Background(), config, runnerAdapter{provider})
		if err != nil {
			t.Fatalf("new adapter: %v", err)
		}
		return binding
	}
	// A bound below the document must refuse it with the specific machine code, so
	// the operator reads "this record is larger than the configured bound" instead
	// of "the provider is broken".
	small := build(t, 1024)
	_, err := small.Detail(context.Background(), protocol.SessionDetailQuery{ProviderSessionID: "s-1"})
	if err == nil {
		t.Fatal("a document above the configured bound was accepted")
	}
	var coded interface{ ErrorCode() string }
	if !errors.As(err, &coded) || coded.ErrorCode() != protocol.DetailResponseTooLarge {
		t.Fatalf("error = %v, want code %q", err, protocol.DetailResponseTooLarge)
	}
	// The same document must be accepted once the bound is raised, which is what
	// proves the value reached the decoder rather than being ignored.
	large := build(t, 8192)
	result, err := large.Detail(context.Background(), protocol.SessionDetailQuery{ProviderSessionID: "s-1"})
	if err != nil {
		t.Fatalf("a document within the configured bound was refused: %v", err)
	}
	if result.ProviderMetadata != document {
		t.Fatalf("provider_metadata length = %d, want %d", len(result.ProviderMetadata), len(document))
	}
}
