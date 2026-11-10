//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"testing"
	"time"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
	"topsailai_connector/internal/server"
	"topsailai_connector/internal/server/cli"
)

// endToEndFixture is one live Server and one live Node wired over a real socket.
//
// Nothing here is a double: the Server binds a real port, the Node dials it, and
// the CLI talks HTTP to the same listener. The point of this layer is that the
// three secrets and the path fence work together across a process boundary, which
// a unit test with a fake connection cannot prove.
type endToEndFixture struct {
	serverURL   string
	clientToken security.Secret
	pair        string
	scopeDir    string
	fileName    string
	fileContent []byte
}

// newEndToEndFixture starts a Server and a Node and waits until the Node is
// registered, so a test never races the handshake.
func newEndToEndFixture(t *testing.T) *endToEndFixture {
	t.Helper()

	root := t.TempDir()
	scopeDir := filepath.Join(root, "project")
	if err := os.MkdirAll(scopeDir, 0o755); err != nil {
		t.Fatalf("create the scope directory: %v", err)
	}

	// The content is deliberately not valid UTF-8 at the end, so a transport that
	// silently treated the payload as a string would corrupt it and the byte
	// comparison below would catch that.
	content := []byte("connector end to end\n\xff\xfe")
	fileName := "note.txt"
	if err := os.WriteFile(filepath.Join(scopeDir, fileName), content, 0o644); err != nil {
		t.Fatalf("write the scope file: %v", err)
	}

	policyPath := filepath.Join(root, "policy.yaml")
	policy := "version: 1\nscopes:\n  project:\n    path: " + scopeDir +
		"\ngrants:\n  - scope: project\n    permissions: [read]\n"
	if err := os.WriteFile(policyPath, []byte(policy), 0o644); err != nil {
		t.Fatalf("write the policy file: %v", err)
	}

	tunnelToken := security.Secret("tunnel-token-for-the-end-to-end-test")
	clientToken := security.Secret("client-token-for-the-end-to-end-test")
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

	// The config directory must exist before Open: Load creates it, but this test
	// builds Config directly, so it owns that step.
	configDir := filepath.Join(root, "node")
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatalf("create the node config directory: %v", err)
	}

	runtime, err := node.Open(node.Config{
		ServerURL:   "ws://" + address + server.ChannelPath,
		TunnelToken: tunnelToken,
		ConfigDir:   configDir,
		PolicyPath:  policyPath,
	}, logger)
	if err != nil {
		t.Fatalf("open the node runtime: %v", err)
	}
	t.Cleanup(func() {
		if err := runtime.Close(); err != nil {
			t.Errorf("close the node runtime: %v", err)
		}
	})

	identity, _ := runtime.NewIdentity()
	dispatcher := node.NewDispatcher(runtime.Authority(), identity, logger)
	dialer, err := node.NewDialer(runtime.Config(), identity, dispatcher, logger)
	if err != nil {
		t.Fatalf("build the dialer: %v", err)
	}

	nodeContext, stopNode := context.WithCancel(context.Background())
	nodeDone := make(chan error, 1)
	go func() {
		nodeDone <- dialer.Run(nodeContext)
	}()
	t.Cleanup(func() {
		stopNode()
		select {
		case err := <-nodeDone:
			if err != nil {
				t.Errorf("the dialer returned %v, want nil after a clean shutdown", err)
			}
		case <-time.After(15 * time.Second):
			t.Error("the dialer did not stop")
		}
	})

	waitForRegistration(t, registry)

	return &endToEndFixture{
		serverURL:   "http://" + address,
		clientToken: clientToken,
		pair:        identity.String(),
		scopeDir:    scopeDir,
		fileName:    fileName,
		fileContent: content,
	}
}

