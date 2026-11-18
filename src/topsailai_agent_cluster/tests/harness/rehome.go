package harness

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	_ "modernc.org/sqlite"
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
	// frozen makes the proxy a blackhole: it keeps reading from both sides so
	// neither sender blocks, and discards every byte instead of forwarding it.
	// The connections stay open, so the peer observes a Server that accepts
	// bytes and never answers rather than a Server that went away.
	frozen bool
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
		go p.pump(upstream, client)
		go p.pump(client, upstream)
	}
}

// pump copies bytes from src to dst until either side closes.
//
// It is a hand-written loop rather than io.Copy because Freeze must be able to
// stop forwarding on a connection that is already open. io.Copy would keep
// moving bytes for as long as the peer sends them, so a frozen proxy would still
// deliver the Endpoint's frames to the Server and the Server's replies back, and
// the Endpoint would never observe an unresponsive Server. Reading and
// discarding is what makes the freeze a blackhole: the sender never blocks, and
// nothing arrives.
func (p *ChannelProxy) pump(dst, src net.Conn) {
	buffer := make([]byte, 32*1024)
	for {
		n, err := src.Read(buffer)
		if n > 0 {
			p.mu.Lock()
			frozen := p.frozen
			p.mu.Unlock()
			if !frozen {
				if _, writeErr := dst.Write(buffer[:n]); writeErr != nil {
					break
				}
			}
		}
		if err != nil {
			break
		}
	}
	_ = dst.Close()
}

// track records the connections that Sever must close.
func (p *ChannelProxy) track(conns ...net.Conn) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.conns = append(p.conns, conns...)
}

// Freeze turns the proxy into a blackhole without closing anything.
//
// This is the only way to reproduce a Server that is still running, still
// accepting bytes at the TCP layer, and no longer answering at the application
// layer. Severing the transport is a different failure: the Endpoint's read
// returns an error immediately, so a build with no liveness detection still
// reconnects and the scenario would pass for the wrong reason. A frozen proxy
// keeps every socket open and discards every byte, so the only way the Endpoint
// can notice is by deciding that the Server stopped answering.
func (p *ChannelProxy) Freeze() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.frozen = true
}

// Thaw resumes forwarding on the connections that are still open.
//
// It exists so a scenario can prove that a frozen Server is not permanently
// abandoned: the Endpoint must be able to come back to it once it answers again.
func (p *ChannelProxy) Thaw() {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.frozen = false
}

