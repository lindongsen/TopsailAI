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
	"syscall"
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
	CollectionDelayMS           int
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
	certs, err := CertificatesE(root)
	if err != nil {
		return nil, fmt.Errorf("create certificates: %w", err)
	}
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
	apiPort, err := FreePortE()
	if err != nil {
		return nil, fmt.Errorf("allocate API port: %w", err)
	}
	channelPort, err := FreePortE()
	if err != nil {
		return nil, fmt.Errorf("allocate channel port: %w", err)
	}
	cluster := &Cluster{Root: root, API: apiPort, Channel: channelPort, ServerDB: filepath.Join(root, "server.db"), EndpointDB: filepath.Join(root, "endpoint.db"), Record: filepath.Join(root, "records.jsonl"), Certs: certs}
	serverEnv := []string{"AGENT_CLUSTER_API_LISTEN_ADDR=127.0.0.1:" + cluster.API, "AGENT_CLUSTER_CHANNEL_LISTEN_ADDR=127.0.0.1:" + cluster.Channel, "AGENT_CLUSTER_DATABASE_PATH=" + cluster.ServerDB, "AGENT_CLUSTER_AUTH_TOKEN=secret", "AGENT_CLUSTER_TLS_CA_FILE=" + certs.CA, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE=" + certs.ServerCert, "AGENT_CLUSTER_TLS_KEY_FILE=" + certs.ServerKey}
	serverEnv = appendFaultEnvironment(serverEnv, options.Faults)
	for key, value := range options.Environment {
		serverEnv = append(serverEnv, key+"="+value)
	}
	cluster.Server, err = StartProcessE(serverBin, serverEnv)
	if err != nil {
		return nil, err
	}
	t.Cleanup(func() {
		if err := StopProcessE(cluster.Endpoint); err != nil {
			t.Logf("stop endpoint: %v", err)
		}
		if err := StopProcessE(cluster.Server); err != nil {
			t.Logf("stop server: %v", err)
		}
	})
	if err := WaitHTTPE(cluster.URL("/healthz"), "", http.StatusOK, 15*time.Second); err != nil {
		return nil, err
	}
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
	adapterJSON, err := marshalAdapterConfigurationFn(adapterArgs)
	if err != nil {
		return nil, fmt.Errorf("marshal adapter configuration: %w", err)
	}
	args := "AGENT_CLUSTER_ADAPTERS=" + string(adapterJSON)
	endpointEnv := []string{"AGENT_CLUSTER_CHANNEL_ADDRESS=wss://127.0.0.1:" + cluster.Channel, "AGENT_CLUSTER_ENDPOINT_ID=endpoint-1", "AGENT_CLUSTER_DATABASE_PATH=" + cluster.EndpointDB, "AGENT_CLUSTER_TLS_CA_FILE=" + certs.CA, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE=" + certs.ClientCert, "AGENT_CLUSTER_TLS_KEY_FILE=" + certs.ClientKey, args}
	endpointEnv = appendFaultEnvironment(endpointEnv, options.Faults)
	cluster.EndpointPath = endpointBin
	cluster.EndpointEnv = append([]string(nil), endpointEnv...)
	cluster.Endpoint, err = StartProcessE(endpointBin, endpointEnv)
	if err != nil {
		return nil, err
	}
	if err := WaitInventoryE(cluster.URL("/api/v1/endpoints/endpoint-1/session-state"), "secret", 20*time.Second); err != nil {
		return nil, err
	}
	return cluster, nil
}

var marshalAdapterConfigurationFn = json.Marshal

// WaitForBeforeInvocationCrash waits for the process-composition crash marker.
func (c *Cluster) WaitForBeforeInvocationCrashE(limit time.Duration) error {
	marker := c.EndpointDB + ".crash-before-invocation"
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(marker); err == nil {
			return nil
		}
		time.Sleep(25 * time.Millisecond)
	}
	return fmt.Errorf("wait for crash marker before deadline: %s", marker)
}

// WaitForBeforeInvocationCrash preserves the legacy testing.TB API.
func (c *Cluster) WaitForBeforeInvocationCrash(t testing.TB, limit time.Duration) {
	t.Helper()
	if err := c.WaitForBeforeInvocationCrashE(limit); err != nil {
		t.Fatal(err)
	}
}

