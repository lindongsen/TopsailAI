//go:build integration && testhooks

package integration_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// TestEndpointRefusesARemovedProviderType proves a configuration that still names
// a removed adapter fails at startup instead of being accepted.
//
// The Endpoint ships exactly one adapter implementation, so a provider type is a
// name to validate, not a selector. Before this change the name chose a factory
// through a switch, which meant a stale configuration could reach provider-specific
// Endpoint code. The failure mode that matters is silent acceptance: an Endpoint
// that starts with "topsailai" and then fails on the first operation looks like a
// provider defect, so an operator debugs the wrong component.
//
// The assertion is on the process, not on a helper: the binary must exit non-zero
// and say which type this node implements, because that message is what an operator
// reads to fix the configuration.
func TestEndpointRefusesARemovedProviderType(t *testing.T) {
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	endpointBinary := filepath.Join(root, "endpoint")
	build(t, endpointBinary, "./src/main/agent-cluster-endpoint")

	for _, providerType := range []string{"topsailai", "fixture", "command"} {
		t.Run(providerType, func(t *testing.T) {
			adapters := `[{"adapter_id":"stale","provider_type":"` + providerType + `","command":"/bin/true","timeout_ms":5000}]`
			cmd := exec.Command(endpointBinary)
			cmd.Dir = moduleRoot(t)
			cmd.Env = append(os.Environ(),
				"AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS=wss://127.0.0.1:"+free(t),
				"AGENT_CLUSTER_ENDPOINT_ID=endpoint-1",
				"AGENT_CLUSTER_DATABASE_PATH="+filepath.Join(root, "endpoint-"+providerType+".db"),
				"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
				"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert,
				"AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey,
				"AGENT_CLUSTER_ENDPOINT_ADAPTERS="+adapters,
			)
			output, err := cmd.CombinedOutput()
			if err == nil {
				t.Fatalf("endpoint accepted provider type %q and kept running: %s", providerType, output)
			}
			// The process must have exited on its own, not been killed by the test.
			var exitErr *exec.ExitError
			if !asExitError(err, &exitErr) {
				t.Fatalf("endpoint did not exit with a status for %q: %v", providerType, err)
			}
			text := string(output)
			if !strings.Contains(text, "is not registered") {
				t.Fatalf("endpoint did not report the unregistered type for %q: %s", providerType, text)
			}
			if !strings.Contains(text, "genericcli") {
				t.Fatalf("endpoint did not name the implemented type for %q: %s", providerType, text)
			}
		})
	}
}

// asExitError reports whether err is an exit status and stores it.
//
// It exists so the test can distinguish "the Endpoint refused the configuration and
// exited" from "the test failed to start the process at all". A start failure would
// make the assertion pass for the wrong reason.
func asExitError(err error, target **exec.ExitError) bool {
	exitErr, ok := err.(*exec.ExitError)
	if !ok {
		return false
	}
	*target = exitErr
	return true
}

// TestEndpointAcceptsTheShippedProviderType is the reverse case: the shipped name
// must pass the name check, so the refusal above cannot pass by refusing everything.
//
// /bin/true is not a Provider CLI, so the Endpoint still exits. What matters is
// why: the output must not contain the unregistered-type message. A test that only
// asserted "the process exits" would pass even if every provider type were refused,
// which is exactly the regression the refusal test cannot see on its own.
func TestEndpointAcceptsTheShippedProviderType(t *testing.T) {
	root := t.TempDir()
	certs := makeIntegrationCerts(t, root)
	endpointBinary := filepath.Join(root, "endpoint")
	build(t, endpointBinary, "./src/main/agent-cluster-endpoint")

	adapters := `[{"adapter_id":"shipped","provider_type":"genericcli","command":"/bin/true","timeout_ms":5000}]`
	cmd := exec.Command(endpointBinary)
	cmd.Dir = moduleRoot(t)
	cmd.Env = append(os.Environ(),
		"AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS=wss://127.0.0.1:"+free(t),
		"AGENT_CLUSTER_ENDPOINT_ID=endpoint-1",
		"AGENT_CLUSTER_DATABASE_PATH="+filepath.Join(root, "endpoint.db"),
		"AGENT_CLUSTER_TLS_CA_FILE="+certs.ca,
		"AGENT_CLUSTER_TLS_CERTIFICATE_FILE="+certs.clientCert,
		"AGENT_CLUSTER_TLS_KEY_FILE="+certs.clientKey,
		"AGENT_CLUSTER_ENDPOINT_ADAPTERS="+adapters,
	)
	output, _ := cmd.CombinedOutput()
	text := string(output)
	if strings.Contains(text, "is not registered") {
		t.Fatalf("the shipped provider type was refused by the name check: %s", text)
	}
}
