package endpoint

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// countingExecutor records whether any read path reached the adapter. A policy
// refusal must leave every counter at zero, because a refused caller must not be
// able to infer from the response whether this Endpoint has an adapter at all.
type countingExecutor struct {
	outputCalls   int
	followCalls   int
	historyCalls  int
	messagesCalls int
	modelCalls    int
	launchCalls   int
}

func (e *countingExecutor) Execute(context.Context, protocol.ImmutableIntent, string) (protocol.ExecutionReceipt, error) {
	return protocol.ExecutionReceipt{}, nil
}

func (e *countingExecutor) ReadOutput(context.Context, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	e.outputCalls++
	return protocol.OutputSnapshotResponse{Data: "adapter-output", ObservedAtMS: time.Now().UnixMilli()}, nil
}

func (e *countingExecutor) FollowOutput(context.Context, protocol.OutputFollowRequest, func(protocol.OutputChunk) error) error {
	e.followCalls++
	return nil
}

func (e *countingExecutor) History(context.Context, protocol.HistoryQuery) (protocol.HistoryResult, error) {
	e.historyCalls++
	return protocol.HistoryResult{}, nil
}

func (e *countingExecutor) Messages(context.Context, protocol.MessagesQuery) (protocol.MessagesResult, error) {
	e.messagesCalls++
	return protocol.MessagesResult{}, nil
}

func (e *countingExecutor) ModelCatalog(context.Context, protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	e.modelCalls++
	return protocol.ModelCatalog{}, nil
}

func (e *countingExecutor) LaunchOptions(context.Context, protocol.LaunchQuery) (protocol.LaunchOptions, error) {
	e.launchCalls++
	return protocol.LaunchOptions{}, nil
}

// newPolicyService builds a Service whose access policy is loaded from one
// directory holding the supplied rule files.
func newPolicyService(t *testing.T, endpointID string, files map[string]string) (*Service, *serviceChannel, *countingExecutor) {
	t.Helper()
	dir := t.TempDir()
	for name, body := range files {
		writePolicyFile(t, dir, name, body)
	}
	loaded, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load policy dir: %v", err)
	}
	policy := loaded.Policy
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	transport := newServiceChannel()
	executor := &countingExecutor{}
	service, err := NewService(ServiceDeps{
		Collector:    &serviceCollector{},
		Channel:      transport,
		Storage:      store,
		Executor:     executor,
		AccessPolicy: policy,
		EndpointID:   endpointID,
	})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}
	return service, transport, executor
}

// lastFrameOfType returns the most recent frame of one type, failing the test
// when the handler produced none.
func lastFrameOfType(t *testing.T, transport *serviceChannel, kind string) channel.Frame {
	t.Helper()
	transport.mu.Lock()
	defer transport.mu.Unlock()
	for i := len(transport.frames) - 1; i >= 0; i-- {
		if transport.frames[i].Type == kind {
			return transport.frames[i]
		}
	}
	t.Fatalf("no %s frame was published", kind)
	return channel.Frame{}
}

// readFrame builds one read request frame carrying the supplied token.
func readFrame(kind, token string) channel.Frame {
	frame := channel.Frame{Type: kind, ProtocolVersion: channel.ProtocolVersion, RequestID: "req-1", EndpointToken: token}
	switch kind {
	case channel.FrameOutputRequest:
		frame.OutputRequest = &protocol.OutputSnapshotRequest{ResourceID: "r1", ProviderGeneration: "g1"}
	case channel.FrameOutputFollowRequest:
		frame.OutputFollowRequest = &protocol.OutputFollowRequest{ResourceID: "r1", ProviderGeneration: "g1"}
	case channel.FrameHistoryRequest:
		frame.HistoryQuery = &protocol.HistoryQuery{Limit: 10}
	case channel.FrameMessagesRequest:
		frame.MessagesQuery = &protocol.MessagesQuery{ProviderSessionID: "s1"}
	case channel.FrameModelCatalogRequest:
		frame.ModelCatalogQuery = &protocol.ModelCatalogQuery{Target: protocol.CommandTarget{Kind: "session", ResourceID: "r1", ProviderGeneration: "g1"}}
	case channel.FrameLaunchRequest:
		frame.LaunchQuery = &protocol.LaunchQuery{}
	}
	return frame
}

