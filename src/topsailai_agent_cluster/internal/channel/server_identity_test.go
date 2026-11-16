package channel

import (
	"context"
	"crypto/tls"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/security"
)

// TestServerInitiatedHandshakeCarriesTheServerIdentity proves the identity
// reaches the Endpoint in the direction where the Server dials.
//
// Without it the Endpoint cannot tell a restarted Server from a different one,
// so it would either discard receipts a restarted Server can still apply or
// re-send receipts a different Server can never apply.
func TestServerInitiatedHandshakeCarriesTheServerIdentity(t *testing.T) {
	acceptorTLS, dialTLS, _ := reverseTLSMaterial(t)
	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1", Hostname: "host-1"}
	acceptor := &EndpointAcceptor{EndpointID: "endpoint-1", ServerName: "agent-cluster-server", TLSConfig: acceptorTLS, Client: client}
	httpServer := acceptorServer(t, acceptor, acceptorTLS)
	defer httpServer.Close()
	defer acceptor.Close()

	server := NewServer(nil)
	server.Identity = "server-database-a"
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if _, err := server.DialEndpoint(ctx, "endpoint-1", wssAddress(httpServer.URL), dialTLS); err != nil {
		t.Fatalf("dial endpoint: %v", err)
	}

	if got := client.ServerDatabaseIdentity(); got != "server-database-a" {
		t.Fatalf("endpoint recorded server identity = %q, want server-database-a", got)
	}
}

// TestEndpointInitiatedHandshakeCarriesTheServerIdentity proves the identity
// reaches the Endpoint in the direction where the Endpoint dials.
//
// Both directions must carry it, because the Endpoint learns the generation from
// whichever direction won. Reporting it in only one direction would leave the
// other unable to detect a re-home.
func TestEndpointInitiatedHandshakeCarriesTheServerIdentity(t *testing.T) {
	material := newChannelTLSMaterial(t)
	serverTLS, err := security.LoadMTLSConfig(security.MTLSConfig{CAFile: material.ca, CertificateFile: material.serverCert, KeyFile: material.serverKey}, true)
	if err != nil {
		t.Fatalf("load server TLS: %v", err)
	}
	clientCert, err := tls.LoadX509KeyPair(material.clientCert, material.clientKey)
	if err != nil {
		t.Fatalf("load client certificate: %v", err)
	}
	clientTLS := &tls.Config{RootCAs: material.pool(t), ServerName: "agent-cluster-server", Certificates: []tls.Certificate{clientCert}, MinVersion: tls.VersionTLS13}

	server := NewServer(serverTLS)
	server.Identity = "server-database-b"
	httpServer := httpServerForChannel(t, server, serverTLS)
	defer httpServer.Close()
	defer server.Close()

	client := &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1", Hostname: "host-1", TLSConfig: clientTLS}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := client.Dial(ctx, wssAddress(httpServer.URL)); err != nil {
		t.Fatalf("dial server: %v", err)
	}
	defer func() { _ = client.Close() }()

	if got := client.ServerDatabaseIdentity(); got != "server-database-b" {
		t.Fatalf("endpoint recorded server identity = %q, want server-database-b", got)
	}
}

// TestServerIdentityIsEmptyWithoutAConnection proves the accessor reports no
// identity before a handshake, so a caller cannot mistake "not connected" for
// "connected to a Server with no identity".
func TestServerIdentityIsEmptyWithoutAConnection(t *testing.T) {
	client := &EndpointClient{EndpointID: "endpoint-1"}
	if got := client.ServerDatabaseIdentity(); got != "" {
		t.Fatalf("identity without a connection = %q, want empty", got)
	}
}
