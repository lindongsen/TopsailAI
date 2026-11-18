package node

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// dispatchFixture is an authority, an identity and a dispatcher wired together.
type dispatchFixture struct {
	t           *testing.T
	authority   *Authority
	nodeID      string
	credentials *security.CredentialSet
	holder      *IdentityHolder
	dispatcher  *Dispatcher
	project     string
	scratch     string
	logs        *bytes.Buffer
}

// newDispatchFixture builds a dispatcher over the two-scope policy fixture.
//
// The policy grants read, list and stat on `project` and only list on `scratch`,
// so a test can prove that a permission granted on one scope does not leak into
// another.
func newDispatchFixture(t *testing.T) *dispatchFixture {
	t.Helper()

	authorityFixture := newAuthorityFixture(t)
	authority := authorityFixture.load(t, nil)

	nodeID, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("NewNodeID() = %v, want nil", err)
	}
	credentials := nodeTestCredentialSet(t)
	holder := NewIdentityHolder(nodeID, credentials)

	logs := &bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug}))

	dispatcher, err := NewDispatcher(authority, holder, security.DefaultReplayWindow, security.DefaultReplayCapacity, logger)
	if err != nil {
		t.Fatalf("NewDispatcher() = %v, want nil", err)
	}

	return &dispatchFixture{
		t:           t,
		authority:   authority,
		nodeID:      nodeID,
		credentials: credentials,
		holder:      holder,
		dispatcher:  dispatcher,
		project:     authorityFixture.project,
		scratch:     authorityFixture.scratch,
		logs:        logs,
	}
}

// request builds a signed request addressed to this Node, so a test only states the
// field it is actually exercising.
func (f *dispatchFixture) request(operation protocol.Operation, scope security.Scope, path string) protocol.Request {
	return signNodeRequest(f.t, protocol.Request{
		NodeID:    f.nodeID,
		Operation: operation,
		Scope:     scope,
		Path:      path,
	}, nodeTestCredential)
}

// TestDispatchRefusesRequestForAnotherNode checks that a request addressed to a
// different Node is refused even when it carries a valid proof.
//
// The address is checked before the proof on purpose: a misrouted request must not be
// able to test whether a credential is valid here.
func TestDispatchRefusesRequestForAnotherNode(t *testing.T) {
	fixture := newDispatchFixture(t)

	other, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("NewNodeID() = %v, want nil", err)
	}

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeID = other

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}

// TestDispatchRefusesEmptyNodeID checks that a request naming no Node is refused,
// because an empty address is not this Node's address.
func TestDispatchRefusesEmptyNodeID(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeID = ""

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}

// TestDispatchRefusesAForgedProof checks that a proof signed with a secret this Node
// does not hold is refused.
//
// This is the Node's own gate: the Server authenticated the caller but does not know
// this secret, so only the Node can decide whether the caller may operate here.
func TestDispatchRefusesAForgedProof(t *testing.T) {
	fixture := newDispatchFixture(t)

	impostor := security.Credential{
		KeyID:  nodeTestCredential.KeyID,
		Secret: security.Secret("not-the-right-secret-0123456789ab"),
	}
	request := signNodeRequest(t, protocol.Request{
		NodeID:    fixture.nodeID,
		Operation: protocol.OperationFileRead,
		Scope:     "project",
		Path:      "inside.txt",
	}, impostor)

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}
}

// TestDispatchRefusesAnUnknownKeyID checks that a proof naming a key identifier this
// Node does not hold is refused with the same answer as a bad signature, so a caller
// cannot enumerate which key identifiers exist.
func TestDispatchRefusesAnUnknownKeyID(t *testing.T) {
	fixture := newDispatchFixture(t)

	unknown := security.Credential{
		KeyID:  "not-a-configured-key",
		Secret: nodeTestCredential.Secret,
	}
	request := signNodeRequest(t, protocol.Request{
		NodeID:    fixture.nodeID,
		Operation: protocol.OperationFileRead,
		Scope:     "project",
		Path:      "inside.txt",
	}, unknown)

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}
}

