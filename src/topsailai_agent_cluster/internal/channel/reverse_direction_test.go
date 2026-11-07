package channel

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"

	"github.com/coder/websocket"
	"github.com/coder/websocket/wsjson"
	"topsailai_agent_cluster/internal/security"
)

// reverseTLSMaterial builds the two TLS configurations a reverse-direction
// handshake needs: the Endpoint presents its own certificate and requires a
// client certificate, while the dialing Server presents the Server certificate
// and verifies the Endpoint certificate by name.
func reverseTLSMaterial(t *testing.T) (acceptorTLS, dialTLS *tls.Config, material channelTLSMaterial) {
	t.Helper()
	material = newChannelTLSMaterial(t)
	acceptorTLS, err := security.LoadMTLSConfig(security.MTLSConfig{CAFile: material.ca, CertificateFile: material.clientCert, KeyFile: material.clientKey}, true)
	if err != nil {
		t.Fatalf("load acceptor TLS: %v", err)
	}
	dialTLS, err = security.LoadMTLSConfig(security.MTLSConfig{CAFile: material.ca, CertificateFile: material.serverCert, KeyFile: material.serverKey, ServerName: "endpoint-1"}, false)
	if err != nil {
		t.Fatalf("load dial TLS: %v", err)
	}
	return acceptorTLS, dialTLS, material
}

// acceptorServer starts an Endpoint acceptor behind a TLS test server.
func acceptorServer(t *testing.T, acceptor *EndpointAcceptor, acceptorTLS *tls.Config) *httptest.Server {
	t.Helper()
	httpServer := httptest.NewUnstartedServer(http.HandlerFunc(acceptor.Handler))
	httpServer.TLS = acceptorTLS
	httpServer.StartTLS()
	return httpServer
}

func wssAddress(raw string) string {
	u, _ := url.Parse(raw)
	u.Scheme = "wss"
	return u.String()
}

// TestServerDialEndpointAttachesPeer verifies the reverse direction end to end:
// the Server dials, the Endpoint accepts, and the Server records the Endpoint
// identity it needs to match a later disconnect.
func TestServerDialEndpointAttachesPeer(t *testing.T) {
	acceptorTLS, dialTLS, _ := reverseTLSMaterial(t)
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1", Hostname: "host-1"}
	acceptor := &EndpointAcceptor{EndpointID: "endpoint-1", ServerName: "agent-cluster-server", TLSConfig: acceptorTLS, Client: client}
	httpServer := acceptorServer(t, acceptor, acceptorTLS)
	defer httpServer.Close()
	defer acceptor.Close()

	server := NewServer(nil)
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	peer, err := server.DialEndpoint(ctx, "endpoint-1", wssAddress(httpServer.URL), dialTLS)
	if err != nil {
		t.Fatalf("dial endpoint: %v", err)
	}
	if peer.EndpointID != "endpoint-1" {
		t.Fatalf("peer endpoint = %q", peer.EndpointID)
	}
	// The acknowledgement must carry the Endpoint identity. An empty instance ID
	// would make a later disconnect impossible to match to its stored row.
	if peer.InstanceID != "instance-1" {
		t.Fatalf("peer instance = %q, want instance-1", peer.InstanceID)
	}
	if peer.Hostname != "host-1" {
		t.Fatalf("peer hostname = %q, want host-1", peer.Hostname)
	}
	if peer.Initiator != InitiatorServer {
		t.Fatalf("peer initiator = %q, want %q", peer.Initiator, InitiatorServer)
	}
	// The Endpoint adopts the generation the Server allocated, so both sides
	// agree on authority.
	if client.Generation != peer.ConnectionGeneration {
		t.Fatalf("endpoint generation = %d, server generation = %d", client.Generation, peer.ConnectionGeneration)
	}
	if !client.Ready() {
		t.Fatal("endpoint channel is not ready after attach")
	}
	if client.Initiator != InitiatorServer {
		t.Fatalf("endpoint initiator = %q, want %q", client.Initiator, InitiatorServer)
	}
}

// TestAcceptorRejectsEndpointInitiatedHello verifies the acceptor refuses a
// connection that dialed the wrong side instead of silently accepting it.
func TestAcceptorRejectsEndpointInitiatedHello(t *testing.T) {
	acceptorTLS, dialTLS, _ := reverseTLSMaterial(t)
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	acceptor := &EndpointAcceptor{EndpointID: "endpoint-1", ServerName: "agent-cluster-server", TLSConfig: acceptorTLS, Client: client}
	httpServer := acceptorServer(t, acceptor, acceptorTLS)
	defer httpServer.Close()
	defer acceptor.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wssAddress(httpServer.URL), &websocket.DialOptions{HTTPClient: &http.Client{Transport: &http.Transport{TLSClientConfig: dialTLS}}})
	if err != nil {
		t.Fatalf("dial acceptor: %v", err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "done")
	hello := Frame{Type: FrameHello, ProtocolVersion: ProtocolVersion, EndpointID: "endpoint-1", InstanceID: "instance-1", RequestID: "request-1", Initiator: InitiatorEndpoint}
	if err := wsjson.Write(ctx, conn, hello); err != nil {
		t.Fatalf("write hello: %v", err)
	}
	var rejection Frame
	if err := wsjson.Read(ctx, conn, &rejection); err != nil {
		t.Fatalf("read rejection: %v", err)
	}
	if rejection.Type != FrameHelloRejected || rejection.Reason != "wrong_initiator" {
		t.Fatalf("unexpected rejection: %+v", rejection)
	}
	if client.Ready() {
		t.Fatal("endpoint attached a connection it should have rejected")
	}
}

