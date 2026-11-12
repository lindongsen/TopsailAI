//go:build integration

package integration_test

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// TestCommandRoundTrip verifies the real API-to-WSS-to-provider receipt path.
func TestCommandRoundTrip(t *testing.T) {
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	serverBin, endpointBin, fixture := filepath.Join(root, "server"), filepath.Join(root, "endpoint"), filepath.Join(root, "fixture")
	build(t, serverBin, "./src/main/agent-cluster-server")
	build(t, endpointBin, "./src/main/agent-cluster-endpoint")
	build(t, fixture, "./tests/fixtures/provider")
	api, channel := free(t), free(t)
	serverDB, endpointDB := filepath.Join(root, "server.db"), filepath.Join(root, "endpoint.db")
	server := exec.Command(serverBin)
	server.Dir = moduleRoot(t)
	server.Env = append(os.Environ(), "AGENT_CLUSTER_SERVER_API_LISTEN_ADDR=127.0.0.1:"+api, "AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR=127.0.0.1:"+channel, "AGENT_CLUSTER_DATABASE_PATH="+serverDB, "AGENT_CLUSTER_SERVER_AUTH_TOKEN=secret", "AGENT_CLUSTER_TLS_CA_FILE="+certs.ca, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.serverCert, "AGENT_CLUSTER_TLS_KEY_FILE="+certs.serverKey)
	server.Stdout, server.Stderr = os.Stdout, os.Stderr
	if err := server.Start(); err != nil {
		t.Fatal(err)
	}
	defer terminate(t, server)
	waitHTTP(t, "http://127.0.0.1:"+api+"/healthz", "", http.StatusOK, 15*time.Second)
	endpoint := exec.Command(endpointBin)
	endpoint.Dir = moduleRoot(t)
	endpoint.Env = append(os.Environ(), "AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS=wss://127.0.0.1:"+channel, "AGENT_CLUSTER_ENDPOINT_ID=endpoint-1", "AGENT_CLUSTER_DATABASE_PATH="+endpointDB, "AGENT_CLUSTER_TLS_CA_FILE="+certs.ca, "AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert, "AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey, "AGENT_CLUSTER_ENDPOINT_ADAPTERS="+`[{"adapter_id":"fixture-main","provider_type":"fixture","command":"`+fixture+`","args":["--mode","one"],"timeout_ms":5000}]`)
	endpoint.Stdout, endpoint.Stderr = os.Stdout, os.Stderr
	if err := endpoint.Start(); err != nil {
		t.Fatal(err)
	}
	defer terminate(t, endpoint)
	waitInventory(t, "http://127.0.0.1:"+api+"/api/v1/endpoints/endpoint-1/session-state", "secret", 20*time.Second)
	intent := map[string]any{"hash_version": "v1", "command_id": "cmd-roundtrip", "endpoint_id": "endpoint-1", "launch_profile_id": "fixture-main", "operation": "message.send", "operation_version": "v1", "capability_revision": "v1", "payload_schema_version": "v1", "payload": json.RawMessage(`{"text":"hello"}`), "execute_before_at_ms": time.Now().Add(20 * time.Second).UnixMilli()}
	if err := addU12Target(&u12Cluster{api: api}, intent); err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(intent)
	request, _ := http.NewRequest(http.MethodPost, "http://127.0.0.1:"+api+"/api/v1/commands", bytes.NewReader(body))
	request.Header.Set("Authorization", "Bearer secret")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusAccepted {
		t.Fatalf("command admission status %d", response.StatusCode)
	}
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		request, _ := http.NewRequest(http.MethodGet, "http://127.0.0.1:"+api+"/api/v1/commands/cmd-roundtrip", nil)
		request.Header.Set("Authorization", "Bearer secret")
		response, err := http.DefaultClient.Do(request)
		if err == nil {
			data, readErr := io.ReadAll(response.Body)
			response.Body.Close()
			var envelope struct {
				Data struct {
					Status          string `json:"Status"`
					EffectCertainty string `json:"EffectCertainty"`
				} `json:"data"`
			}
			if readErr == nil && response.StatusCode == http.StatusOK && json.Unmarshal(data, &envelope) == nil && envelope.Data.Status == "finished" && envelope.Data.EffectCertainty == "acknowledged" {
				return
			}
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("command did not reach acknowledged finished state")
}
