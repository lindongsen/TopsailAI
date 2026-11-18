//go:build integration && testhooks

package integration_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

// zeroAdapterEndpoint is one Endpoint started with no configured Adapter.
type zeroAdapterEndpoint struct {
	api      string
	serverDB string
	endpoint string
	server   *exec.Cmd
	process  *exec.Cmd
}

// TestZeroAdapterEndpointConnectsAndReportsHealth proves an Endpoint with no
// configured Adapter is a supported state rather than a startup failure.
//
// A zero-Adapter node is the state a fresh install and a Provider CLI rollout
// both pass through, so an operator must be able to verify the channel and the
// deployment before any Adapter exists. The Endpoint therefore connects, reports
// health and publishes a structurally complete report that advertises no
// resource, instead of exiting and leaving nothing to observe.
func TestZeroAdapterEndpointConnectsAndReportsHealth(t *testing.T) {
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	serverBinary := filepath.Join(root, "server")
	endpointBinary := filepath.Join(root, "endpoint")
	build(t, serverBinary, "./src/main/agent-cluster-server")
	build(t, endpointBinary, "./src/main/agent-cluster-endpoint")

	c := &zeroAdapterEndpoint{
		api:      free(t),
		serverDB: filepath.Join(root, "server.db"),
		endpoint: filepath.Join(root, "endpoint.db"),
	}
	channel := free(t)
	c.server = exec.Command(serverBinary)
	c.server.Dir = moduleRoot(t)
	c.server.Env = append(os.Environ(),
		"AGENT_CLUSTER_SERVER_API_LISTEN_ADDR=127.0.0.1:"+c.api,
		"AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR=127.0.0.1:"+channel,
		"AGENT_CLUSTER_DATABASE_PATH="+c.serverDB,
		"AGENT_CLUSTER_SERVER_AUTH_TOKEN=secret",
		"AGENT_CLUSTER_SERVER_AUTH_MODE=bearer",
		"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.serverCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+certs.serverKey,
	)
	c.server.Stdout, c.server.Stderr = os.Stdout, os.Stderr
	if err := c.server.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { stopProcess(t, c.server) })
	waitHTTP(t, "http://127.0.0.1:"+c.api+"/healthz", "", http.StatusOK, 15*time.Second)

	// AGENT_CLUSTER_ENDPOINT_ADAPTERS is deliberately absent, which is the
	// zero-Adapter configuration. Setting it to an empty list is equivalent and
	// is covered by the config parser test.
	c.process = exec.Command(endpointBinary)
	c.process.Dir = moduleRoot(t)
	c.process.Env = append(os.Environ(),
		"AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS=wss://127.0.0.1:"+channel,
		"AGENT_CLUSTER_ENDPOINT_ID=endpoint-1",
		"AGENT_CLUSTER_ENDPOINT_AUTH_MODE=bearer",
		"AGENT_CLUSTER_DATABASE_PATH="+c.endpoint,
		"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey,
	)
	c.process.Stdout, c.process.Stderr = os.Stdout, os.Stderr
	if err := c.process.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { stopProcess(t, c.process) })

	// The Endpoint must still be running after startup. A process that exited
	// would make the health assertion below meaningless, because the Server would
	// simply report the Endpoint as offline.
	if err := c.process.Process.Signal(syscall.Signal(0)); err != nil {
		t.Fatalf("endpoint exited during startup: %v", err)
	}

	waitEndpointOnline(t, c.url("/api/v1/endpoints"), 30*time.Second)

	report := waitZeroAdapterReport(t, c.url("/api/v1/endpoints/endpoint-1/session-state"), 30*time.Second)
	if len(report.Adapters) != 0 {
		t.Fatalf("zero-adapter endpoint advertised adapters: %#v", report.Adapters)
	}
	if len(report.Sessions) != 0 {
		t.Fatalf("zero-adapter endpoint advertised sessions: %#v", report.Sessions)
	}
	if !report.ReportComplete {
		t.Fatalf("zero-adapter report is not complete: %#v", report)
	}
	if report.CollectionStatus != "succeeded" {
		t.Fatalf("zero-adapter collection status=%q", report.CollectionStatus)
	}
}

// url builds one Server API URL.
func (c *zeroAdapterEndpoint) url(path string) string { return "http://127.0.0.1:" + c.api + path }

// stopProcess terminates one exact process and waits for it, so no orphan is
// left behind. It never terminates by name.
func stopProcess(t *testing.T, cmd *exec.Cmd) {
	t.Helper()
	if cmd == nil || cmd.Process == nil {
		return
	}
	_ = cmd.Process.Signal(os.Interrupt)
	done := make(chan struct{})
	go func() { _, _ = cmd.Process.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(30 * time.Second):
		_ = cmd.Process.Kill()
		<-done
	}
}

// waitEndpointOnline waits until the Server reports the Endpoint as online.
func waitEndpointOnline(t *testing.T, url string, limit time.Duration) {
	t.Helper()
	deadline := time.Now().Add(limit)
	var last string
	for time.Now().Before(deadline) {
		body, err := getAuthorized(url)
		if err == nil {
			var payload struct {
				Data []struct {
					EndpointID      string `json:"endpoint_id"`
					ConnectionState string `json:"connection_state"`
				} `json:"data"`
			}
			if json.Unmarshal(body, &payload) == nil {
				for _, item := range payload.Data {
					if item.EndpointID == "endpoint-1" && item.ConnectionState == "online" {
						return
					}
					last = fmt.Sprintf("%s=%s", item.EndpointID, item.ConnectionState)
				}
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("endpoint-1 never reported online; last observed %q", last)
}

// zeroAdapterReport is the subset of the inventory document this test asserts.
type zeroAdapterReport struct {
	Adapters         []json.RawMessage `json:"adapters"`
	Sessions         []json.RawMessage `json:"sessions"`
	ReportComplete   bool              `json:"report_complete"`
	CollectionStatus string            `json:"collection_status"`
}

// waitZeroAdapterReport waits until the Endpoint has published a report.
func waitZeroAdapterReport(t *testing.T, url string, limit time.Duration) zeroAdapterReport {
	t.Helper()
	deadline := time.Now().Add(limit)
	var last error
	for time.Now().Before(deadline) {
		body, err := getAuthorized(url)
		if err == nil {
			var payload struct {
				Data zeroAdapterReport `json:"data"`
			}
			if json.Unmarshal(body, &payload) == nil && payload.Data.CollectionStatus != "" {
				return payload.Data
			}
			last = fmt.Errorf("report not published yet: %s", string(body))
		} else {
			last = err
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("zero-adapter report never appeared: %v", last)
	return zeroAdapterReport{}
}

// getAuthorized performs one authenticated GET against the Server API.
func getAuthorized(url string) ([]byte, error) {
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	buf := make([]byte, 0, 4096)
	chunk := make([]byte, 4096)
	for {
		n, readErr := resp.Body.Read(chunk)
		buf = append(buf, chunk[:n]...)
		if readErr != nil {
			break
		}
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("status %d: %s", resp.StatusCode, string(buf))
	}
	return buf, nil
}
