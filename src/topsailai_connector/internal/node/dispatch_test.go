package node

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/protocol"
	"topsailai_connector/internal/security"
)

// dispatchFixture is an authority, an identity and a dispatcher wired together.
type dispatchFixture struct {
	authority  *Authority
	identity   security.NodeIdentity
	dispatcher *Dispatcher
	project    string
	scratch    string
	logs       *bytes.Buffer
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

	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}

	logs := &bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug}))

	return &dispatchFixture{
		authority:  authority,
		identity:   identity,
		dispatcher: NewDispatcher(authority, identity, logger),
		project:    authorityFixture.project,
		scratch:    authorityFixture.scratch,
		logs:       logs,
	}
}

// request builds a request addressed to this Node with the correct token, so a
// test only states the field it is actually exercising.
func (f *dispatchFixture) request(operation protocol.Operation, scope security.Scope, path string) protocol.Request {
	return protocol.Request{
		NodeID:    f.identity.ID,
		NodeToken: f.identity.Token,
		Operation: operation,
		Scope:     scope,
		Path:      path,
	}
}

// TestDispatchRefusesRequestForAnotherNode checks that a request addressed to a
// different Node is refused even when it carries this Node's token.
//
// The address is checked before the token on purpose: a misrouted request must
// not be able to test whether a token is valid here.
func TestDispatchRefusesRequestForAnotherNode(t *testing.T) {
	fixture := newDispatchFixture(t)

	other, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeID = other.ID

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}

// TestDispatchRefusesEmptyNodeID checks that a request naming no Node is
// refused, because an empty address is not this Node's address.
func TestDispatchRefusesEmptyNodeID(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeID = ""

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}

// TestDispatchRefusesWrongToken checks that a wrong node-token is refused, which
// is the Node's own gate: the Server authenticated the caller but does not know
// this value.
func TestDispatchRefusesWrongToken(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeToken = security.Secret("not-the-right-token-value")

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}
}

// TestDispatchRefusesEmptyToken checks that an absent token is refused rather
// than treated as "no token required".
func TestDispatchRefusesEmptyToken(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeToken = ""

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

// TestDispatchLogNeverContainsToken checks that a refusal logs the reason and
// never the token, not even in redacted form.
//
// A redacted form is still a value derived from the secret, and the design
// forbids the Node from keeping one.
func TestDispatchLogNeverContainsToken(t *testing.T) {
	fixture := newDispatchFixture(t)

	request := fixture.request(protocol.OperationFileRead, "project", "inside.txt")
	request.NodeToken = security.Secret("a-very-secret-token-value")

	response := fixture.dispatcher.Dispatch(request)
	if response.Code != protocol.CodeUnauthenticated {
		t.Fatalf("Dispatch() code = %s, want unauthenticated", response.Code.Name())
	}

	logged := fixture.logs.String()
	if logged == "" {
		t.Fatalf("log is empty, want a refusal line")
	}
	if strings.Contains(logged, "a-very-secret-token-value") {
		t.Fatalf("log = %q, want no token value", logged)
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
	identity, err := security.NewNodeIdentity()
	if err != nil {
		t.Fatalf("NewNodeIdentity() = %v, want nil", err)
	}
	dispatcher := NewDispatcher(nil, identity, nil)

	response := dispatcher.Dispatch(protocol.Request{
		NodeID:    identity.ID,
		NodeToken: identity.Token,
		Operation: protocol.OperationFileRead,
		Scope:     "project",
		Path:      "inside.txt",
	})
	if response.Code != protocol.CodeInternal {
		t.Fatalf("Dispatch() code = %s, want internal", response.Code.Name())
	}
}

// TestNewDispatcherFallsBackToDefaultLogger checks that a nil logger yields a
// working dispatcher rather than a nil dereference on the first refusal.
func TestNewDispatcherFallsBackToDefaultLogger(t *testing.T) {
	fixture := newDispatchFixture(t)
	dispatcher := NewDispatcher(fixture.authority, fixture.identity, nil)

	response := dispatcher.Dispatch(fixture.request(protocol.OperationFileRead, "nowhere", "inside.txt"))
	if response.Code != protocol.CodeDenied {
		t.Fatalf("Dispatch() code = %s, want denied", response.Code.Name())
	}
}
