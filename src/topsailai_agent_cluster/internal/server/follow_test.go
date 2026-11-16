package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
)

// followRequester is a streaming transport double. It records the request it
// received and replays a fixed event sequence.
type followRequester struct {
	events   []channel.FollowEvent
	err      error
	gotReq   protocol.OutputFollowRequest
	gotEP    string
	callSeen bool
}

func (f *followRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (f *followRequester) RequestFollow(_ context.Context, endpointID string, req protocol.OutputFollowRequest) (<-chan channel.FollowEvent, error) {
	f.callSeen = true
	f.gotEP = endpointID
	f.gotReq = req
	if f.err != nil {
		return nil, f.err
	}
	events := make(chan channel.FollowEvent, len(f.events))
	for _, event := range f.events {
		events <- event
	}
	close(events)
	return events, nil
}

// snapshotOnlyRequester implements only the snapshot interface, so the handler
// must report unsupported rather than degrade into a snapshot.
type snapshotOnlyRequester struct{}

func (snapshotOnlyRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

// followHandler builds a handler with the given output transport.
func followHandler(output any) *Handler {
	h := &Handler{Authenticator: security.BearerAuthenticator{Token: "secret"}}
	if requester, ok := output.(OutputRequester); ok {
		h.Output = requester
	}
	return h
}

// callFollow issues one authenticated follow request and returns the recorder.
func callFollow(t *testing.T, h *Handler, method, path string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	req.Header.Set("Authorization", "Bearer secret")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

// decodeRecords parses the newline-delimited JSON body into generic records.
func decodeRecords(t *testing.T, body string) []map[string]any {
	t.Helper()
	var records []map[string]any
	decoder := json.NewDecoder(strings.NewReader(body))
	for decoder.More() {
		var record map[string]any
		if err := decoder.Decode(&record); err != nil {
			t.Fatalf("decode record: %v (body=%q)", err, body)
		}
		records = append(records, record)
	}
	return records
}

// TestOutputFollowStreamsChunksThenEnd verifies the streamed record shape and
// that the terminal record is always last.
func TestOutputFollowStreamsChunksThenEnd(t *testing.T) {
	follower := &followRequester{events: []channel.FollowEvent{
		{Chunk: &protocol.OutputChunk{Lines: []string{"one", "two"}, ObservedAtMS: 10}},
		{Chunk: &protocol.OutputChunk{Lines: []string{"three"}, ObservedAtMS: 20, Truncated: true}},
		{End: &protocol.OutputEnd{ObservedAtMS: 30}},
	}}
	h := followHandler(follower)
	rec := callFollow(t, h, http.MethodGet, "/api/v1/output/follow?endpoint_id=e1&resource_id=res_1&provider_generation=g1")

	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Content-Type"); got != "application/x-ndjson" {
		t.Fatalf("content type %q", got)
	}
	if got := rec.Header().Get("Cache-Control"); got != "no-store" {
		t.Fatalf("cache control %q", got)
	}
	if rec.Header().Get("X-Request-ID") == "" {
		t.Fatal("request id header is missing")
	}
	records := decodeRecords(t, rec.Body.String())
	if len(records) != 3 {
		t.Fatalf("records %d: %s", len(records), rec.Body.String())
	}
	for i, want := range []string{"chunk", "chunk", "end"} {
		if records[i]["type"] != want {
			t.Fatalf("record %d type %v, want %s", i, records[i]["type"], want)
		}
	}
	if records[0]["observed_at_ms"] != float64(10) {
		t.Fatalf("chunk observation %v", records[0]["observed_at_ms"])
	}
	if records[1]["truncated"] != true {
		t.Fatalf("chunk truncation flag %v", records[1]["truncated"])
	}
	if records[2]["observed_at_ms"] != float64(30) {
		t.Fatalf("end observation %v", records[2]["observed_at_ms"])
	}
	if follower.gotEP != "e1" || follower.gotReq.ResourceID != "res_1" || follower.gotReq.ProviderGeneration != "g1" {
		t.Fatalf("forwarded request %+v for %q", follower.gotReq, follower.gotEP)
	}
}

// TestOutputFollowRejectsUnsupportedTransport verifies a snapshot-only transport
// reports unsupported instead of silently returning one snapshot.
func TestOutputFollowRejectsUnsupportedTransport(t *testing.T) {
	h := followHandler(snapshotOnlyRequester{})
	rec := callFollow(t, h, http.MethodGet, "/api/v1/output/follow?endpoint_id=e1&resource_id=res_1")
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "unsupported") {
		t.Fatalf("body %q", rec.Body.String())
	}
}

// TestOutputFollowValidatesMethodAndTarget verifies rejected requests never reach
// the transport.
func TestOutputFollowValidatesMethodAndTarget(t *testing.T) {
	follower := &followRequester{}
	h := followHandler(follower)
	if rec := callFollow(t, h, http.MethodPost, "/api/v1/output/follow?endpoint_id=e1&resource_id=res_1"); rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("method status %d", rec.Code)
	}
	if rec := callFollow(t, h, http.MethodGet, "/api/v1/output/follow?endpoint_id=e1"); rec.Code != http.StatusBadRequest {
		t.Fatalf("target status %d", rec.Code)
	}
	if rec := callFollow(t, h, http.MethodGet, "/api/v1/output/follow?resource_id=res_1"); rec.Code != http.StatusBadRequest {
		t.Fatalf("endpoint status %d", rec.Code)
	}
	if follower.callSeen {
		t.Fatal("an invalid request reached the transport")
	}
}

