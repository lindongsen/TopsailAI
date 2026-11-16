package harness

import (
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

// ChannelProxy forwards raw TCP bytes to one channel listener and can sever
// every live connection on demand.
//
// A proxy is needed because the generation an Endpoint holds only advances on a
// real reconnect to the same Server process. Stopping and restarting the Server
// resets its in-memory fence to 1, which is the opposite of the precondition a
// re-home scenario needs: the Endpoint must hold a generation higher than the
// one a different Server will hand out.
//
// The proxy forwards bytes rather than terminating TLS, so the handshake still
// happens with the real Server and the certificate under test is the Server's
// own.
type ChannelProxy struct {
	listener net.Listener
	target   string
	mu       sync.Mutex
	conns    []net.Conn
	closed   bool
}

// StartChannelProxy listens on a free loopback port and forwards to target,
// which is a bare host:port with no URL scheme.
func StartChannelProxy(t testing.TB, target string) *ChannelProxy {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen for channel proxy: %v", err)
	}
	proxy := &ChannelProxy{listener: listener, target: target}
	go proxy.serve()
	t.Cleanup(proxy.Close)
	return proxy
}

// Address reports the channel address an Endpoint should dial to reach the
// proxied Server.
func (p *ChannelProxy) Address() string { return "wss://" + p.listener.Addr().String() }

// serve accepts connections and forwards each one to the target.
func (p *ChannelProxy) serve() {
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

// track records the connections that Sever must close.
func (p *ChannelProxy) track(conns ...net.Conn) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.conns = append(p.conns, conns...)
}

// Sever closes every live connection so the Endpoint observes a transport
// failure while the Server process keeps running and keeps its fence.
func (p *ChannelProxy) Sever() {
	p.mu.Lock()
	conns := p.conns
	p.conns = nil
	p.mu.Unlock()
	for _, conn := range conns {
		_ = conn.Close()
	}
}

// Close stops accepting and severs what is left. It is idempotent so the
// cleanup and an explicit call cannot double-close the listener.
func (p *ChannelProxy) Close() {
	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		return
	}
	p.closed = true
	p.mu.Unlock()
	_ = p.listener.Close()
	p.Sever()
}

// SeverChannelE forces one real reconnect to the primary Server.
//
// The reconnect is what advances the primary Server's in-memory fence, and it is
// the only way to establish the precondition a re-home scenario needs: the
// Endpoint must hold a generation higher than the one a different Server will
// hand out. A scenario that cannot sever the channel must fail rather than
// proceed, because a re-home between two fresh Servers compares 1 against 1 and
// passes even when the connection-layer fix is absent.
func (c *Cluster) SeverChannelE() error {
	if c.ChannelProxy == nil {
		return fmt.Errorf("cluster has no channel proxy, so the primary Server's fence cannot be advanced")
	}
	c.ChannelProxy.Sever()
	return nil
}

