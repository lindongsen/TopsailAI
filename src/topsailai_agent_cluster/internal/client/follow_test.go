package client

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// TestFollowOutputDecodesRecordsUntilEnd verifies the streaming client decodes
// chunk records and stops at the terminal record.
func TestFollowOutputDecodesRecordsUntilEnd(t *testing.T) {
	var query string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		query = r.URL.RawQuery
		if r.Header.Get("Authorization") != "Bearer token" {
			http.Error(w, `{"message":"unauthorized"}`, http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = fmt.Fprint(w, `{"type":"chunk","lines":["one","two"],"observed_at_ms":10}`+"\n")
		_, _ = fmt.Fprint(w, `{"type":"chunk","lines":["three"],"observed_at_ms":20,"truncated":true}`+"\n")
		_, _ = fmt.Fprint(w, `{"type":"end","error_code":"","observed_at_ms":30}`+"\n")
	}))
	defer server.Close()

	records, err := NewAPIClient(server.URL, "token").FollowOutput(context.Background(), "e1", "res_1", "g1", 4096, 250)
	if err != nil {
		t.Fatal(err)
	}
	var chunks []FollowChunk
	for chunk := range records {
		chunks = append(chunks, chunk)
	}
	if len(chunks) != 3 {
		t.Fatalf("chunks %d: %+v", len(chunks), chunks)
	}
	if len(chunks[0].Lines) != 2 || chunks[0].Lines[0] != "one" || chunks[0].ObservedAtMS != 10 {
		t.Fatalf("first chunk %+v", chunks[0])
	}
	if !chunks[1].Truncated || chunks[1].Lines[0] != "three" {
		t.Fatalf("second chunk %+v", chunks[1])
	}
	if !chunks[2].End || chunks[2].ErrorCode != "" || chunks[2].ObservedAtMS != 30 {
		t.Fatalf("end chunk %+v", chunks[2])
	}
	for _, want := range []string{"endpoint_id=e1", "resource_id=res_1", "generation=g1", "max_bytes=4096", "max_lines=250"} {
		if !strings.Contains(query, want) {
			t.Fatalf("query %q missing %q", query, want)
		}
	}
}

// TestFollowOutputReportsInterruptedStream verifies a body that ends without an
// end record is reported as interrupted rather than complete.
func TestFollowOutputReportsInterruptedStream(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = fmt.Fprint(w, `{"type":"chunk","lines":["one"],"observed_at_ms":10}`+"\n")
	}))
	defer server.Close()

	records, err := NewAPIClient(server.URL, "").FollowOutput(context.Background(), "e1", "res_1", "g1", 4096, 250)
	if err != nil {
		t.Fatal(err)
	}
	var chunks []FollowChunk
	for chunk := range records {
		chunks = append(chunks, chunk)
	}
	if len(chunks) != 2 {
		t.Fatalf("chunks %d: %+v", len(chunks), chunks)
	}
	if !chunks[1].End || chunks[1].ErrorCode != "stream_interrupted" {
		t.Fatalf("terminal chunk %+v", chunks[1])
	}
}

// TestFollowOutputRejectsFailedResponse verifies a non-2xx response surfaces the
// server message instead of an empty stream.
func TestFollowOutputRejectsFailedResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = fmt.Fprint(w, `{"code":"unsupported","message":"Endpoint output follow is unavailable"}`)
	}))
	defer server.Close()

	if _, err := NewAPIClient(server.URL, "").FollowOutput(context.Background(), "e1", "res_1", "g1", 4096, 250); err == nil {
		t.Fatal("a failed response was accepted")
	} else if !strings.Contains(err.Error(), "unavailable") {
		t.Fatalf("error %v", err)
	}
}

// TestFollowOutputStopsOnContextCancel verifies cancelling the caller context
// closes the stream instead of blocking forever.
func TestFollowOutputStopsOnContextCancel(t *testing.T) {
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/x-ndjson")
		_, _ = fmt.Fprint(w, `{"type":"chunk","lines":["one"],"observed_at_ms":10}`+"\n")
		w.(http.Flusher).Flush()
		select {
		case <-release:
		case <-r.Context().Done():
		}
	}))
	defer server.Close()
	defer close(release)

	ctx, cancel := context.WithCancel(context.Background())
	records, err := NewAPIClient(server.URL, "").FollowOutput(ctx, "e1", "res_1", "g1", 4096, 250)
	if err != nil {
		t.Fatal(err)
	}
	if chunk := <-records; len(chunk.Lines) != 1 {
		t.Fatalf("first chunk %+v", chunk)
	}
	cancel()
	for range records {
	}
}
