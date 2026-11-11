//go:build integration

package integration

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
	"topsailai_connector/internal/server"
	"topsailai_connector/internal/server/cli"
)

// regenerateFixture is a live Server and a live Node child process, so that
// `regenerate` runs in a different process from `run`.
//
// The process boundary is the whole point. A unit test can call RegenerateIdentity
// and then inspect a holder in the same process, but the defect this file exists to
// catch only appears when the writer and the reader are separate processes: the
// running Node read its identity at startup and nothing told it the file changed.
type regenerateFixture struct {
	serverURL   string
	clientToken security.Secret
	configDir   string
	policyPath  string
	scopeDir    string
	tunnelToken string
	nodeCommand *exec.Cmd
	nodeOutput  *syncBuffer
}

// newRegenerateFixture starts a Server in this process and a Node as a child
// process, then waits until the Node is registered and serving.
func newRegenerateFixture(t *testing.T) *regenerateFixture {
	t.Helper()

	root := t.TempDir()
	configDir := filepath.Join(root, "config")
	scopeDir := filepath.Join(root, "project")
	if err := os.MkdirAll(configDir, 0o700); err != nil {
		t.Fatalf("create the config directory: %v", err)
	}
	if err := os.MkdirAll(scopeDir, 0o755); err != nil {
		t.Fatalf("create the scope directory: %v", err)
	}
	if err := os.WriteFile(filepath.Join(scopeDir, "note.txt"), []byte("hello\n"), 0o644); err != nil {
		t.Fatalf("write the scope file: %v", err)
	}

	policyPath := filepath.Join(configDir, "policy.yaml")
	policy := "version: 1\nscopes:\n  project:\n    path: " + scopeDir +
		"\ngrants:\n  - scope: project\n    permissions: [read]\n"
	if err := os.WriteFile(policyPath, []byte(policy), 0o600); err != nil {
		t.Fatalf("write the policy file: %v", err)
	}

	tunnelToken := security.Secret("tunnel-token-for-the-regenerate-test")
	clientToken := security.Secret("client-token-for-the-regenerate-test")
	logger := slog.New(slog.DiscardHandler)

	registry := server.NewRegistry()
	listener, err := server.NewListener(server.Config{
		Listen:         "127.0.0.1:0",
		TunnelToken:    tunnelToken,
		ClientToken:    clientToken,
		RequestTimeout: 10 * time.Second,
	}, registry, logger)
	if err != nil {
		t.Fatalf("build the listener: %v", err)
	}

	serverContext, stopServer := context.WithCancel(context.Background())
	serverDone := make(chan error, 1)
	go func() {
		serverDone <- listener.Serve(serverContext)
	}()
	t.Cleanup(func() {
		stopServer()
		select {
		case err := <-serverDone:
			if err != nil {
				t.Errorf("the server returned %v, want nil after a clean shutdown", err)
			}
		case <-time.After(15 * time.Second):
			t.Error("the server did not stop")
		}
	})

	address := waitForBind(t, listener)

	environment := []string{
		"CONNECTOR_NODE_SERVER_URL=ws://" + address + server.ChannelPath,
		"CONNECTOR_NODE_TUNNEL_TOKEN=" + string(tunnelToken),
		"CONNECTOR_NODE_CONFIG_DIR=" + configDir,
		"CONNECTOR_NODE_POLICY_FILE=" + policyPath,
	}

	command, output := start(t, environment, "run")
	t.Cleanup(func() {
		stop(t, command)
	})

	waitForOutput(t, output, "connector-node ready", 30*time.Second)
	waitForRegistration(t, registry)

	return &regenerateFixture{
		serverURL:   "http://" + address,
		clientToken: clientToken,
		configDir:   configDir,
		policyPath:  policyPath,
		scopeDir:    scopeDir,
		tunnelToken: string(tunnelToken),
		nodeCommand: command,
		nodeOutput:  output,
	}
}

// vars returns the environment the child process needs, so a second invocation
// reads and writes the same identity file.
func (f *regenerateFixture) vars() []string {
	return []string{
		"CONNECTOR_NODE_SERVER_URL=ws://" + strings.TrimPrefix(f.serverURL, "http://") + server.ChannelPath,
		"CONNECTOR_NODE_TUNNEL_TOKEN=" + f.tunnelToken,
		"CONNECTOR_NODE_CONFIG_DIR=" + f.configDir,
		"CONNECTOR_NODE_POLICY_FILE=" + f.policyPath,
	}
}

// read sends one file.read with the given pair and returns the envelope.
func (f *regenerateFixture) read(t *testing.T, pair string) cli.Envelope {
	t.Helper()

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(cli.Options{
		ServerURL:   f.serverURL,
		ClientToken: f.clientToken,
		Pair:        pair,
		Operation:   protocol.OperationFileRead,
		Scope:       security.Scope("project"),
		Path:        "note.txt",
	})
	if err != nil {
		t.Fatalf("send the read with pair %q: %v", pair, err)
	}
	return envelope
}

