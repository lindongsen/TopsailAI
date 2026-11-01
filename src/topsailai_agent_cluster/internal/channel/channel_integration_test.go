package channel

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/coder/websocket/wsjson"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

func TestOutputSnapshotLargeResponseExceedsDefaultReadLimit(t *testing.T) {
	server := NewServer(nil)
	received := make(chan Frame, 1)
	server.OnFrame = func(_ Peer, frame Frame) { received <- frame }
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	address := websocketAddress(httpServer.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "large-output"}
	if err := client.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	payload := strings.Repeat("x", 64<<10)
	if err := client.SendFrame(ctx, Frame{Type: FrameOutputResponse, ProtocolVersion: ProtocolVersion, RequestID: "large-output-request", OutputResponse: &protocol.OutputSnapshotResponse{Data: payload}}); err != nil {
		t.Fatal(err)
	}
	select {
	case frame := <-received:
		if frame.OutputResponse == nil || len(frame.OutputResponse.Data) != len(payload) {
			t.Fatalf("large output length=%d, want %d", len(frame.OutputResponse.Data), len(payload))
		}
	case <-ctx.Done():
		t.Fatal("large output response was not received")
	}
}

func TestEndpointConnectionsFenceOlderTCPConnection(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	address := websocketAddress(httpServer.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	first := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	if err := first.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	oldGeneration := first.Generation

	second := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-2"}
	if err := second.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	defer second.Close()
	if second.Generation <= oldGeneration {
		t.Fatalf("generation did not advance: old=%d new=%d", oldGeneration, second.Generation)
	}
	if err := server.Fence.Check("endpoint-1", oldGeneration); err != ErrFenced {
		t.Fatalf("old generation check = %v", err)
	}
	if !server.IsOnline("endpoint-1", time.Now()) {
		t.Fatalf("endpoint is not online after second dial")
	}
	if err := server.RequestRefresh(ctx, "endpoint-1", "refresh-1"); err != nil {
		t.Fatalf("refresh through current peer: %v", err)
	}
	var frame Frame
	if err := wsjson.Read(ctx, second.Conn, &frame); err != nil {
		t.Fatal(err)
	}
	if frame.Type != FrameInventoryRefresh || frame.ConnectionGeneration != strconv.FormatInt(second.Generation, 10) {
		t.Fatalf("unexpected refresh frame: %+v", frame)
	}
}

func TestReconnectUsesDurableJournalWithoutSecondAdmission(t *testing.T) {
	root := t.TempDir()
	databasePath := filepath.Join(root, "dedup.sqlite")
	store, err := endpointstorage.Open(context.Background(), databasePath)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "command-1", EndpointID: "endpoint-1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "cap-1", PayloadSchemaVersion: "v1", Payload: []byte(`{"message":"hello"}`)}
	first, inserted, err := store.AdmitJournal(context.Background(), intent, "hash-1", 100)
	if err != nil || !inserted {
		t.Fatalf("first admission: entry=%+v inserted=%v err=%v", first, inserted, err)
	}
	second, inserted, err := store.AdmitJournal(context.Background(), intent, "hash-1", 101)
	if err != nil || inserted || second.CommandID != first.CommandID {
		t.Fatalf("reconnect admission: entry=%+v inserted=%v err=%v", second, inserted, err)
	}
}

func websocketAddress(raw string) string {
	u, _ := url.Parse(raw)
	u.Scheme = "ws"
	return u.String()
}

func TestEndpointClientOfflineAndHeartbeatValidation(t *testing.T) {
	client := &EndpointClient{}
	if client.Ready() {
		t.Fatal("empty client reported ready")
	}
	if err := client.Reconnect(context.Background()); err == nil {
		t.Fatal("reconnect without address succeeded")
	}
	if err := client.SendHeartbeat(context.Background()); err != ErrOffline {
		t.Fatalf("heartbeat=%v", err)
	}
	if err := client.RunHeartbeat(context.Background(), 0); err == nil {
		t.Fatal("zero heartbeat interval accepted")
	}
	if err := client.Close(); err != nil {
		t.Fatal(err)
	}
}
