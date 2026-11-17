package server

import (
	"context"
	"net/http"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// admissionEndpointHandler builds a handler over a store that knows exactly one
// Endpoint, so a command for any other identifier is a routing failure.
func admissionEndpointHandler(t *testing.T) http.Handler {
	t.Helper()
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	endpoint := protocol.Endpoint{
		EndpointID:         "known",
		InstanceID:         "known-1",
		DisplayName:        "known",
		ConnectionState:    "online",
		ObservedAtMS:       1,
		CapabilityRevision: "c1",
	}
	if err := store.UpsertEndpoint(context.Background(), endpoint, 1); err != nil {
		t.Fatal(err)
	}
	return NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store, "secret", &CommandService{Store: store}, nil, nil, nil)
}

// admissionIntent builds the smallest intent that passes canonical hashing, so a
// test can reach the Endpoint existence decision instead of failing earlier.
func admissionIntent(commandID, endpointID string) protocol.ImmutableIntent {
	return protocol.ImmutableIntent{
		HashVersion:          "v1",
		CommandID:            commandID,
		EndpointID:           endpointID,
		Operation:            "message.send",
		OperationVersion:     "v1",
		CapabilityRevision:   "c1",
		PayloadSchemaVersion: "v1",
		Payload:              []byte(`{"text":"hello"}`),
		ExecuteBeforeAtMS:    100,
	}
}

// TestCommandAdmissionRefusesUnregisteredEndpoint proves an unknown Endpoint is
// reported as a routing failure rather than as a storage failure.
//
// Before this guard existed the only thing refusing the request was the foreign
// key on the command table, so the caller received
// `admission_failed: constraint failed: FOREIGN KEY constraint failed (787)`.
// That answer names the database for a mistyped identifier, and it disappears
// entirely whenever foreign key enforcement is not active on the connection that
// handles the insert.
func TestCommandAdmissionRefusesUnregisteredEndpoint(t *testing.T) {
	handler := admissionEndpointHandler(t)
	rec := postCommand(t, handler, admissionIntent("cmd-unknown", "missing"))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status=%d want=%d body=%s", rec.Code, http.StatusNotFound, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"endpoint_not_found"`) {
		t.Fatalf("body=%s want code endpoint_not_found", rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), "FOREIGN KEY") || strings.Contains(rec.Body.String(), "constraint failed") {
		t.Fatalf("body=%s leaks the storage error", rec.Body.String())
	}
}

// TestCommandAdmissionRefusesUnregisteredEndpointWithoutWriting proves the guard
// runs before persistence, so a refused admission leaves no command row behind.
//
// A guard that only changed the response would still store the intent, and the
// orphan row would then be visible to every later command query.
func TestCommandAdmissionRefusesUnregisteredEndpointWithoutWriting(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	endpoint := protocol.Endpoint{
		EndpointID:         "known",
		InstanceID:         "known-1",
		DisplayName:        "known",
		ConnectionState:    "online",
		ObservedAtMS:       1,
		CapabilityRevision: "c1",
	}
	if err := store.UpsertEndpoint(context.Background(), endpoint, 1); err != nil {
		t.Fatal(err)
	}
	handler := NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store, "secret", &CommandService{Store: store}, nil, nil, nil)
	rec := postCommand(t, handler, admissionIntent("cmd-orphan", "missing"))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status=%d want=%d body=%s", rec.Code, http.StatusNotFound, rec.Body.String())
	}
	if _, err := store.GetCommand(context.Background(), "cmd-orphan"); err == nil {
		t.Fatal("a refused admission stored a command row for an unregistered endpoint")
	}
}

// TestCommandAdmissionStillAcceptsRegisteredEndpoint proves the guard is a
// condition rather than a blanket refusal.
//
// Without this case the two tests above would also pass if admission had been
// disabled entirely, which would hide a regression in the normal path.
func TestCommandAdmissionStillAcceptsRegisteredEndpoint(t *testing.T) {
	handler := admissionEndpointHandler(t)
	rec := postCommand(t, handler, admissionIntent("cmd-known", "known"))
	if rec.Code == http.StatusNotFound {
		t.Fatalf("a registered endpoint was refused: %s", rec.Body.String())
	}
	if strings.Contains(rec.Body.String(), `"endpoint_not_found"`) {
		t.Fatalf("body=%s reports endpoint_not_found for a registered endpoint", rec.Body.String())
	}
}
