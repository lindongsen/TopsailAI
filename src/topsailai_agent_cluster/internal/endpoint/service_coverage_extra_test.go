package endpoint

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

type coverageExecutor struct {
	receipt protocol.ExecutionReceipt
	err     error
	output  protocol.OutputSnapshotResponse
	outErr  error
}

func (e coverageExecutor) Execute(context.Context, protocol.ImmutableIntent, string) (protocol.ExecutionReceipt, error) {
	return e.receipt, e.err
}
func (e coverageExecutor) ReadOutput(context.Context, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return e.output, e.outErr
}

type readyCoverageChannel struct {
	*serviceChannel
	ready   bool
	sendErr error
}

func (c *readyCoverageChannel) Ready() bool { return c.ready }
func (c *readyCoverageChannel) SendFrame(_ context.Context, frame channel.Frame) error {
	if c.sendErr != nil {
		return c.sendErr
	}
	return c.serviceChannel.SendFrame(context.Background(), frame)
}

func openCoverageStore(t *testing.T) *endpointstorage.Store {
	t.Helper()
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.sqlite")
	if err != nil {
		t.Fatal(err)
	}
	return store
}

func TestServiceOutputFrameReportsUnsupportedAndProviderErrors(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	transport := newServiceChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: coverageExecutor{}})
	if err != nil {
		t.Fatal(err)
	}
	service.outputFrame(context.Background(), channel.Frame{Type: channel.FrameOutputRequest, RequestID: "unsupported"})
	service.outputFrame(context.Background(), channel.Frame{Type: channel.FrameOutputRequest, RequestID: "nil-request", OutputRequest: &protocol.OutputSnapshotRequest{}})
	if transport.count(channel.FrameOutputResponse) != 2 {
		t.Fatalf("output responses=%d", transport.count(channel.FrameOutputResponse))
	}
	provider := coverageExecutor{output: protocol.OutputSnapshotResponse{}, outErr: errors.New("provider unavailable")}
	service.executor = provider
	service.outputFrame(context.Background(), channel.Frame{Type: channel.FrameOutputRequest, RequestID: "provider", OutputRequest: &protocol.OutputSnapshotRequest{ResourceID: "r", Generation: "g"}})
	transport.mu.Lock()
	last := transport.frames[len(transport.frames)-1]
	transport.mu.Unlock()
	if last.OutputResponse == nil || last.OutputResponse.ErrorCode != "provider_error" {
		t.Fatalf("provider error response=%#v", last.OutputResponse)
	}
}