// TestDispatchRefusesAMissingProof checks that an absent proof is refused rather than
// treated as "no credential required".
func TestDispatchRefusesAMissingProof(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeAuth = security.Proof{}

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}
}

// TestDispatchRefusesATamperedOperation checks that a valid proof cannot be reused
// with a different operation.
//
// The proof signs the logical operation, so changing the operation after signing must
// invalidate it. Without this binding a caller could keep a proof for a granted read
// and ask for something else.
func TestDispatchRefusesATamperedOperation(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileList, "project", "")
	request.Operation = protocol.OperationFileRead

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}
}

// TestDispatchRefusesATamperedPath checks that a valid proof cannot be reused with a
// different path, which is the field a caller would change to read another file.
func TestDispatchRefusesATamperedPath(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.Path = "other.txt"

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}
}

// TestDispatchRefusesAReplayedProof checks that the same proof is refused the second
// time it arrives.
//
// A signature alone cannot stop a replay: the bytes are identical and still verify.
// The nonce cache is what makes the second copy a refusal.
func TestDispatchRefusesAReplayedProof(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")

	first := fixture.dispatcher.Dispatch(request)
	if !first.Succeeded() {
		t.Fatalf("first Dispatch() code = %s, want success", first.Code.Name())
	}

	second := fixture.dispatcher.Dispatch(request)
	if second.Code != protocol.CodeUnauthenticated {
		t.Fatalf("second Dispatch() code = %s, want unauthenticated", second.Code.Name())
	}
}

// TestDispatchRefusesAnExpiredProof checks that a proof outside the Node's window is
// refused even though its signature verifies.
//
// The window is the Node's, not the caller's: a request cannot choose or widen it.
func TestDispatchRefusesAnExpiredProof(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeAuth.TimestampMS = time.Now().Add(-2 * security.DefaultReplayWindow).UnixMilli()

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}
}

// TestDispatchRefusesDataOnRead checks that a `data` field on a read is refused
// rather than ignored, because an ignored field would let a caller believe a
// write happened.
func TestDispatchRefusesDataOnRead(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.Data = []byte("payload")

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeInvalidArgument {
		t.Fatalf("Dispatch() code = %s, want invalid_argument", response.Code.Name())
	}
}

// TestDispatchRefusesArgvOnRead checks that an `argv` field on a read is refused
// for the same reason as `data`.
func TestDispatchRefusesArgvOnRead(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.Argv = []string{"sh", "-c", "true"}

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeInvalidArgument {
		t.Fatalf("Dispatch() code = %s, want invalid_argument", response.Code.Name())
	}
}

// TestDispatchRefusesEmptyOperation checks that a request naming no operation is
// refused before authorization runs.
func TestDispatchRefusesEmptyOperation(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request("", "project", "inside.txt")

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeInvalidArgument {
		t.Fatalf("Dispatch() code = %s, want invalid_argument", response.Code.Name())
	}
}

// TestDispatchRefusesUnknownOperation checks that an operation this version does
// not know is unsupported, not invalid.
//
// The code is shared with a declared-but-disabled operation so a caller cannot
// enumerate the vocabulary by comparing the two answers.
func TestDispatchRefusesUnknownOperation(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.Operation("file.delete"), "project", "inside.txt")

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnsupportedOperation {
		t.Fatalf("Dispatch() code = %s, want unsupported_operation", response.Code.Name())
	}
}

// TestDispatchRefusesDisabledOperation checks that `file.write` is unsupported
// even on a scope that grants write, because this version implements no write.
func TestDispatchRefusesDisabledOperation(t *testing.T) {
	fixture := newDispatchFixture(t)

	for _, operation := range []protocol.Operation{protocol.OperationFileWrite, protocol.OperationCommandExec} {
		t.Run(string(operation), func(t *testing.T) {
			request := fixture.request(operation, "project", "inside.txt")

			response := fixture.dispatcher.Dispatch(request)
			if response.Code != protocol.CodeUnsupportedOperation {
				t.Fatalf("Dispatch() code = %s, want unsupported_operation", response.Code.Name())
			}
		})
	}
}