// waitForBind returns the address the listener bound.
//
// Addr reports the configured address until Serve has bound, so a different value
// means the kernel has chosen a port. Polling the public accessor rather than the
// private field keeps this test free of the data race the accessor exists to
// prevent.
func waitForBind(t *testing.T, listener *server.Listener) string {
	t.Helper()

	deadline := time.Now().Add(15 * time.Second)
	for {
		if address := listener.Addr(); address != "127.0.0.1:0" {
			return address
		}
		if time.Now().After(deadline) {
			t.Fatal("the listener did not bind")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// waitForRegistration waits until the Node has completed the handshake.
//
// The CLI request would otherwise race the handshake and be answered with
// node_offline, which is a correct answer to a different question.
func waitForRegistration(t *testing.T, registry *server.Registry) {
	t.Helper()

	deadline := time.Now().Add(15 * time.Second)
	for {
		if registry.Len() == 1 {
			return
		}
		if time.Now().After(deadline) {
			t.Fatal("the node did not register")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// readResult mirrors the payload the Node returns for file.read.
type readResult struct {
	Content   []byte `json:"content"`
	Size      int64  `json:"size"`
	Truncated bool   `json:"truncated"`
}

// TestEndToEndFileRead drives one file.read from the CLI through the Server to the
// Node and back, over a real socket.
//
// This is the test that proves the three secrets are wired to the three gates: the
// tunnel token opened the channel, the client token opened the Server, and the node
// token authorized the operation on the Node. A unit test with a fake connection
// can prove each gate in isolation but not that they compose.
func TestEndToEndFileRead(t *testing.T) {
	fixture := newEndToEndFixture(t)

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(cli.Options{
		ServerURL:   fixture.serverURL,
		ClientToken: fixture.clientToken,
		Pair:        fixture.pair,
		Operation:   protocol.OperationFileRead,
		Scope:       security.Scope("project"),
		Path:        fixture.fileName,
	})
	if err != nil {
		t.Fatalf("send the read: %v", err)
	}
	if !envelope.Succeeded() {
		t.Fatalf("the read was refused with code %d and message %q", envelope.Code, envelope.Message)
	}

	var result readResult
	if err := json.Unmarshal(envelope.Data, &result); err != nil {
		t.Fatalf("decode the read payload: %v", err)
	}
	if string(result.Content) != string(fixture.fileContent) {
		t.Fatalf("content is %q, want %q", result.Content, fixture.fileContent)
	}
	if result.Size != int64(len(fixture.fileContent)) {
		t.Fatalf("size is %d, want %d", result.Size, len(fixture.fileContent))
	}
	if result.Truncated {
		t.Fatal("a short file was reported as truncated")
	}
}

// TestEndToEndRefusesAWrongClientToken proves the Server's own gate answers before
// the request reaches the Node.
func TestEndToEndRefusesAWrongClientToken(t *testing.T) {
	fixture := newEndToEndFixture(t)

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(cli.Options{
		ServerURL:   fixture.serverURL,
		ClientToken: security.Secret("not-the-client-token"),
		Pair:        fixture.pair,
		Operation:   protocol.OperationFileRead,
		Scope:       security.Scope("project"),
		Path:        fixture.fileName,
	})
	if err != nil {
		t.Fatalf("send the read: %v", err)
	}
	if envelope.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code is %d, want %d", envelope.Code, protocol.CodeUnauthenticated)
	}
	if len(envelope.Data) != 0 {
		t.Fatalf("a refusal carried data: %s", envelope.Data)
	}
}

// TestEndToEndRefusesAWrongNodeToken proves the Node's own gate answers, and that
// the Server relays that refusal rather than deciding it.
func TestEndToEndRefusesAWrongNodeToken(t *testing.T) {
	fixture := newEndToEndFixture(t)

	identity, err := security.ParseNodeIdentity(fixture.pair)
	if err != nil {
		t.Fatalf("parse the pair: %v", err)
	}
	wrongPair := identity.ID + "." + string(security.Secret("notthetoken"))

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(cli.Options{
		ServerURL:   fixture.serverURL,
		ClientToken: fixture.clientToken,
		Pair:        wrongPair,
		Operation:   protocol.OperationFileRead,
		Scope:       security.Scope("project"),
		Path:        fixture.fileName,
	})
	if err != nil {
		t.Fatalf("send the read: %v", err)
	}
	if envelope.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code is %d, want %d", envelope.Code, protocol.CodeUnauthenticated)
	}
}

// TestEndToEndRefusesAPathOutsideTheScope proves the fence holds across the wire.
//
// The path is refused by the Node, not by the Server, because only the Node knows
// where the scope directory is. A Server that refused it would be guessing.
func TestEndToEndRefusesAPathOutsideTheScope(t *testing.T) {
	fixture := newEndToEndFixture(t)

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(cli.Options{
		ServerURL:   fixture.serverURL,
		ClientToken: fixture.clientToken,
		Pair:        fixture.pair,
		Operation:   protocol.OperationFileRead,
		Scope:       security.Scope("project"),
		Path:        "../policy.yaml",
	})
	if err != nil {
		t.Fatalf("send the read: %v", err)
	}
	if envelope.Succeeded() {
		t.Fatal("a path outside the scope was served")
	}
	if len(envelope.Data) != 0 {
		t.Fatalf("a refusal carried data: %s", envelope.Data)
	}
}

// TestEndToEndRefusesAnUngrantedPermission proves default deny across the wire.
//
// The policy grants read only, so a list on the same scope must be refused even
// though the scope exists and the token is valid.
func TestEndToEndRefusesAnUngrantedPermission(t *testing.T) {
	fixture := newEndToEndFixture(t)

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(cli.Options{
		ServerURL:   fixture.serverURL,
		ClientToken: fixture.clientToken,
		Pair:        fixture.pair,
		Operation:   protocol.OperationFileList,
		Scope:       security.Scope("project"),
		Path:        "",
	})
	if err != nil {
		t.Fatalf("send the list: %v", err)
	}
	if envelope.Code != protocol.CodeDenied {
		t.Fatalf("code is %d, want %d", envelope.Code, protocol.CodeDenied)
	}
}
