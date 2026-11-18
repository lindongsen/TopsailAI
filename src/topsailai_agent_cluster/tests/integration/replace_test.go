//go:build integration

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

// replaceCluster is one Server plus one Endpoint whose adapters are standalone
// Provider CLI programs.
//
// The adapters are real child processes rather than the in-process TopsailAI
// adapter, because activation replaces the program an adapter runs. An
// in-process adapter has no program to replace, so it cannot exercise the path
// this test exists to prove.
type replaceCluster struct {
	root, api, serverDB, endpointDB string
	providerDir                     string
	requestFile, resultFile         string
	server, endpoint                *exec.Cmd
}

// replaceAdapterSummary is the part of one reported adapter this test asserts on.
type replaceAdapterSummary struct {
	AdapterID string `json:"adapter_id"`
	Version   string `json:"version"`
	Health    string `json:"health"`
}

// replaceInventoryPayload is the committed inventory document this test reads.
type replaceInventoryPayload struct {
	Adapters []replaceAdapterSummary `json:"adapters"`
}

// replaceFileAnswer mirrors the answer document the Endpoint writes.
type replaceFileAnswer struct {
	RequestID string `json:"request_id"`
	OK        bool   `json:"ok"`
	Error     string `json:"error"`
	Result    struct {
		AdapterID         string `json:"adapter_id"`
		Executable        string `json:"executable"`
		PreviousVersion   string `json:"previous_version"`
		EffectiveVersion  string `json:"effective_version"`
		EffectiveRevision string `json:"effective_revision"`
		InFlight          int    `json:"in_flight"`
		Reverted          bool   `json:"reverted"`
		RevertReason      string `json:"revert_reason"`
	} `json:"result"`
}

// replaceCapabilities is the operator-declared capability allowlist.
//
// A revision is mandatory: the adapter intersects the declared capabilities with
// what the provider advertises and keeps the declared revision, and activation
// rejects a candidate whose descriptor carries no revision. Without this value
// every candidate would be refused for a reason unrelated to the behaviour under
// test.
const replaceCapabilities = `{"revision":"mock-cli-r1","capabilities":[{"name":"message.send","version":"v1","target_kinds":["session"],"safety_class":"mutating","required_permission":"send_message"}]}`

// buildProviderModule builds a program that lives in its own Go module.
//
// providers/mock is a separate module, so the shared build helper cannot build
// it: that helper sets the working directory to the repository root, where the
// package is not part of the main module.
func buildProviderModule(t *testing.T, out, moduleDir string) {
	t.Helper()
	cmd := exec.Command("go", "build", "-o", out, "./src")
	cmd.Dir = moduleDir
	if b, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("build %s: %v\n%s", moduleDir, err, b)
	}
}

