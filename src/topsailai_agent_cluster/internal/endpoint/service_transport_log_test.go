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
)

// protocolIntent builds a minimal immutable intent for journal tests.
func protocolIntent(commandID string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{HashVersion: "v1", CommandID: commandID, EndpointID: "e", Operation: "op", OperationVersion: "v1", CapabilityRevision: "c", PayloadSchemaVersion: "v1", Payload: []byte(`{}`)}
}

// protocolReceipt builds a minimal receipt for journal tests.
func protocolReceipt(commandID string) protocol.ExecutionReceipt {
	return protocol.ExecutionReceipt{CommandID: commandID, RequestHash: commandID + "-hash", Outcome: "accepted"}
}

// newLogCaptureService builds a Service whose logger writes into the returned
// buffer, so tests can assert the severity of transport diagnostics.
func newLogCaptureService(t *testing.T, transport ChannelClient) (*Service, *bytes.Buffer) {
	t.Helper()
	store := openCoverageStore(t)
	t.Cleanup(func() { _ = store.Close() })
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))
	return service, &logs
}

// TestServiceLogTransportErrorClassifiesOffline verifies that an offline
// channel is reported at WARN while a genuine failure stays at ERROR.
func TestServiceLogTransportErrorClassifiesOffline(t *testing.T) {
	service, logs := newLogCaptureService(t, newServiceChannel())

	service.logTransportError("publish inventory", channel.ErrOffline)
	output := logs.String()
	if !strings.Contains(output, "level=WARN") {
		t.Fatalf("offline transport log=%q, want WARN level", output)
	}
	if !strings.Contains(output, "publish inventory deferred until the channel is ready") {
		t.Fatalf("offline transport log=%q, want deferred message", output)
	}
	if strings.Contains(output, "level=ERROR") {
		t.Fatalf("offline transport log=%q, want no ERROR level", output)
	}

	logs.Reset()
	service.logTransportError("publish inventory", errors.New("marshal failed"))
	output = logs.String()
	if !strings.Contains(output, "level=ERROR") {
		t.Fatalf("real failure log=%q, want ERROR level", output)
	}
	if strings.Contains(output, "deferred") {
		t.Fatalf("real failure log=%q, want no deferred wording", output)
	}
}

// TestServiceCollectionLoopWaitsForChannelReady verifies that the first
// collection is gated on the connection, so a restart does not collect and
// publish before the channel exists.
func TestServiceCollectionLoopWaitsForChannelReady(t *testing.T) {
	collector := &serviceCollector{}
	transport := &readyCoverageChannel{serviceChannel: newServiceChannel(), ready: false}
	store := openCoverageStore(t)
	defer store.Close()
	service, err := NewService(ServiceDeps{Collector: collector, Channel: transport, Storage: store, CollectionDelay: time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	service.wg.Add(1)
	service.collectionLoop(ctx)
	service.wg.Wait()

	collector.mu.Lock()
	calls := collector.calls
	collector.mu.Unlock()
	if calls != 0 {
		t.Fatalf("collection calls=%d, want none before the channel is ready", calls)
	}
	if !strings.Contains(logs.String(), "inventory collection stopped before channel ready") {
		t.Fatalf("gate log=%q, want stopped-before-ready message", logs.String())
	}
	if transport.count(channel.FrameInventory) != 0 {
		t.Fatalf("inventory frames=%d, want none", transport.count(channel.FrameInventory))
	}
}

// TestServiceCollectionLoopDefersOfflinePublish verifies that a publish on an
// offline channel is logged at WARN instead of ERROR.
func TestServiceCollectionLoopDefersOfflinePublish(t *testing.T) {
	collector := &serviceCollector{}
	transport := &readyCoverageChannel{serviceChannel: newServiceChannel(), ready: true, sendErr: channel.ErrOffline}
	store := openCoverageStore(t)
	defer store.Close()
	service, err := NewService(ServiceDeps{Collector: collector, Channel: transport, Storage: store, CollectionDelay: 5 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))

	ctx, cancel := context.WithCancel(context.Background())
	service.wg.Add(1)
	go service.collectionLoop(ctx)
	deadline := time.Now().Add(2 * time.Second)
	for {
		collector.mu.Lock()
		calls := collector.calls
		collector.mu.Unlock()
		if calls > 0 || time.Now().After(deadline) {
			break
		}
		time.Sleep(time.Millisecond)
	}
	cancel()
	service.wg.Wait()

	collector.mu.Lock()
	calls := collector.calls
	collector.mu.Unlock()
	if calls == 0 {
		t.Fatal("collection never ran on a ready channel")
	}
	output := logs.String()
	if !strings.Contains(output, "publish inventory deferred until the channel is ready") {
		t.Fatalf("offline publish log=%q, want deferred message", output)
	}
	if strings.Contains(output, "level=ERROR") {
		t.Fatalf("offline publish log=%q, want no ERROR level", output)
	}
}

// TestServiceResendRecordedReceiptsWaitsForChannelReady verifies that recorded
// receipts are not resent before the connection exists.
func TestServiceResendRecordedReceiptsWaitsForChannelReady(t *testing.T) {
	store := openCoverageStore(t)
	defer store.Close()
	ctx := context.Background()
	intent := protocolIntent("recorded")
	if _, _, err := store.AdmitJournal(ctx, intent, "recorded-hash", 1); err != nil {
		t.Fatal(err)
	}
	receipt := protocolReceipt("recorded")
	if err := store.RecordReceipt(ctx, intent.CommandID, receipt, 2); err != nil {
		t.Fatal(err)
	}
	transport := &readyCoverageChannel{serviceChannel: newServiceChannel(), ready: false}
	service, err := NewService(ServiceDeps{Collector: &serviceCollector{}, Channel: transport, Storage: store})
	if err != nil {
		t.Fatal(err)
	}
	var logs bytes.Buffer
	service.logger = slog.New(slog.NewTextHandler(&logs, nil))

	gateCtx, cancel := context.WithTimeout(ctx, 20*time.Millisecond)
	defer cancel()
	service.wg.Add(1)
	service.resendRecordedReceipts(gateCtx)
	service.wg.Wait()

	if transport.count(channel.FrameReceipt) != 0 {
		t.Fatalf("resent receipts=%d, want none before the channel is ready", transport.count(channel.FrameReceipt))
	}
	if !strings.Contains(logs.String(), "recorded receipt resend stopped before channel ready") {
		t.Fatalf("gate log=%q, want stopped-before-ready message", logs.String())
	}

	transport.ready = true
	service.wg.Add(1)
	service.resendRecordedReceipts(ctx)
	service.wg.Wait()
	if transport.count(channel.FrameReceipt) != 1 {
		t.Fatalf("resent receipts=%d, want one after the channel is ready", transport.count(channel.FrameReceipt))
	}
}
