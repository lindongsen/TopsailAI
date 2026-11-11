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
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

func TestInventoryHTTPRequiresAuthAndRoundTrips(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	endpoint := protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}
	if err := store.UpsertEndpoint(context.Background(), endpoint, 1); err != nil {
		t.Fatal(err)
	}
	h := NewHandler(store, "secret")
	unauth := httptest.NewRecorder()
	h.ServeHTTP(unauth, httptest.NewRequest(http.MethodGet, "/api/v1/endpoints", nil))
	if unauth.Code != http.StatusUnauthorized {
		t.Fatalf("status %d", unauth.Code)
	}
	report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "g1", SnapshotRevision: 1, ObservedAtMS: 1, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "a1", ProviderType: "fixture"}}}
	body, _ := json.Marshal(report)
	req := httptest.NewRequest(http.MethodPut, "/api/v1/endpoints/e1/session-state", strings.NewReader(string(body)))
	req.Header.Set("Authorization", "Bearer secret")
	put := httptest.NewRecorder()
	h.ServeHTTP(put, req)
	if put.Code != http.StatusOK {
		t.Fatalf("put status %d: %s", put.Code, put.Body.String())
	}
	getReq := httptest.NewRequest(http.MethodGet, "/api/v1/endpoints/e1/session-state", nil)
	getReq.Header.Set("Authorization", "Bearer secret")
	get := httptest.NewRecorder()
	h.ServeHTTP(get, getReq)
	if get.Code != http.StatusOK {
		t.Fatalf("get status %d", get.Code)
	}
}

func TestCommandAdmissionIsIdempotentAndConflicts(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	svc := &CommandService{Store: store}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "cmd-http", EndpointID: "e1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"x"}`), ExecuteBeforeAtMS: 100}
	h := NewHandlerWithCommands(store, "secret", svc)
	body, _ := json.Marshal(intent)
	for i := 0; i < 2; i++ {
		req := httptest.NewRequest(http.MethodPost, "/api/v1/commands", strings.NewReader(string(body)))
		req.Header.Set("Authorization", "Bearer secret")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusAccepted && rec.Code != http.StatusOK {
			t.Fatalf("admit %d: %d %s", i, rec.Code, rec.Body.String())
		}
	}
	intent.Payload = []byte(`{"text":"changed"}`)
	body, _ = json.Marshal(intent)
	req := httptest.NewRequest(http.MethodPost, "/api/v1/commands", strings.NewReader(string(body)))
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusConflict {
		t.Fatalf("conflict status %d", rec.Code)
	}
}

func TestReadOutputEndpointOfflineReturnsError(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	h := NewHandlerWithCommandsAndBrokerAndOutput(store, "secret", &CommandService{Store: store}, nil, nil)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/output?endpoint_id=e1&resource_id=res_1&provider_generation=g1", nil)
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusServiceUnavailable || !strings.Contains(rec.Body.String(), "endpoint_offline") {
		t.Fatalf("response status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestHTTPRoutesValidateMethodsAndCapabilities(t *testing.T) {
	store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	broker := NewEventBroker(2)
	h := NewHandlerWithBroker(store, "secret", broker)
	call := func(method, path, body string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer secret")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec
	}
	if rec := call(http.MethodGet, "/readyz", ""); rec.Code != http.StatusOK {
		t.Fatalf("ready=%d", rec.Code)
	}
	if rec := call(http.MethodPost, "/api/v1/endpoints", "{}"); rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("method=%d", rec.Code)
	}
	endpoint := `{"endpoint_id":"e1","instance_id":"i1","display_name":"one","connection_state":"online","observed_at_ms":1,"capability_revision":"c1"}`
	if rec := call(http.MethodPut, "/api/v1/endpoints", endpoint); rec.Code != http.StatusOK {
		t.Fatalf("put endpoint=%d %s", rec.Code, rec.Body)
	}
	report := `{"schema_version":"v1","source_generation":"g1","snapshot_revision":1,"observed_at_ms":1,"report_complete":true,"collection_status":"succeeded","adapters":[{"adapter_id":"a1","provider_type":"fixture","capabilities":{"revision":"r1","capabilities":[{"name":"message.send","version":"v1"}]}}]}`
	if rec := call(http.MethodPut, "/api/v1/endpoints/e1/session-state", report); rec.Code != http.StatusOK {
		t.Fatalf("put report=%d %s", rec.Code, rec.Body)
	}
	if rec := call(http.MethodGet, "/api/v1/endpoints/e1/capabilities?name=message.send", ""); rec.Code != http.StatusOK {
		t.Fatalf("capability=%d", rec.Code)
	}
	if rec := call(http.MethodGet, "/api/v1/endpoints/e1/capabilities?name=missing", ""); rec.Code != http.StatusNotImplemented {
		t.Fatalf("unsupported=%d", rec.Code)
	}
	if rec := call(http.MethodPost, "/api/v1/endpoints/e1/capabilities", ""); rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("cap method=%d", rec.Code)
	}
	if rec := call(http.MethodGet, "/api/v1/commands?limit=0", ""); rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("commands=%d", rec.Code)
	}
	if rec := call(http.MethodGet, "/api/v1/commands/missing", ""); rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("command=%d", rec.Code)
	}
	if rec := call(http.MethodPost, "/api/v1/commands/missing/cancel", ""); rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("cancel=%d", rec.Code)
	}
}