// startReplaceCluster starts one Server and one Endpoint with two standalone
// Provider CLI adapters and an activation request file.
func startReplaceCluster(t *testing.T) *replaceCluster {
	t.Helper()
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	serverBinary := filepath.Join(root, "server")
	endpointBinary := filepath.Join(root, "endpoint")
	providerDir := filepath.Join(root, "provider")
	build(t, serverBinary, "./src/main/agent-cluster-server")
	build(t, endpointBinary, "./src/main/agent-cluster-endpoint")
	buildProviderModule(t, filepath.Join(providerDir, "mock"), filepath.Join(moduleRoot(t), "providers", "mock"))
	// The candidate is a second copy of the same program at a different path, so
	// the activation has a distinct artifact to install. The mock reports a fixed
	// provider version, so the assertions rest on the recorded previous version,
	// the published revision and the installed path rather than on a version
	// string that cannot change.
	if err := os.MkdirAll(providerDir, 0o755); err != nil {
		t.Fatal(err)
	}
	installed, err := os.ReadFile(filepath.Join(providerDir, "mock"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(providerDir, "mock-next"), installed, 0o755); err != nil {
		t.Fatal(err)
	}
	c := &replaceCluster{
		root: root, api: free(t),
		serverDB:    filepath.Join(root, "server.db"),
		endpointDB:  filepath.Join(root, "endpoint.db"),
		providerDir: providerDir,
		requestFile: filepath.Join(root, "replace-request.json"),
		resultFile:  filepath.Join(root, "replace-result.json"),
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
	waitHTTP(t, c.url("/healthz"), "", http.StatusOK, 15*time.Second)
	// Two adapters share one program on purpose: mock-main is the adapter under
	// replacement and mock-other must keep serving, which is what proves an
	// activation is scoped to one adapter instead of the whole Endpoint.
	adapters := fmt.Sprintf(`AGENT_CLUSTER_ENDPOINT_ADAPTERS=[`+
		`{"adapter_id":"mock-main","provider_type":"genericcli","command":%q,"timeout_ms":5000,"capabilities":%s},`+
		`{"adapter_id":"mock-other","provider_type":"genericcli","command":%q,"timeout_ms":5000,"capabilities":%s}]`,
		filepath.Join(providerDir, "mock"), replaceCapabilities,
		filepath.Join(providerDir, "mock"), replaceCapabilities)
	c.endpoint = exec.Command(endpointBinary)
	c.endpoint.Dir = moduleRoot(t)
	c.endpoint.Env = append(os.Environ(),
		"AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS=wss://127.0.0.1:"+channel,
		"AGENT_CLUSTER_ENDPOINT_ID=endpoint-1",
		"AGENT_CLUSTER_DATABASE_PATH="+c.endpointDB,
		"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey,
		"AGENT_CLUSTER_ENDPOINT_REPLACE_REQUEST_FILE="+c.requestFile,
		adapters,
	)
	c.endpoint.Stdout, c.endpoint.Stderr = os.Stdout, os.Stderr
	if err := c.endpoint.Start(); err != nil {
		t.Fatal(err)
	}
	waitReplaceInventory(t, c.url("/api/v1/endpoints/endpoint-1/session-state"), 30*time.Second)
	return c
}

// url builds one Server API URL.
func (c *replaceCluster) url(path string) string { return "http://127.0.0.1:" + c.api + path }

// stop terminates the Endpoint and Server by exact PID.
func (c *replaceCluster) stop(t *testing.T) {
	t.Helper()
	for _, process := range []*exec.Cmd{c.endpoint, c.server} {
		if process == nil || process.Process == nil {
			continue
		}
		_ = syscall.Kill(process.Process.Pid, syscall.SIGTERM)
		done := make(chan error, 1)
		go func(p *exec.Cmd) { done <- p.Wait() }(process)
		select {
		case <-done:
		case <-time.After(30 * time.Second):
			t.Fatalf("process %d did not stop", process.Process.Pid)
		}
	}
}

// waitReplaceInventory waits until both adapters are reported, so the test never
// signals an Endpoint whose registry is still empty.
func waitReplaceInventory(t *testing.T, url string, limit time.Duration) replaceInventoryPayload {
	t.Helper()
	deadline := time.Now().Add(limit)
	var last replaceInventoryPayload
	for time.Now().Before(deadline) {
		payload, err := readReplaceInventory(url)
		if err == nil {
			last = payload
			if len(payload.Adapters) >= 2 {
				return payload
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("inventory did not report both adapters: %+v", last)
	return last
}

// readReplaceInventory reads the committed inventory document.
func readReplaceInventory(url string) (replaceInventoryPayload, error) {
	var payload replaceInventoryPayload
	req, err := http.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return payload, err
	}
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return payload, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return payload, fmt.Errorf("inventory returned %d", resp.StatusCode)
	}
	var envelope struct {
		Data replaceInventoryPayload `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		return payload, err
	}
	return envelope.Data, nil
}

// adapterByID returns one reported adapter summary.
func adapterByID(payload replaceInventoryPayload, adapterID string) (replaceAdapterSummary, bool) {
	for _, adapter := range payload.Adapters {
		if adapter.AdapterID == adapterID {
			return adapter, true
		}
	}
	return replaceAdapterSummary{}, false
}

// requestReplace writes one activation request and signals the Endpoint.
func (c *replaceCluster) requestReplace(t *testing.T, requestID, adapterID, executable string) {
	t.Helper()
	document := fmt.Sprintf(`{"request_id":%q,"adapter_id":%q,"executable":%q}`, requestID, adapterID, executable)
	if err := os.WriteFile(c.requestFile, []byte(document), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Kill(c.endpoint.Process.Pid, syscall.SIGHUP); err != nil {
		t.Fatalf("signal endpoint: %v", err)
	}
}

// waitReplaceAnswer waits for the answer carrying the expected request ID.
//
// The answer is correlated by request ID rather than by file existence, because a
// stale answer from an earlier activation must never be read as the outcome of
// this one.
func (c *replaceCluster) waitReplaceAnswer(t *testing.T, requestID string, limit time.Duration) replaceFileAnswer {
	t.Helper()
	deadline := time.Now().Add(limit)
	var last string
	for time.Now().Before(deadline) {
		data, err := os.ReadFile(c.resultFile)
		if err == nil {
			last = string(data)
			var answer replaceFileAnswer
			if decodeErr := json.Unmarshal(data, &answer); decodeErr == nil && answer.RequestID == requestID {
				return answer
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("no answer for request %q within %s, last document: %s", requestID, limit, last)
	return replaceFileAnswer{}
}

// TestReplaceActivatesProviderCLIWithoutRestartingEndpoint proves one adapter's
// Provider CLI version is replaced while the Endpoint keeps running and the other
// adapter keeps serving.
func TestReplaceActivatesProviderCLIWithoutRestartingEndpoint(t *testing.T) {
	c := startReplaceCluster(t)
	defer c.stop(t)
	pid := c.endpoint.Process.Pid
	before, ok := adapterByID(waitReplaceInventory(t, c.url("/api/v1/endpoints/endpoint-1/session-state"), 30*time.Second), "mock-main")
	if !ok {
		t.Fatalf("mock-main was not reported before activation")
	}
	c.requestReplace(t, "replace-live-1", "mock-main", filepath.Join(c.providerDir, "mock-next"))
	answer := c.waitReplaceAnswer(t, "replace-live-1", 40*time.Second)
	if !answer.OK {
		t.Fatalf("activation was refused: %+v", answer)
	}
	if answer.Result.AdapterID != "mock-main" {
		t.Fatalf("answer names adapter %q, want mock-main", answer.Result.AdapterID)
	}
	if answer.Result.PreviousVersion == "" {
		t.Fatalf("answer did not record the previous version: %+v", answer.Result)
	}
	if answer.Result.EffectiveRevision == "" {
		t.Fatalf("answer did not publish an effective revision: %+v", answer.Result)
	}
	if answer.Result.Reverted {
		t.Fatalf("activation reported a revert: %+v", answer.Result)
	}
	if answer.Result.Executable != filepath.Join(c.providerDir, "mock-next") {
		t.Fatalf("answer names executable %q, want the candidate", answer.Result.Executable)
	}
	// The request document is consumed before the Endpoint acts, so its absence is
	// the evidence that the signal reached the handler instead of being ignored.
	if _, err := os.Stat(c.requestFile); !os.IsNotExist(err) {
		t.Fatalf("request document still present after activation: %v", err)
	}
	// No restart: the same process is still alive and still the one the test
	// started, which is the property the whole unit exists to provide.
	if err := syscall.Kill(pid, 0); err != nil {
		t.Fatalf("endpoint pid %d is gone after activation: %v", pid, err)
	}
	if c.endpoint.Process.Pid != pid {
		t.Fatalf("endpoint pid changed from %d to %d", pid, c.endpoint.Process.Pid)
	}
	after := waitReplaceInventory(t, c.url("/api/v1/endpoints/endpoint-1/session-state"), 30*time.Second)
	main, ok := adapterByID(after, "mock-main")
	if !ok {
		t.Fatalf("mock-main disappeared after activation")
	}
	if main.Version != answer.Result.EffectiveVersion {
		t.Fatalf("inventory reports version %q, answer published %q", main.Version, answer.Result.EffectiveVersion)
	}
	// The unrelated adapter must be untouched: an activation is scoped to one
	// adapter, never to the Endpoint.
	other, ok := adapterByID(after, "mock-other")
	if !ok {
		t.Fatalf("mock-other disappeared after activating mock-main")
	}
	if other.Version != before.Version {
		t.Fatalf("mock-other version changed from %q to %q", before.Version, other.Version)
	}
}

// TestReplaceRejectsCandidateAndKeepsPreviousVersion proves a refused candidate
// leaves the previously activated version serving.
func TestReplaceRejectsCandidateAndKeepsPreviousVersion(t *testing.T) {
	c := startReplaceCluster(t)
	defer c.stop(t)
	pid := c.endpoint.Process.Pid
	// A plain text file is not an executable, so the candidate is refused before
	// anything is swapped.
	notExecutable := filepath.Join(c.root, "not-executable")
	if err := os.WriteFile(notExecutable, []byte("not a program\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	c.requestReplace(t, "replace-live-reject", "mock-main", notExecutable)
	answer := c.waitReplaceAnswer(t, "replace-live-reject", 40*time.Second)
	if answer.OK {
		t.Fatalf("activation accepted a non-executable candidate: %+v", answer)
	}
	if answer.Error == "" {
		t.Fatalf("refusal did not state a reason: %+v", answer)
	}
	if answer.Result.Reverted {
		t.Fatalf("a refused candidate must not report a revert: %+v", answer.Result)
	}
	if err := syscall.Kill(pid, 0); err != nil {
		t.Fatalf("endpoint pid %d is gone after a refused activation: %v", pid, err)
	}
	// The previous version is still serving, so the adapter is still reported and
	// still healthy.
	after := waitReplaceInventory(t, c.url("/api/v1/endpoints/endpoint-1/session-state"), 30*time.Second)
	main, ok := adapterByID(after, "mock-main")
	if !ok {
		t.Fatalf("mock-main disappeared after a refused activation")
	}
	if main.Version == "" {
		t.Fatalf("mock-main reports no version after a refused activation")
	}
	if main.Health == "" {
		t.Fatalf("mock-main reports no health after a refused activation")
	}
}
