package server

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// refreshRequesterStub returns a fixed report or error for one forced collection.
type refreshRequesterStub struct {
	report protocol.InventoryReport
	err    error
	calls  int
}

func (s *refreshRequesterStub) RequestRefreshAndWait(context.Context, string) (protocol.InventoryReport, error) {
	s.calls++
	if s.err != nil {
		return protocol.InventoryReport{}, s.err
	}
	return s.report, nil
}

// refreshStore opens a server store holding one committed report.
func refreshStore(t *testing.T, report protocol.InventoryReport) *serverstorage.Store {
	t.Helper()
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	if err := store.ReplaceInventory(context.Background(), "e1", report, 1); err != nil {
		t.Fatal(err)
	}
	return store
}

// refreshCall issues one authenticated refresh request.
func refreshCall(t *testing.T, handler http.Handler, method string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, "/api/v1/endpoints/e1/session-state/refresh", nil)
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)
	return rec
}

// TestRefreshInventoryReturnsCommittedDocument proves the response is the document
// re-read from storage, so it always equals a following GET session-state.
func TestRefreshInventoryReturnsCommittedDocument(t *testing.T) {
	committed := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 4, ObservedAtMS: 900, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", ProviderType: "fixture", DataKnown: true}}, Sessions: []protocol.Session{{SessionID: "res-1", AdapterID: "adapter-1", Generation: "generation-1", State: "running"}}}
	store := refreshStore(t, committed)
	requester := &refreshRequesterStub{report: committed}
	handler := NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store, "secret", &CommandService{Store: store}, nil, nil, requester)
	rec := refreshCall(t, handler, http.MethodPost)
	if rec.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if requester.calls != 1 {
		t.Fatalf("forced collection calls=%d", requester.calls)
	}
	var envelope struct {
		Data protocol.InventoryReport `json:"data"`
	}
	if err := json.Unmarshal(rec.Body.Bytes(), &envelope); err != nil {
		t.Fatal(err)
	}
	if envelope.Data.SnapshotRevision != committed.SnapshotRevision || len(envelope.Data.Sessions) != 1 || envelope.Data.Sessions[0].SessionID != "res-1" {
		t.Fatalf("data=%+v", envelope.Data)
	}
	// The response must equal the persisted document, not the submitted report.
	getReq := httptest.NewRequest(http.MethodGet, "/api/v1/endpoints/e1/session-state", nil)
	getReq.Header.Set("Authorization", "Bearer secret")
	get := httptest.NewRecorder()
	handler.ServeHTTP(get, getReq)
	if get.Code != http.StatusOK {
		t.Fatalf("get status=%d", get.Code)
	}
	var stored struct {
		Data protocol.InventoryReport `json:"data"`
	}
	if err := json.Unmarshal(get.Body.Bytes(), &stored); err != nil {
		t.Fatal(err)
	}
	if stored.Data.SnapshotRevision != envelope.Data.SnapshotRevision || stored.Data.ObservedAtMS != envelope.Data.ObservedAtMS {
		t.Fatalf("refresh=%+v get=%+v", envelope.Data, stored.Data)
	}
}

// TestRefreshInventoryRejectsMissingRequester proves an unconfigured channel is an
// explicit failure rather than a silent cached answer.
func TestRefreshInventoryRejectsMissingRequester(t *testing.T) {
	committed := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 1, ObservedAtMS: 900, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}
	store := refreshStore(t, committed)
	handler := NewHandlerWithCommandsAndBrokerAndOutput(store, "secret", &CommandService{Store: store}, nil, nil)
	rec := refreshCall(t, handler, http.MethodPost)
	if rec.Code != http.StatusServiceUnavailable || !strings.Contains(rec.Body.String(), "unavailable") {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}

// TestRefreshInventoryReportsTransportFailure proves an unreachable Endpoint is an
// explicit error, not a cached success.
func TestRefreshInventoryReportsTransportFailure(t *testing.T) {
	committed := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 1, ObservedAtMS: 900, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}
	store := refreshStore(t, committed)
	requester := &refreshRequesterStub{err: errors.New("endpoint offline")}
	handler := NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store, "secret", &CommandService{Store: store}, nil, nil, requester)
	rec := refreshCall(t, handler, http.MethodPost)
	if rec.Code != http.StatusServiceUnavailable || !strings.Contains(rec.Body.String(), "endpoint_unavailable") {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}

// TestRefreshInventoryRejectsSilentlyIgnoredReport proves a report that storage
// ignored cannot be reported as fresh.
func TestRefreshInventoryRejectsSilentlyIgnoredReport(t *testing.T) {
	committed := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 9, ObservedAtMS: 900, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}
	store := refreshStore(t, committed)
	// The Endpoint returned a newer report but the persistence hook never committed it,
	// so the stored document stays older than the report this request forced.
	ignored := committed
	ignored.SnapshotRevision = 10
	ignored.ObservedAtMS = 1000
	requester := &refreshRequesterStub{report: ignored}
	handler := NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store, "secret", &CommandService{Store: store}, nil, nil, requester)
	rec := refreshCall(t, handler, http.MethodPost)
	if rec.Code != http.StatusConflict || !strings.Contains(rec.Body.String(), "not_committed") {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}

// TestRefreshInventoryValidatesMethod proves the refresh route rejects a read.
func TestRefreshInventoryValidatesMethod(t *testing.T) {
	committed := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "endpoint-local", SnapshotRevision: 1, ObservedAtMS: 900, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}
	store := refreshStore(t, committed)
	requester := &refreshRequesterStub{report: committed}
	handler := NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store, "secret", &CommandService{Store: store}, nil, nil, requester)
	rec := refreshCall(t, handler, http.MethodGet)
	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
	if requester.calls != 0 {
		t.Fatalf("rejected method forced a collection: calls=%d", requester.calls)
	}
}