// TestOutputFollowReportsEndpointOffline verifies a transport failure is reported
// as endpoint_offline rather than an empty successful stream.
func TestOutputFollowReportsEndpointOffline(t *testing.T) {
	h := followHandler(&followRequester{err: context.DeadlineExceeded})
	rec := callFollow(t, h, http.MethodGet, "/api/v1/output/follow?endpoint_id=e1&resource_id=res_1")
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "endpoint_offline") {
		t.Fatalf("body %q", rec.Body.String())
	}
}

// TestOutputFollowClampsByteBudget verifies an oversized byte budget is clamped
// before it reaches the transport.
func TestOutputFollowClampsByteBudget(t *testing.T) {
	follower := &followRequester{events: []channel.FollowEvent{{End: &protocol.OutputEnd{}}}}
	h := followHandler(follower)
	rec := callFollow(t, h, http.MethodGet, "/api/v1/output/follow?endpoint_id=e1&resource_id=res_1&max_bytes=99999999&max_lines=250")
	if rec.Code != http.StatusOK {
		t.Fatalf("status %d: %s", rec.Code, rec.Body.String())
	}
	if follower.gotReq.MaxBytes != 1<<20 {
		t.Fatalf("max bytes %d", follower.gotReq.MaxBytes)
	}
	if follower.gotReq.MaxLines != 250 {
		t.Fatalf("max lines %d", follower.gotReq.MaxLines)
	}
}

// blockingFollowRequester serves a stream that produces nothing until the test
// releases it, so a caller can prove the response headers arrive before the
// first record instead of after it.
type blockingFollowRequester struct {
	events chan channel.FollowEvent
}

func (b *blockingFollowRequester) RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error) {
	return protocol.OutputSnapshotResponse{}, nil
}

func (b *blockingFollowRequester) RequestFollow(context.Context, string, protocol.OutputFollowRequest) (<-chan channel.FollowEvent, error) {
	return b.events, nil
}

// TestOutputFollowFlushesHeadersBeforeTheFirstRecord proves the follow response
// returns to the caller before any record exists.
//
// The caller is the REPL prompt, and it opens the stream before it starts
// reading keys. A response that waits for the first record therefore makes the
// terminal deaf for the whole provider startup window, so "any key stops" waits
// for the provider instead of for the operator. The assertion is that the
// request returns while the event channel is still open and empty: a return
// caused by data would be indistinguishable from a return caused by the flush.
func TestOutputFollowFlushesHeadersBeforeTheFirstRecord(t *testing.T) {
	requester := &blockingFollowRequester{events: make(chan channel.FollowEvent)}
	h := followHandler(requester)
	server := httptest.NewServer(h)
	defer server.Close()
	// The handler ranges over the event channel, so it must be released before
	// the server waits for outstanding requests. Deferred calls run last-in
	// first-out, so this close runs before server.Close above.
	defer close(requester.events)

	req, err := http.NewRequest(http.MethodGet, server.URL+"/api/v1/output/follow?endpoint_id=e1&resource_id=res_1", nil)
	if err != nil {
		t.Fatalf("new request: %v", err)
	}
	req.Header.Set("Authorization", "Bearer secret")

	type outcome struct {
		resp *http.Response
		err  error
	}
	returned := make(chan outcome, 1)
	go func() {
		resp, doErr := server.Client().Do(req)
		returned <- outcome{resp: resp, err: doErr}
	}()

	select {
	case got := <-returned:
		if got.err != nil {
			t.Fatalf("follow request: %v", got.err)
		}
		defer got.resp.Body.Close()
		if got.resp.StatusCode != http.StatusOK {
			t.Fatalf("status %d", got.resp.StatusCode)
		}
		if got.resp.Header.Get("Content-Type") != "application/x-ndjson" {
			t.Fatalf("content type %q", got.resp.Header.Get("Content-Type"))
		}
		// No record was produced, so the return can only be the flushed header.
		if pending := len(requester.events); pending != 0 {
			t.Fatalf("the stream already held %d records, so this return proves nothing", pending)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("the follow response did not return before the first record, so the caller is blocked on provider output")
	}
}
