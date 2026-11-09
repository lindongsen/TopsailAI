//go:build integration

package integration_test

import (
	"bytes"
	"encoding/json"
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

// execCluster is one Server plus one Endpoint bound to the TopsailAI fixture.
type execCluster struct {
	root, api, serverDB, endpointDB, sessionDir, allowlist string
	// controlActions is the ctl. catalog file the Endpoint loads. It is always
	// written, because the catalog is the only source of ctl. actions: an
	// Endpoint without one advertises no action and refuses every ctl.
	// operation, so a control test would fail on a missing fixture rather than
	// on the behaviour it asserts.
	controlActions   string
	server, endpoint *exec.Cmd
}

// execCommandView is the durable command projection this test asserts on.
type execCommandView struct {
	Status           string `json:"status"`
	EffectCertainty  string `json:"effect_certainty"`
	ExitConfirmed    bool   `json:"exit_confirmed"`
	ErrorCode        string `json:"error_code"`
	ProviderResponse string `json:"provider_response"`
}

// controlActionCatalog is the Endpoint-local ctl. catalog the fixture node uses.
//
// The catalog is the only source of ctl. actions, so a fixture Endpoint without
// one advertises no action and refuses every ctl. operation. The two entries
// below are the ones the control tests exercise, and their permissions differ on
// purpose: heartbeat requires control while get_session_messages requires
// read_output, so a scope test can prove a refusal is specific to the missing
// scope instead of a blanket denial.
const controlActionCatalog = `{"actions": [
  {"name": "heartbeat", "permission": "control",
   "payload_schema": {"type": "object", "properties": {}},
   "command": ["runtime", "control", "heartbeat", "-s", "{session}", "-a", "{payload}", "--json"]},
  {"name": "get_session_messages", "permission": "read_output",
   "payload_schema": {"type": "object", "properties": {}},
   "payload_session_field": "session_id",
   "command": ["runtime", "control", "get_session_messages", "-s", "{session}", "-a", "{payload}", "--json"]}
]}
`

// TestCommandExecRunsInSessionDirectory proves an allowlisted argv array executes
// in the session working directory and reports a confirmed exit.
func TestCommandExecRunsInSessionDirectory(t *testing.T) {
	c := startExecCluster(t, "pwd\n")
	defer c.stop(t)
	postExecCommand(t, c, "exec-allowed", []string{"pwd"})
	view := waitExecCommand(t, c, "exec-allowed", func(v execCommandView) bool { return v.Status == "finished" })
	if view.EffectCertainty != "acknowledged" || !view.ExitConfirmed {
		t.Fatalf("expected an acknowledged confirmed exit, got %+v", view)
	}
	want, err := filepath.EvalSymlinks(c.sessionDir)
	if err != nil {
		t.Fatal(err)
	}
	var result struct {
		Stdout   string `json:"stdout"`
		ExitCode int    `json:"exit_code"`
	}
	if err := json.Unmarshal([]byte(view.ProviderResponse), &result); err != nil {
		t.Fatalf("decode provider response %q: %v", view.ProviderResponse, err)
	}
	if result.Stdout != want+"\n" {
		t.Fatalf("command ran in %q, want %q", result.Stdout, want+"\n")
	}
	if result.ExitCode != 0 {
		t.Fatalf("exit code=%d want=0", result.ExitCode)
	}
}

// TestCommandExecRejectsUnlistedCommand proves the Endpoint allowlist denies an
// argv array that no entry covers, and that the denial is terminal and not applied.
func TestCommandExecRejectsUnlistedCommand(t *testing.T) {
	c := startExecCluster(t, "pwd\n")
	defer c.stop(t)
	postExecCommand(t, c, "exec-denied", []string{"echo", "denied"})
	view := waitExecCommand(t, c, "exec-denied", func(v execCommandView) bool { return v.Status == "rejected" })
	if view.EffectCertainty != "not_applied" {
		t.Fatalf("expected not_applied, got %+v", view)
	}
	if view.ErrorCode != "policy_denied" {
		t.Fatalf("expected policy_denied, got %+v", view)
	}
}

// TestCommandExecRejectsWithoutAllowlist proves an Endpoint started without an
// allowlist file fails closed instead of permitting every command.
func TestCommandExecRejectsWithoutAllowlist(t *testing.T) {
	c := startExecCluster(t, "")
	defer c.stop(t)
	postExecCommand(t, c, "exec-unconfigured", []string{"pwd"})
	view := waitExecCommand(t, c, "exec-unconfigured", func(v execCommandView) bool { return v.Status == "rejected" })
	if view.EffectCertainty != "not_applied" || view.ErrorCode != "policy_denied" {
		t.Fatalf("expected a policy denial, got %+v", view)
	}
}

// startExecCluster builds the Server, the Endpoint and both provider fixtures, then
// waits for the fixture inventory to be committed. The Server credential is left
// unrestricted, which is the single-administrator deployment.
func startExecCluster(t *testing.T, allowlist string) *execCluster {
	t.Helper()
	return startExecClusterWithScopes(t, allowlist, "")
}

// startExecClusterWithScopes starts the same cluster with an explicit Server
// operator scope list, so a test can prove admission honours a restricted
// credential instead of only the unrestricted default.
func startExecClusterWithScopes(t *testing.T, allowlist, scopes string) *execCluster {
	t.Helper()
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	serverBinary := filepath.Join(root, "server")
	endpointBinary := filepath.Join(root, "endpoint")
	// Both provider entry points must share one directory: the adapter resolves
	// topsailai_session_info as a sibling of the configured executable and never
	// through PATH.
	providerDir := filepath.Join(root, "provider")
	build(t, serverBinary, "./src/main/agent-cluster-server")
	build(t, endpointBinary, "./src/main/agent-cluster-endpoint")
	// The source directories carry a _fixture suffix so they never collide with
	// the real provider tree, while the built binaries keep the provider names
	// the adapter resolves.
	build(t, filepath.Join(providerDir, "topsailai"), "./tests/fixtures/topsailai_fixture")
	build(t, filepath.Join(providerDir, "topsailai_session_info"), "./tests/fixtures/topsailai_session_info_fixture")
	c := &execCluster{
		root: root, api: free(t),
		serverDB:   filepath.Join(root, "server.db"),
		endpointDB: filepath.Join(root, "endpoint.db"),
		sessionDir: filepath.Join(root, "session"),
	}
	if err := os.MkdirAll(c.sessionDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if allowlist != "" {
		c.allowlist = filepath.Join(root, "allowlist.conf")
		if err := os.WriteFile(c.allowlist, []byte(allowlist), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	// The ctl. catalog is written for every cluster, not only for the control
	// tests, because the Endpoint advertises its capabilities once at startup and
	// the inventory the tests wait for is the same document. A catalog that
	// appeared only for some tests would make the advertised capability list
	// depend on which test ran first.
	c.controlActions = filepath.Join(root, "control-actions.conf")
	if err := os.WriteFile(c.controlActions, []byte(controlActionCatalog), 0o600); err != nil {
		t.Fatal(err)
	}
	channel := free(t)
	c.server = exec.Command(serverBinary)
	c.server.Dir = moduleRoot(t)
	serverEnv := append(os.Environ(),
		"AGENT_CLUSTER_API_LISTEN_ADDR=127.0.0.1:"+c.api,
		"AGENT_CLUSTER_CHANNEL_LISTEN_ADDR=127.0.0.1:"+channel,
		"AGENT_CLUSTER_DATABASE_PATH="+c.serverDB,
		"AGENT_CLUSTER_AUTH_TOKEN=secret",
		"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.serverCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+certs.serverKey,
	)
	if scopes != "" {
		serverEnv = append(serverEnv, "AGENT_CLUSTER_AUTH_SCOPES="+scopes)
	}
	c.server.Env = serverEnv
	c.server.Stdout, c.server.Stderr = os.Stdout, os.Stderr
	if err := c.server.Start(); err != nil {
		t.Fatal(err)
	}
	waitHTTP(t, c.url("/healthz"), "", http.StatusOK, 15*time.Second)
	adapters := fmt.Sprintf(`AGENT_CLUSTER_ADAPTERS=[{"adapter_id":"topsailai-main","provider_type":"topsailai","command":%q,"timeout_ms":5000}]`, filepath.Join(providerDir, "topsailai"))
	endpointEnv := append(os.Environ(),
		"AGENT_CLUSTER_CHANNEL_ADDRESS=wss://127.0.0.1:"+channel,
		"AGENT_CLUSTER_ENDPOINT_ID=endpoint-1",
		"AGENT_CLUSTER_DATABASE_PATH="+c.endpointDB,
		"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey,
		"AGENT_CLUSTER_TEST_SESSION_DIR="+c.sessionDir,
		adapters,
	)
	if c.allowlist != "" {
		endpointEnv = append(endpointEnv, "AGENT_CLUSTER_COMMAND_ALLOWLIST_FILE="+c.allowlist)
	}
	// The catalog path is passed explicitly so the Endpoint advertises the ctl.
	// actions the control tests address. Without it the Endpoint fails closed and
	// every ctl. operation is refused, which would make the control tests assert
	// the fail-closed default instead of the control channel.
	endpointEnv = append(endpointEnv, "AGENT_CLUSTER_CONTROL_ACTION_FILE="+c.controlActions)
	c.endpoint = exec.Command(endpointBinary)
	c.endpoint.Dir = moduleRoot(t)
	c.endpoint.Env = endpointEnv
	c.endpoint.Stdout, c.endpoint.Stderr = os.Stdout, os.Stderr
	if err := c.endpoint.Start(); err != nil {
		t.Fatal(err)
	}
	waitExecInventory(t, c.url("/api/v1/endpoints/endpoint-1/session-state"), 20*time.Second)
	return c
}

// waitExecInventory waits until the fixture adapter inventory is committed, so the
// Server can read the advertised command.exec capability before admission.
func waitExecInventory(t *testing.T, url string, limit time.Duration) {
	t.Helper()
	type adapterSummary struct {
		AdapterID string `json:"adapter_id"`
	}
	type payload struct {
		Adapters []adapterSummary `json:"adapters"`
		Sessions []struct {
			ResourceID string `json:"session_id"`
			Generation string `json:"generation"`
		} `json:"sessions"`
	}
	type envelope struct {
		Data payload `json:"data"`
	}
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		req, _ := http.NewRequest(http.MethodGet, url, nil)
		req.Header.Set("Authorization", "Bearer secret")
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			body, readErr := io.ReadAll(resp.Body)
			resp.Body.Close()
			var decoded envelope
			if readErr == nil && resp.StatusCode == http.StatusOK && json.Unmarshal(body, &decoded) == nil &&
				len(decoded.Data.Adapters) > 0 && decoded.Data.Adapters[0].AdapterID == "topsailai-main" &&
				len(decoded.Data.Sessions) > 0 && decoded.Data.Sessions[0].ResourceID != "" && decoded.Data.Sessions[0].Generation != "" {
				return
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("inventory %s did not publish the fixture adapter", url)
}

// postExecCommand admits one command.exec intent against the published session.
func postExecCommand(t *testing.T, c *execCluster, id string, argv []string) {
	t.Helper()
	payload, err := json.Marshal(map[string]any{"argv": argv})
	if err != nil {
		t.Fatal(err)
	}
	intent := map[string]any{
		"hash_version": "v1", "command_id": id, "endpoint_id": "endpoint-1",
		"launch_profile_id": "topsailai-main", "operation": "command.exec",
		"operation_version": "1", "capability_revision": "topsailai-v1",
		"payload_schema_version": "1", "payload": json.RawMessage(payload),
		"execute_before_at_ms": time.Now().Add(20 * time.Second).UnixMilli(),
	}
	if err := addExecTarget(c, intent); err != nil {
		t.Fatal(err)
	}
	body, err := json.Marshal(intent)
	if err != nil {
		t.Fatal(err)
	}
	req, err := http.NewRequest(http.MethodPost, c.url("/api/v1/commands"), bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusAccepted {
		data, _ := io.ReadAll(resp.Body)
		t.Fatalf("admit status=%d body=%s", resp.StatusCode, data)
	}
}

// addExecTarget attaches the opaque resource target published by the live inventory.
func addExecTarget(c *execCluster, intent map[string]any) error {
	req, err := http.NewRequest(http.MethodGet, c.url("/api/v1/endpoints/endpoint-1/session-state"), nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("inventory status=%d body=%s", resp.StatusCode, body)
	}
	var envelope struct {
		Data struct {
			Sessions []struct {
				ResourceID string `json:"session_id"`
				Generation string `json:"generation"`
			} `json:"sessions"`
		} `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
		return err
	}
	if len(envelope.Data.Sessions) == 0 || envelope.Data.Sessions[0].ResourceID == "" {
		return fmt.Errorf("inventory has no opaque target: %+v", envelope.Data.Sessions)
	}
	intent["target"] = map[string]any{"kind": "session", "resource_id": envelope.Data.Sessions[0].ResourceID, "generation": envelope.Data.Sessions[0].Generation}
	return nil
}

// waitExecCommand polls the durable command projection until done reports true.
func waitExecCommand(t *testing.T, c *execCluster, id string, done func(execCommandView) bool) execCommandView {
	t.Helper()
	deadline := time.Now().Add(20 * time.Second)
	var last execCommandView
	for time.Now().Before(deadline) {
		req, _ := http.NewRequest(http.MethodGet, c.url("/api/v1/commands/"+id), nil)
		req.Header.Set("Authorization", "Bearer secret")
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			body, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			var envelope struct {
				Data execCommandView `json:"data"`
			}
			if resp.StatusCode == http.StatusOK && json.Unmarshal(body, &envelope) == nil {
				last = envelope.Data
				if done(last) {
					return last
				}
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("command %s did not reach the expected state: %+v", id, last)
	return last
}

// url builds one Server API URL.
func (c *execCluster) url(path string) string { return "http://127.0.0.1:" + c.api + path }

// stop terminates the Endpoint and Server by exact PID.
func (c *execCluster) stop(t *testing.T) {
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