// TestEveryReadOperationIsRefusedForAnUnlistedToken proves the enforcement point
// exists on all six read paths. A single missing check would let one token read
// provider detail that the policy never granted, so the six cases are enumerated
// rather than sampled.
func TestEveryReadOperationIsRefusedForAnUnlistedToken(t *testing.T) {
	service, transport, executor := newPolicyService(t, "gd-dev", map[string]string{
		"admin.conf": "token admin-token\nallow-all\n",
	})
	ctx := context.Background()
	cases := []struct {
		name      string
		kind      string
		response  string
		adapterOK func() bool
	}{
		{"output.read", channel.FrameOutputRequest, channel.FrameOutputResponse, func() bool { return executor.outputCalls == 0 }},
		{"output.follow", channel.FrameOutputFollowRequest, channel.FrameOutputEnd, func() bool { return executor.followCalls == 0 }},
		{"history.read", channel.FrameHistoryRequest, channel.FrameHistoryResponse, func() bool { return executor.historyCalls == 0 }},
		{"messages.read", channel.FrameMessagesRequest, channel.FrameMessagesResponse, func() bool { return executor.messagesCalls == 0 }},
		{"agent.model.list", channel.FrameModelCatalogRequest, channel.FrameModelCatalogResponse, func() bool { return executor.modelCalls == 0 }},
		{"launch.query", channel.FrameLaunchRequest, channel.FrameLaunchResponse, func() bool { return executor.launchCalls == 0 }},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			frame := readFrame(testCase.kind, "unlisted-token")
			switch testCase.kind {
			case channel.FrameOutputRequest:
				service.outputFrame(ctx, frame)
			case channel.FrameOutputFollowRequest:
				service.startFollow(ctx, frame)
			case channel.FrameHistoryRequest:
				service.historyFrame(ctx, frame)
			case channel.FrameMessagesRequest:
				service.messagesFrame(ctx, frame)
			case channel.FrameModelCatalogRequest:
				service.modelCatalogFrame(ctx, frame)
			case channel.FrameLaunchRequest:
				service.launchFrame(ctx, frame)
			}
			if !testCase.adapterOK() {
				t.Fatalf("%s reached the adapter despite a policy refusal", testCase.name)
			}
			if code := refusalCode(t, lastFrameOfType(t, transport, testCase.response)); code != policyDeniedCode {
				t.Fatalf("%s refusal code = %q, want %q", testCase.name, code, policyDeniedCode)
			}
		})
	}
}

// refusalCode extracts the error code from whichever response frame carries one.
func refusalCode(t *testing.T, frame channel.Frame) string {
	t.Helper()
	switch {
	case frame.OutputResponse != nil:
		return frame.OutputResponse.ErrorCode
	case frame.OutputEnd != nil:
		return frame.OutputEnd.ErrorCode
	case frame.HistoryResult != nil:
		return frame.HistoryResult.ErrorCode
	case frame.MessagesResult != nil:
		return frame.MessagesResult.ErrorCode
	case frame.ModelCatalog != nil:
		return frame.ModelCatalog.ErrorCode
	case frame.LaunchOptions != nil:
		return frame.LaunchOptions.ErrorCode
	}
	t.Fatalf("frame %s carries no error code", frame.Type)
	return ""
}

// TestMissingTokenIsRefused proves an absent credential is not weaker than a
// wrong one. A configured policy must never fall back to the unconfigured
// default merely because the caller omitted the token.
func TestMissingTokenIsRefused(t *testing.T) {
	service, transport, executor := newPolicyService(t, "gd-dev", map[string]string{
		"admin.conf": "token admin-token\nallow-all\n",
	})
	service.outputFrame(context.Background(), readFrame(channel.FrameOutputRequest, ""))
	if executor.outputCalls != 0 {
		t.Fatal("an empty token reached the adapter")
	}
	if code := refusalCode(t, lastFrameOfType(t, transport, channel.FrameOutputResponse)); code != policyDeniedCode {
		t.Fatalf("refusal code = %q, want %q", code, policyDeniedCode)
	}
}

// TestGrantedTokenReachesTheAdapter proves the check is a filter rather than a
// blanket refusal: a token the policy grants must still reach the adapter.
func TestGrantedTokenReachesTheAdapter(t *testing.T) {
	service, transport, executor := newPolicyService(t, "gd-dev", map[string]string{
		"reader.conf": "token reader-token\nscopes read_output\n",
	})
	service.outputFrame(context.Background(), readFrame(channel.FrameOutputRequest, "reader-token"))
	if executor.outputCalls != 1 {
		t.Fatalf("adapter calls = %d, want 1", executor.outputCalls)
	}
	response := lastFrameOfType(t, transport, channel.FrameOutputResponse)
	if response.OutputResponse == nil || response.OutputResponse.ErrorCode != "" {
		t.Fatalf("granted read returned an error: %+v", response.OutputResponse)
	}
}

