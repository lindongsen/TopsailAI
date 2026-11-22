package channel

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// TestOnConnectedReportsAdoptedLink verifies the adoption callback fires exactly
// once for a link that becomes active, and carries the generation the Server
// assigned.
//
// The callback is the only evidence that an Endpoint connected, because a
// successful dial writes no log of its own. A test that only asserted the
// connection worked would pass even if the callback were never invoked, so the
// assertion here is on the callback itself.
func TestOnConnectedReportsAdoptedLink(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	address := websocketAddress(httpServer.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	type adoption struct {
		address    string
		generation int64
		initiator  string
	}
	adoptions := make([]adoption, 0, 1)
	client := &EndpointClient{
		EndpointID: "endpoint-1",
		InstanceID: "instance-1",
		OnConnected: func(address string, generation int64, initiator string) {
			adoptions = append(adoptions, adoption{address: address, generation: generation, initiator: initiator})
		},
	}
	if err := client.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = client.Close() }()

	if len(adoptions) != 1 {
		t.Fatalf("adoptions = %d, want 1", len(adoptions))
	}
	got := adoptions[0]
	if got.address != address {
		t.Fatalf("address = %q, want %q", got.address, address)
	}
	if got.generation != client.Generation || got.generation <= 0 {
		t.Fatalf("generation = %d, want the adopted %d", got.generation, client.Generation)
	}
	if got.initiator != InitiatorEndpoint {
		t.Fatalf("initiator = %q, want %q", got.initiator, InitiatorEndpoint)
	}
}

// TestOnConnectedSilentForSupersededLink verifies a rejected link reports
// nothing. A superseded connection never becomes active, so reporting it would
// tell an operator that a link was adopted when the Endpoint discarded it.
func TestOnConnectedSilentForSupersededLink(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	address := websocketAddress(httpServer.URL)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	if err := client.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = client.Close() }()
	active := client.Generation

	// A second real connection stands in for the link the other side dialed, so
	// the supersede path closes a real socket instead of a nil handle.
	other := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-2"}
	if err := other.Dial(ctx, address); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = other.Close() }()

	reported := 0
	client.OnConnected = func(string, int64, string) { reported++ }
	if client.Attach(other.Conn, active-1, InitiatorServer, "") {
		t.Fatalf("older generation replaced the active link")
	}
	if reported != 0 {
		t.Fatalf("reported = %d, want 0 for a superseded link", reported)
	}
}
