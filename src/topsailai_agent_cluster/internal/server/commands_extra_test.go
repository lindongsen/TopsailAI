package server

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

type recordingTransport struct {
	err      error
	envelope protocol.TransportEnvelope
}

func (t *recordingTransport) Send(_ context.Context, envelope protocol.TransportEnvelope) error {
	t.envelope = envelope
	return t.err
}

func commandTestStore(t *testing.T) *serverstorage.Store {
	t.Helper()
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "instance-1", DisplayName: "test", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "cap-1"}, 1); err != nil {
		store.Close()
		t.Fatal(err)
	}
	return store
}

func commandTestIntent() protocol.ImmutableIntent {
	return protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-extra", EndpointID: "endpoint-1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "cap-1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"hello"}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
}

func TestCommandServiceAdmitValidationAndConflict(t *testing.T) {
	ctx := context.Background()
	service := &CommandService{}
	if _, _, err := service.Admit(ctx, commandTestIntent(), "hash"); err == nil {
		t.Fatal("nil store was accepted")
	}
	store := commandTestStore(t)
	defer store.Close()
	service.Store = store
	intent := commandTestIntent()
	if _, _, err := service.Admit(ctx, intent, "hash-1"); err != nil {
		t.Fatal(err)
	}
	if _, fresh, err := service.Admit(ctx, intent, "hash-1"); err != nil || fresh {
		t.Fatalf("idempotent admission fresh=%v err=%v", fresh, err)
	}
	if _, _, err := service.Admit(ctx, intent, "hash-2"); err == nil {
		t.Fatal("conflicting intent was accepted")
	}
}

func TestCommandServiceDispatchBranches(t *testing.T) {
	ctx := context.Background()
	store := commandTestStore(t)
	defer store.Close()
	intent := commandTestIntent()
	if err := store.AdmitCommand(ctx, intent, "hash", 1); err != nil {
		t.Fatal(err)
	}
	service := &CommandService{Store: store, DispatchDelay: time.Hour}
	cancelled, cancel := context.WithCancel(ctx)
	cancel()
	if err := service.Dispatch(cancelled, intent, "hash", "request"); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancelled dispatch err=%v", err)
	}
	service.DispatchDelay = 0
	if err := service.Dispatch(ctx, intent, "hash", "request"); err == nil {
		t.Fatal("nil transport was accepted")
	}
	intent2 := intent
	intent2.CommandID = "cmd-transport-error"
	if err := store.AdmitCommand(ctx, intent2, "hash-2", 2); err != nil {
		t.Fatal(err)
	}
	transport := &recordingTransport{err: errors.New("send failed")}
	service.Transport = transport
	if err := service.Dispatch(ctx, intent2, "hash-2", "request-2"); err == nil {
		t.Fatal("transport error was swallowed")
	}
	if transport.envelope.Intent.CommandID != intent2.CommandID {
		t.Fatalf("wrong envelope=%#v", transport.envelope)
	}
}

func TestCommandServiceNowUsesConfiguredAndDefaultClock(t *testing.T) {
	configured := time.Unix(123, 0)
	service := &CommandService{Now: func() time.Time { return configured }}
	if got := service.now(); !got.Equal(configured) {
		t.Fatalf("configured time=%v", got)
	}
	service.Now = nil
	before := time.Now()
	got := service.now()
	if got.Before(before) || got.After(time.Now()) {
		t.Fatalf("default time=%v", got)
	}
}

func TestChannelTransportRejectsUnavailableChannel(t *testing.T) {
	if err := (ChannelTransport{}).Send(context.Background(), protocol.TransportEnvelope{}); err == nil || err.Error() != "channel server is unavailable" {
		t.Fatalf("unavailable channel error=%v", err)
	}
}
