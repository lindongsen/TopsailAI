//go:build integration

package integration_test

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// rehomeServer starts one real Server process with its own database and API port
// and returns its API base URL, channel address and process.
//
// Each Server owns a separate SQLite file, which is the whole point of the
// scenario: the Endpoint moves between two independent Servers, not between two
// replicas of one.
func rehomeServer(t *testing.T, root, name string, certs certFiles) (apiURL, channelAddress string, cmd *exec.Cmd) {
	t.Helper()
	serverBin := filepath.Join(root, "server")
	api, channel := free(t), free(t)
	db := filepath.Join(root, name+".db")
	cmd = exec.Command(serverBin)
	cmd.Dir = moduleRoot(t)
	cmd.Env = append(os.Environ(),
		"AGENT_CLUSTER_SERVER_API_LISTEN_ADDR=127.0.0.1:"+api,
		"AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR=127.0.0.1:"+channel,
		"AGENT_CLUSTER_DATABASE_PATH="+db,
		"AGENT_CLUSTER_SERVER_AUTH_TOKEN=secret",
		"AGENT_CLUSTER_SERVER_AUTH_MODE=bearer",
		"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.serverCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+certs.serverKey,
		"AGENT_CLUSTER_LOG_OUTPUT=stderr",
	)
	cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	if err := cmd.Start(); err != nil {
		t.Fatalf("start %s: %v", name, err)
	}
	t.Cleanup(func() { terminate(t, cmd) })
	apiURL = "http://127.0.0.1:" + api
	waitHTTP(t, apiURL+"/healthz", "", http.StatusOK, 15*time.Second)
	return apiURL, "wss://127.0.0.1:" + channel, cmd
}

// rehomeEndpoint starts one real Endpoint process pointed at the supplied
// ordered address list, using the mock Provider CLI.
//
// An optional writer receives the Endpoint's stdout and stderr. A test that must
// observe a reconnect passes a file so it can assert on the Endpoint's own log
// line; a test that only needs the process passes nothing and inherits the test
// output.
func rehomeEndpoint(t *testing.T, root string, certs certFiles, addresses []string, mock string, logTo ...io.Writer) *exec.Cmd {
	t.Helper()
	endpointBin := filepath.Join(root, "endpoint")
	endpointDB := filepath.Join(root, "endpoint.db")
	cmd := exec.Command(endpointBin)
	cmd.Dir = moduleRoot(t)
	joined := ""
	for i, address := range addresses {
		if i > 0 {
			joined += ","
		}
		joined += address
	}
	cmd.Env = append(os.Environ(),
		"AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESSES="+joined,
		"AGENT_CLUSTER_ENDPOINT_ID=endpoint-1",
		"AGENT_CLUSTER_ENDPOINT_AUTH_MODE=bearer",
		"AGENT_CLUSTER_DATABASE_PATH="+endpointDB,
		"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey,
		"AGENT_CLUSTER_ENDPOINT_ADAPTERS="+fmt.Sprintf(`[{"adapter_id":"fixture-main","provider_type":"genericcli","command":%q,"args":["--mode","one"],"timeout_ms":5000,"capabilities":%s}]`, mock, replaceCapabilities),
		"AGENT_CLUSTER_LOG_OUTPUT=stderr",
	)
	if len(logTo) > 0 && logTo[0] != nil {
		cmd.Stdout, cmd.Stderr = logTo[0], logTo[0]
	} else {
		cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
	}
	if err := cmd.Start(); err != nil {
		t.Fatalf("start endpoint: %v", err)
	}
	t.Cleanup(func() { terminate(t, cmd) })
	return cmd
}

// endpointOnline reports whether the Server at apiURL currently reports
// endpoint-1 as online.
func endpointOnline(t *testing.T, apiURL string) bool {
	t.Helper()
	request, err := http.NewRequest(http.MethodGet, apiURL+"/api/v1/endpoints", nil)
	if err != nil {
		t.Fatalf("build request: %v", err)
	}
	request.Header.Set("Authorization", "Bearer secret")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return false
	}
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		return false
	}
	var envelope struct {
		Data []struct {
			EndpointID      string `json:"endpoint_id"`
			ConnectionState string `json:"connection_state"`
		} `json:"data"`
	}
	if err := json.NewDecoder(response.Body).Decode(&envelope); err != nil {
		return false
	}
	for _, item := range envelope.Data {
		if item.EndpointID == "endpoint-1" {
			return item.ConnectionState == "online"
		}
	}
	return false
}