// Frozen reports whether the proxy is currently discarding bytes.
func (p *ChannelProxy) Frozen() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.frozen
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
	// The second Server writes its own log, because the only evidence that it
	// received a receipt is its own rejection line. Without that log a scenario
	// could only assert that a settlement row exists, which is reachable by two
	// independent paths and therefore cannot attribute which one ran.
	c.SecondaryLogPath = filepath.Join(c.Root, "server-secondary.log")
	env := []string{
		"AGENT_CLUSTER_SERVER_API_LISTEN_ADDR=127.0.0.1:" + c.SecondaryAPI,
		"AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR=127.0.0.1:" + c.SecondaryChannel,
		"AGENT_CLUSTER_DATABASE_PATH=" + c.SecondaryServerDB,
		"AGENT_CLUSTER_SERVER_AUTH_TOKEN=secret",
		"AGENT_CLUSTER_SERVER_AUTH_MODE=bearer",
		"AGENT_CLUSTER_TLS_CA_FILE=" + c.Certs.CA,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE=" + c.Certs.ServerCert,
		"AGENT_CLUSTER_TLS_KEY_FILE=" + c.Certs.ServerKey,
		"AGENT_CLUSTER_LOG_OUTPUT=file",
		"AGENT_CLUSTER_LOG_PATH=" + c.SecondaryLogPath,
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

// SecondaryRequestWithEndpointTokenE performs one authenticated request against
// the secondary Server.
//
// A re-home scenario must read the Server that actually holds the state after the
// move. Reading the primary Server would report the pre-move world, so a scenario
// that resolved a target or polled a command through the primary would fail with
// "inventory has no sessions" and look like a defect in the re-home instead of a
// scenario reading the wrong Server.
func (c *Cluster) SecondaryRequestWithEndpointTokenE(method, path string, payload any, endpointToken string) (int, []byte, error) {
	if c.SecondaryAPI == "" {
		return 0, nil, fmt.Errorf("cluster was not started with a second Server")
	}
	return c.requestAtE("http://127.0.0.1:"+c.SecondaryAPI, method, path, payload, endpointToken)
}

// WaitEndpointOnlineE waits until the primary Server reports the Endpoint online.
//
// The primary Server is the only authority for whether the Endpoint reached it,
// so a deployment-shape scenario reads that Server's own endpoint list instead of
// inferring connectivity from a successful process start. A process that started
// and never connected would otherwise look like a passing scenario.
func (c *Cluster) WaitEndpointOnlineE(limit time.Duration) error {
	deadline := time.Now().Add(limit)
	var last string
	for time.Now().Before(deadline) {
		state, err := c.endpointConnectionStateE(c.URL("/api/v1/endpoints"))
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
	return fmt.Errorf("the primary Server never reported endpoint-1 online within %s; last observation: %s", limit, last)
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

// EndpointLogOffset reports the current length of the Endpoint log.
//
// A scenario that waits for a log line after a restart must search only the bytes
// written after that restart. The log is append-only for the life of the process
// tree, so a needle such as "endpoint channel reconnected" may already be present
// from an earlier reconnect, and a plain substring search would pass before the
// event under test happened.
func (c *Cluster) EndpointLogOffset() (int64, error) {
	if c.EndpointLogPath == "" {
		return 0, fmt.Errorf("cluster was not started with an Endpoint log file")
	}
	info, err := os.Stat(c.EndpointLogPath)
	if err != nil {
		return 0, fmt.Errorf("stat endpoint log: %w", err)
	}
	return info.Size(), nil
}

// WaitEndpointLogAfterE polls the Endpoint log for needle written after offset.
//
// It is the only honest way to assert on an event that can happen more than once
// in one process lifetime. Searching the whole file would accept an occurrence
// that predates the action under test.
func (c *Cluster) WaitEndpointLogAfterE(offset int64, needle string, limit time.Duration) error {
	if c.EndpointLogPath == "" {
		return fmt.Errorf("cluster was not started with an Endpoint log file")
	}
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		content, err := os.ReadFile(c.EndpointLogPath)
		if err == nil && int64(len(content)) > offset && strings.Contains(string(content[offset:]), needle) {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	content, _ := os.ReadFile(c.EndpointLogPath)
	tail := ""
	if int64(len(content)) > offset {
		tail = logTailOf(string(content[offset:]))
	}
	return fmt.Errorf("endpoint log never contained %q after offset %d within %s; log tail:\n%s", needle, offset, limit, tail)
}

// SettledReceipts reads the Endpoint's own settlement decisions.
//
// The assertion target is the Endpoint database, not the log. A log line proves
// that a decision was attempted; a row proves that it was persisted, which is
// what decides whether the receipt is re-sent after the next reconnect. Asserting
// only on the log would pass for a build that logs the decision and then fails to
// write it.
//
// The driver is the same one the Endpoint uses, so the schema under test is the
// real one rather than a copy. It is opened with the production busy timeout
// because modernc.org/sqlite ignores a mode=ro query parameter and always opens
// read-write; the helper therefore only reads, and the timeout keeps a concurrent
// Endpoint write from failing the read with SQLITE_BUSY.
func (c *Cluster) SettledReceipts() (map[string]string, error) {
	if c.EndpointDB == "" {
		return nil, fmt.Errorf("cluster has no Endpoint database path")
	}
	db, err := sql.Open("sqlite", c.EndpointDB+"?_pragma=busy_timeout(5000)")
	if err != nil {
		return nil, fmt.Errorf("open endpoint database: %w", err)
	}
	defer func() { _ = db.Close() }()
	rows, err := db.QueryContext(context.Background(), `SELECT command_id, reason FROM receipt_settlement`)
	if err != nil {
		return nil, fmt.Errorf("read receipt settlement: %w", err)
	}
	defer func() { _ = rows.Close() }()
	settled := map[string]string{}
	for rows.Next() {
		var commandID string
		// reason is NULL for an acknowledgement, because an acknowledgement
		// carries no rejection reason. Scanning it into a plain string would fail
		// the whole read with "converting NULL to string is unsupported", so the
		// absence is mapped to the empty string here and a caller that asserts on
		// a rejection reason still sees exactly that reason.
		var reason sql.NullString
		if err := rows.Scan(&commandID, &reason); err != nil {
			return nil, fmt.Errorf("scan receipt settlement: %w", err)
		}
		settled[commandID] = reason.String
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate receipt settlement: %w", err)
	}
	return settled, nil
}

// ReceiptSettlement is one persisted settlement decision.
//
// The origin and the reason are separate fields because they answer different
// questions. The origin says which terminal outcome ended the resend obligation,
// and the reason is only meaningful for a rejection: an acknowledgement carries
// no rejection reason, so its reason is empty.
type ReceiptSettlement struct {
	Origin string
	Reason string
}

// Settlements reads every persisted settlement decision with its origin.
//
// A scenario that asserts only on the reason cannot tell an acknowledgement from
// a rejection, because an acknowledgement stores no reason at all. Reading the
// origin is what makes "the receipt was settled because the Server stored it"
// distinguishable from "the receipt was settled because the Server refused it".
func (c *Cluster) Settlements() (map[string]ReceiptSettlement, error) {
	if c.EndpointDB == "" {
		return nil, fmt.Errorf("cluster has no Endpoint database path")
	}
	db, err := sql.Open("sqlite", c.EndpointDB+"?_pragma=busy_timeout(5000)")
	if err != nil {
		return nil, fmt.Errorf("open endpoint database: %w", err)
	}
	defer func() { _ = db.Close() }()
	rows, err := db.QueryContext(context.Background(), `SELECT command_id, settled_by, reason FROM receipt_settlement`)
	if err != nil {
		return nil, fmt.Errorf("read receipt settlement: %w", err)
	}
	defer func() { _ = rows.Close() }()
	settlements := map[string]ReceiptSettlement{}
	for rows.Next() {
		var commandID, origin string
		var reason sql.NullString
		if err := rows.Scan(&commandID, &origin, &reason); err != nil {
			return nil, fmt.Errorf("scan receipt settlement: %w", err)
		}
		settlements[commandID] = ReceiptSettlement{Origin: origin, Reason: reason.String}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate receipt settlement: %w", err)
	}
	return settlements, nil
}

// WaitReceiptSettledOriginE waits until the Endpoint has persisted a settlement
// for one command and returns its origin and reason.
//
// It exists so a scenario can assert which terminal outcome settled the receipt.
// Asserting only that a row exists would pass for either outcome, and the two
// outcomes are the whole point: an acknowledgement proves the Server stored the
// receipt, while a rejection proves it never will.
func (c *Cluster) WaitReceiptSettledOriginE(commandID string, limit time.Duration) (ReceiptSettlement, error) {
	deadline := time.Now().Add(limit)
	var lastErr error
	for time.Now().Before(deadline) {
		settlements, err := c.Settlements()
		if err != nil {
			lastErr = err
		} else if settlement, ok := settlements[commandID]; ok {
			return settlement, nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	if lastErr != nil {
		return ReceiptSettlement{}, fmt.Errorf("no settlement recorded for %q within %s: %w", commandID, limit, lastErr)
	}
	return ReceiptSettlement{}, fmt.Errorf("no settlement recorded for %q within %s", commandID, limit)
}

// WaitReceiptSettledE waits until the Endpoint has persisted a settlement for one
// command and returns the recorded reason.
//
// The wait exists because settlement happens on the Endpoint's own channel loop
// after a rejection arrives, so a scenario that read the table immediately would
// race the decision it is asserting.
func (c *Cluster) WaitReceiptSettledE(commandID string, limit time.Duration) (string, error) {
	deadline := time.Now().Add(limit)
	var lastErr error
	for time.Now().Before(deadline) {
		settled, err := c.SettledReceipts()
		if err != nil {
			lastErr = err
		} else if reason, ok := settled[commandID]; ok {
			return reason, nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	if lastErr != nil {
		return "", fmt.Errorf("no settlement recorded for %q within %s: %w", commandID, limit, lastErr)
	}
	return "", fmt.Errorf("no settlement recorded for %q within %s", commandID, limit)
}

// AssertReceiptNotSettledE fails when the Endpoint has settled one command.
//
// It waits for the whole budget before failing, because the absence of a row is
// only meaningful once the decision had time to happen. A check that returned
// immediately would pass for a build that settles a moment later.
func (c *Cluster) AssertReceiptNotSettledE(commandID string, limit time.Duration) error {
	deadline := time.Now().Add(limit)
	var lastErr error
	for time.Now().Before(deadline) {
		settled, err := c.SettledReceipts()
		if err != nil {
			lastErr = err
		} else if reason, ok := settled[commandID]; ok {
			return fmt.Errorf("command %q was settled with reason %q, but this reason must never settle", commandID, reason)
		}
		time.Sleep(100 * time.Millisecond)
	}
	if lastErr != nil {
		return fmt.Errorf("could not read receipt settlement for %q: %w", commandID, lastErr)
	}
	return nil
}

// RewriteStoredReceiptE rewrites the receipt the Server already holds for one
// command, while the Server is stopped.
//
// It exists to produce the two states a re-home cannot produce on its own. The
// Endpoint always submits revision 1, so a stale revision and a same-revision
// conflict can only be created by changing what the Server already stored:
//
//   - a higher stored revision makes the Endpoint's revision 1 stale;
//   - the same revision with different bytes makes it a conflict.
//
// The Server must be stopped first, because writing to a live SQLite file from a
// second process would contend with the Server's own writes and could be lost.
func (c *Cluster) RewriteStoredReceiptE(commandID string, revision int64, outcome string) error {
	if c.ServerDB == "" {
		return fmt.Errorf("cluster has no Server database path")
	}
	db, err := sql.Open("sqlite", c.ServerDB)
	if err != nil {
		return fmt.Errorf("open server database: %w", err)
	}
	defer func() { _ = db.Close() }()
	var existing []byte
	err = db.QueryRowContext(context.Background(), `SELECT receipt_json FROM commands WHERE command_id=?`, commandID).Scan(&existing)
	if err == sql.ErrNoRows {
		return fmt.Errorf("command %q is not stored on the Server, so its receipt cannot be rewritten", commandID)
	}
	if err != nil {
		return fmt.Errorf("read stored receipt for %q: %w", commandID, err)
	}
	var receipt map[string]any
	if err := json.Unmarshal(existing, &receipt); err != nil {
		return fmt.Errorf("decode stored receipt for %q: %w", commandID, err)
	}
	receipt["command_revision"] = revision
	if outcome != "" {
		receipt["outcome"] = outcome
	}
	rewritten, err := json.Marshal(receipt)
	if err != nil {
		return fmt.Errorf("encode rewritten receipt for %q: %w", commandID, err)
	}
	if _, err := db.ExecContext(context.Background(), `UPDATE commands SET receipt_json=? WHERE command_id=?`, rewritten, commandID); err != nil {
		return fmt.Errorf("rewrite stored receipt for %q: %w", commandID, err)
	}
	return nil
}

// StoredReceiptRevisionE reads the revision the Server currently holds for one
// command.
//
// A scenario uses it to prove the rewrite actually landed before it asserts on the
// Endpoint's reaction, so a failed rewrite cannot be mistaken for a correct
// rejection.
func (c *Cluster) StoredReceiptRevisionE(commandID string) (int64, error) {
	if c.ServerDB == "" {
		return 0, fmt.Errorf("cluster has no Server database path")
	}
	db, err := sql.Open("sqlite", c.ServerDB+"?_pragma=busy_timeout(5000)")
	if err != nil {
		return 0, fmt.Errorf("open server database: %w", err)
	}
	defer func() { _ = db.Close() }()
	var existing []byte
	err = db.QueryRowContext(context.Background(), `SELECT receipt_json FROM commands WHERE command_id=?`, commandID).Scan(&existing)
	if err == sql.ErrNoRows {
		return 0, fmt.Errorf("command %q is not stored on the Server", commandID)
	}
	if err != nil {
		return 0, fmt.Errorf("read stored receipt for %q: %w", commandID, err)
	}
	var receipt struct {
		CommandRevision int64 `json:"command_revision"`
	}
	if err := json.Unmarshal(existing, &receipt); err != nil {
		return 0, fmt.Errorf("decode stored receipt for %q: %w", commandID, err)
	}
	return receipt.CommandRevision, nil
}

// RecordedReceiptCountE counts the receipts the Endpoint would still re-send.
//
// It reads the Endpoint's own journal through the same query the resend path
// uses, so a scenario can assert that a settlement actually shrank the resend set
// rather than only that a row exists.
func (c *Cluster) RecordedReceiptCountE() (int, error) {
	if c.EndpointDB == "" {
		return 0, fmt.Errorf("cluster has no Endpoint database path")
	}
	db, err := sql.Open("sqlite", c.EndpointDB+"?_pragma=busy_timeout(5000)")
	if err != nil {
		return 0, fmt.Errorf("open endpoint database: %w", err)
	}
	defer func() { _ = db.Close() }()
	var count int
	err = db.QueryRowContext(context.Background(), `SELECT COUNT(*) FROM command_journal WHERE phase='receipt_recorded' AND NOT EXISTS (SELECT 1 FROM receipt_settlement s WHERE s.command_id = command_journal.command_id)`).Scan(&count)
	if err != nil {
		return 0, fmt.Errorf("count recorded receipts: %w", err)
	}
	return count, nil
}

// SecondaryLog reads the second Server's own log.
//
// It is the only evidence that the second Server received a receipt. A settlement
// row proves the Endpoint decided something, but it cannot prove the receipt was
// never sent: the per-receipt rejection path settles the same row after the
// Server has already refused it.
func (c *Cluster) SecondaryLog() (string, error) {
	if c.SecondaryLogPath == "" {
		return "", fmt.Errorf("cluster was not started with a second Server log")
	}
	data, err := os.ReadFile(c.SecondaryLogPath)
	if err != nil {
		return "", fmt.Errorf("read secondary server log: %w", err)
	}
	return string(data), nil
}

// CountSecondaryLogOccurrences counts how often one needle appears in the second
// Server's log.
//
// A scenario uses it to prove the second Server received no receipt for a
// command: the Server logs one rejection line per receipt it refuses, so a count
// of zero is the only evidence that the receipt was never sent at all.
func (c *Cluster) CountSecondaryLogOccurrences(needle string) (int, error) {
	log, err := c.SecondaryLog()
	if err != nil {
		return 0, err
	}
	return strings.Count(log, needle), nil
}

// PrimaryDialAddress reports the address the Endpoint dials to reach the primary
// Server.
//
// It is the proxy address when a proxy sits in front of the primary Server, and
// the direct address otherwise. A scenario that asserts on a refused address must
// name the address the Endpoint actually dialled, because the proxy address and
// the Server address are different strings and asserting the wrong one would
// never match.
func (c *Cluster) PrimaryDialAddress() string {
	if c.ChannelProxy != nil {
		return c.ChannelProxy.Address()
	}
	return "wss://127.0.0.1:" + c.Channel
}

// StopPrimaryServerE stops the primary Server and leaves it stopped.
//
// This is deliberately separate from RestartServerE, which stops and starts in
// one step. A fallback scenario must observe the Endpoint while the primary is
// genuinely absent, because the event under test is the Endpoint's own walk to
// the next address. A stop-and-start helper would hide that window entirely.
func (c *Cluster) StopPrimaryServerE() error {
	if err := StopProcessE(c.Server); err != nil {
		return fmt.Errorf("stop primary server: %w", err)
	}
	return nil
}

// StartPrimaryServerE starts the primary Server again with its original
// configuration and waits for readiness.
//
// The database survives, so the Server keeps its durable identity, while the
// in-memory fence starts again at 1. A scenario that restores the primary must
// therefore not expect the Endpoint to adopt it: the Endpoint holds a higher
// generation from the second Server, and nothing forces a reconnect while the
// second link is healthy.
//
// Startup also marks every persisted online row offline, so the primary Server
// reports the Endpoint offline until a real link is installed. That is what makes
// "the primary Server reports the Endpoint online" a discriminating assertion: it
// can only become true through an actual reconnect.
func (c *Cluster) StartPrimaryServerE() error {
	if len(c.ServerEnv) == 0 {
		return fmt.Errorf("cluster did not retain the primary server environment, so it cannot be restarted")
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

// FreezeSecondaryE makes the second Server stop answering without closing its
// sockets.
//
// A stopped Server cannot discriminate liveness detection: the closed socket
// produces an immediate read error, so a build with no heartbeat timeout still
// reconnects and the scenario would pass for the wrong reason. Freezing keeps
// every socket open and discards every byte, so the Endpoint can only recover by
// deciding the Server is unhealthy.
func (c *Cluster) FreezeSecondaryE() error {
	if c.SecondaryChannelProxy == nil {
		return fmt.Errorf("cluster has no second channel proxy, so the second Server cannot be frozen without closing its sockets")
	}
	c.SecondaryChannelProxy.Freeze()
	return nil
}

// AssertNoReconnectAfterE fails when the Endpoint reconnected after the offset.
//
// The final online state cannot discriminate here. Whether the Endpoint never
// attempted a switch-back or attempted one and was refused, the second Server
// still reports it online. Only the absence of a new "endpoint channel
// reconnected" line proves that no attempt was made, so the assertion reads the
// Endpoint's own log from a recorded offset and counts occurrences.
//
// The window is the honest bound of the claim: the assertion proves that no
// reconnect happened within it, not that none can ever happen. A window shorter
// than the unhealthy window would pass for a build that reconnects only after
// deciding the Server is unhealthy, so the caller must pass a window longer than
// that decision takes.
func (c *Cluster) AssertNoReconnectAfterE(offset int64, window time.Duration) error {
	if c.EndpointLogPath == "" {
		return fmt.Errorf("cluster was not started with an Endpoint log file")
	}
	time.Sleep(window)
	content, err := os.ReadFile(c.EndpointLogPath)
	if err != nil {
		return fmt.Errorf("read endpoint log: %w", err)
	}
	if int64(len(content)) <= offset {
		return nil
	}
	after := string(content[offset:])
	if count := strings.Count(after, "endpoint channel reconnected"); count > 0 {
		return fmt.Errorf("the Endpoint reconnected %d time(s) within %s after the first Server was restored, so a healthy link did not hold it; log tail:\n%s", count, window, logTailOf(after))
	}
	return nil
}
