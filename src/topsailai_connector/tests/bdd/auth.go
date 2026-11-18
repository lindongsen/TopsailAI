//go:build bdd

package bdd

import (
	"bytes"
	"log/slog"
	"strings"
	"time"

	"topsailai_connector/internal/node"
	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// authentication is the state the signed-request scenarios build up. It is kept
// beside the world rather than inside it so the policy scenarios do not carry
// fields they never read.
type authentication struct {
	nodeID      string
	credentials *security.CredentialSet
	dispatcher  *node.Dispatcher
	logs        *bytes.Buffer
	lastRequest protocol.Request
	lastResult  protocol.Response
}

// prepare builds the dispatcher the signed-request scenarios drive.
//
// The dispatcher is built from the authority the scenario already loaded, so a
// scenario cannot send a request to a Node whose policy was never read. The
// credential set is the one the scenario declared, which is what makes "a
// credential the Node does not hold" a real state rather than a comment.
func (w *world) prepare() *authentication {
	w.t.Helper()
	if w.auth != nil {
		return w.auth
	}
	if w.authority == nil {
		w.t.Fatalf("no authority was loaded; the policy step must run first")
	}
	nodeID, err := security.NewNodeID()
	if err != nil {
		w.t.Fatalf("NewNodeID() = %v, want nil", err)
	}
	credentials := bddCredentialSet(w.t)
	logs := &bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug}))
	dispatcher, err := node.NewDispatcher(w.authority, node.NewIdentityHolder(nodeID, credentials), security.DefaultReplayWindow, security.DefaultReplayCapacity, logger)
	if err != nil {
		w.t.Fatalf("NewDispatcher() = %v, want nil", err)
	}
	w.auth = &authentication{nodeID: nodeID, credentials: credentials, dispatcher: dispatcher, logs: logs}
	return w.auth
}

// send signs a request with the credential the scenario chose and dispatches it.
//
// The request is signed before it is dispatched, so a scenario that tampers with a
// field afterwards is exercising the signature check rather than the shape check.
func (w *world) send(operation protocol.Operation, scope security.Scope, path string) {
	w.t.Helper()
	state := w.prepare()
	request := signRequest(w.t, protocol.Request{
		NodeID:    state.nodeID,
		Operation: operation,
		Scope:     scope,
		Path:      path,
	}, w.signWith, w.timestampAge)
	state.lastRequest = request
	state.lastResult = state.dispatcher.Dispatch(request)
}

// resend dispatches the request the scenario already sent, unchanged. It is the
// replay: same nonce, same signature, same timestamp.
func (w *world) resend() {
	w.t.Helper()
	state := w.prepare()
	state.lastResult = state.dispatcher.Dispatch(state.lastRequest)
}

// tamper changes the path after signing and dispatches the result.
func (w *world) tamper(path string) {
	w.t.Helper()
	state := w.prepare()
	request := state.lastRequest
	request.Path = path
	state.lastResult = state.dispatcher.Dispatch(request)
}

// stripProof removes the proof after signing and dispatches the result.
func (w *world) stripProof() {
	w.t.Helper()
	state := w.prepare()
	request := state.lastRequest
	request.NodeAuth = security.Proof{}
	state.lastResult = state.dispatcher.Dispatch(request)
}

// readdress changes the node id after signing and dispatches the result.
func (w *world) readdress() {
	w.t.Helper()
	state := w.prepare()
	request := state.lastRequest
	request.NodeID = "node_aaaaaaaaaaaaaaaaaaaaaaaaaa"
	state.lastResult = state.dispatcher.Dispatch(request)
}

// code returns the name of the code the last dispatch answered with.
func (w *world) code() string {
	if w.auth == nil {
		return ""
	}
	return w.auth.lastResult.Code.Name()
}

// data returns the payload of the last dispatch.
func (w *world) data() []byte {
	if w.auth == nil {
		return nil
	}
	return w.auth.lastResult.Data
}

// logText returns everything the Node logged during the scenario.
func (w *world) logText() string {
	if w.auth == nil {
		return ""
	}
	return w.auth.logs.String()
}

// staleAge is an age the freshness window must refuse. It is twice the window, so
// the scenario cannot pass because of a boundary rounding.
var staleAge = int64(2 * security.DefaultReplayWindow / time.Millisecond)

// containsSecret reports whether a log line discloses the fixture secret. It is a
// helper rather than an inline check so every scenario that asserts non-disclosure
// asks the same question.
func containsSecret(text string) bool {
	return strings.Contains(text, string(bddNodeCredential.Secret))
}
