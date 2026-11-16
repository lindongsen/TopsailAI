//go:build integration

package integration_test

import (
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// tcpProxy forwards raw TCP bytes to one target and can sever every live
// connection on demand.
//
// A proxy is needed because the generation an Endpoint holds only advances on a
// real reconnect to the same Server process. Stopping and restarting the Server
// would reset its in-memory fence to 1, which is the opposite of the
// precondition this test needs: the Endpoint must hold a generation higher than
// the one a different Server will hand out.
//
// The proxy forwards bytes rather than terminating TLS, so the handshake still
// happens with the real Server and the certificate under test is the Server's
// own.
type tcpProxy struct {
	listener net.Listener
	target   string
	mu       sync.Mutex
	conns    []net.Conn
	closed   bool
}

// startTCPProxy listens on a free loopback port and forwards to target, which is
// a bare host:port with no URL scheme.
func startTCPProxy(t *testing.T, target string) *tcpProxy {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen for proxy: %v", err)
	}
	proxy := &tcpProxy{listener: listener, target: target}
	go proxy.serve()
	t.Cleanup(proxy.close)
	return proxy
}

// address reports the channel address an Endpoint should dial to reach the
// proxied Server.
func (p *tcpProxy) address() string {
	return "wss://" + p.listener.Addr().String()
}

// serve accepts connections and forwards each one to the target.
func (p *tcpProxy) serve() {
	for {
		client, err := p.listener.Accept()
		if err != nil {
			return
		}
		upstream, err := net.Dial("tcp", p.target)
		if err != nil {
			_ = client.Close()
			continue
		}
		p.track(client, upstream)
		go func() {
			_, _ = io.Copy(upstream, client)
			_ = upstream.Close()
		}()
		go func() {
			_, _ = io.Copy(client, upstream)
			_ = client.Close()
		}()
	}
}

// track records the connections that sever must close.
func (p *tcpProxy) track(conns ...net.Conn) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.conns = append(p.conns, conns...)
}

// sever closes every live connection so the Endpoint observes a transport
// failure while the Server process keeps running and keeps its fence.
func (p *tcpProxy) sever() {
	p.mu.Lock()
	conns := p.conns
	p.conns = nil
	p.mu.Unlock()
	for _, conn := range conns {
		_ = conn.Close()
	}
}

// close stops accepting and severs what is left. It is idempotent so the
// cleanup and an explicit call cannot double-close the listener.
func (p *tcpProxy) close() {
	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		return
	}
	p.closed = true
	p.mu.Unlock()
	_ = p.listener.Close()
	p.sever()
}

// waitForLogLine polls a log file until it contains needle.
//
// The precondition of the generation test is a real reconnect, and a reconnect
// is only observable in the Endpoint's own log. Asserting on the log is what
// turns "the Endpoint is still online" into "the Endpoint reconnected and
// therefore holds a higher generation".
func waitForLogLine(t *testing.T, path, needle string, limit time.Duration) {
	t.Helper()
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		content, err := os.ReadFile(path)
		if err == nil && strings.Contains(string(content), needle) {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	content, _ := os.ReadFile(path)
	t.Fatalf("endpoint log never contained %q within %s; log tail:\n%s", needle, limit, logTail(string(content)))
}

// logTail returns the last 2000 bytes of a log so a failure shows the recent
// context instead of the whole file.
func logTail(content string) string {
	const limit = 2000
	if len(content) <= limit {
		return content
	}
	return content[len(content)-limit:]
}

// TestEndpointAdoptsALowerGenerationFromADifferentServer proves the Unit 1 fix
// is what makes a re-home possible.
//
// The scenario is deliberately built so the Endpoint holds a generation higher
// than the one the second Server will hand out. Two fresh Servers both start
// their in-memory fence at 1, so a naive test that moves between two fresh
// Servers compares 1 against 1 and passes even when the fix is absent. That is
// why the Endpoint is first forced through one real reconnect to the first
// Server: the fence then reads 2, and adopting the second Server's 1 is only
// possible if the Endpoint released the dead connection.
//
// The assertion is the absence of the rejection symptom, not the final online
// state. The reconnect loop retries, and a retry against the second Server
// receives generation 2, which equals the 2 the Endpoint holds, so Attach
// accepts it and the Endpoint eventually becomes online even when the fix is
// missing. The functional outcome therefore cannot discriminate. What does
// discriminate is that without the fix the Endpoint rejects the first attempt
// with "channel connection was superseded by a newer link", and with the fix
// that rejection never happens.
func TestEndpointAdoptsALowerGenerationFromADifferentServer(t *testing.T) {
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	build(t, filepath.Join(root, "server"), "./src/main/agent-cluster-server")
	build(t, filepath.Join(root, "endpoint"), "./src/main/agent-cluster-endpoint")
	mock := filepath.Join(root, "mock")
	buildProviderModule(t, mock, filepath.Join(moduleRoot(t), "providers", "mock"))

	firstAPI, firstChannel, _ := rehomeServer(t, root, "server-a", certs)
	secondAPI, secondChannel, _ := rehomeServer(t, root, "server-b", certs)

	proxy := startTCPProxy(t, strings.TrimPrefix(firstChannel, "wss://"))

	logPath := filepath.Join(root, "endpoint.log")
	logFile, err := os.Create(logPath)
	if err != nil {
		t.Fatalf("create endpoint log: %v", err)
	}
	defer func() { _ = logFile.Close() }()

	rehomeEndpoint(t, root, certs, []string{proxy.address(), secondChannel}, mock, logFile)

	// Precondition one: the Endpoint prefers the first address, so the first
	// Server's fence reads 1.
	waitEndpointOnlineOn(t, firstAPI, 30*time.Second)

	// Precondition two: force one real reconnect to the same Server process so
	// the fence reads 2. Severing the transport is the only way to do this
	// without resetting the fence, which is why the proxy exists.
	proxy.sever()
	waitForLogLine(t, logPath, "endpoint channel reconnected", 30*time.Second)
	waitEndpointOnlineOn(t, firstAPI, 30*time.Second)

	// Now remove the first Server's path entirely. The Endpoint must adopt the
	// second Server's generation 1, which is lower than the 2 it holds.
	proxy.close()
	waitEndpointOnlineOn(t, secondAPI, 60*time.Second)

	// A connection that cannot serve inventory would look online and be useless,
	// so the re-homed Endpoint must also publish a report.
	waitInventory(t, secondAPI+"/api/v1/endpoints/endpoint-1/session-state", "secret", 30*time.Second)

	// The discriminating assertion. Without the detach fix the Endpoint still
	// holds the dead connection and its generation 2, so the first attempt
	// against the second Server is rejected as superseded. With the fix the dead
	// connection is released, so no attempt is ever rejected for that reason.
	content, err := os.ReadFile(logPath)
	if err != nil {
		t.Fatalf("read endpoint log: %v", err)
	}
	if strings.Contains(string(content), "superseded by a newer link") {
		t.Fatalf("the Endpoint rejected a link from the second Server as superseded, so it still held the dead connection's generation; log tail:\n%s", logTail(string(content)))
	}
}
