package harness

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// ClusterOptions controls the real Server, Endpoint, and fixture process wiring.
type ClusterOptions struct {
	Environment map[string]string
	DelayMS     int
	Faults      FaultInjection
}

// FaultInjection contains test-only process-composition controls shared by integration and BDD tests.
// These values are translated to AGENT_CLUSTER_TEST_* variables only when starting test processes.
type FaultInjection struct {
	DelayMS                     int
	DropAck                     bool
	DispatchDelayMS             int
	ReceiptDelayMS              int
	CrashAfterInvocationStarted bool
	CrashBeforeInvocation       bool
	ProviderFailAfterN          int
	ProviderAlwaysFail          bool
	CollectionIntervalMS        int
	ProviderFailAdapterID       string
	TwoAdapters                 bool
	NoSessions                  bool
	OutputUnsupported           bool
	OutputSize                  int
	ProviderInvocationLog       string
	HoldPhase                   string
	HoldDir                     string
	UnsupportedCapability       string
}

// StartCluster starts an isolated real Server and Endpoint connected over mTLS.
func StartCluster(t testing.TB, options ClusterOptions) (*Cluster, error) {
	t.Helper()
	root := t.TempDir()
	certs := Certificates(t, root)
	serverBin, endpointBin, fixtureBin := filepath.Join(root, "server"), filepath.Join(root, "endpoint"), filepath.Join(root, "fixture")
	if err := Build(serverBin, "./src/main/agent-cluster-server"); err != nil {
		return nil, err
	}
	if err := Build(endpointBin, "./src/main/agent-cluster-endpoint"); err != nil {
		return nil, err
	}
	if err := Build(fixtureBin, "./tests/fixtures/provider"); err != nil {
		return nil, err
	}
	cluster := &Cluster{Root: root, API: FreePort(t), Channel: FreePort(t), ServerDB: filepath.Join(root, "server.db"), EndpointDB: filepath.Join(root, "endpoint.db"), Record: filepath.Join(root, "records.jsonl"), Certs: certs}
	serverEnv := []string{"AGENT_CLUSTER_API_LISTEN_ADDR=127.0.0.1:" + cluster.API, "AGENT_CLUSTER_CHANNEL_LISTEN_ADDR=127.0.0.1:" + cluster.Channel, "AGENT_CLUSTER_DATABASE_PATH=" + cluster.ServerDB, "AGENT_CLUSTER_AUTH_TOKEN=secret", "AGENT_CLUSTER_TLS_CA_FILE=" + certs.CA, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE=" + certs.ServerCert, "AGENT_CLUSTER_TLS_KEY_FILE=" + certs.ServerKey}
	serverEnv = appendFaultEnvironment(serverEnv, options.Faults)
	for key, value := range options.Environment {
		serverEnv = append(serverEnv, key+"="+value)
	}
	cluster.Server = StartProcess(t, serverBin, serverEnv)
	WaitHTTP(t, cluster.URL("/healthz"), "", http.StatusOK, 15*time.Second)
	mode := "one"
	if options.Faults.NoSessions {
		mode = "empty"
	}
	discoveryCount := filepath.Join(root, "discovery-count")
	adapterArgs := []map[string]any{{"adapter_id": "fixture-main", "provider_type": "fixture", "command": fixtureBin, "args": []string{"--mode", mode, "--record-file", cluster.Record, "--discovery-count-file", discoveryCount, "--delay-ms", fmt.Sprint(options.DelayMS), "--output-size", fmt.Sprint(options.Faults.OutputSize)}, "timeout_ms": 5000}}
	if options.Faults.TwoAdapters {
		adapterArgs = []map[string]any{{"adapter_id": "adapter-a", "provider_type": "fixture", "command": fixtureBin, "args": []string{"--mode", "one", "--record-file", cluster.Record, "--discovery-count-file", discoveryCount + "-a"}, "timeout_ms": 5000}, {"adapter_id": "adapter-b", "provider_type": "fixture", "command": fixtureBin, "args": []string{"--mode", "one", "--always-fail", "--record-file", cluster.Record, "--discovery-count-file", discoveryCount + "-b"}, "timeout_ms": 5000}}
	}
	if options.Faults.ProviderAlwaysFail && !options.Faults.TwoAdapters {
		adapterArgs[0]["args"].([]string)[1] = "fail"
	}
	if options.Faults.UnsupportedCapability != "" {
		capabilities := []map[string]string{{"name": "message.send", "version": "v1"}, {"name": "execution.interrupt", "version": "v1"}, {"name": "agent.stop", "version": "v1"}}
		filtered := capabilities[:0]
		for _, capability := range capabilities {
			if capability["name"] != options.Faults.UnsupportedCapability {
				filtered = append(filtered, capability)
			}
		}
		adapterArgs[0]["capabilities"] = map[string]any{"capabilities": filtered}
	}
	for i := range adapterArgs {
		if options.Faults.ProviderFailAdapterID == adapterArgs[i]["adapter_id"] {
			adapterArgs[i]["args"] = append(adapterArgs[i]["args"].([]string), "--fail-execution")
		}
	}
	adapterJSON, err := json.Marshal(adapterArgs)
	if err != nil {
		t.Fatal(err)
	}
	args := "AGENT_CLUSTER_ADAPTERS=" + string(adapterJSON)
	endpointEnv := []string{"AGENT_CLUSTER_CHANNEL_ADDRESS=wss://127.0.0.1:" + cluster.Channel, "AGENT_CLUSTER_ENDPOINT_ID=endpoint-1", "AGENT_CLUSTER_DATABASE_PATH=" + cluster.EndpointDB, "AGENT_CLUSTER_TLS_CA_FILE=" + certs.CA, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE=" + certs.ClientCert, "AGENT_CLUSTER_TLS_KEY_FILE=" + certs.ClientKey, args}
	endpointEnv = appendFaultEnvironment(endpointEnv, options.Faults)
	cluster.EndpointPath = endpointBin
	cluster.EndpointEnv = append([]string(nil), endpointEnv...)
	cluster.Endpoint = StartProcess(t, endpointBin, endpointEnv)
	WaitInventory(t, cluster.URL("/api/v1/endpoints/endpoint-1/session-state"), "secret", 20*time.Second)
	t.Cleanup(func() { StopProcess(t, cluster.Endpoint); StopProcess(t, cluster.Server) })
	return cluster, nil
}

// WaitForBeforeInvocationCrash waits for the process-composition crash marker.
func (c *Cluster) WaitForBeforeInvocationCrash(t testing.TB, limit time.Duration) {
	t.Helper()
	marker := c.EndpointDB + ".crash-before-invocation"
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(marker); err == nil {
			return
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatalf("Endpoint did not reach accepted journal crash marker %s", marker)
}

// RestartEndpoint stops and starts the owned Endpoint with its original configuration.
func (c *Cluster) RestartEndpoint(t testing.TB) {
	t.Helper()
	StopProcess(t, c.Endpoint)
	c.Endpoint = StartProcess(t, c.EndpointPath, c.EndpointEnv)
	WaitInventory(t, c.URL("/api/v1/endpoints/endpoint-1/session-state"), "secret", 20*time.Second)
}

// Stop stops all processes owned by the cluster exactly once.
func (c *Cluster) Stop(t testing.TB) {
	t.Helper()
	c.stopMu.Lock()
	defer c.stopMu.Unlock()
	if c.stopped {
		return
	}
	c.stopped = true
	StopProcess(t, c.Endpoint2)
	StopProcess(t, c.Endpoint)
	StopProcess(t, c.Server)
}

// URL returns a Server API URL for the cluster.
func (c *Cluster) URL(path string) string { return "http://127.0.0.1:" + c.API + path }

// Request performs an authenticated request against the real Server.
func (c *Cluster) Request(t testing.TB, method, path string, payload any) (int, []byte) {
	t.Helper()
	var body io.Reader
	if payload != nil {
		data, err := json.Marshal(payload)
		if err != nil {
			t.Fatal(err)
		}
		body = bytes.NewReader(data)
	}
	req, err := http.NewRequest(method, c.URL(path), body)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer secret")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return resp.StatusCode, data
}

// WaitHTTP waits for a bounded HTTP status result.
func WaitHTTP(t testing.TB, url, token string, want int, limit time.Duration) {
	t.Helper()
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == want {
				return
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("HTTP %s did not return %d", url, want)
}

// WaitInventory waits for the first real Endpoint inventory report.
func WaitInventory(t testing.TB, url, token string, limit time.Duration) {
	t.Helper()
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		req.Header.Set("Authorization", "Bearer "+token)
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			data, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK && (bytes.Contains(data, []byte("fixture-main")) || bytes.Contains(data, []byte("adapter-a"))) {
				return
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("real Endpoint inventory was not reported")
}

// ProviderInvocations returns the fixture's durable invocation evidence.
func (c *Cluster) ProviderInvocations(t testing.TB) []map[string]any {
	t.Helper()
	data, err := os.ReadFile(c.Record)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	var result []map[string]any
	for _, line := range bytes.Split(bytes.TrimSpace(data), []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		var item map[string]any
		if err := json.Unmarshal(line, &item); err != nil {
			t.Fatal(err)
		}
		result = append(result, item)
	}
	return result
}

func appendFaultEnvironment(env []string, faults FaultInjection) []string {
	if faults.HoldPhase != "" && faults.HoldDir != "" {
		env = append(env, "AGENT_CLUSTER_TEST_HOLD_PHASE="+faults.HoldPhase, "AGENT_CLUSTER_TEST_HOLD_DIR="+faults.HoldDir)
	}
	if faults.DropAck {
		env = append(env, "AGENT_CLUSTER_TEST_DROP_ACK=1")
	}
	if faults.DispatchDelayMS > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_DISPATCH_DELAY_MS=%d", faults.DispatchDelayMS))
	}
	if faults.ReceiptDelayMS > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_DELAY_RECEIPT_MS=%d", faults.ReceiptDelayMS))
	}
	if faults.CrashAfterInvocationStarted {
		env = append(env, "AGENT_CLUSTER_TEST_CRASH_AFTER_INVOCATION_STARTED=1")
	}
	if faults.CrashBeforeInvocation {
		env = append(env, "AGENT_CLUSTER_TEST_CRASH_BEFORE_INVOCATION=1")
	}
	if faults.CollectionIntervalMS > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_COLLECTION_INTERVAL_MS=%d", faults.CollectionIntervalMS))
	}
	if faults.ProviderFailAfterN > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_PROVIDER_FAIL_AFTER_N=%d", faults.ProviderFailAfterN))
	}
	if faults.ProviderAlwaysFail {
		env = append(env, "AGENT_CLUSTER_TEST_PROVIDER_FAIL_AFTER_N=0")
	}
	if faults.OutputUnsupported {
		env = append(env, "AGENT_CLUSTER_TEST_OUTPUT_UNSUPPORTED=1")
	}
	if faults.ProviderInvocationLog != "" {
		env = append(env, "AGENT_CLUSTER_TEST_PROVIDER_INVOCATION_LOG="+faults.ProviderInvocationLog)
	}
	return env
}

// BuildTUI compiles and caches the non-interactive TUI binary for this cluster.
func (c *Cluster) BuildTUI(tb testing.TB) (string, error) {
	tb.Helper()
	c.tuiBuildMu.Lock()
	defer c.tuiBuildMu.Unlock()
	if c.TUIPath != "" {
		return c.TUIPath, nil
	}
	path := filepath.Join(c.Root, "agent-cluster-tui")
	if err := Build(path, "./src/main/agent-cluster-tui"); err != nil {
		return "", err
	}
	c.TUIPath = path
	return path, nil
}

// RunTUI executes the TUI without a TTY and returns complete output and exit status.
func (c *Cluster) RunTUI(args ...string) (stdout string, stderr string, exitCode int, err error) {
	if c.TUIPath == "" {
		return "", "", -1, fmt.Errorf("TUI binary has not been built; call BuildTUI first")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, c.TUIPath, args...)
	cmd.Dir = ModuleRootForRun()
	cmd.Env = append(os.Environ(),
		"AGENT_CLUSTER_SERVER_URL="+c.URL(""),
		"AGENT_CLUSTER_TOKEN=secret",
		"AGENT_CLUSTER_TLS_CA_FILE="+c.Certs.CA,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+c.Certs.ClientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+c.Certs.ClientKey,
	)
	var out, stderrBuffer bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &stderrBuffer
	runErr := cmd.Run()
	if ctx.Err() != nil {
		return out.String(), stderrBuffer.String(), -1, ctx.Err()
	}
	exitCode = 0
	if runErr != nil {
		exitCode = 1
		var exitErr *exec.ExitError
		if errors.As(runErr, &exitErr) {
			exitCode = exitErr.ExitCode()
		}
	}
	return out.String(), stderrBuffer.String(), exitCode, runErr
}

// ModuleRootForRun returns the repository root from the harness package working directory.
func ModuleRootForRun() string {
	wd, err := os.Getwd()
	if err != nil {
		return wd
	}
	return filepath.Clean(filepath.Join(wd, "..", ".."))
}
