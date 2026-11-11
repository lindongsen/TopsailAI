package node

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// TestAdvertisedScopesListsThePolicyNames checks that the handshake advertises
// the scope names the policy defines, because an operator reading a log uses them
// to see what a Node offers without asking it.
func TestAdvertisedScopesListsThePolicyNames(t *testing.T) {
	fixture := newDispatchFixture(t)
	dialer := &Dialer{dispatcher: fixture.dispatcher, logger: slog.New(slog.DiscardHandler)}

	scopes := dialer.advertisedScopes()
	if len(scopes) != 2 {
		t.Fatalf("advertisedScopes() = %v, want two names", scopes)
	}
	if scopes[0] != "project" || scopes[1] != "scratch" {
		t.Fatalf("advertisedScopes() = %v, want [project scratch]", scopes)
	}
}

// TestAdvertisedScopesIsEmptyWithoutAnAuthority checks that a dispatcher with no
// authority advertises nothing instead of panicking.
//
// A nil authority is a legal dispatcher because it already refuses everything, so
// a crash during the handshake would turn a wiring mistake into a Node that
// cannot connect at all.
func TestAdvertisedScopesIsEmptyWithoutAnAuthority(t *testing.T) {
	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}

	dialer := &Dialer{
		dispatcher: NewDispatcher(nil, identity, slog.New(slog.DiscardHandler)),
		logger:     slog.New(slog.DiscardHandler),
	}
	if scopes := dialer.advertisedScopes(); scopes != nil {
		t.Fatalf("advertisedScopes() = %v, want nil", scopes)
	}
}

// TestDialReportsTheHTTPStatus checks that a refused upgrade names the status,
// because a proxy answering 407 and a Server answering 404 need different fixes
// and the error is the only place the operator learns which happened.
func TestDialReportsTheHTTPStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		writer.WriteHeader(http.StatusForbidden)
	}))
	t.Cleanup(server.Close)

	dialer := &Dialer{
		config: Config{ServerURL: "ws" + strings.TrimPrefix(server.URL, "http")},
		logger: slog.New(slog.DiscardHandler),
	}

	_, err := dialer.dial(context.Background())
	if err == nil {
		t.Fatal("dial() = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "403") {
		t.Fatalf("dial() error = %v, want the status in the message", err)
	}
}

// TestDialHonoursACancelledContext checks that a cancellation during the dial
// returns promptly instead of waiting for the dial timeout, because a shutdown
// must not wait for a network that is not answering.
func TestDialHonoursACancelledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	dialer := &Dialer{
		config: Config{ServerURL: "ws://127.0.0.1:1/channel"},
		logger: slog.New(slog.DiscardHandler),
	}

	started := time.Now()
	if _, err := dialer.dial(ctx); err == nil {
		t.Fatal("dial() = nil error, want a cancellation")
	}
	if elapsed := time.Since(started); elapsed > 5*time.Second {
		t.Fatalf("dial() took %s, want a prompt return", elapsed)
	}
}

