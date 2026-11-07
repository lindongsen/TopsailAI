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

func TestCommandAdmissionEnforcesDeclaredPermission(t *testing.T) {
	capability := protocol.Capability{Name: "ctl.get_session_messages", Version: "v1", RequiredPermission: security.ScopeControl}
	tests := []struct {
		name     string
		scopes   []string
		wantCode int
	}{
		{name: "unrestricted credential is admitted", scopes: nil, wantCode: http.StatusAccepted},
		{name: "credential holding the permission is admitted", scopes: []string{security.ScopeControl}, wantCode: http.StatusAccepted},
		{name: "credential lacking the permission is rejected", scopes: []string{security.ScopeView}, wantCode: http.StatusForbidden},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			handler := scopeTestHandler(t, test.scopes, capability)
			intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-scope", EndpointID: "e1", Operation: "ctl.get_session_messages", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"action":"get_session_messages"}`), ExecuteBeforeAtMS: 100}
			rec := postCommand(t, handler, intent)
			if rec.Code != test.wantCode {
				t.Fatalf("status=%d body=%s, want %d", rec.Code, rec.Body.String(), test.wantCode)
			}
			if test.wantCode == http.StatusForbidden && !strings.Contains(rec.Body.String(), "permission_denied") {
				t.Fatalf("expected permission_denied code, got %s", rec.Body.String())
			}
		})
	}
}

func TestCommandAdmissionRejectsUndeclaredControlOperation(t *testing.T) {
	// The Endpoint advertises an unrelated capability, so the control operation is
	// not advertised at all and must fail closed even for an unrestricted credential.
	handler := scopeTestHandler(t, nil, protocol.Capability{Name: "message.send", Version: "v1"})
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-undeclared", EndpointID: "e1", Operation: "ctl.heartbeat", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{}`), ExecuteBeforeAtMS: 100}
	rec := postCommand(t, handler, intent)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("status=%d body=%s, want 403", rec.Code, rec.Body.String())
	}
}

func TestCommandAdmissionKeepsUndeclaredStandardOperationAdmissible(t *testing.T) {
	// No capability declares a permission today, so a standard operation without a
	// declaration must keep its previous behaviour and remain admissible.
	handler := scopeTestHandler(t, []string{security.ScopeView}, protocol.Capability{Name: "message.send", Version: "v1"})
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-standard", EndpointID: "e1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	rec := postCommand(t, handler, intent)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status=%d body=%s, want 202", rec.Code, rec.Body.String())
	}
}
