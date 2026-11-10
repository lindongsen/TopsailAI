package protocol

import (
	"encoding/json"
	"testing"

	"topsailai_connector/internal/security"
)

// TestOperationPermission checks that every declared operation maps to exactly
// one permission, because an operation without a mapping would be refused at
// runtime and an operation mapped to the wrong permission would consume
// authority the caller never held.
func TestOperationPermission(t *testing.T) {
	cases := []struct {
		operation  Operation
		permission security.Permission
	}{
		{operation: OperationFileRead, permission: security.PermissionRead},
		{operation: OperationFileWrite, permission: security.PermissionWrite},
		{operation: OperationFileList, permission: security.PermissionList},
		{operation: OperationFileStat, permission: security.PermissionStat},
		{operation: OperationCommandExec, permission: security.PermissionExec},
	}

	for _, testCase := range cases {
		t.Run(string(testCase.operation), func(t *testing.T) {
			permission, ok := testCase.operation.Permission()
			if !ok {
				t.Fatalf("Permission() reported no mapping for %q", testCase.operation)
			}
			if permission != testCase.permission {
				t.Fatalf("Permission() = %q, want %q", permission, testCase.permission)
			}
		})
	}
}

// TestOperationPermissionUnknown checks that an undeclared operation reports no
// mapping, so a caller cannot invent an operation and have it run unchecked.
func TestOperationPermissionUnknown(t *testing.T) {
	if _, ok := Operation("file.chmod").Permission(); ok {
		t.Fatal("Permission() mapped an undeclared operation, want no mapping")
	}
}

// TestOperationEnabled checks that only the read-only operations are enabled in
// this version. `file.write` and `command.exec` are declared so a second-version
// policy parses, but a declared operation must not be a callable one.
func TestOperationEnabled(t *testing.T) {
	cases := []struct {
		operation Operation
		enabled   bool
	}{
		{operation: OperationFileRead, enabled: true},
		{operation: OperationFileList, enabled: true},
		{operation: OperationFileStat, enabled: true},
		{operation: OperationFileWrite, enabled: false},
		{operation: OperationCommandExec, enabled: false},
	}

	for _, testCase := range cases {
		t.Run(string(testCase.operation), func(t *testing.T) {
			if got := testCase.operation.Enabled(); got != testCase.enabled {
				t.Fatalf("Enabled() = %v, want %v", got, testCase.enabled)
			}
		})
	}
}

// TestOperationEnabledUnknown checks that an operation outside the vocabulary is
// not enabled, so an invented name cannot reach a handler.
func TestOperationEnabledUnknown(t *testing.T) {
	if Operation("file.chmod").Enabled() {
		t.Fatal("Enabled() = true for an undeclared operation, want false")
	}
}

// TestOperationValidate checks that Validate accepts every declared operation
// and refuses an undeclared one. Validate answers "is this a known name", which
// is a different question from "is this implemented".
func TestOperationValidate(t *testing.T) {
	declared := []Operation{
		OperationFileRead, OperationFileWrite, OperationFileList,
		OperationFileStat, OperationCommandExec,
	}
	for _, operation := range declared {
		if err := operation.Validate(); err != nil {
			t.Fatalf("Validate() on declared operation %q: %v", operation, err)
		}
	}

	undeclared := []Operation{"", "file.chmod", "FILE.READ", "file.read ", "file.read/../write"}
	for _, operation := range undeclared {
		if err := operation.Validate(); err == nil {
			t.Fatalf("Validate() accepted undeclared operation %q", operation)
		}
	}
}

// TestRequestCarriesNodeIdentitySeparately checks that the node id and the node
// token are separate fields. They are different kinds of value: the id may be
// logged and routed on, the token may never be. A single combined field would
// force every log site to split a value that is half public and half secret.
func TestRequestCarriesNodeIdentitySeparately(t *testing.T) {
	request := Request{
		NodeID:    "node_abc",
		NodeToken: security.Secret("token-value"),
		Operation: OperationFileRead,
		Scope:     security.Scope("project"),
		Path:      "a.txt",
	}

	if request.NodeID != "node_abc" {
		t.Fatalf("NodeID = %q, want %q", request.NodeID, "node_abc")
	}
	if string(request.NodeToken) != "token-value" {
		t.Fatalf("NodeToken = %q, want %q", request.NodeToken, "token-value")
	}
}

// TestRequestJSONKeepsNodeToken checks that the node token survives a JSON round
// trip, because the Server forwards the request body unchanged and a lost token
// would surface as an authentication failure at the Node.
func TestRequestJSONKeepsNodeToken(t *testing.T) {
	original := Request{
		NodeID:    "node_abc",
		NodeToken: security.Secret("token-value"),
		Operation: OperationFileList,
		Scope:     security.Scope("project"),
		Path:      "sub",
	}

	encoded, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("marshal request: %v", err)
	}

	var decoded Request
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("unmarshal request: %v", err)
	}

	if decoded.NodeID != original.NodeID {
		t.Fatalf("node id = %q, want %q", decoded.NodeID, original.NodeID)
	}
	if decoded.NodeToken != original.NodeToken {
		t.Fatalf("node token = %q, want %q", decoded.NodeToken, original.NodeToken)
	}
	if decoded.Operation != original.Operation {
		t.Fatalf("operation = %q, want %q", decoded.Operation, original.Operation)
	}
	if decoded.Scope != original.Scope {
		t.Fatalf("scope = %q, want %q", decoded.Scope, original.Scope)
	}
	if decoded.Path != original.Path {
		t.Fatalf("path = %q, want %q", decoded.Path, original.Path)
	}
}

// TestResponseSuccessCarriesData checks that a success response carries the
// success code and the payload.
func TestResponseSuccessCarriesData(t *testing.T) {
	response := Success([]byte("contents"))

	if !response.Succeeded() {
		t.Fatalf("Succeeded() = false, want true for code %s", response.Code.Name())
	}
	if string(response.Data) != "contents" {
		t.Fatalf("Data = %q, want %q", response.Data, "contents")
	}
}

// TestResponseFailureCarriesNoData checks that a failure response carries no
// data. A refusal with a partial payload is how a caller mistakes a refusal for
// a truncated success.
func TestResponseFailureCarriesNoData(t *testing.T) {
	codes := []Code{
		CodeInvalidArgument, CodeUnauthenticated, CodeNodeOffline, CodeNodeTimeout,
		CodeDenied, CodeNotFound, CodeUnsupportedOperation, CodeTooLarge, CodeInternal,
	}

	for _, code := range codes {
		t.Run(code.Name(), func(t *testing.T) {
			response := Failure(code)
			if response.Succeeded() {
				t.Fatalf("Succeeded() = true for failure code %s", code.Name())
			}
			if len(response.Data) != 0 {
				t.Fatalf("Data = %q, want empty for failure code %s", response.Data, code.Name())
			}
		})
	}
}

// TestResponseJSONKeepsCode checks that the code survives a JSON round trip as a
// number, because the Server relays the Node's response and a code that decodes
// as zero would turn a refusal into a success.
func TestResponseJSONKeepsCode(t *testing.T) {
	original := Failure(CodeDenied)

	encoded, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("marshal response: %v", err)
	}

	var decoded Response
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("unmarshal response: %v", err)
	}

	if decoded.Code != CodeDenied {
		t.Fatalf("code = %s, want %s", decoded.Code.Name(), CodeDenied.Name())
	}
	if decoded.Succeeded() {
		t.Fatal("Succeeded() = true after round trip of a refusal")
	}
}