// TestAcceptorRejectsWrongEndpoint verifies the acceptor refuses a hello that
// targets another Endpoint identity.
func TestAcceptorRejectsWrongEndpoint(t *testing.T) {
	acceptorTLS, dialTLS, _ := reverseTLSMaterial(t)
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	acceptor := &EndpointAcceptor{EndpointID: "endpoint-1", ServerName: "agent-cluster-server", TLSConfig: acceptorTLS, Client: client}
	httpServer := acceptorServer(t, acceptor, acceptorTLS)
	defer httpServer.Close()
	defer acceptor.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wssAddress(httpServer.URL), &websocket.DialOptions{HTTPClient: &http.Client{Transport: &http.Transport{TLSClientConfig: dialTLS}}})
	if err != nil {
		t.Fatalf("dial acceptor: %v", err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "done")
	hello := Frame{Type: FrameHello, ProtocolVersion: ProtocolVersion, EndpointID: "endpoint-2", ConnectionGeneration: "1", Initiator: InitiatorServer}
	if err := wsjson.Write(ctx, conn, hello); err != nil {
		t.Fatalf("write hello: %v", err)
	}
	var rejection Frame
	if err := wsjson.Read(ctx, conn, &rejection); err != nil {
		t.Fatalf("read rejection: %v", err)
	}
	if rejection.Type != FrameHelloRejected || rejection.Reason != "wrong_endpoint" {
		t.Fatalf("unexpected rejection: %+v", rejection)
	}
}

// TestAcceptorRejectsInvalidGeneration verifies the acceptor refuses a
// hello_confirm frame without a usable connection generation. The generation is
// no longer proposed in the hello: the Server assigns it when it installs the
// connection and reports it in hello_confirm, so that frame is what the Endpoint
// must validate before attaching.
func TestAcceptorRejectsInvalidGeneration(t *testing.T) {
	acceptorTLS, dialTLS, _ := reverseTLSMaterial(t)
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1"}
	acceptor := &EndpointAcceptor{EndpointID: "endpoint-1", ServerName: "agent-cluster-server", TLSConfig: acceptorTLS, Client: client}
	httpServer := acceptorServer(t, acceptor, acceptorTLS)
	defer httpServer.Close()
	defer acceptor.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, wssAddress(httpServer.URL), &websocket.DialOptions{HTTPClient: &http.Client{Transport: &http.Transport{TLSClientConfig: dialTLS}}})
	if err != nil {
		t.Fatalf("dial acceptor: %v", err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "done")
	hello := Frame{Type: FrameHello, ProtocolVersion: ProtocolVersion, EndpointID: "endpoint-1", InstanceID: "instance-1", Initiator: InitiatorServer}
	if err := wsjson.Write(ctx, conn, hello); err != nil {
		t.Fatalf("write hello: %v", err)
	}
	var ack Frame
	if err := wsjson.Read(ctx, conn, &ack); err != nil {
		t.Fatalf("read ack: %v", err)
	}
	if ack.Type != FrameHelloAck {
		t.Fatalf("unexpected ack: %+v", ack)
	}
	// The Endpoint must not attach before a valid confirm arrives.
	if client.Ready() {
		t.Fatal("endpoint attached before hello_confirm")
	}
	confirm := Frame{Type: FrameHelloConfirm, ProtocolVersion: ProtocolVersion, EndpointID: "endpoint-1", ConnectionGeneration: "0"}
	if err := wsjson.Write(ctx, conn, confirm); err != nil {
		t.Fatalf("write confirm: %v", err)
	}
	var frame Frame
	if err := wsjson.Read(ctx, conn, &frame); err == nil && frame.Type == FrameHelloAck {
		t.Fatalf("acceptor accepted an invalid generation: %+v", frame)
	}
	if client.Ready() {
		t.Fatal("endpoint attached a connection with an invalid generation")
	}
}