// TestDispatchRefusesUndefinedScope checks that a scope the policy does not
// define is refused with the same code as a scope that exists without the
// permission, so the difference is not an oracle.
func TestDispatchRefusesUndefinedScope(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "nowhere", "inside.txt")

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}

// TestDispatchRefusesPermissionGrantedOnAnotherScope checks that `read` granted
// on `project` does not authorize a read on `scratch`, which grants only `list`.
func TestDispatchRefusesPermissionGrantedOnAnotherScope(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "scratch", "inside.txt")

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}

// TestDispatchReadReturnsContent checks that a granted read returns the file
// bytes, the size and the truncation flag in the documented shape.
func TestDispatchReadReturnsContent(t *testing.T) {
	fixture := newDispatchFixture(t)

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileRead, "project", "inside.txt"))
	if !response.Succeeded() {
		t.Fatalf("Dispatch() code = %s, want success", response.Code.Name())
	}

	var payload struct {
		Content   []byte `json:"content"`
		Size      int64  `json:"size"`
		Truncated bool   `json:"truncated"`
	}
	if err := json.Unmarshal(response.Data, &payload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if string(payload.Content) != "inside content" {
		t.Fatalf("content = %q, want %q", payload.Content, "inside content")
	}
	if payload.Size != int64(len("inside content")) {
		t.Fatalf("size = %d, want %d", payload.Size, len("inside content"))
	}
	if payload.Truncated {
		t.Fatalf("truncated = true, want false")
	}
}

// TestDispatchReadEncodesContentAsBase64 checks that the content is base64 in
// the JSON document, which is what a caller decodes.
//
// The content is a byte slice so the encoder emits base64. Encoding it as a
// string would fail on the first file that is not valid UTF-8.
func TestDispatchReadEncodesContentAsBase64(t *testing.T) {
	fixture := newDispatchFixture(t)

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileRead, "project", "inside.txt"))
	if !response.Succeeded() {
		t.Fatalf("Dispatch() code = %s, want success", response.Code.Name())
	}
	if !strings.Contains(string(response.Data), `"content":"aW5zaWRlIGNvbnRlbnQ="`) {
		t.Fatalf("payload = %s, want base64 content", response.Data)
	}
}

// TestDispatchReadHonoursOffsetAndLength checks that the range fields reach the
// fence instead of being dropped on the way.
func TestDispatchReadHonoursOffsetAndLength(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.Offset = 7
	request.Length = 7
	request = signNodeRequest(t, request, nodeTestCredential)

	response := fixture.dispatcher.Dispatch(request)
	if !response.Succeeded() {
		t.Fatalf("Dispatch() code = %s, want success", response.Code.Name())
	}

	var payload struct {
		Content []byte `json:"content"`
	}
	if err := json.Unmarshal(response.Data, &payload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if string(payload.Content) != "content" {
		t.Fatalf("content = %q, want %q", payload.Content, "content")
	}
}

// TestDispatchReadMissingFile checks that a missing file is reported as not
// found rather than as a refusal, because the caller asked for something that
// does not exist and that is a normal answer.
func TestDispatchReadMissingFile(t *testing.T) {
	fixture := newDispatchFixture(t)

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileRead, "project", "absent.txt"))
	if response.Code != protocol.CodeNotFound {
		t.Fatalf("Dispatch() code = %s, want not_found", response.Code.Name())
	}
}