// TestHandshakeRefusesAnUnreadableRefusal checks that a refusal frame whose
// payload does not decode is reported as a refusal rather than as a decode error,
// because the operator needs to know the Server said no, not how it said it.
func TestHandshakeRefusesAnUnreadableRefusal(t *testing.T) {
	fixture := newDialerFixture(t, func(protocol.Hello) []protocol.Frame {
		return []protocol.Frame{{Type: protocol.FrameError, Payload: []byte("not json")}}
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := fixture.dialer.connectOnce(ctx)
	if !errors.Is(err, ErrHandshakeRefused) {
		t.Fatalf("connectOnce() error = %v, want ErrHandshakeRefused", err)
	}
}

// TestHandshakeRefusesAnUndecodableFrame checks that a frame that is not JSON at
// all is reported, because a peer speaking something other than this protocol
// must not be mistaken for a peer that agreed.
func TestHandshakeRefusesAnUndecodableFrame(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		upgrader := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}
		conn, err := upgrader.Upgrade(writer, request, nil)
		if err != nil {
			return
		}
		defer func() {
			_ = conn.Close()
		}()
		if _, _, err := conn.ReadMessage(); err != nil {
			return
		}
		_ = conn.WriteMessage(websocket.TextMessage, []byte("not a frame"))
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	t.Cleanup(server.Close)

	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	config := Config{
		ServerURL:   "ws" + strings.TrimPrefix(server.URL, "http"),
		TunnelToken: security.Secret("tunnel-token-value-1234"),
		ConfigDir:   t.TempDir(),
	}
	dialer, err := NewDialer(config, identity, NewDispatcher(nil, identity, slog.New(slog.DiscardHandler)), slog.New(slog.DiscardHandler))
	if err != nil {
		t.Fatalf("NewDialer() error = %v", err)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := dialer.connectOnce(ctx); err == nil {
		t.Fatal("connectOnce() = nil error, want a decode refusal")
	}
}

// TestSaveIdentityReportsAnUnwritableDirectory checks that a directory that
// cannot hold the temporary file is reported, because a Node that silently failed
// to persist its identity would regenerate a pair on every start and invalidate
// every copy the operator distributed.
func TestSaveIdentityReportsAnUnwritableDirectory(t *testing.T) {
	parent := t.TempDir()
	missing := filepath.Join(parent, "absent")

	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}

	if err := SaveIdentity(filepath.Join(missing, "identity"), identity); err == nil {
		t.Fatal("SaveIdentity() = nil error, want a failure for a missing directory")
	}
}

// TestSaveIdentityRejectsAnInvalidToken checks that a token outside the generated
// alphabet is refused before anything is written, because a file holding a token
// the loader will reject is a Node that cannot start after a restart.
func TestSaveIdentityRejectsAnInvalidToken(t *testing.T) {
	configDir, identityPath := newIdentityFixture(t)

	identity := security.NodeIdentity{ID: "node_0123456789abcdefghijklmnop", Token: security.Secret("bad-token")}
	if err := SaveIdentity(identityPath, identity); err == nil {
		t.Fatal("SaveIdentity() = nil error, want a token refusal")
	}

	entries, err := os.ReadDir(configDir)
	if err != nil {
		t.Fatalf("ReadDir() error = %v", err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".identity-") {
			t.Fatalf("a temporary file %q survived a refused save", entry.Name())
		}
	}
}

// TestStatPayloadEncodesTheEntry checks that a successful stat encodes the
// documented shape, because a caller reads the size and the directory flag from
// it and a missing field would read as a zero.
func TestStatPayloadEncodesTheEntry(t *testing.T) {
	fixture := newDispatchFixture(t)
	writeFile(t, filepath.Join(fixture.project, "note.txt"), "hello")

	scope, ok := fixture.authority.Scope("project")
	if !ok {
		t.Fatal("Scope(project) = false, want true")
	}

	payload, err := statPayload(scope, protocol.Request{Path: "note.txt"})
	if err != nil {
		t.Fatalf("statPayload() error = %v", err)
	}

	var entry Entry
	if err := json.Unmarshal(payload, &entry); err != nil {
		t.Fatalf("Unmarshal() error = %v", err)
	}
	if entry.Size != 5 {
		t.Fatalf("size = %d, want 5", entry.Size)
	}
	if entry.Type != "file" {
		t.Fatalf("type = %q, want file", entry.Type)
	}
}

// TestStatPayloadReportsAMissingFile checks that a missing path is reported
// rather than encoded as an empty entry, because an empty entry reads as a file
// of size zero.
func TestStatPayloadReportsAMissingFile(t *testing.T) {
	fixture := newDispatchFixture(t)

	scope, ok := fixture.authority.Scope("project")
	if !ok {
		t.Fatal("Scope(project) = false, want true")
	}

	if _, err := statPayload(scope, protocol.Request{Path: "absent.txt"}); err == nil {
		t.Fatal("statPayload() = nil error, want a missing-file refusal")
	}
}

// TestPerformRefusesAnOperationWithNoHandler checks that an operation that passed
// authorization but has no handler is reported as internal, because a success
// with no data is indistinguishable from an empty file.
func TestPerformRefusesAnOperationWithNoHandler(t *testing.T) {
	fixture := newDispatchFixture(t)

	scope, ok := fixture.authority.Scope("project")
	if !ok {
		t.Fatal("Scope(project) = false, want true")
	}

	_, err := fixture.dispatcher.perform(scope, protocol.Request{Operation: protocol.Operation("file.nonexistent")})
	if err == nil {
		t.Fatal("perform() = nil error, want an internal refusal")
	}
	if code := CodeOf(err); code != protocol.CodeInternal {
		t.Fatalf("CodeOf() = %s, want internal", code.Name())
	}
}

// TestOpenScopeRejectsARelativeMapping checks that a scope mapped to a relative
// path is refused, because a relative path resolves differently per launch and
// the fence would guard a directory the policy never named.
func TestOpenScopeRejectsARelativeMapping(t *testing.T) {
	if _, err := OpenScope("project", "relative/path", nil); err == nil {
		t.Fatal("OpenScope() = nil error, want a refusal for a relative mapping")
	}
}

// TestOpenScopeRejectsAMissingDirectory checks that a scope mapped to a directory
// that does not exist is refused, because a fence over nothing serves nothing and
// the operator would believe the scope is live.
func TestOpenScopeRejectsAMissingDirectory(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "absent")
	if _, err := OpenScope("project", missing, nil); err == nil {
		t.Fatal("OpenScope() = nil error, want a refusal for a missing directory")
	}
}

