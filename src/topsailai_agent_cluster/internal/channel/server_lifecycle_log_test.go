package channel

import (
	"bytes"
	"context"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// TestServerLogsEndpointOnlineAndOffline verifies the Server records both ends of
// a connection's life.
//
// The two lines are the only Server-side evidence that an Endpoint became
// reachable and later stopped being reachable. The heartbeat-expiry path already
// logs its own transition, so this test drives the other path: a link that ends
// because its read loop returned. Without these lines an operator reading the
// Server log after an outage sees nothing at all, which is exactly how a
// deliberate restart was mistaken for a network fault.
func TestServerLogsEndpointOnlineAndOffline(t *testing.T) {
	var buffer bytes.Buffer
	server := NewServer(nil)
	server.Logger = slog.New(slog.NewTextHandler(&buffer, &slog.HandlerOptions{Level: slog.LevelInfo}))
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	address := websocketAddress(httpServer.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	if err := client.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(buffer.String(), "endpoint online") {
		t.Fatalf("log after connect = %q, want an endpoint online line", buffer.String())
	}
	if !strings.Contains(buffer.String(), "endpoint_id=endpoint-1") {
		t.Fatalf("log after connect = %q, want the endpoint identity", buffer.String())
	}

	// Closing the client ends the read loop, which is the disconnect path this
	// test covers. The Server removes the peer on its own goroutine, so the log
	// is polled rather than read once: a single read races that cleanup.
	_ = client.Close()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if strings.Contains(buffer.String(), "endpoint offline") {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !strings.Contains(buffer.String(), "endpoint offline") {
		t.Fatalf("log after disconnect = %q, want an endpoint offline line", buffer.String())
	}
}