// TestDispatchReadRefusesTraversalAfterAuthorization checks that a granted read
// still cannot escape the scope.
//
// Authorization succeeding and the path being refused is the normal case, not an
// inconsistency: the two checks answer different questions.
func TestDispatchReadRefusesTraversalAfterAuthorization(t *testing.T) {
	fixture := newDispatchFixture(t)

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileRead, "project", "../scratch/inside.txt"))
	if response.Code != protocol.CodeInvalidArgument {
		t.Fatalf("Dispatch() code = %s, want invalid_argument", response.Code.Name())
	}
}

// TestDispatchReadRefusesSymlinkEscape checks that a symlink pointing outside the
// scope is refused by the fence, not followed.
func TestDispatchReadRefusesSymlinkEscape(t *testing.T) {
	fixture := newDispatchFixture(t)

	outside := filepath.Join(filepath.Dir(fixture.project), "outside.txt")
	writeFile(t, outside, "outside content")
	mustSymlink(t, outside, filepath.Join(fixture.project, "escape"))

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileRead, "project", "escape"))
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}

// TestDispatchListReturnsSortedEntries checks that a granted list returns the
// entries in sorted order, so a caller sees a stable answer.
func TestDispatchListReturnsSortedEntries(t *testing.T) {
	fixture := newDispatchFixture(t)

	writeFile(t, filepath.Join(fixture.project, "aaa.txt"), "a")
	writeFile(t, filepath.Join(fixture.project, "zzz.txt"), "z")

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileList, "project", ""))
	if !response.Succeeded() {
		t.Fatalf("Dispatch() code = %s, want success", response.Code.Name())
	}

	var payload struct {
		Entries []Entry `json:"entries"`
	}
	if err := json.Unmarshal(response.Data, &payload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	names := entryNames(payload.Entries)
	for index := 1; index < len(names); index++ {
		if names[index-1] > names[index] {
			t.Fatalf("entries = %v, want sorted order", names)
		}
	}
	if len(names) < 3 {
		t.Fatalf("entries = %v, want at least three", names)
	}
}

// TestDispatchListRefusesFile checks that listing a file is refused, because a
// file is not a directory.
func TestDispatchListRefusesFile(t *testing.T) {
	fixture := newDispatchFixture(t)

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileList, "project", "inside.txt"))
	if response.Code != protocol.CodeInvalidArgument {
		t.Fatalf("Dispatch() code = %s, want invalid_argument", response.Code.Name())
	}
}

// TestDispatchStatReportsSymlinkWithoutFollowing checks that stat reports a
// symlink as a symlink and names its target, instead of following it.
//
// Following it would make stat a way to probe whether a file outside the scope
// exists.
func TestDispatchStatReportsSymlinkWithoutFollowing(t *testing.T) {
	fixture := newDispatchFixture(t)

	mustSymlink(t, "inside.txt", filepath.Join(fixture.project, "link"))

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileStat, "project", "link"))
	if !response.Succeeded() {
		t.Fatalf("Dispatch() code = %s, want success", response.Code.Name())
	}

	var entry Entry
	if err := json.Unmarshal(response.Data, &entry); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if !entry.IsSymlink {
		t.Fatalf("IsSymlink = false, want true")
	}
	if entry.LinkTarget != "inside.txt" {
		t.Fatalf("LinkTarget = %q, want %q", entry.LinkTarget, "inside.txt")
	}
}

// TestDispatchRefusalCarriesNoData checks that a refusal carries no payload, so
// a caller cannot mistake a refusal for an empty result.
func TestDispatchRefusalCarriesNoData(t *testing.T) {
	fixture := newDispatchFixture(t)

	response := fixture.dispatcher.Dispatch(fixture.request(protocol.OperationFileRead, "nowhere", "inside.txt"))
	if response.Code == protocol.CodeSuccess {
		t.Fatalf("Dispatch() code = success, want a refusal")
	}
	if len(response.Data) != 0 {
		t.Fatalf("data = %q, want no data", response.Data)
	}
}