func TestCommandHTTPRoutesWithStore(t *testing.T) {
	store := commandTestStore(t)
	defer store.Close()
	service := &CommandService{Store: store}
	h := NewHandlerWithCommands(store, "secret", service)
	call := func(method, path string) *httptest.ResponseRecorder {
		req := httptest.NewRequest(method, path, nil)
		req.Header.Set("Authorization", "Bearer secret")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec
	}
	if got := call(http.MethodGet, "/api/v1/commands"); got.Code != http.StatusOK {
		t.Fatalf("commands list status=%d", got.Code)
	}
	if got := call(http.MethodGet, "/api/v1/commands/missing"); got.Code != http.StatusNotFound {
		t.Fatalf("missing command status=%d", got.Code)
	}
	if got := call(http.MethodPut, "/api/v1/commands"); got.Code != http.StatusMethodNotAllowed {
		t.Fatalf("commands method status=%d", got.Code)
	}
	if got := call(http.MethodGet, "/api/v1/commands/"); got.Code != http.StatusNotFound {
		t.Fatalf("empty command status=%d", got.Code)
	}
}

// recordingOutputRequester captures the forwarded output request so the Server
// boundary can be asserted without a live Endpoint.
type recordingOutputRequester struct {
	request protocol.OutputSnapshotRequest
}

func (r *recordingOutputRequester) RequestOutput(_ context.Context, _ string, request protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	r.request = request
	return protocol.OutputSnapshotResponse{Data: "ok"}, nil
}

// TestOutputHTTPForwardsLineBudget proves the Server parses and clamps the
// optional max_lines parameter, because a line count dropped at this boundary
// never reaches the Endpoint and leaves `logs -n` ineffective.
func TestOutputHTTPForwardsLineBudget(t *testing.T) {
	cases := []struct {
		name  string
		query string
		want  int
	}{
		{name: "absent keeps provider default", query: "", want: 0},
		{name: "explicit count is forwarded", query: "&max_lines=250", want: 250},
		{name: "count above provider maximum is clamped", query: "&max_lines=10001", want: 10000},
		{name: "non-numeric count keeps provider default", query: "&max_lines=abc", want: 0},
		{name: "zero count keeps provider default", query: "&max_lines=0", want: 0},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			store, err := serverstorage.Open(context.Background(), filepath.Join(t.TempDir(), "server.db"))
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			// The Server verifies that the target is registered before it forwards,
			// so the fixture must register the endpoint. This test asserts the line
			// budget, not reachability, so an unregistered target would fail for an
			// unrelated reason.
			if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "e1", InstanceID: "i1", DisplayName: "one", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
				t.Fatal(err)
			}
			requester := &recordingOutputRequester{}
			h := NewHandlerWithCommandsAndBrokerAndOutput(store, "secret", &CommandService{Store: store}, nil, requester)
			req := httptest.NewRequest(http.MethodGet, "/api/v1/output?endpoint_id=e1&resource_id=res_1&provider_generation=g1"+testCase.query, nil)
			req.Header.Set("Authorization", "Bearer secret")
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			if rec.Code != http.StatusOK {
				t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
			}
			if requester.request.MaxLines != testCase.want {
				t.Fatalf("max_lines=%d, want %d", requester.request.MaxLines, testCase.want)
			}
			if requester.request.MaxBytes != 64<<10 {
				t.Fatalf("max_bytes=%d, want the default byte budget", requester.request.MaxBytes)
			}
		})
	}
}