// waitEndpointOnlineOn polls until the named Server reports the Endpoint online.
func waitEndpointOnlineOn(t *testing.T, apiURL string, limit time.Duration) {
	t.Helper()
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if endpointOnline(t, apiURL) {
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatalf("endpoint-1 never became online on %s within %s", apiURL, limit)
}

// waitEndpointGone polls until the named Server no longer reports the Endpoint
// online, which is how a re-home is observed from the abandoned Server.
func waitEndpointGone(t *testing.T, apiURL string, limit time.Duration) {
	t.Helper()
	deadline := time.Now().Add(limit)
	for time.Now().Before(deadline) {
		if !endpointOnline(t, apiURL) {
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatalf("endpoint-1 stayed online on %s for %s after the Server stopped", apiURL, limit)
}

// TestEndpointRehomesToTheNextServerWhenTheFirstStops proves the requirement end
// to end with real processes: two independent Servers, one Endpoint configured
// with both addresses in order, and the mock Provider CLI.
//
// The Endpoint must move to the second Server on its own, without a restart and
// without operator action. A restart would prove nothing, because a restarted
// process starts with an empty generation and would connect for the wrong reason.
//
// Scope of the claim: this test proves the requirement is satisfied, not that the
// detach fix is what satisfies it. Both Servers are fresh, so both fences start
// at 1, and the Endpoint's held generation is also 1; Attach accepts an equal
// generation, so the move succeeds even without the fix. The discriminating
// proof lives in TestEndpointAdoptsALowerGenerationFromADifferentServer, which
// forces the Endpoint to hold a higher generation first.
func TestEndpointRehomesToTheNextServerWhenTheFirstStops(t *testing.T) {
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	build(t, filepath.Join(root, "server"), "./src/main/agent-cluster-server")
	build(t, filepath.Join(root, "endpoint"), "./src/main/agent-cluster-endpoint")
	mock := filepath.Join(root, "mock")
	buildProviderModule(t, mock, filepath.Join(moduleRoot(t), "providers", "mock"))

	firstAPI, firstChannel, firstServer := rehomeServer(t, root, "server-a", certs)
	secondAPI, secondChannel, _ := rehomeServer(t, root, "server-b", certs)

	rehomeEndpoint(t, root, certs, []string{firstChannel, secondChannel}, mock)

	// The Endpoint must prefer the first address, so the first Server is the one
	// that observes it. This also proves the list is walked in order rather than
	// in reverse.
	waitEndpointOnlineOn(t, firstAPI, 30*time.Second)
	if endpointOnline(t, secondAPI) {
		t.Fatal("the second Server also reports the Endpoint online, so the Endpoint connected to both")
	}

	// Stop the first Server. The Endpoint must move to the second on its own.
	if err := firstServer.Process.Signal(os.Interrupt); err != nil {
		t.Fatalf("stop the first server: %v", err)
	}
	waitEndpointGone(t, firstAPI, 30*time.Second)
	waitEndpointOnlineOn(t, secondAPI, 60*time.Second)

	// The re-homed Endpoint must be fully functional, not merely connected: a
	// connection that cannot serve inventory would look online and be useless.
	waitInventory(t, secondAPI+"/api/v1/endpoints/endpoint-1/session-state", "secret", 30*time.Second)
}

// TestEndpointStartsOnTheSecondServerWhenTheFirstIsUnreachable proves the
// fall-through path at startup, which is the case an operator hits when the
// preferred Server is already down before the Endpoint boots.
func TestEndpointStartsOnTheSecondServerWhenTheFirstIsUnreachable(t *testing.T) {
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	build(t, filepath.Join(root, "server"), "./src/main/agent-cluster-server")
	build(t, filepath.Join(root, "endpoint"), "./src/main/agent-cluster-endpoint")
	mock := filepath.Join(root, "mock")
	buildProviderModule(t, mock, filepath.Join(moduleRoot(t), "providers", "mock"))

	// The first address is a port nothing listens on, so the Endpoint must skip it.
	deadChannel := "wss://127.0.0.1:" + free(t)
	liveAPI, liveChannel, _ := rehomeServer(t, root, "server-b", certs)

	rehomeEndpoint(t, root, certs, []string{deadChannel, liveChannel}, mock)

	waitEndpointOnlineOn(t, liveAPI, 60*time.Second)
	waitInventory(t, liveAPI+"/api/v1/endpoints/endpoint-1/session-state", "secret", 30*time.Second)
}