// AdvanceFenceE forces one real reconnect to the primary Server and proves the
// primary Server's fence advanced.
//
// A re-home between two fresh Servers compares generation 1 against generation 1,
// so the second Server is accepted even when the connection-layer fix is absent.
// The scenario would then be green for the wrong reason. Severing the transport
// makes the Endpoint reconnect to the same Server process, whose fence then reads
// 2, so adopting a different Server's 1 is only possible if the Endpoint released
// the dead connection.
//
// The precondition is observed rather than assumed: the Endpoint's own
// "endpoint channel reconnected" line is the only evidence that a reconnect
// happened. A scenario that cannot reach that state fails with an explicit
// "cannot discriminate" message instead of reporting success.
func (c *Cluster) AdvanceFenceE(limit time.Duration) error {
	if c.ChannelProxy == nil {
		return fmt.Errorf("cluster has no channel proxy, so the primary Server's fence cannot be advanced")
	}
	if c.EndpointLogPath == "" {
		return fmt.Errorf("cluster was not started with an Endpoint log file, so the fence advance cannot be observed")
	}
	before, err := c.EndpointLog()
	if err != nil {
		return err
	}
	reconnectsBefore := strings.Count(before, "endpoint channel reconnected")
	c.ChannelProxy.Sever()
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		content, readErr := c.EndpointLog()
		if readErr == nil && strings.Count(content, "endpoint channel reconnected") > reconnectsBefore {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	content, _ := c.EndpointLog()
	return fmt.Errorf("this run cannot discriminate: the Endpoint never reconnected to the primary Server within %s, so its fence did not advance; log tail:\n%s", limit, logTailOf(content))
}

// AssertNoSupersededRejectionE fails when the Endpoint rejected a link as
// superseded.
//
// This is the discriminating assertion for the connection-layer fix. Without the
// fix the Endpoint still holds the dead connection and its generation, so its
// first attempt against a Server with a lower fence is rejected with
// "channel connection was superseded by a newer link". With the fix the dead
// connection is released, so no attempt is ever rejected for that reason.
//
// The final online state cannot discriminate, because the reconnect loop retries
// and a retry receives a generation the Endpoint already holds. Only the absence
// of the rejection symptom distinguishes the two builds.
func (c *Cluster) AssertNoSupersededRejectionE() error {
	content, err := c.EndpointLog()
	if err != nil {
		return err
	}
	if strings.Contains(content, "superseded by a newer link") {
		return fmt.Errorf("the Endpoint rejected a link as superseded, so it still held the dead connection's generation; log tail:\n%s", logTailOf(content))
	}
	return nil
}

// StartSecondaryServerE starts the second independent Server.
//
// The second Server owns its own SQLite file and its own API and channel ports,
// which is the whole point of a re-home: the Endpoint moves between two
// independent Servers, not between two replicas of one. Reusing the primary
// database would make the scenario pass for the wrong reason, because the "new"
// Server would already know the previous Server's commands.
//
// The optional seed runs before the process opens the database, because a
// scenario that must observe a rejection needs a row the Server has not written
// itself. A seed that ran after startup would race the Server's own writes.
func (c *Cluster) StartSecondaryServerE(seed func(path string) error) error {
	if c.SecondaryServerDB == "" {
		return fmt.Errorf("cluster was not started with a second Server")
	}
	if seed != nil {
		if err := seed(c.SecondaryServerDB); err != nil {
			return fmt.Errorf("seed secondary server database: %w", err)
		}
	}
	env := []string{
		"AGENT_CLUSTER_SERVER_API_LISTEN_ADDR=127.0.0.1:" + c.SecondaryAPI,
		"AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR=127.0.0.1:" + c.SecondaryChannel,
		"AGENT_CLUSTER_DATABASE_PATH=" + c.SecondaryServerDB,
		"AGENT_CLUSTER_SERVER_AUTH_TOKEN=secret",
		"AGENT_CLUSTER_TLS_CA_FILE=" + c.Certs.CA,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE=" + c.Certs.ServerCert,
		"AGENT_CLUSTER_TLS_KEY_FILE=" + c.Certs.ServerKey,
	}
	server, err := StartProcessE(c.ServerPath, env)
	if err != nil {
		return fmt.Errorf("start secondary server: %w", err)
	}
	c.SecondaryServer = server
	if err := WaitHTTPE(c.SecondaryURL("/healthz"), "", 200, serverReadinessWait); err != nil {
		return fmt.Errorf("wait for secondary server readiness: %w", err)
	}
	return nil
}

// StopServerE stops the primary Server by exact process identity.
//
// A re-home scenario stops the primary Server on purpose, and that stop is the
// event under test. The Endpoint must then move to the next configured address
// on its own, without being restarted, because a restarted Endpoint would never
// have held the dead Server's generation and would prove nothing.
func (c *Cluster) StopServerE() error {
	if err := StopProcessE(c.Server); err != nil {
		return fmt.Errorf("stop primary server: %w", err)
	}
	return nil
}

// RestartServerE restarts the primary Server with its original configuration.
//
// The database survives, so the Server keeps its durable identity, while the
// in-memory fence starts again at 1. That combination is exactly the case a
// restarted Server presents to an Endpoint that still holds a higher generation.
func (c *Cluster) RestartServerE() error {
	if err := StopProcessE(c.Server); err != nil {
		return fmt.Errorf("stop primary server: %w", err)
	}
	server, err := StartProcessE(c.ServerPath, c.ServerEnv)
	if err != nil {
		return fmt.Errorf("start primary server: %w", err)
	}
	c.Server = server
	if err := WaitHTTPE(c.URL("/healthz"), "", 200, serverReadinessWait); err != nil {
		return fmt.Errorf("wait for primary server readiness: %w", err)
	}
	return nil
}

// SecondaryURL returns a secondary Server API URL for the cluster.
func (c *Cluster) SecondaryURL(path string) string {
	return "http://127.0.0.1:" + c.SecondaryAPI + path
}

// WaitSecondaryEndpointOnlineE waits until the second Server reports the
// Endpoint online.
//
// The second Server is the only authority for whether the re-homed Endpoint
// reached it, so the assertion reads that Server's own endpoint list rather than
// inferring connectivity from the primary Server's state.
func (c *Cluster) WaitSecondaryEndpointOnlineE(limit time.Duration) error {
	if c.SecondaryAPI == "" {
		return fmt.Errorf("cluster was not started with a second Server")
	}
	deadline := time.Now().Add(limit)
	var last string
	for time.Now().Before(deadline) {
		state, err := c.endpointConnectionStateE(c.SecondaryURL("/api/v1/endpoints"))
		if err == nil {
			last = state
			if state == "online" {
				return nil
			}
		} else {
			last = err.Error()
		}
		time.Sleep(100 * time.Millisecond)
	}
	return fmt.Errorf("the second Server never reported endpoint-1 online within %s; last observation: %s", limit, last)
}

// WaitSecondaryInventoryE waits until the second Server has accepted an
// inventory report from the re-homed Endpoint.
//
// A connection that cannot serve inventory would look online and be useless, so
// a re-home scenario must prove the Endpoint publishes through the new Server
// rather than only that it connected.
func (c *Cluster) WaitSecondaryInventoryE(limit time.Duration) error {
	if c.SecondaryAPI == "" {
		return fmt.Errorf("cluster was not started with a second Server")
	}
	return WaitInventoryForE(c.SecondaryURL("/api/v1/endpoints/endpoint-1/session-state"), "secret", "", limit)
}

// endpointConnectionStateE reads endpoint-1's connection state from one Server.
func (c *Cluster) endpointConnectionStateE(url string) (string, error) {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return "", fmt.Errorf("create endpoint list request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("read endpoint list: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("read endpoint list body: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("endpoint list status=%d body=%s", resp.StatusCode, body)
	}
	var envelope struct {
		Data []struct {
			EndpointID      string `json:"endpoint_id"`
			ConnectionState string `json:"connection_state"`
		} `json:"data"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		return "", fmt.Errorf("decode endpoint list: %w", err)
	}
	for _, item := range envelope.Data {
		if item.EndpointID == "endpoint-1" {
			return item.ConnectionState, nil
		}
	}
	return "", fmt.Errorf("endpoint-1 is absent from the endpoint list")
}

// EndpointLog reads the Endpoint's own log file.
//
// The log is the only place a reconnect or a superseded rejection is observable.
// Asserting on the log is what turns "the Endpoint is still online" into "the
// Endpoint reconnected and therefore holds a higher generation", and what turns
// "the re-home worked" into "the re-home did not happen through a rejected
// link".
func (c *Cluster) EndpointLog() (string, error) {
	if c.EndpointLogPath == "" {
		return "", fmt.Errorf("cluster was not started with an Endpoint log file")
	}
	content, err := os.ReadFile(c.EndpointLogPath)
	if err != nil {
		return "", fmt.Errorf("read endpoint log: %w", err)
	}
	return string(content), nil
}

// WaitEndpointLogE polls the Endpoint log until it contains needle.
func (c *Cluster) WaitEndpointLogE(needle string, limit time.Duration) error {
	if c.EndpointLogPath == "" {
		return fmt.Errorf("cluster was not started with an Endpoint log file")
	}
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		content, err := os.ReadFile(c.EndpointLogPath)
		if err == nil && strings.Contains(string(content), needle) {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	content, _ := os.ReadFile(c.EndpointLogPath)
	return fmt.Errorf("endpoint log never contained %q within %s; log tail:\n%s", needle, limit, logTailOf(string(content)))
}

// logTailOf returns the last 2000 bytes of a log so a failure shows the recent
// context instead of the whole file.
func logTailOf(content string) string {
	const limit = 2000
	if len(content) <= limit {
		return content
	}
	return content[len(content)-limit:]
}