// waitForCode polls until a read with the given pair answers with the wanted code.
//
// Polling rather than sleeping is required because the Node drops its channel and
// reconnects after a regeneration: a request sent during the reconnect is answered
// with node_offline, which is a correct answer to a different question. Waiting for
// the specific code proves the Node is back and has made a decision about the pair.
func (f *regenerateFixture) waitForCode(t *testing.T, pair string, want protocol.Code, timeout time.Duration) cli.Envelope {
	t.Helper()

	deadline := time.Now().Add(timeout)
	var last cli.Envelope
	for time.Now().Before(deadline) {
		last = f.read(t, pair)
		if last.Code == want {
			return last
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("a read with pair %q never answered with code %d (%s); last answer was %d (%s)",
		pair, want, want.Name(), last.Code, last.Message)
	return last
}

// TestRegenerateInvalidatesTheTokenOfARunningNode is the regression test for the
// defect where a running Node kept accepting the token it read at startup.
//
// The sequence is the one an operator performs after a token leak: regenerate, then
// confirm the leaked token no longer works. Before the fix the old token kept
// working and the new one was refused, which made regeneration useless as a
// revocation mechanism while the Node was running.
func TestRegenerateInvalidatesTheTokenOfARunningNode(t *testing.T) {
	fixture := newRegenerateFixture(t)

	before, err := runOnce(t, fixture.vars(), "id")
	if err != nil {
		t.Fatalf("run connector-node id: %v", err)
	}
	oldPair := strings.TrimSpace(before)

	if envelope := fixture.read(t, oldPair); !envelope.Succeeded() {
		t.Fatalf("the original pair was refused before any regeneration: %d %s", envelope.Code, envelope.Message)
	}

	after, err := runOnce(t, fixture.vars(), "regenerate", "--keep-id")
	if err != nil {
		t.Fatalf("run connector-node regenerate --keep-id: %v", err)
	}
	newPair := strings.TrimSpace(after)
	if newPair == oldPair {
		t.Fatalf("regenerate returned the same pair %q", newPair)
	}

	// The old token must stop working. This is the assertion the defect failed.
	fixture.waitForCode(t, oldPair, protocol.CodeUnauthenticated, 30*time.Second)

	// The new token must work, which proves the Node adopted the new pair rather
	// than simply refusing everything.
	if envelope := fixture.waitForCode(t, newPair, protocol.CodeSuccess, 30*time.Second); !envelope.Succeeded() {
		t.Fatalf("the regenerated pair was refused: %d %s", envelope.Code, envelope.Message)
	}
}

// TestRegenerateKeepIDKeepsTheRunningNodeAddressable proves the routing name
// survives a --keep-id regeneration, so the operator does not have to reconfigure
// the CLI's target.
//
// The identifier is the first half of the pair, so a Node that adopted the new
// token but announced the old identifier would be unreachable under the name the
// operator holds.
func TestRegenerateKeepIDKeepsTheRunningNodeAddressable(t *testing.T) {
	fixture := newRegenerateFixture(t)

	before, err := runOnce(t, fixture.vars(), "id")
	if err != nil {
		t.Fatalf("run connector-node id: %v", err)
	}
	oldPair := strings.TrimSpace(before)
	oldID := strings.SplitN(oldPair, ".", 2)[0]

	after, err := runOnce(t, fixture.vars(), "regenerate", "--keep-id")
	if err != nil {
		t.Fatalf("run connector-node regenerate --keep-id: %v", err)
	}
	newPair := strings.TrimSpace(after)
	newID := strings.SplitN(newPair, ".", 2)[0]

	if newID != oldID {
		t.Fatalf("--keep-id changed the identifier from %q to %q", oldID, newID)
	}

	// The same routing name must still resolve, now with the new secret.
	if envelope := fixture.waitForCode(t, newPair, protocol.CodeSuccess, 30*time.Second); !envelope.Succeeded() {
		t.Fatalf("the node is no longer addressable as %q: %d %s", newID, envelope.Code, envelope.Message)
	}
}

// TestRegenerateWithANewIdentifierMovesTheRunningNode proves a full regeneration
// moves the Node to a new routing name and retires the old one.
//
// A full regeneration changes both halves, so the old name must stop resolving and
// the new name must resolve. A Node that kept serving the old name would leave a
// retired identifier addressable.
func TestRegenerateWithANewIdentifierMovesTheRunningNode(t *testing.T) {
	fixture := newRegenerateFixture(t)

	before, err := runOnce(t, fixture.vars(), "id")
	if err != nil {
		t.Fatalf("run connector-node id: %v", err)
	}
	oldPair := strings.TrimSpace(before)

	after, err := runOnce(t, fixture.vars(), "regenerate")
	if err != nil {
		t.Fatalf("run connector-node regenerate: %v", err)
	}
	newPair := strings.TrimSpace(after)

	if strings.SplitN(newPair, ".", 2)[0] == strings.SplitN(oldPair, ".", 2)[0] {
		t.Fatalf("a full regeneration kept the identifier %q", strings.SplitN(oldPair, ".", 2)[0])
	}

	// The new name must resolve with the new secret.
	if envelope := fixture.waitForCode(t, newPair, protocol.CodeSuccess, 30*time.Second); !envelope.Succeeded() {
		t.Fatalf("the regenerated pair was refused: %d %s", envelope.Code, envelope.Message)
	}

	// The old name must no longer resolve. The answer is node_offline rather than
	// unauthenticated, because the Server routes by the identifier and the Node no
	// longer announces the old one.
	fixture.waitForCode(t, oldPair, protocol.CodeNodeOffline, 30*time.Second)
}
