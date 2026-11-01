//go:build integration

package integration_test

import (
	"bytes"
	"context"
	"database/sql"
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

	_ "modernc.org/sqlite"

	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

type u12Cluster struct {
	root, api, serverDB, endpointDB, record, record2 string
	server, endpoint, endpoint2                      *exec.Cmd
}

// TestReceiptAckLossDoesNotReexecute verifies durable receipt retry without a second provider call.
func TestReceiptAckLossDoesNotReexecute(t *testing.T) {
	c := startU12Cluster(t, map[string]string{"AGENT_CLUSTER_TEST_DROP_ACK": "1"}, false)
	defer c.stop(t)
	postU12Command(t, c, "u12-ack-loss", time.Time{})
	waitRecordCount(t, c.record, 1)
	r := waitCommand(t, c, "u12-ack-loss", func(r commandView) bool { return r.EffectCertainty == "acknowledged" })
	if r.EffectCertainty != "acknowledged" {
		t.Fatalf("receipt was not persisted: %+v", r)
	}
}

// TestRestartDoesNotReplayExecutedCommand verifies journal and command persistence across restart.
func TestRestartDoesNotReplayExecutedCommand(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	postU12Command(t, c, "u12-restart", time.Time{})
	want := waitCommand(t, c, "u12-restart", func(r commandView) bool { return r.Status == "finished" })
	c.stop(t)
	c = restartU12Cluster(t, c)
	defer c.stop(t)
	waitRecordCount(t, c.record, 1)
	got := waitCommand(t, c, "u12-restart", func(r commandView) bool { return r.Status == "finished" })
	if got.Status != want.Status || got.EffectCertainty != want.EffectCertainty {
		t.Fatalf("command changed after restart: before=%+v after=%+v", want, got)
	}
}

// TestInvocationStartedWithoutReceiptReportsUnknown verifies recovery never re-invokes an uncertain call.
func TestInvocationStartedWithoutReceiptReportsUnknown(t *testing.T) {
	root := t.TempDir()
	endpointDB := filepath.Join(root, "endpoint.db")
	intent := u12ProtocolIntent("u12-unknown", "endpoint-1", time.Time{})
	store, err := endpointstorage.Open(context.Background(), endpointDB)
	if err != nil {
		t.Fatal(err)
	}
	mapping, err := store.GetOrCreateResourceID(context.Background(), "fixture-main", "fixture-session", time.Now().UnixMilli())
	if err != nil {
		t.Fatal(err)
	}
	intent.Target = &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, Generation: "fixture-generation"}
	// Match the authenticated identity injected by the Server before hashing.
	intent.IssuerID = "operator"
	hash, err := protocol.CanonicalHash(intent)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err = store.AdmitJournal(context.Background(), intent, hash, time.Now().UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if err = store.MarkInvocationStarted(context.Background(), intent.CommandID, time.Now().UnixMilli()); err != nil {
		t.Fatal(err)
	}
	if err = store.Close(); err != nil {
		t.Fatal(err)
	}
	c := startU12ClusterAt(t, root, nil, false)
	defer c.stop(t)
	postU12Intent(t, c, intent)
	r := waitCommand(t, c, "u12-unknown", func(r commandView) bool { return r.EffectCertainty == "unknown" })
	if r.EffectCertainty != "unknown" {
		t.Fatalf("expected unknown effect certainty, got %+v", r)
	}
	assertRecordCount(t, c.record, 0)
}

// TestCancelBeforeDispatch verifies cancellation wins during the admitted dispatch window.
func TestCancelBeforeDispatch(t *testing.T) {
	c := startU12Cluster(t, map[string]string{"AGENT_CLUSTER_TEST_DISPATCH_DELAY_MS": "2000"}, false)
	defer c.stop(t)
	postDone := make(chan error, 1)
	go func() { postDone <- postU12CommandErr(c, "u12-cancel-before", time.Time{}) }()
	waitCommand(t, c, "u12-cancel-before", func(r commandView) bool { return r.Status == "admitted" })
	status, body := cancelU12Command(t, c, "u12-cancel-before")
	if status != http.StatusOK {
		t.Fatalf("cancel status=%d body=%s", status, body)
	}
	if !bytes.Contains(body, []byte("cancelled_before_execution")) {
		t.Fatalf("unexpected cancel response: %s", body)
	}
	if err := <-postDone; err != nil {
		t.Fatalf("admission request failed: %v", err)
	}
	final := waitCommand(t, c, "u12-cancel-before", func(r commandView) bool { return r.Status == string(protocol.StatusCancelled) })
	if final.Status != string(protocol.StatusCancelled) {
		t.Fatalf("expected cancelled final status, got %+v", final)
	}
	assertRecordCount(t, c.record, 0)
}

// TestCancelAfterDispatchTooLate verifies an already dispatched command cannot be cancelled.
func TestCancelAfterDispatchTooLate(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	defer c.stop(t)
	postU12Command(t, c, "u12-cancel-late", time.Time{})
	waitCommand(t, c, "u12-cancel-late", func(r commandView) bool { return r.Status == "dispatched" || r.Status == "finished" })
	status, body := cancelU12Command(t, c, "u12-cancel-late")
	if status != http.StatusConflict || !bytes.Contains(body, []byte("too_late_to_cancel")) {
		t.Fatalf("expected too_late_to_cancel: status=%d body=%s", status, body)
	}
}

// TestExecuteBeforeExpiredNotApplied verifies expired commands have no provider effect.
// TestRestartDoesNotReplayRejectedCommand verifies a durable early rejection is not re-executed after restart.
func TestRestartDoesNotReplayRejectedCommand(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	postU12Command(t, c, "u12-rejected-restart", time.Now().Add(-time.Second))
	rejected := waitCommand(t, c, "u12-rejected-restart", func(r commandView) bool { return r.EffectCertainty == "not_applied" })
	if rejected.EffectCertainty != "not_applied" || rejected.Status == "finished" {
		t.Fatalf("unexpected rejection result: %+v", rejected)
	}
	c.stop(t)
	c = restartU12Cluster(t, c)
	defer c.stop(t)
	assertRecordCount(t, c.record, 0)
	got := waitCommand(t, c, "u12-rejected-restart", func(r commandView) bool { return r.EffectCertainty == "not_applied" })
	if got.EffectCertainty != "not_applied" {
		t.Fatalf("rejected command changed after restart: %+v", got)
	}
}

func TestExecuteBeforeExpiredNotApplied(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	defer c.stop(t)
	postU12Command(t, c, "u12-expired", time.Now().Add(-time.Second))
	r := waitCommand(t, c, "u12-expired", func(r commandView) bool { return r.EffectCertainty == "not_applied" })
	if r.EffectCertainty != "not_applied" {
		t.Fatalf("expected not_applied, got %+v", r)
	}
	assertRecordCount(t, c.record, 0)
}

// TestSameTargetSerialized verifies two commands for one target do not overlap.
func TestSameTargetSerialized(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	defer c.stop(t)
	postU12Command(t, c, "u12-serial-1", time.Time{})
	postU12Command(t, c, "u12-serial-2", time.Time{})
	waitRecordCount(t, c.record, 2)
	entries := readRecords(t, c.record)
	if len(entries) != 2 {
		t.Fatalf("record count=%d want=2", len(entries))
	}
	if entries[1].StartNS < entries[0].StartNS {
		entries[0], entries[1] = entries[1], entries[0]
	}
	t.Logf("serialized execution intervals: first=[%d,%d] second=[%d,%d]", entries[0].StartNS, entries[0].EndNS, entries[1].StartNS, entries[1].EndNS)
	if entries[1].StartNS < entries[0].EndNS {
		t.Fatalf("target executions overlap: first=[%d,%d] second=[%d,%d]", entries[0].StartNS, entries[0].EndNS, entries[1].StartNS, entries[1].EndNS)
	}
}

// TestCrossEndpointSameSessionNotMisrouted verifies endpoint identity selects the execution target.
func TestCrossEndpointSameSessionNotMisrouted(t *testing.T) {
	c := startU12Cluster(t, nil, true)
	defer c.stop(t)
	postU12Command(t, c, "u12-routing", time.Time{})
	waitRecordCount(t, c.record, 1)
	waitRecordCount(t, c.record2, 0)
	if c.endpoint == nil || c.endpoint2 == nil {
		t.Fatal("both endpoints were not started")
	}
	r := waitCommand(t, c, "u12-routing", func(r commandView) bool { return r.Status == "finished" })
	if r.EndpointID != "endpoint-1" {
		t.Fatalf("command routed to %q, want endpoint-1", r.EndpointID)
	}
}

type commandView struct {
	Status          string `json:"Status"`
	EffectCertainty string `json:"EffectCertainty"`
	EndpointID      string `json:"EndpointID"`
}
type recordView struct {
	TimestampNS int64 `json:"timestamp_ns"`
	StartNS     int64 `json:"start_ns"`
	EndNS       int64 `json:"end_ns"`
}

func u12Intent(id, endpoint string, expiry time.Time) map[string]any {
	intent := u12ProtocolIntent(id, endpoint, expiry)
	return map[string]any{
		"hash_version": intent.HashVersion, "command_id": intent.CommandID, "endpoint_id": intent.EndpointID,
		"launch_profile_id": intent.LaunchProfileID, "operation": intent.Operation,
		"operation_version": intent.OperationVersion, "capability_revision": intent.CapabilityRevision,
		"payload_schema_version": intent.PayloadSchemaVersion, "payload": intent.Payload,
		"execute_before_at_ms": intent.ExecuteBeforeAtMS,
	}
}

func u12ProtocolIntent(id, endpoint string, expiry time.Time) protocol.ImmutableIntent {
	d := time.Now().Add(20 * time.Second).UnixMilli()
	if !expiry.IsZero() {
		d = expiry.UnixMilli()
	}
	return protocol.ImmutableIntent{
		HashVersion: "v1", CommandID: id, EndpointID: endpoint, LaunchProfileID: "fixture-main",
		Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "v1",
		PayloadSchemaVersion: "v1", Payload: json.RawMessage(`{"text":"u12"}`), ExecuteBeforeAtMS: d,
	}
}

// addU12Target adds the opaque resource target published by the live inventory.
func addU12Target(c *u12Cluster, intent map[string]any) error {
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
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("inventory status=%d body=%s", resp.StatusCode, b)
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
	if len(envelope.Data.Sessions) == 0 || envelope.Data.Sessions[0].ResourceID == "" || envelope.Data.Sessions[0].Generation == "" {
		return fmt.Errorf("inventory has no opaque target: %+v", envelope.Data.Sessions)
	}
	intent["target"] = map[string]any{"kind": "session", "resource_id": envelope.Data.Sessions[0].ResourceID, "generation": envelope.Data.Sessions[0].Generation}
	return nil
}

func postU12CommandErr(c *u12Cluster, id string, expiry time.Time) error {
	intent := u12Intent(id, "endpoint-1", expiry)
	if err := addU12Target(c, intent); err != nil {
		return err
	}
	b, err := json.Marshal(intent)
	if err != nil {
		return err
	}
	req, err := http.NewRequest(http.MethodPost, c.url("/api/v1/commands"), bytes.NewReader(b))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusAccepted {
		data, _ := io.ReadAll(resp.Body)
		if (resp.StatusCode == http.StatusConflict || resp.StatusCode == http.StatusServiceUnavailable) && bytes.Contains(data, []byte("command is no longer dispatchable")) {
			return nil
		}
		return fmt.Errorf("admit status=%d body=%s", resp.StatusCode, data)
	}
	return nil
}
func postU12Command(t *testing.T, c *u12Cluster, id string, expiry time.Time) {
	t.Helper()
	intent := u12Intent(id, "endpoint-1", expiry)
	if err := addU12Target(c, intent); err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(intent)
	req, _ := http.NewRequest(http.MethodPost, c.url("/api/v1/commands"), bytes.NewReader(b))
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

func postU12Intent(t *testing.T, c *u12Cluster, intent protocol.ImmutableIntent) {
	t.Helper()
	payload := u12Intent(intent.CommandID, intent.EndpointID, time.UnixMilli(intent.ExecuteBeforeAtMS))
	payload["target"] = map[string]any{"kind": "session", "resource_id": intent.Target.ResourceID, "generation": intent.Target.Generation}
	b, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	req, err := http.NewRequest(http.MethodPost, c.url("/api/v1/commands"), bytes.NewReader(b))
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

func cancelU12Command(t *testing.T, c *u12Cluster, id string) (int, []byte) {
	req, _ := http.NewRequest(http.MethodPost, c.url("/api/v1/commands/"+id+"/cancel"), nil)
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, b
}
func waitCommand(t *testing.T, c *u12Cluster, id string, done func(commandView) bool) commandView {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	var last commandView
	for time.Now().Before(deadline) {
		req, _ := http.NewRequest(http.MethodGet, c.url("/api/v1/commands/"+id), nil)
		req.Header.Set("Authorization", "Bearer secret")
		resp, err := http.DefaultClient.Do(req)
		if err == nil {
			b, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			var env struct {
				Data commandView `json:"data"`
			}
			if resp.StatusCode == http.StatusOK && json.Unmarshal(b, &env) == nil {
				last = env.Data
				if done(last) {
					return last
				}
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("command %s did not reach expected state: %+v", id, last)
	return last
}
func (c *u12Cluster) url(path string) string { return "http://127.0.0.1:" + c.api + path }
func waitRecordCount(t *testing.T, path string, n int) {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if len(readRecords(t, path)) == n {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("record count did not reach %d", n)
}
func assertRecordCount(t *testing.T, path string, n int) {
	t.Helper()
	time.Sleep(300 * time.Millisecond)
	if got := len(readRecords(t, path)); got != n {
		t.Fatalf("record count=%d want=%d", got, n)
	}
}
func readRecords(t *testing.T, path string) []recordView {
	t.Helper()
	b, err := os.ReadFile(path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	var out []recordView
	for _, line := range bytes.Split(bytes.TrimSpace(b), []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		var r recordView
		if json.Unmarshal(line, &r) != nil {
			t.Fatalf("invalid record: %s", line)
		}
		out = append(out, r)
	}
	return out
}

func startU12Cluster(t *testing.T, env map[string]string, second bool) *u12Cluster {
	return startU12ClusterAt(t, t.TempDir(), env, second)
}
func startU12ClusterAt(t *testing.T, root string, extra map[string]string, second bool) *u12Cluster {
	t.Helper()
	certs := makeIntegrationCerts(t, root)
	sb, eb, fb := filepath.Join(root, "server"), filepath.Join(root, "endpoint"), filepath.Join(root, "fixture")
	build(t, sb, "./src/main/agent-cluster-server")
	build(t, eb, "./src/main/agent-cluster-endpoint")
	build(t, fb, "./tests/fixtures/provider")
	c := &u12Cluster{root: root, api: free(t), serverDB: filepath.Join(root, "server.db"), endpointDB: filepath.Join(root, "endpoint.db"), record: filepath.Join(root, "records.jsonl"), record2: filepath.Join(root, "records-2.jsonl")}
	channel := free(t)
	senv := append(os.Environ(), "AGENT_CLUSTER_API_LISTEN_ADDR=127.0.0.1:"+c.api, "AGENT_CLUSTER_CHANNEL_LISTEN_ADDR=127.0.0.1:"+channel, "AGENT_CLUSTER_DATABASE_PATH="+c.serverDB, "AGENT_CLUSTER_AUTH_TOKEN=secret", "AGENT_CLUSTER_TLS_CA_FILE="+certs.ca, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.serverCert, "AGENT_CLUSTER_TLS_KEY_FILE="+certs.serverKey)
	for k, v := range extra {
		senv = append(senv, k+"="+v)
	}
	c.server = exec.Command(sb)
	c.server.Dir = moduleRoot(t)
	c.server.Env = senv
	c.server.Stdout, c.server.Stderr = os.Stdout, os.Stderr
	if err := c.server.Start(); err != nil {
		t.Fatal(err)
	}
	waitHTTP(t, c.url("/healthz"), "", http.StatusOK, 15*time.Second)
	c.endpoint = exec.Command(eb)
	c.endpoint.Dir = moduleRoot(t)
	c.endpoint.Env = append(os.Environ(), "AGENT_CLUSTER_CHANNEL_ADDRESS=wss://127.0.0.1:"+channel, "AGENT_CLUSTER_ENDPOINT_ID=endpoint-1", "AGENT_CLUSTER_DATABASE_PATH="+c.endpointDB, "AGENT_CLUSTER_TLS_CA_FILE="+certs.ca, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert, "AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey, fmt.Sprintf(`AGENT_CLUSTER_ADAPTERS=[{"adapter_id":"fixture-main","provider_type":"fixture","command":%q,"args":["--mode","one","--record-file",%q,"--delay-ms","100"],"timeout_ms":5000}]`, fb, c.record))
	c.endpoint.Stdout, c.endpoint.Stderr = os.Stdout, os.Stderr
	if err := c.endpoint.Start(); err != nil {
		t.Fatal(err)
	}
	waitInventory(t, c.url("/api/v1/endpoints/endpoint-1/session-state"), "secret", 20*time.Second)
	if second {
		c.endpoint2 = exec.Command(eb)
		c.endpoint2.Dir = moduleRoot(t)
		endpointDB2 := filepath.Join(root, "endpoint-2.db")
		c.endpoint2.Env = append(os.Environ(), "AGENT_CLUSTER_CHANNEL_ADDRESS=wss://127.0.0.1:"+channel, "AGENT_CLUSTER_ENDPOINT_ID=endpoint-2", "AGENT_CLUSTER_DATABASE_PATH="+endpointDB2, "AGENT_CLUSTER_TLS_CA_FILE="+certs.ca, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert2, "AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey2, fmt.Sprintf(`AGENT_CLUSTER_ADAPTERS=[{"adapter_id":"fixture-main","provider_type":"fixture","command":%q,"args":["--mode","one","--record-file",%q,"--delay-ms","100"],"timeout_ms":5000}]`, fb, c.record2))
		c.endpoint2.Stdout, c.endpoint2.Stderr = os.Stdout, os.Stderr
		if err := c.endpoint2.Start(); err != nil {
			t.Fatal(err)
		}
		waitInventory(t, c.url("/api/v1/endpoints/endpoint-2/session-state"), "secret", 20*time.Second)
	}
	return c
}
func restartU12Cluster(t *testing.T, c *u12Cluster) *u12Cluster {
	return startU12ClusterAt(t, c.root, nil, false)
}
func (c *u12Cluster) stop(t *testing.T) {
	t.Helper()
	for _, p := range []*exec.Cmd{c.endpoint, c.endpoint2, c.server} {
		if p != nil && p.Process != nil {
			_ = syscall.Kill(p.Process.Pid, syscall.SIGTERM)
			done := make(chan error, 1)
			go func() { done <- p.Wait() }()
			select {
			case <-done:
			case <-time.After(30 * time.Second):
				t.Fatalf("process did not stop")
			}
		}
	}
}

// Compile-time reference keeps the SQL driver available to journal setup extensions.
var _ = sql.ErrNoRows