// TestUnconfiguredPolicyPermitsEveryRead proves the default state is unchanged.
// An Endpoint that was never pointed at a policy directory must keep serving
// every read, otherwise the feature would break existing deployments.
func TestUnconfiguredPolicyPermitsEveryRead(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	defer store.Close()
	transport := newServiceChannel()
	executor := &countingExecutor{}
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: executor})
	if err != nil {
		t.Fatalf("new service: %v", err)
	}
	ctx := context.Background()
	service.outputFrame(ctx, readFrame(channel.FrameOutputRequest, ""))
	service.historyFrame(ctx, readFrame(channel.FrameHistoryRequest, ""))
	service.messagesFrame(ctx, readFrame(channel.FrameMessagesRequest, ""))
	service.modelCatalogFrame(ctx, readFrame(channel.FrameModelCatalogRequest, ""))
	service.launchFrame(ctx, readFrame(channel.FrameLaunchRequest, ""))
	if executor.outputCalls != 1 || executor.historyCalls != 1 || executor.messagesCalls != 1 || executor.modelCalls != 1 || executor.launchCalls != 1 {
		t.Fatalf("unconfigured policy blocked a read: %+v", executor)
	}
}

// TestRefusalLogsOperationWithoutToken proves the refusal log names the operation
// and never the token. A log that records a token turns every log reader into a
// credential holder.
func TestRefusalLogsOperationWithoutToken(t *testing.T) {
	service, _, _ := newPolicyService(t, "gd-dev", map[string]string{
		"admin.conf": "token admin-token\nallow-all\n",
	})
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))
	service.outputFrame(context.Background(), readFrame(channel.FrameOutputRequest, "secret-token-value"))
	joined := logs.String()
	if !strings.Contains(joined, protocol.OperationOutputRead) {
		t.Fatalf("refusal log does not name the operation: %s", joined)
	}
	if strings.Contains(joined, "secret-token-value") {
		t.Fatalf("refusal log leaked the token: %s", joined)
	}
}

// TestRefusalDoesNotConsultTheAdapter proves the check runs before the adapter,
// so a refused caller cannot infer adapter presence from a response time or a
// different error code.
func TestRefusalDoesNotConsultTheAdapter(t *testing.T) {
	service, transport, executor := newPolicyService(t, "gd-dev", map[string]string{
		"admin.conf": "token admin-token\nallow-all\n",
	})
	service.historyFrame(context.Background(), readFrame(channel.FrameHistoryRequest, "wrong-token"))
	if executor.historyCalls != 0 {
		t.Fatal("history adapter was consulted before the policy check")
	}
	response := lastFrameOfType(t, transport, channel.FrameHistoryResponse)
	if response.HistoryResult == nil || response.HistoryResult.ErrorCode != policyDeniedCode {
		t.Fatalf("refusal did not use the shared code: %+v", response.HistoryResult)
	}
}

// TestEndpointScopeNarrowsOneTokenOnly proves the endpoints declaration narrows
// the token that carries it without affecting another token.
func TestEndpointScopeNarrowsOneTokenOnly(t *testing.T) {
	service, transport, executor := newPolicyService(t, "gd-dev", map[string]string{
		"elsewhere.conf": "token elsewhere-token\nendpoints other-host\nscopes read_output\n",
		"local.conf":     "token local-token\nscopes read_output\n",
	})
	ctx := context.Background()
	service.outputFrame(ctx, readFrame(channel.FrameOutputRequest, "elsewhere-token"))
	if executor.outputCalls != 0 {
		t.Fatal("a token scoped to another endpoint was accepted")
	}
	if code := refusalCode(t, lastFrameOfType(t, transport, channel.FrameOutputResponse)); code != policyDeniedCode {
		t.Fatalf("refusal code = %q, want %q", code, policyDeniedCode)
	}
	service.outputFrame(ctx, readFrame(channel.FrameOutputRequest, "local-token"))
	if executor.outputCalls != 1 {
		t.Fatalf("adapter calls = %d, want 1", executor.outputCalls)
	}
}

