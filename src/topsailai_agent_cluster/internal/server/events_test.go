package server

import (
	"net/http/httptest"
	"testing"
)

func TestEventBrokerOverflowEmitsResyncRequired(t *testing.T) {
	broker := NewEventBroker(1)
	stream, cleanup := broker.Subscribe()
	defer cleanup()
	broker.Publish("endpoint-1", 1)
	broker.Publish("endpoint-1", 2)
	got := <-stream
	if got.Type != "resync_required" {
		t.Fatalf("event type=%q", got.Type)
	}
	if got.ServerInstanceID == "" {
		t.Fatal("missing server instance ID")
	}
}

func TestEventBrokerPublishesOrderedInventoryEvents(t *testing.T) {
	broker := NewEventBroker(2)
	stream, cleanup := broker.Subscribe()
	defer cleanup()
	broker.Publish("e1", 1)
	broker.Publish("e1", 2)
	first, second := <-stream, <-stream
	if first.Sequence != 1 || second.Sequence != 2 || first.EndpointID != "e1" || second.SnapshotRevision != 2 {
		t.Fatalf("events=%#v %#v", first, second)
	}
}

func TestEventHandlerManifestAndRouting(t *testing.T) {
	broker := NewEventBroker(1)
	h := NewEventHandler(broker, nil)
	for _, tc := range []struct {
		path, method string
		want         int
	}{{"/bad", "GET", 404}, {"/api/v1/events", "POST", 405}, {"/api/v1/manifest", "GET", 200}} {
		req := httptest.NewRequest(tc.method, tc.path, nil)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != tc.want {
			t.Fatalf("%s %s status=%d want=%d", tc.method, tc.path, rec.Code, tc.want)
		}
	}
	if broker.ServerInstanceID() == "" {
		t.Fatal("missing instance ID")
	}
}
