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

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
	"topsailai_connector/internal/server"
	"topsailai_connector/internal/server/cli"
)

// regenerateFixture is a live Server and a live Node child process, so that
// `regenerate` and `credential remove` run in a different process from `run`.
//
// The process boundary is the whole point. A unit test can call RegenerateIdentity
// and then inspect a holder in the same process, but the defect this file exists to
// catch only appears when the writer and the reader are separate processes: the
// running Node read its identity and its credentials at startup and nothing told it
// the files changed.
type regenerateFixture struct {
	serverURL        string
	clientCredential security.Credential
	nodeCredential   security.Credential
	configDir        string
	policyPath       string
	scopeDir         string
	tunnelToken      string
	nodeCommand      *exec.Cmd
	nodeOutput       *syncBuffer
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
	clientCredential := mustCredential(t, "client-for-the-regenerate-test")
	logger := slog.New(slog.DiscardHandler)

	registry := server.NewRegistry()
	listener, err := server.NewListener(server.Config{
		Listen:            "127.0.0.1:0",
		TunnelToken:       tunnelToken,
		ClientCredentials: mustCredentialSet(t, clientCredential),
		RequestTimeout:    10 * time.Second,
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

	// The first start generates the credential, and the line naming it is the only
	// place the secret is printed. It is captured here because the CLI must present
	// it, and there is no command that reads a secret back.
	text := waitForOutput(t, output, "node credential generated: ", 30*time.Second)
	credentialLine := lineAfter(text, "node credential generated: ")
	nodeCredential, err := security.ParseCredential(credentialLine)
	if err != nil {
		t.Fatalf("parse the generated node credential %q: %v", credentialLine, err)
	}

	waitForOutput(t, output, "connector-node ready", 30*time.Second)
	waitForRegistration(t, registry)

	return &regenerateFixture{
		serverURL:        "http://" + address,
		clientCredential: clientCredential,
		nodeCredential:   nodeCredential,
		configDir:        configDir,
		policyPath:       policyPath,
		scopeDir:         scopeDir,
		tunnelToken:      string(tunnelToken),
		nodeCommand:      command,
		nodeOutput:       output,
	}
}

// lineAfter returns the first line that follows the marker, trimmed.
//
// The generated credential is printed on the same line as its marker, so the value
// is the remainder of that line. Splitting on the marker rather than scanning for a
// pattern keeps the helper from matching a different line that happens to look like
// a credential.
func lineAfter(text string, marker string) string {
	index := strings.Index(text, marker)
	if index < 0 {
		return ""
	}
	remainder := text[index+len(marker):]
	if newline := strings.IndexByte(remainder, '\n'); newline >= 0 {
		remainder = remainder[:newline]
	}
	return strings.TrimSpace(remainder)
}

// vars returns the environment the child process needs, so a second invocation
// reads and writes the same identity and credential files.
func (f *regenerateFixture) vars() []string {
	return []string{
		"CONNECTOR_NODE_SERVER_URL=ws://" + strings.TrimPrefix(f.serverURL, "http://") + server.ChannelPath,
		"CONNECTOR_NODE_TUNNEL_TOKEN=" + f.tunnelToken,
		"CONNECTOR_NODE_CONFIG_DIR=" + f.configDir,
		"CONNECTOR_NODE_POLICY_FILE=" + f.policyPath,
	}
}

// nodeID returns the identifier the Node currently announces.
//
// It is read from the identity file rather than from a running command, because the
// file is what the running Node polls. Reading it here is what makes the assertion
// about the value the Node will adopt rather than about the value a command printed.
func (f *regenerateFixture) nodeID(t *testing.T) string {
	t.Helper()
	nodeID, err := node.LoadIdentity(node.IdentityPath(f.configDir))
	if err != nil {
		t.Fatalf("read the identity file: %v", err)
	}
	return nodeID
}

// read sends one file.read with the given node id and credential and returns the
// envelope.
func (f *regenerateFixture) read(t *testing.T, nodeID string, credential security.Credential) cli.Envelope {
	t.Helper()

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(cli.Options{
		ServerURL:        f.serverURL,
		ClientCredential: f.clientCredential,
		NodeCredential:   credential,
		NodeID:           nodeID,
		Operation:        protocol.OperationFileRead,
		Scope:            security.Scope("project"),
		Path:             "note.txt",
	})
	if err != nil {
		t.Fatalf("send the read for node %q: %v", nodeID, err)
	}
	return envelope
}

// waitForCode polls until a read answers with the wanted code.
//
// Polling rather than sleeping is required because the Node drops its channel and
// reconnects after an identity change: a request sent during the reconnect is
// answered with node_offline, which is a correct answer to a different question.
// Waiting for the specific code proves the Node is back and has made a decision.
func (f *regenerateFixture) waitForCode(t *testing.T, nodeID string, credential security.Credential, want protocol.Code, timeout time.Duration) cli.Envelope {
	t.Helper()

	deadline := time.Now().Add(timeout)
	var last cli.Envelope
	for time.Now().Before(deadline) {
		last = f.read(t, nodeID, credential)
		if last.Code == want {
			return last
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("a read for node %q never answered with code %d (%s); last answer was %d (%s)",
		nodeID, want, want.Name(), last.Code, last.Message)
	return last
}

// TestRegenerateMovesTheRunningNodeToANewAddress proves a regeneration changes the
// address the running Node answers to.
//
// Regeneration changes the address and nothing else. The credential the caller holds
// stays valid, which is the property that makes an address change a routine
// operation rather than a coordinated revocation.
func TestRegenerateMovesTheRunningNodeToANewAddress(t *testing.T) {
	fixture := newRegenerateFixture(t)

	oldID := fixture.nodeID(t)
	if envelope := fixture.read(t, oldID, fixture.nodeCredential); !envelope.Succeeded() {
		t.Fatalf("the original address was refused before any regeneration: %d %s", envelope.Code, envelope.Message)
	}

	if _, err := runOnce(t, fixture.vars(), "regenerate"); err != nil {
		t.Fatalf("run connector-node regenerate: %v", err)
	}

	newID := fixture.nodeID(t)
	if newID == oldID {
		t.Fatalf("regenerate kept the identifier %q", oldID)
	}

	// The new address must resolve with the same credential, which proves the
	// credential was not touched by the regeneration.
	if envelope := fixture.waitForCode(t, newID, fixture.nodeCredential, protocol.CodeSuccess, 30*time.Second); !envelope.Succeeded() {
		t.Fatalf("the regenerated address was refused: %d %s", envelope.Code, envelope.Message)
	}

	// The old address must no longer resolve. The answer is node_offline rather than
	// unauthenticated, because the Server routes by the identifier and the Node no
	// longer announces the old one.
	fixture.waitForCode(t, oldID, fixture.nodeCredential, protocol.CodeNodeOffline, 30*time.Second)
}

// TestRegenerateKeepsTheCredentialValid proves regeneration does not revoke a
// caller.
//
// The two values answer different questions, so a routine address change must not
// lock every caller out. Before the split, regeneration replaced the token and the
// operator had to copy a new value into every CLI.
func TestRegenerateKeepsTheCredentialValid(t *testing.T) {
	fixture := newRegenerateFixture(t)

	before := fixture.nodeID(t)
	if envelope := fixture.read(t, before, fixture.nodeCredential); !envelope.Succeeded() {
		t.Fatalf("the original read was refused: %d %s", envelope.Code, envelope.Message)
	}

	if _, err := runOnce(t, fixture.vars(), "regenerate"); err != nil {
		t.Fatalf("run connector-node regenerate: %v", err)
	}

	after := fixture.nodeID(t)
	if after == before {
		t.Fatalf("regenerate kept the identifier %q", before)
	}

	// The same credential must still authorize an operation on the new address.
	if envelope := fixture.waitForCode(t, after, fixture.nodeCredential, protocol.CodeSuccess, 30*time.Second); !envelope.Succeeded() {
		t.Fatalf("the credential stopped working after a regeneration: %d %s", envelope.Code, envelope.Message)
	}
}

// TestCredentialRemovalRevokesARunningNode proves removing a credential from the
// file revokes it on the running Node without a restart.
//
// This is the revocation mechanism the design promises. A Node that kept accepting a
// removed credential would make revocation a restart-time operation, and an operator
// responding to a leak would have to stop the Node to end the exposure.
func TestCredentialRemovalRevokesARunningNode(t *testing.T) {
	fixture := newRegenerateFixture(t)

	nodeID := fixture.nodeID(t)
	if envelope := fixture.read(t, nodeID, fixture.nodeCredential); !envelope.Succeeded() {
		t.Fatalf("the credential was refused before removal: %d %s", envelope.Code, envelope.Message)
	}

	// A second credential is added first, because removing the last one is refused:
	// a Node with no credential accepts nothing, which looks like a policy that
	// denies everything.
	added, err := runOnce(t, fixture.vars(), "credential", "add", "--key-id", "replacement")
	if err != nil {
		t.Fatalf("run connector-node credential add: %v", err)
	}
	replacement, err := security.ParseCredential(strings.TrimSpace(added))
	if err != nil {
		t.Fatalf("parse the added credential %q: %v", strings.TrimSpace(added), err)
	}

	// The new credential must work before the old one is removed, so the removal is
	// not the reason it works.
	if envelope := fixture.waitForCode(t, nodeID, replacement, protocol.CodeSuccess, 30*time.Second); !envelope.Succeeded() {
		t.Fatalf("the added credential was refused: %d %s", envelope.Code, envelope.Message)
	}

	if _, err := runOnce(t, fixture.vars(), "credential", "remove", "--key-id", fixture.nodeCredential.KeyID); err != nil {
		t.Fatalf("run connector-node credential remove: %v", err)
	}

	// The removed credential must stop working within one poll interval.
	fixture.waitForCode(t, nodeID, fixture.nodeCredential, protocol.CodeUnauthenticated, 30*time.Second)

	// The replacement must still work, which proves the Node adopted the new set
	// rather than refusing everything.
	if envelope := fixture.waitForCode(t, nodeID, replacement, protocol.CodeSuccess, 30*time.Second); !envelope.Succeeded() {
		t.Fatalf("the replacement credential was refused after the removal: %d %s", envelope.Code, envelope.Message)
	}
}

// TestCredentialRemovalDoesNotDropTheChannel proves a credential change keeps the
// live channel.
//
// The channel was authenticated with the tunnel token, which is a different secret.
// Dropping a working channel because an operator revoked an unrelated caller would
// be a self-inflicted outage, and the Node would reconnect for no reason.
func TestCredentialRemovalDoesNotDropTheChannel(t *testing.T) {
	fixture := newRegenerateFixture(t)

	nodeID := fixture.nodeID(t)

	added, err := runOnce(t, fixture.vars(), "credential", "add", "--key-id", "second-caller")
	if err != nil {
		t.Fatalf("run connector-node credential add: %v", err)
	}
	second, err := security.ParseCredential(strings.TrimSpace(added))
	if err != nil {
		t.Fatalf("parse the added credential: %v", err)
	}

	if _, err := runOnce(t, fixture.vars(), "credential", "remove", "--key-id", second.KeyID); err != nil {
		t.Fatalf("run connector-node credential remove: %v", err)
	}

	// The original credential must keep working immediately, without waiting for a
	// reconnect. A dropped channel would answer node_offline for a moment, so a
	// single successful read right after the removal is the evidence that the channel
	// survived.
	envelope := fixture.read(t, nodeID, fixture.nodeCredential)
	if !envelope.Succeeded() {
		t.Fatalf("the channel did not survive a credential change: %d %s", envelope.Code, envelope.Message)
	}
}
