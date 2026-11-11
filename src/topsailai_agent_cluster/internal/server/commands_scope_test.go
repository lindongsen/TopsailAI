package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// scopeTestHandler builds a handler whose credential is restricted to the given
// scopes and whose Endpoint advertises one capability with a declared permission.
func scopeTestHandler(t *testing.T, scopes []string, capability protocol.Capability) http.Handler {
	t.Helper()
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	endpoint := protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}
	if err := store.UpsertEndpoint(context.Background(), endpoint, 1); err != nil {
		t.Fatal(err)
	}
	report := protocol.InventoryReport{
		SchemaVersion:    "v1",
		SourceGeneration: "g1",
		SnapshotRevision: 1,
		ObservedAtMS:     1,
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		Adapters: []protocol.AdapterSummary{{
			AdapterID:    "a1",
			ProviderType: "fixture",
			Capabilities: protocol.CapabilityDescriptor{Revision: "r1", Capabilities: []protocol.Capability{capability}},
		}},
	}
	if err := store.ReplaceInventory(context.Background(), "e1", report, 1); err != nil {
		t.Fatal(err)
	}
	return NewHandlerWithScopes(store, "secret", scopes, &CommandService{Store: store}, nil, nil, nil)
}

// postCommand submits one command intent and returns the recorded response.
func postCommand(t *testing.T, handler http.Handler, intent protocol.ImmutableIntent) *httptest.ResponseRecorder {
	t.Helper()
	body, err := json.Marshal(intent)
	if err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/api/v1/commands", strings.NewReader(string(body)))
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

// TestCommandAdmissionForwardsRegardlessOfDeclaredPermission proves the Server no
// longer refuses a command on permission grounds.
//
// Authorization belongs to the Endpoint that owns the machine. A Server-side
// refusal would be a second authority the Endpoint could not revoke, so a
// credential that lacks the declared permission must still be admitted: the
// Endpoint decides, and it answers with policy_denied.
func TestCommandAdmissionForwardsRegardlessOfDeclaredPermission(t *testing.T) {
	capability := protocol.Capability{Name: "ctl.get_session_messages", Version: "v1", RequiredPermission: security.ScopeControl}
	tests := []struct {
		name   string
		scopes []string
	}{
		{name: "unrestricted credential", scopes: nil},
		{name: "credential holding the permission", scopes: []string{security.ScopeControl}},
		{name: "credential lacking the permission", scopes: []string{security.ScopeView}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			handler := scopeTestHandler(t, test.scopes, capability)
			intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-scope", EndpointID: "e1", Operation: "ctl.get_session_messages", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"action":"get_session_messages"}`), ExecuteBeforeAtMS: 100}
			rec := postCommand(t, handler, intent)
			if rec.Code == http.StatusForbidden {
				t.Fatalf("the Server refused a command on permission grounds: %s", rec.Body.String())
			}
		})
	}
}

// TestCommandAdmissionForwardsUndeclaredControlOperation proves the Server no
// longer refuses a control operation that the Endpoint did not advertise.
//
// Advertising is the Endpoint's statement about what it can do, so the Endpoint
// is the only component that can enforce it. A Server-side refusal would mean the
// Server had to interpret the advertised capability list, which is exactly the
// provider knowledge the abstraction boundary forbids.
func TestCommandAdmissionForwardsUndeclaredControlOperation(t *testing.T) {
	handler := scopeTestHandler(t, nil, protocol.Capability{Name: "message.send", Version: "v1"})
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-undeclared", EndpointID: "e1", Operation: "ctl.heartbeat", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{}`), ExecuteBeforeAtMS: 100}
	rec := postCommand(t, handler, intent)
	if rec.Code == http.StatusForbidden {
		t.Fatalf("the Server refused an undeclared control operation: %s", rec.Body.String())
	}
}

// TestCommandAdmissionKeepsStandardOperationAdmissible proves a standard
// operation without a declared permission keeps its previous behaviour.
func TestCommandAdmissionKeepsStandardOperationAdmissible(t *testing.T) {
	handler := scopeTestHandler(t, []string{security.ScopeView}, protocol.Capability{Name: "message.send", Version: "v1"})
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-standard", EndpointID: "e1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	rec := postCommand(t, handler, intent)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status=%d body=%s, want 202", rec.Code, rec.Body.String())
	}
}

// TestCommandAdmissionStillRejectsIssuerMismatch proves removing the permission
// check did not remove the identity check.
//
// The issuer check is not authorization: it proves the request was not rewritten
// in flight to claim another caller's identity. That is an integrity property of
// the request, so it stays on the Server.
func TestCommandAdmissionStillRejectsIssuerMismatch(t *testing.T) {
	handler := scopeTestHandler(t, nil, protocol.Capability{Name: "message.send", Version: "v1"})
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-issuer", EndpointID: "e1", IssuerID: "someone-else", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	rec := postCommand(t, handler, intent)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("status=%d body=%s, want 403", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "issuer_mismatch") {
		t.Fatalf("body=%s want code issuer_mismatch", rec.Body.String())
	}
}