// TestHandlerRejectsServerInitiatedHello verifies the forward-direction handler
// refuses a hello that claims the Server dialed, so the two directions cannot be
// confused with each other.
func TestHandlerRejectsServerInitiatedHello(t *testing.T) {
	server := NewServer(nil)
	httpServer := httptest.NewServer(http.HandlerFunc(server.Handler))
	defer httpServer.Close()
	defer server.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, websocketAddress(httpServer.URL), nil)
	if err != nil {
		t.Fatalf("dial handler: %v", err)
	}
	defer conn.Close(websocket.StatusNormalClosure, "done")
	hello := Frame{Type: FrameHello, ProtocolVersion: ProtocolVersion, EndpointID: "endpoint-1", RequestID: "request-1", Initiator: InitiatorServer}
	if err := wsjson.Write(ctx, conn, hello); err != nil {
		t.Fatalf("write hello: %v", err)
	}
	var rejection Frame
	if err := wsjson.Read(ctx, conn, &rejection); err != nil {
		t.Fatalf("read rejection: %v", err)
	}
	if rejection.Type != FrameHelloRejected || rejection.Reason != "wrong_initiator" {
		t.Fatalf("unexpected rejection: %+v", rejection)
	}
}

// TestInstallPeerAssignsGenerationAtInstall verifies the generation is assigned
// under the same lock that installs the peer, so install order and generation
// order are identical and the newest connection always wins. Assigning the
// generation before the handshake instead would let a slower handshake overwrite
// a newer connection, which is the opposite of latest-wins.
func TestInstallPeerAssignsGenerationAtInstall(t *testing.T) {
	server := NewServer(nil)
	if got := server.Fence.Current("endpoint-1"); got != 0 {
		t.Fatalf("fresh fence = %d, want 0", got)
	}
	first := server.installPeer("endpoint-1", "instance-1", "host-1", InitiatorEndpoint, nil)
	if first.ConnectionGeneration != 1 {
		t.Fatalf("first generation = %d, want 1", first.ConnectionGeneration)
	}
	second := server.installPeer("endpoint-1", "instance-1", "host-1", InitiatorServer, nil)
	if second.ConnectionGeneration != 2 {
		t.Fatalf("second generation = %d, want 2", second.ConnectionGeneration)
	}
	// The newest install is authoritative, so the older generation is fenced.
	if err := server.Fence.Check("endpoint-1", first.ConnectionGeneration); !errors.Is(err, ErrFenced) {
		t.Fatalf("older generation check = %v, want ErrFenced", err)
	}
	if err := server.Fence.Check("endpoint-1", second.ConnectionGeneration); err != nil {
		t.Fatalf("newest generation rejected: %v", err)
	}
}

// TestDialEndpointFailureDoesNotFence verifies an unreachable Endpoint leaves the
// fence untouched, so a later successful dial still gets the next generation.
func TestDialEndpointFailureDoesNotFence(t *testing.T) {
	server := NewServer(nil)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if _, err := server.DialEndpoint(ctx, "endpoint-1", "ws://127.0.0.1:1/channel", nil); err == nil {
		t.Fatal("dial to an unreachable address succeeded")
	}
	if got := server.Fence.Current("endpoint-1"); got != 0 {
		t.Fatalf("failed dial advanced the fence to %d", got)
	}
}

// TestDialEndpointRejectsInvalidAddress verifies the dialer validates its input
// before opening a connection.
func TestDialEndpointRejectsInvalidAddress(t *testing.T) {
	server := NewServer(nil)
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	cases := []struct{ endpointID, address string }{
		{"", "ws://127.0.0.1:1/channel"},
		{"endpoint-1", ""},
		{"endpoint-1", "http://127.0.0.1:1/channel"},
	}
	for _, item := range cases {
		if _, err := server.DialEndpoint(ctx, item.endpointID, item.address, nil); err == nil {
			t.Fatalf("dial accepted endpoint=%q address=%q", item.endpointID, item.address)
		}
	}
}

// TestReconnectWaitsForServerDial verifies the Endpoint does not dial in the
// reverse direction, because the network path only works the other way round.
func TestReconnectWaitsForServerDial(t *testing.T) {
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1", Initiator: InitiatorServer, Address: "ws://127.0.0.1:1/channel"}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := client.Reconnect(ctx); !errors.Is(err, ErrAwaitingServerDial) {
		t.Fatalf("reconnect error = %v, want ErrAwaitingServerDial", err)
	}
}

// TestValidateServerIdentity verifies the Endpoint confirms the dialer is the
// Server it expects, rather than trusting the transport alone.
func TestValidateServerIdentity(t *testing.T) {
	material := newChannelTLSMaterial(t)
	serverCert, err := tls.LoadX509KeyPair(material.serverCert, material.serverKey)
	if err != nil {
		t.Fatalf("load server certificate: %v", err)
	}
	leaf, err := x509.ParseCertificate(serverCert.Certificate[0])
	if err != nil {
		t.Fatalf("parse server certificate: %v", err)
	}
	if err := security.ValidateServerIdentity(leaf, "agent-cluster-server"); err != nil {
		t.Fatalf("matching identity rejected: %v", err)
	}
	if err := security.ValidateServerIdentity(leaf, "other-server"); err == nil {
		t.Fatal("mismatched identity accepted")
	}
	if err := security.ValidateServerIdentity(nil, "agent-cluster-server"); err == nil {
		t.Fatal("missing certificate accepted")
	}
	if err := security.ValidateServerIdentity(leaf, ""); err == nil {
		t.Fatal("empty expected name accepted")
	}
}