// TestDenyAllRefusesOnlyItsOwnToken proves deny-all is per token. A revoked
// credential must not revoke the whole machine.
func TestDenyAllRefusesOnlyItsOwnToken(t *testing.T) {
	service, transport, executor := newPolicyService(t, "gd-dev", map[string]string{
		"revoked.conf": "token revoked-token\ndeny-all\n",
		"admin.conf":   "token admin-token\nallow-all\n",
	})
	ctx := context.Background()
	service.outputFrame(ctx, readFrame(channel.FrameOutputRequest, "revoked-token"))
	if executor.outputCalls != 0 {
		t.Fatal("a revoked token was accepted")
	}
	if code := refusalCode(t, lastFrameOfType(t, transport, channel.FrameOutputResponse)); code != policyDeniedCode {
		t.Fatalf("refusal code = %q, want %q", code, policyDeniedCode)
	}
	service.outputFrame(ctx, readFrame(channel.FrameOutputRequest, "admin-token"))
	if executor.outputCalls != 1 {
		t.Fatalf("adapter calls = %d, want 1", executor.outputCalls)
	}
}

// TestFollowRefusalEndsTheStream proves a refused follow terminates with exactly
// one end frame. A consumer waiting for a stream must learn the refusal rather
// than wait for chunks that will never arrive.
func TestFollowRefusalEndsTheStream(t *testing.T) {
	service, transport, executor := newPolicyService(t, "gd-dev", map[string]string{
		"admin.conf": "token admin-token\nallow-all\n",
	})
	service.startFollow(context.Background(), readFrame(channel.FrameOutputFollowRequest, "wrong-token"))
	if executor.followCalls != 0 {
		t.Fatal("follow reached the adapter despite a refusal")
	}
	if count := transport.count(channel.FrameOutputEnd); count != 1 {
		t.Fatalf("end frames = %d, want 1", count)
	}
	if count := transport.count(channel.FrameOutputChunk); count != 0 {
		t.Fatalf("chunk frames = %d, want 0", count)
	}
	if code := refusalCode(t, lastFrameOfType(t, transport, channel.FrameOutputEnd)); code != policyDeniedCode {
		t.Fatalf("refusal code = %q, want %q", code, policyDeniedCode)
	}
}

// TestPolicyRefusalIsNotAnAdapterGap proves a refusal is distinguishable from an
// unsupported adapter. Collapsing them would tell the operator to configure an
// adapter when the real problem is a missing permission.
func TestPolicyRefusalIsNotAnAdapterGap(t *testing.T) {
	service, transport, _ := newPolicyService(t, "gd-dev", map[string]string{
		"admin.conf": "token admin-token\nallow-all\n",
	})
	service.launchFrame(context.Background(), readFrame(channel.FrameLaunchRequest, "wrong-token"))
	response := lastFrameOfType(t, transport, channel.FrameLaunchResponse)
	if response.LaunchOptions == nil {
		t.Fatal("launch refusal produced no options document")
	}
	if response.LaunchOptions.ErrorCode == "unsupported" {
		t.Fatal("a policy refusal was reported as an unsupported adapter")
	}
	if response.LaunchOptions.ErrorCode != policyDeniedCode {
		t.Fatalf("refusal code = %q, want %q", response.LaunchOptions.ErrorCode, policyDeniedCode)
	}
}

// TestRefusalErrorIsNotNil proves the helper always receives a reason, so the log
// line can explain the refusal instead of recording an empty message.
func TestRefusalErrorIsNotNil(t *testing.T) {
	empty, err := LoadAccessPolicyDir(t.TempDir())
	if err != nil {
		t.Fatalf("load empty dir: %v", err)
	}
	if err := empty.Policy.Permit("gd-dev", "any", protocol.OperationOutputRead); err != nil {
		t.Fatalf("an empty directory must permit everything: %v", err)
	}
	dir := t.TempDir()
	writePolicyFile(t, dir, "admin.conf", "token admin-token\nallow-all\n")
	restricted, err := LoadAccessPolicyDir(dir)
	if err != nil {
		t.Fatalf("load restricted dir: %v", err)
	}
	refusal := restricted.Policy.Permit("gd-dev", "wrong", protocol.OperationOutputRead)
	if refusal == nil {
		t.Fatal("a restricted policy returned no refusal reason")
	}
	if errors.Is(refusal, context.Canceled) {
		t.Fatal("refusal reason is a cancellation, not a policy decision")
	}
}
