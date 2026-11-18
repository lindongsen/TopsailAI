package client

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestAdmitCommandIsSentExactlyOnceOnTransportFailure locks the property that a
// sent write is never retried.
//
// A write that reached a Server may have been admitted and dispatched. Re-sending
// it to a second Server creates a second intent, and the second Server has no
// channel to the Endpoint, so the operator would see a failure while the operation
// actually ran. For agent.stop and workspace.clean that duplicate is destructive.
//
// The assertion is the request count, not the error: a retry would still return an
// error, so only the count distinguishes "sent once" from "sent twice".
func TestAdmitCommandIsSentExactlyOnceOnTransportFailure(t *testing.T) {
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		// Abort the connection without a response, which is the transport failure
		// a retry would be tempted to absorb.
		hijacker, ok := w.(http.Hijacker)
		if !ok {
			t.Errorf("response writer does not support hijacking")
			return
		}
		conn, _, err := hijacker.Hijack()
		if err != nil {
			t.Errorf("hijack: %v", err)
			return
		}
		_ = conn.Close()
	}))
	t.Cleanup(server.Close)
	api := newBearerClient(server.URL, "token")
	intent := protocol.ImmutableIntent{CommandID: "cmd-1", EndpointID: "endpoint-1"}
	if _, err := api.AdmitCommand(context.Background(), intent); err == nil {
		t.Fatal("AdmitCommand returned no error, want a transport failure")
	}
	if got := atomic.LoadInt32(&hits); got != 1 {
		t.Fatalf("request count = %d, want 1: a sent write must never be retried", got)
	}
}

// TestCancelCommandIsSentExactlyOnceOnTransportFailure locks the same property for
// the other write surface.
func TestCancelCommandIsSentExactlyOnceOnTransportFailure(t *testing.T) {
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		hijacker, ok := w.(http.Hijacker)
		if !ok {
			t.Errorf("response writer does not support hijacking")
			return
		}
		conn, _, err := hijacker.Hijack()
		if err != nil {
			t.Errorf("hijack: %v", err)
			return
		}
		_ = conn.Close()
	}))
	t.Cleanup(server.Close)
	api := newBearerClient(server.URL, "token")
	if _, err := api.CancelCommand(context.Background(), "cmd-1"); err == nil {
		t.Fatal("CancelCommand returned no error, want a transport failure")
	}
	if got := atomic.LoadInt32(&hits); got != 1 {
		t.Fatalf("request count = %d, want 1: a sent write must never be retried", got)
	}
}

// TestReadIsSentExactlyOnceOnTransportFailure asserts that a read is not retried
// either, so the no-retry property is a property of the request path rather than a
// special case for writes.
//
// A read could be retried safely, but it is not, and that is the simpler contract:
// one invocation sends one request to one Server. Retrying a read against a
// different Server would silently mix two worlds in one answer.
func TestReadIsSentExactlyOnceOnTransportFailure(t *testing.T) {
	var hits int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&hits, 1)
		hijacker, ok := w.(http.Hijacker)
		if !ok {
			t.Errorf("response writer does not support hijacking")
			return
		}
		conn, _, err := hijacker.Hijack()
		if err != nil {
			t.Errorf("hijack: %v", err)
			return
		}
		_ = conn.Close()
	}))
	t.Cleanup(server.Close)
	api := newBearerClient(server.URL, "token")
	if _, err := api.ListEndpoints(context.Background()); err == nil {
		t.Fatal("ListEndpoints returned no error, want a transport failure")
	}
	if got := atomic.LoadInt32(&hits); got != 1 {
		t.Fatalf("request count = %d, want 1", got)
	}
}
