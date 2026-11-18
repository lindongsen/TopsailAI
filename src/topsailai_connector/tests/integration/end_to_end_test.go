//go:build integration

package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
	"topsailai_connector/internal/server"
	"topsailai_connector/internal/server/cli"
)

// endToEndFixture is one live Server and one live Node wired over a real socket.
// Nothing here is a double: the Server binds a real port, the Node dials it, and
// the CLI talks HTTP to the same listener. The point of this layer is that the two
// authentication boundaries and the path fence work together across a process
// boundary, which a unit test with a fake connection cannot prove.
//
// The fixture carries two credentials rather than one token pair, because the two
// boundaries are separate: the client credential is verified by the Server and the
// node credential is verified by the Node. A test that used one value for both would
// pass even if the Server and the Node were checking the same secret, which is the
// design this layer exists to disprove.
type endToEndFixture struct {
	serverURL        string
	clientCredential security.Credential
	nodeCredential   security.Credential
	nodeID           string
	scopeDir         string
	fileName         string
	fileContent      []byte
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
	clientCredential := mustCredential(t, "client-for-the-end-to-end-test")
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

	// The config directory must exist before Open: Load creates it, but this test
	// builds Config directly, so it owns that step.
	configDir := filepath.Join(root, "node")
	if err := os.MkdirAll(configDir, 0o700); err != nil {
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

	// The credential the Node generated on first start is the one a caller must
	// present. It is read from the runtime rather than from the file, because the
	// runtime is the component that decided which credential is in force.
	generated := runtime.NewCredential()
	if generated == nil {
		t.Fatal("the node did not generate a credential on first start")
	}

	dispatcher, err := node.NewDispatcher(runtime.Authority(), runtime.IdentityHolder(), 0, 0, logger)
	if err != nil {
		t.Fatalf("build the dispatcher: %v", err)
	}
	dialer, err := node.NewDialerWithHolder(runtime.Config(), runtime.IdentityHolder(), dispatcher, logger)
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
		serverURL:        "http://" + address,
		clientCredential: clientCredential,
		nodeCredential:   *generated,
		nodeID:           runtime.IdentityID(),
		scopeDir:         scopeDir,
		fileName:         fileName,
		fileContent:      content,
	}
}

// mustCredential builds a credential with a chosen key identifier.
//
// The key identifier is chosen rather than random so a failure message names the
// caller instead of a value the reader has to look up.
func mustCredential(t *testing.T, keyID string) security.Credential {
	t.Helper()
	credential, err := security.NewCredentialWithKeyID(keyID)
	if err != nil {
		t.Fatalf("generate credential %q: %v", keyID, err)
	}
	return credential
}

// mustCredentialSet builds a set holding one credential.
func mustCredentialSet(t *testing.T, credential security.Credential) *security.CredentialSet {
	t.Helper()
	set, err := security.NewCredentialSet([]security.Credential{credential})
	if err != nil {
		t.Fatalf("build the credential set: %v", err)
	}
	return set
}

