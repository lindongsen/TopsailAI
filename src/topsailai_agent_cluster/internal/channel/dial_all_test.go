package channel

import (
	"context"
	"crypto/tls"
	"errors"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/security"
)

// dialableServer starts a Server that accepts Endpoint-initiated connections and
// returns its wss address.
//
// The TLS material is supplied by the caller rather than minted here, because
// every call to newChannelTLSMaterial mints a fresh CA. A client built from a
// different material would fail certificate verification, and the test would
// then report a TLS error instead of the dial behaviour it exists to prove.
func dialableServer(t *testing.T, material channelTLSMaterial, identity string) (string, func()) {
	t.Helper()
	serverTLS, err := security.LoadMTLSConfig(security.MTLSConfig{CAFile: material.ca, CertificateFile: material.serverCert, KeyFile: material.serverKey}, true)
	if err != nil {
		t.Fatalf("load server TLS: %v", err)
	}
	server := NewServer(serverTLS)
	server.Identity = identity
	httpServer := httpServerForChannel(t, server, serverTLS)
	return wssAddress(httpServer.URL), func() {
		httpServer.Close()
		server.Close()
	}
}

// dialClient builds an Endpoint client that trusts the supplied material.
func dialClient(t *testing.T, material channelTLSMaterial) *EndpointClient {
	t.Helper()
	clientCert, err := tls.LoadX509KeyPair(material.clientCert, material.clientKey)
	if err != nil {
		t.Fatalf("load client certificate: %v", err)
	}
	clientTLS := &tls.Config{RootCAs: material.pool(t), ServerName: "agent-cluster-server", Certificates: []tls.Certificate{clientCert}, MinVersion: tls.VersionTLS13}
	return &EndpointClient{EndpointID: "endpoint-1", InstanceID: "instance-1", Hostname: "host-1", TLSConfig: clientTLS}
}

// TestDialAllFallsThroughToTheNextAddress proves the requirement: when the first
// configured Server is unreachable the Endpoint connects to the next one instead
// of staying offline.
func TestDialAllFallsThroughToTheNextAddress(t *testing.T) {
	material := newChannelTLSMaterial(t)
	address, stop := dialableServer(t, material, "server-b")
	defer stop()

	client := dialClient(t, material)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	defer func() { _ = client.Close() }()
	// The first address is a closed port, so the attempt must fail and the walk
	// must continue. A walk that stopped at the first failure would leave the
	// Endpoint offline while a reachable Server was configured.
	if err := client.DialAll(ctx, []string{"wss://127.0.0.1:1/channel", address}); err != nil {
		t.Fatalf("dial all: %v", err)
	}
	if !client.Ready() {
		t.Fatal("endpoint is not ready after falling through to the reachable address")
	}
	if got := client.ServerDatabaseIdentity(); got != "server-b" {
		t.Fatalf("connected server identity = %q, want server-b", got)
	}
}

// TestDialAllPrefersTheFirstReachableAddress proves order is the contract: the
// operator expresses preference by position, so a reachable first address must
// win even when a second one is also reachable.
func TestDialAllPrefersTheFirstReachableAddress(t *testing.T) {
	material := newChannelTLSMaterial(t)
	first, stopFirst := dialableServer(t, material, "server-first")
	defer stopFirst()
	second, stopSecond := dialableServer(t, material, "server-second")
	defer stopSecond()

	client := dialClient(t, material)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	defer func() { _ = client.Close() }()
	if err := client.DialAll(ctx, []string{first, second}); err != nil {
		t.Fatalf("dial all: %v", err)
	}
	if got := client.ServerDatabaseIdentity(); got != "server-first" {
		t.Fatalf("connected server identity = %q, want server-first", got)
	}
}

// TestDialAllReportsEveryFailure proves a caller can tell "no Server is
// reachable" from "this Server refused me": when every address fails, the error
// names each one instead of reporting only the last.
func TestDialAllReportsEveryFailure(t *testing.T) {
	material := newChannelTLSMaterial(t)
	client := dialClient(t, material)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	err := client.DialAll(ctx, []string{"wss://127.0.0.1:1/channel", "wss://127.0.0.1:2/channel"})
	if err == nil {
		t.Fatal("dial all succeeded with no reachable address")
	}
	message := err.Error()
	for _, address := range []string{"127.0.0.1:1", "127.0.0.1:2"} {
		if !strings.Contains(message, address) {
			t.Fatalf("error %q does not name %s, so the operator cannot tell which Servers were tried", message, address)
		}
	}
}

// TestDialAllRejectsAnEmptyList proves an empty configuration fails closed
// instead of silently reporting success.
func TestDialAllRejectsAnEmptyList(t *testing.T) {
	material := newChannelTLSMaterial(t)
	client := dialClient(t, material)
	if err := client.DialAll(context.Background(), nil); err == nil {
		t.Fatal("dial all succeeded with no configured address")
	}
}

// TestDialAllStopsWhenTheCallerCancels proves a cancelled context ends the walk
// before any address is attempted, so a shutdown does not spend one attempt
// timeout per configured Server.
//
// The assertion is structural on purpose. Checking only that the error mentions
// cancellation would pass even without the guard, because a dial made with an
// already-cancelled context fails immediately and reports the same text. The
// distinguishing fact is that no address was tried at all, so the error names
// none of them and wraps context.Canceled directly.
func TestDialAllStopsWhenTheCallerCancels(t *testing.T) {
	material := newChannelTLSMaterial(t)
	client := dialClient(t, material)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	addresses := []string{"wss://127.0.0.1:1/channel", "wss://127.0.0.1:2/channel"}
	err := client.DialAll(ctx, addresses)
	if err == nil {
		t.Fatal("dial all succeeded with a cancelled context")
	}
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error %v does not wrap context.Canceled, so a shutdown is reported as a dial failure", err)
	}
	for _, address := range addresses {
		if strings.Contains(err.Error(), address) {
			t.Fatalf("error %q names %s, so the walk attempted an address after the caller cancelled", err.Error(), address)
		}
	}
}