// RestartEndpointE stops and starts the owned Endpoint with its original configuration.
func (c *Cluster) RestartEndpointE() error {
	if err := stopProcessForRestartE(c.Endpoint); err != nil {
		return fmt.Errorf("stop endpoint: %w", err)
	}
	endpoint, err := StartProcessE(c.EndpointPath, c.EndpointEnv)
	if err != nil {
		return fmt.Errorf("start endpoint: %w", err)
	}
	c.Endpoint = endpoint
	if err := WaitInventoryE(c.URL("/api/v1/endpoints/endpoint-1/session-state"), "secret", 20*time.Second); err != nil {
		return fmt.Errorf("wait for endpoint inventory: %w", err)
	}
	return nil
}

// stopProcessForRestartE terminates the endpoint and accepts its expected non-zero exit status.
func stopProcessForRestartE(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil || cmd.ProcessState != nil {
		return fmt.Errorf("endpoint process is not running")
	}
	pid := cmd.Process.Pid
	if err := syscall.Kill(pid, syscall.SIGTERM); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("signal process %d: %w", pid, err)
	}
	if err := cmd.Wait(); err != nil && !expectedEndpointExit(err) {
		return fmt.Errorf("wait for endpoint process %d: %w", pid, err)
	}
	return nil
}

// expectedEndpointExit reports the exit status produced by a deliberate endpoint stop.
func expectedEndpointExit(err error) bool {
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		return false
	}
	code := exitErr.ExitCode()
	return code == 98 || code == -1
}

// RestartEndpoint preserves the legacy testing.TB API.
func (c *Cluster) RestartEndpoint(t testing.TB) {
	t.Helper()
	if err := c.RestartEndpointE(); err != nil {
		t.Fatal(err)
	}
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

// RequestE performs an authenticated request against the real Server.
func (c *Cluster) RequestE(method, path string, payload any) (int, []byte, error) {
	var body io.Reader
	if payload != nil {
		data, err := json.Marshal(payload)
		if err != nil {
			return 0, nil, fmt.Errorf("marshal request payload: %w", err)
		}
		body = bytes.NewReader(data)
	}
	req, err := http.NewRequest(method, c.URL(path), body)
	if err != nil {
		return 0, nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer secret")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, nil, fmt.Errorf("send request: %w", err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, nil, fmt.Errorf("read response: %w", err)
	}
	return resp.StatusCode, data, nil
}

// Request preserves the legacy testing.TB API.
func (c *Cluster) Request(t testing.TB, method, path string, payload any) (int, []byte) {
	t.Helper()
	status, body, err := c.RequestE(method, path, payload)
	if err != nil {
		t.Fatal(err)
	}
	return status, body
}

// WaitHTTP preserves the legacy testing.TB API.
func WaitHTTP(t testing.TB, url, token string, want int, limit time.Duration) {
	t.Helper()
	if err := WaitHTTPE(url, token, want, limit); err != nil {
		t.Fatal(err)
	}
}

// WaitInventory preserves the legacy testing.TB API.
func WaitInventory(t testing.TB, url, token string, limit time.Duration) {
	t.Helper()
	if err := WaitInventoryE(url, token, limit); err != nil {
		t.Fatal(err)
	}
}

// ProviderInvocationsE returns durable fixture invocation evidence.
func (c *Cluster) ProviderInvocationsE() ([]map[string]any, error) {
	data, err := os.ReadFile(c.Record)
	if os.IsNotExist(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read provider invocation record: %w", err)
	}
	var result []map[string]any
	for _, line := range bytes.Split(bytes.TrimSpace(data), []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		var item map[string]any
		if err := json.Unmarshal(line, &item); err != nil {
			return nil, fmt.Errorf("decode provider invocation record: %w", err)
		}
		result = append(result, item)
	}
	return result, nil
}

// ProviderInvocations preserves the legacy testing.TB API.
func (c *Cluster) ProviderInvocations(t testing.TB) []map[string]any {
	t.Helper()
	result, err := c.ProviderInvocationsE()
	if err != nil {
		t.Fatal(err)
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
	if faults.CollectionDelayMS > 0 {
		env = append(env, fmt.Sprintf("AGENT_CLUSTER_TEST_COLLECTION_DELAY_MS=%d", faults.CollectionDelayMS))
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
	path := filepath.Join(c.Root, "agent-cluster-cli")
	if err := Build(path, "./src/main/agent-cluster-cli"); err != nil {
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