// TestListReportsAMissingDirectory checks that listing a directory that does not
// exist is reported rather than returning an empty list, because an empty list
// reads as a directory with no entries.
func TestListReportsAMissingDirectory(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if _, err := scope.List("absent"); err == nil {
		t.Fatal("List() = nil error, want a missing-directory refusal")
	}
}

// TestListRejectsTraversal checks that a listing outside the scope is refused, so
// the fence guards the directory listing as well as the read.
func TestListRejectsTraversal(t *testing.T) {
	root, _ := newScopeFixture(t)
	scope := openFixtureScope(t, root)

	if _, err := scope.List("../"); err == nil {
		t.Fatal("List() = nil error, want a traversal refusal")
	}
}

// TestEnsureIdentityReportsAnUnwritableDirectory checks that a config directory
// that cannot hold the identity is reported, because a Node that started without
// a persisted identity would present a new pair on every start.
func TestEnsureIdentityReportsAnUnwritableDirectory(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "absent", "identity")

	if _, _, err := EnsureIdentity(missing); err == nil {
		t.Fatal("EnsureIdentity() = nil error, want a failure for a missing directory")
	}
}

// TestRegenerateIdentityReportsAnUnwritableDirectory checks that regeneration
// reports a directory it cannot write, because a silent failure would leave the
// operator using a pair the Node no longer holds.
func TestRegenerateIdentityReportsAnUnwritableDirectory(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "absent", "identity")

	if _, err := RegenerateIdentity(missing, false); err == nil {
		t.Fatal("RegenerateIdentity() = nil error, want a failure for a missing directory")
	}
}

// TestAuthorizeRefusesAnUndefinedScope checks that a request naming a scope the
// policy does not define is refused, because default deny means an unnamed scope
// is not an implicit grant.
func TestAuthorizeRefusesAnUndefinedScope(t *testing.T) {
	fixture := newDispatchFixture(t)

	_, err := fixture.authority.Authorize(security.Scope("absent"), security.PermissionRead)
	if err == nil {
		t.Fatal("Authorize() = nil error, want a refusal for an undefined scope")
	}
}

// TestAuthorizeRefusesAPermissionNotGranted checks that a permission the policy
// does not grant on a scope is refused even when the scope exists.
func TestAuthorizeRefusesAPermissionNotGranted(t *testing.T) {
	fixture := newDispatchFixture(t)

	// The fixture grants only list on scratch, so a read there must be refused.
	if _, err := fixture.authority.Authorize("scratch", security.PermissionRead); err == nil {
		t.Fatal("Authorize() = nil error, want a refusal for an ungranted permission")
	}
}