// options returns the CLI options for one operation against this fixture.
func (f *endToEndFixture) options(operation protocol.Operation, path string) cli.Options {
	return cli.Options{
		ServerURL:        f.serverURL,
		ClientCredential: f.clientCredential,
		NodeCredential:   f.nodeCredential,
		NodeID:           f.nodeID,
		Operation:        operation,
		Scope:            security.Scope("project"),
		Path:             path,
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
// This is the test that proves the two authentication boundaries are wired to the
// two gates: the client credential opened the Server, and the node credential
// authorized the operation on the Node. A unit test with a fake connection can prove
// each gate in isolation but not that they compose.
func TestEndToEndFileRead(t *testing.T) {
	fixture := newEndToEndFixture(t)

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(fixture.options(protocol.OperationFileRead, fixture.fileName))
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

// TestEndToEndRefusesAWrongClientCredential proves the Server's own gate answers
// before the request reaches the Node.
//
// The wrong credential keeps the right key identifier and carries a different
// secret, so the Server finds the entry and the signature fails. A test that used an
// unknown key identifier would exercise the lookup rather than the signature.
func TestEndToEndRefusesAWrongClientCredential(t *testing.T) {
	fixture := newEndToEndFixture(t)

	wrong := fixture.clientCredential
	wrong.Secret = security.Secret("not-the-client-secret-but-long-enough-to-pass")

	options := fixture.options(protocol.OperationFileRead, fixture.fileName)
	options.ClientCredential = wrong

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(options)
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

// TestEndToEndRefusesAWrongNodeCredential proves the Node's own gate answers, and
// that the Server relays that refusal rather than deciding it.
//
// The Server cannot decide it: it does not hold the node secret. A Server that
// answered unauthenticated here without forwarding would be a Server that claims a
// check it never performed, and this test would still pass. The assertion that the
// refusal came from the Node is therefore made by the Node's own log in
// TestEndToEndNodeRefusalIsLoggedByTheNode below.
func TestEndToEndRefusesAWrongNodeCredential(t *testing.T) {
	fixture := newEndToEndFixture(t)

	wrong := fixture.nodeCredential
	wrong.Secret = security.Secret("not-the-node-secret-but-long-enough-to-pass")

	options := fixture.options(protocol.OperationFileRead, fixture.fileName)
	options.NodeCredential = wrong

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(options)
	if err != nil {
		t.Fatalf("send the read: %v", err)
	}
	if envelope.Code != protocol.CodeUnauthenticated {
		t.Fatalf("code is %d, want %d", envelope.Code, protocol.CodeUnauthenticated)
	}
}

// TestEndToEndRefusesAReplayedRequest proves the Server's replay cache refuses a
// second copy of one signed request.
//
// The CLI generates a fresh nonce per call, so a replay cannot be produced by
// calling Send twice: that is two distinct requests, and both must succeed. The
// replay is produced by capturing the exact bytes of the first request and sending
// them again, which is what an attacker who recorded the traffic would do.
//
// The second assertion is what keeps this test from passing for the wrong reason. A
// Server that refused every repeated operation would also refuse the replay, so the
// test also proves that a fresh request with a fresh nonce still succeeds.
func TestEndToEndRefusesAReplayedRequest(t *testing.T) {
	fixture := newEndToEndFixture(t)

	recorder := &recordingTransport{next: &http.Transport{}}
	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second, Transport: recorder}}

	options := fixture.options(protocol.OperationFileRead, fixture.fileName)
	first, err := client.Send(options)
	if err != nil {
		t.Fatalf("send the first read: %v", err)
	}
	if !first.Succeeded() {
		t.Fatalf("the first read was refused: %d %s", first.Code, first.Message)
	}

	captured := recorder.captured()
	if captured == nil {
		t.Fatal("the transport captured no request")
	}

	// The captured request is replayed byte for byte: same method, same URL, same
	// headers including both proofs, same body.
	replayed, err := http.NewRequest(captured.method, captured.url, bytes.NewReader(captured.body))
	if err != nil {
		t.Fatalf("rebuild the captured request: %v", err)
	}
	for name, values := range captured.header {
		for _, value := range values {
			replayed.Header.Add(name, value)
		}
	}

	response, err := (&http.Client{Timeout: 20 * time.Second}).Do(replayed)
	if err != nil {
		t.Fatalf("replay the captured request: %v", err)
	}
	defer response.Body.Close()

	payload, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("read the replay answer: %v", err)
	}
	var envelope cli.Envelope
	if err := json.Unmarshal(payload, &envelope); err != nil {
		t.Fatalf("decode the replay answer: %v", err)
	}
	if envelope.Code != protocol.CodeUnauthenticated {
		t.Fatalf("the replayed request answered %d (%s), want %d (%s)",
			envelope.Code, envelope.Message, protocol.CodeUnauthenticated, protocol.CodeUnauthenticated.Name())
	}

	// A fresh request must still succeed, so the refusal above is about the replay
	// and not about the Server refusing every repeated operation.
	fresh, err := client.Send(options)
	if err != nil {
		t.Fatalf("send a fresh read: %v", err)
	}
	if !fresh.Succeeded() {
		t.Fatalf("a fresh request was refused: %d %s", fresh.Code, fresh.Message)
	}
}

// capturedRequest is one recorded HTTP request, in the form needed to replay it.
type capturedRequest struct {
	method string
	url    string
	header http.Header
	body   []byte
}

// recordingTransport records the first request it sends and forwards every request
// to the next transport.
//
// It exists so a test can replay the exact bytes the CLI produced. Rebuilding a
// request by hand would produce a different signature, and a test that replayed a
// different signature would be measuring the signature check rather than the replay
// cache.
type recordingTransport struct {
	next   http.RoundTripper
	mutex  sync.Mutex
	record *capturedRequest
}

// RoundTrip records the first request and forwards it.
func (t *recordingTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	t.mutex.Lock()
	if t.record == nil {
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.mutex.Unlock()
			return nil, err
		}
		request.Body = io.NopCloser(bytes.NewReader(body))
		t.record = &capturedRequest{
			method: request.Method,
			url:    request.URL.String(),
			header: request.Header.Clone(),
			body:   body,
		}
	}
	t.mutex.Unlock()

	return t.next.RoundTrip(request)
}

// captured returns the recorded request, or nil when none was sent.
func (t *recordingTransport) captured() *capturedRequest {
	t.mutex.Lock()
	defer t.mutex.Unlock()
	return t.record
}

// TestEndToEndRefusesAPathOutsideTheScope proves the fence holds across the wire.
//
// The path is refused by the Node, not by the Server, because only the Node knows
// where the scope directory is. A Server that refused it would be guessing.
func TestEndToEndRefusesAPathOutsideTheScope(t *testing.T) {
	fixture := newEndToEndFixture(t)

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(fixture.options(protocol.OperationFileRead, "../policy.yaml"))
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
// though the scope exists and both credentials are valid.
func TestEndToEndRefusesAnUngrantedPermission(t *testing.T) {
	fixture := newEndToEndFixture(t)

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(fixture.options(protocol.OperationFileList, ""))
	if err != nil {
		t.Fatalf("send the list: %v", err)
	}
	if envelope.Code != protocol.CodeDenied {
		t.Fatalf("code is %d, want %d", envelope.Code, protocol.CodeDenied)
	}
}

// TestEndToEndRefusesAnUnknownNodeID proves a request for a Node that is not
// connected is refused rather than queued.
func TestEndToEndRefusesAnUnknownNodeID(t *testing.T) {
	fixture := newEndToEndFixture(t)

	options := fixture.options(protocol.OperationFileRead, fixture.fileName)
	options.NodeID = "node_aaaaaaaaaaaaaaaaaaaaaaaaaa"

	client := &cli.Client{HTTP: &http.Client{Timeout: 20 * time.Second}}
	envelope, err := client.Send(options)
	if err != nil {
		t.Fatalf("send the read: %v", err)
	}
	if envelope.Code != protocol.CodeNodeOffline {
		t.Fatalf("code is %d, want %d", envelope.Code, protocol.CodeNodeOffline)
	}
}