// TestDispatchLogNeverContainsASecret checks that a refusal logs the reason and never
// the credential secret, not even in redacted form.
//
// A redacted form is still a value derived from the secret, and the design forbids the
// Node from keeping one.
func TestDispatchLogNeverContainsASecret(t *testing.T) {
	fixture := newDispatchFixture(t)

	impostor := security.Credential{
		KeyID:  nodeTestCredential.KeyID,
		Secret: security.Secret("a-very-secret-value-0123456789ab"),
	}
	request := signNodeRequest(t, protocol.Request{
		NodeID:    fixture.nodeID,
		Operation: protocol.OperationFileRead,
		Scope:     "project",
		Path:      "inside.txt",
	}, impostor)

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}

	logged := fixture.logs.String()
	if logged == "" {
		t.Fatalf("log is empty, want a refusal line")
	}
	if strings.Contains(logged, string(impostor.Secret)) {
		t.Fatalf("log = %q, want no secret value", logged)
	}
	if !strings.Contains(logged, "node_id") {
		t.Fatalf("log = %q, want the node id for correlation", logged)
	}
}

// TestDispatchNilDispatcher checks that a nil dispatcher refuses instead of
// panicking, because a panic on the request path is a remote crash.
func TestDispatchNilDispatcher(t *testing.T) {
	var dispatcher *Dispatcher

	response := dispatcher.Dispatch(protocol.Request{})
	if response.Code != protocol.CodeInternal {
		t.Fatalf("Dispatch() code = %s, want internal", response.Code.Name())
	}
}

// TestDispatchNilAuthority checks that a dispatcher built without an authority
// refuses instead of panicking.
//
// A dispatcher with no policy has no answer to give, and the only safe answer is
// a refusal. It must not be a panic, because the request arrives from the
// network.
func TestDispatchNilAuthority(t *testing.T) {
	nodeID, err := security.NewNodeID()
	if err != nil {
		t.Fatalf("NewNodeID() = %v, want nil", err)
	}
	holder := NewIdentityHolder(nodeID, nodeTestCredentialSet(t))
	dispatcher, err := NewDispatcher(nil, holder, security.DefaultReplayWindow, security.DefaultReplayCapacity, nil)
	if err != nil {
		t.Fatalf("NewDispatcher() = %v, want nil", err)
	}

	request := signNodeRequest(t, protocol.Request{
		NodeID:    nodeID,
		Operation: protocol.OperationFileRead,
		Scope:     "project",
		Path:      "inside.txt",
	}, nodeTestCredential)

	response := dispatcher.Dispatch(request)
	if response.Code != protocol.CodeInternal {
		t.Fatalf("Dispatch() code = %s, want internal", response.Code.Name())
	}
}

// TestNewDispatcherFallsBackToDefaultLogger checks that a nil logger yields a
// working dispatcher rather than a nil dereference on the first refusal.
func TestNewDispatcherFallsBackToDefaultLogger(t *testing.T) {
	fixture := newDispatchFixture(t)
	dispatcher, err := NewDispatcher(fixture.authority, fixture.holder, security.DefaultReplayWindow, security.DefaultReplayCapacity, nil)
	if err != nil {
		t.Fatalf("NewDispatcher() = %v, want nil", err)
	}

	response := dispatcher.Dispatch(fixture.request(protocol.OperationFileRead, "nowhere", "inside.txt"))
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}

// TestNewDispatcherRefusesAnUnusableWindow checks that a window the configuration
// could not have produced refuses construction instead of falling back to a default.
//
// A verifier that silently substituted a default would be a verifier whose operator
// cannot state what it enforces.
func TestNewDispatcherRefusesAnUnusableWindow(t *testing.T) {
	fixture := newDispatchFixture(t)

	if _, err := NewDispatcher(fixture.authority, fixture.holder, -time.Second, security.DefaultReplayCapacity, nil); err == nil {
		t.Fatal("NewDispatcher() = nil error for a negative window, want a refusal")
	}
}