// TestSocketFrameConnRoundTripsOverARealSocket checks that a frame written by one
// side is read by the other, because the adapter is the only place the wire format
// and the protocol type meet.
func TestSocketFrameConnRoundTripsOverARealSocket(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		upgrader := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}
		conn, err := upgrader.Upgrade(writer, request, nil)
		if err != nil {
			return
		}
		defer func() {
			_ = conn.Close()
		}()
		adapter, err := NewSocketFrameConn(conn)
		if err != nil {
			return
		}
		frame, err := adapter.ReadFrame()
		if err != nil {
			return
		}
		_ = adapter.WriteFrame(frame)
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	t.Cleanup(server.Close)

	conn, _, err := websocket.DefaultDialer.Dial("ws"+strings.TrimPrefix(server.URL, "http"), nil)
	if err != nil {
		t.Fatalf("Dial() error = %v", err)
	}
	adapter, err := NewSocketFrameConn(conn)
	if err != nil {
		t.Fatalf("NewSocketFrameConn() error = %v", err)
	}
	t.Cleanup(func() {
		if err := adapter.Close(); err != nil {
			t.Errorf("Close() error = %v", err)
		}
	})

	sent := protocol.Frame{Type: protocol.FrameHeartbeat, Payload: []byte(`{"note":"ping"}`)}
	if err := adapter.WriteFrame(sent); err != nil {
		t.Fatalf("WriteFrame() error = %v", err)
	}

	echoed, err := adapter.ReadFrame()
	if err != nil {
		t.Fatalf("ReadFrame() error = %v", err)
	}
	if echoed.Type != sent.Type {
		t.Fatalf("type = %q, want %q", echoed.Type, sent.Type)
	}
	if string(echoed.Payload) != string(sent.Payload) {
		t.Fatalf("payload = %q, want %q", echoed.Payload, sent.Payload)
	}
}

// TestSocketFrameConnCloseReleasesTheConnection checks that closing the adapter
// closes the socket, because a Node that shut down without closing would leave the
// Server waiting for a peer that is gone.
func TestSocketFrameConnCloseReleasesTheConnection(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		upgrader := websocket.Upgrader{CheckOrigin: func(*http.Request) bool { return true }}
		conn, err := upgrader.Upgrade(writer, request, nil)
		if err != nil {
			return
		}
		defer func() {
			_ = conn.Close()
		}()
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	t.Cleanup(server.Close)

	conn, _, err := websocket.DefaultDialer.Dial("ws"+strings.TrimPrefix(server.URL, "http"), nil)
	if err != nil {
		t.Fatalf("Dial() error = %v", err)
	}
	adapter, err := NewSocketFrameConn(conn)
	if err != nil {
		t.Fatalf("NewSocketFrameConn() error = %v", err)
	}

	if err := adapter.Close(); err != nil {
		t.Fatalf("Close() error = %v", err)
	}
	if _, err := adapter.ReadFrame(); err == nil {
		t.Fatal("ReadFrame() = nil error after Close, want a closed-connection error")
	}
}

// TestOpenScopeRejectsASymlinkedRoot checks that a scope root that is a symlink is
// refused, because the fence would guard the link target while the policy named
// the link, and a later retarget would move the fence without changing the policy.
func TestOpenScopeRejectsASymlinkedRoot(t *testing.T) {
	parent := t.TempDir()
	real := filepath.Join(parent, "real")
	if err := os.MkdirAll(real, 0o755); err != nil {
		t.Fatalf("MkdirAll() error = %v", err)
	}
	link := filepath.Join(parent, "link")
	mustSymlink(t, real, link)

	if _, err := OpenScope("project", link, nil); err == nil {
		t.Fatal("OpenScope() = nil error, want a refusal for a symlinked root")
	}
}

// TestSaveIdentityReportsARenameFailure checks that a rename over a path that is a
// directory is reported, because a silent failure would leave the operator using a
// pair the Node does not hold.
func TestSaveIdentityReportsARenameFailure(t *testing.T) {
	configDir := t.TempDir()
	occupied := filepath.Join(configDir, "identity")
	if err := os.MkdirAll(occupied, 0o755); err != nil {
		t.Fatalf("MkdirAll() error = %v", err)
	}

	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}

	if err := SaveIdentity(occupied, identity); err == nil {
		t.Fatal("SaveIdentity() = nil error, want a rename failure")
	}

	entries, err := os.ReadDir(configDir)
	if err != nil {
		t.Fatalf("ReadDir() error = %v", err)
	}
	for _, entry := range entries {
		if strings.HasPrefix(entry.Name(), ".identity-") {
			t.Fatalf("a temporary file %q survived a refused save", entry.Name())
		}
	}
}