func TestServiceExecuteFrameRejectsMissingInputsAndPublishesReceipt(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	transport := newServiceChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: coverageExecutor{receipt: protocol.ExecutionReceipt{CommandID: "cmd"}}})
	if err != nil {
		t.Fatal(err)
	}
	service.executeFrame(context.Background(), channel.Frame{Type: channel.FrameCommand})
	service.executeFrame(context.Background(), channel.Frame{Type: channel.FrameCommand, Intent: &protocol.ImmutableIntent{CommandID: "bad", Operation: "message.send"}})
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd", EndpointID: "e1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{}`), Target: &protocol.CommandTarget{ResourceID: "r", Generation: "g"}}
	service.executeFrame(context.Background(), channel.Frame{Type: channel.FrameCommand, FrameID: "cmd", RequestID: "req", Intent: &intent})
	if transport.count(channel.FrameReceipt) != 3 {
		t.Fatalf("receipt count=%d", transport.count(channel.FrameReceipt))
	}
	transport.mu.Lock()
	frame := transport.frames[len(transport.frames)-1]
	transport.mu.Unlock()
	if frame.Receipt == nil || frame.Receipt.CommandID != "cmd" {
		t.Fatalf("receipt=%#v", frame.Receipt)
	}
	payload, ok := frame.Payload.(json.RawMessage)
	if !ok {
		t.Fatalf("payload type=%T", frame.Payload)
	}
	var decoded protocol.ExecutionReceipt
	if err := json.Unmarshal(payload, &decoded); err != nil || decoded.CommandID != "cmd" {
		t.Fatalf("payload=%s err=%v", payload, err)
	}
}

func TestNewServiceDefaultsAndRejectsInvalidDependencies(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	if _, err := NewService(ServiceDeps{}); err == nil {
		t.Fatal("missing dependencies accepted")
	}
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: newServiceChannel(), Storage: store, CollectionInterval: -1, Heartbeater: nil})
	if err != nil {
		t.Fatal(err)
	}
	if service.interval <= 0 {
		t.Fatalf("default interval=%s", service.interval)
	}
	if err := service.Run(nil); err == nil {
		t.Fatal("nil context accepted")
	}
}

func TestServiceWaitForChannelReadyHonorsContext(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	transport := &readyCoverageChannel{serviceChannel: newServiceChannel(), ready: false}
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Millisecond)
	defer cancel()
	if service.waitForChannelReady(ctx) {
		t.Fatal("unready channel reported ready")
	}
	transport.ready = true
	if !service.waitForChannelReady(context.Background()) {
		t.Fatal("ready channel reported unready")
	}
}

var _ adapter.Adapter = (*coverageAdapter)(nil)

type coverageAdapter struct {
	executeCalls int
	lastIntent   protocol.ImmutableIntent
}

func (*coverageAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{Capabilities: protocol.CapabilityDescriptor{Revision: "rev-1", Capabilities: []protocol.Capability{{Name: "agent.start", Version: "v1"}}}}, nil
}
func (*coverageAdapter) Discover(context.Context, adapter.DiscoverRequest) (adapter.DiscoverResult, error) {
	return adapter.DiscoverResult{}, nil
}
func (*coverageAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{}, nil
}
func (a *coverageAdapter) Execute(_ context.Context, request adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	a.executeCalls++
	a.lastIntent = request.Intent
	return adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{CommandID: request.Intent.CommandID, Outcome: "accepted"}}, nil
}
func (*coverageAdapter) ReadOutput(context.Context, adapter.OutputRequest) (adapter.OutputResult, error) {
	return adapter.OutputResult{}, nil
}
func (*coverageAdapter) QueryCommand(context.Context, adapter.CommandQuery) (adapter.CommandResult, error) {
	return adapter.CommandResult{}, nil
}
func (*coverageAdapter) Watch(context.Context) (<-chan adapter.Event, error) { return nil, nil }
func (*coverageAdapter) Close() error                                        { return nil }

type coverageHeartbeater struct {
	err    error
	called chan struct{}
}

func (h coverageHeartbeater) RunHeartbeat(_ context.Context, _ time.Duration) error {
	close(h.called)
	return h.err
}

type failingReadChannel struct {
	*serviceChannel
	reads int
}

func (f *failingReadChannel) Read(context.Context) (channel.Frame, error) {
	f.reads++
	return channel.Frame{}, errors.New("read failed")
}

func TestServiceHeartbeatAndChannelFailurePaths(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	heartbeat := coverageHeartbeater{err: errors.New("heartbeat failed"), called: make(chan struct{})}
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: newServiceChannel(), Storage: store, Heartbeater: heartbeat, HeartbeatInterval: time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	service.wg.Add(1)
	go service.heartbeatLoop(context.Background())
	select {
	case <-heartbeat.called:
	case <-time.After(time.Second):
		t.Fatal("heartbeat was not started")
	}
	service.wg.Wait()

	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))
	failed := &failingReadChannel{serviceChannel: newServiceChannel()}
	service.channel = failed
	service.wg.Add(1)
	service.channelLoop(context.Background())
	if failed.reads != 1 {
		t.Fatalf("channel reads=%d, want one read before non-reconnecting exit", failed.reads)
	}
	if !strings.Contains(logs.String(), "read failed") {
		t.Fatalf("channel failure log=%q, want read error", logs.String())
	}
}

func TestServiceRecoversAcceptedAndResendsRecordedReceipts(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	ctx := context.Background()
	accepted := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "accepted", EndpointID: "e", Operation: "op", OperationVersion: "v1", CapabilityRevision: "c", PayloadSchemaVersion: "v1", Payload: []byte(`{}`)}
	if _, _, err := store.AdmitJournal(ctx, accepted, "accepted-hash", 1); err != nil {
		t.Fatal(err)
	}
	receipt := protocol.ExecutionReceipt{CommandID: "recorded", RequestHash: "recorded-hash", Outcome: "accepted"}
	recorded := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "recorded", EndpointID: "e", Operation: "op", OperationVersion: "v1", CapabilityRevision: "c", PayloadSchemaVersion: "v1", Payload: []byte(`{}`)}
	if _, _, err := store.AdmitJournal(ctx, recorded, "recorded-hash", 2); err != nil {
		t.Fatal(err)
	}
	if err := store.RecordReceipt(ctx, recorded.CommandID, receipt, 3); err != nil {
		t.Fatal(err)
	}
	transport := newServiceChannel()
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store, Executor: coverageExecutor{receipt: protocol.ExecutionReceipt{CommandID: "accepted"}}})
	if err != nil {
		t.Fatal(err)
	}
	service.wg.Add(1)
	done := make(chan struct{})
	go func() { service.resendRecordedReceipts(ctx); close(done) }()
	<-done
	service.wg.Wait()
	if transport.count(channel.FrameReceipt) != 1 {
		t.Fatalf("resent receipts=%d", transport.count(channel.FrameReceipt))
	}
	service.wg.Add(1)
	done = make(chan struct{})
	go func() { service.recoverAcceptedCommands(ctx); close(done) }()
	<-done
	service.wg.Wait()
	if transport.count(channel.FrameReceipt) < 2 {
		t.Fatalf("recovered receipts=%d", transport.count(channel.FrameReceipt))
	}
}
