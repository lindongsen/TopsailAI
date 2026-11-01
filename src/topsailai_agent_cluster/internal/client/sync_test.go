package client

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestSyncerContiguousEventsDoNotResync(t *testing.T) {
	var mu sync.Mutex
	manifestCalls, resyncs := 0, 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/manifest" {
			mu.Lock()
			manifestCalls++
			mu.Unlock()
			fmt.Fprint(w, `{"server_instance_id":"s1","entries":[]}`)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		fmt.Fprint(w, "event: inventory_changed\ndata: {\"server_instance_id\":\"s1\",\"sequence\":1}\n\nevent: inventory_changed\ndata: {\"server_instance_id\":\"s1\",\"sequence\":2}\n\n")
	}))
	defer srv.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	err := NewSyncer(srv.URL, "").Run(ctx, func(Manifest) error { mu.Lock(); resyncs++; mu.Unlock(); return nil })
	if err == nil {
		t.Fatal("expected context termination")
	}
	mu.Lock()
	defer mu.Unlock()
	if manifestCalls < 1 || resyncs != 0 {
		t.Fatalf("manifest calls=%d resyncs=%d", manifestCalls, resyncs)
	}
}

func TestSyncerGapInstanceAndResyncRequired(t *testing.T) {
	cases := []struct {
		name   string
		events string
		want   int
	}{
		{"gap", "data: {\"server_instance_id\":\"s1\",\"sequence\":1}\n\ndata: {\"server_instance_id\":\"s1\",\"sequence\":3}\n\n", 1},
		{"instance", "data: {\"server_instance_id\":\"s1\",\"sequence\":1}\n\ndata: {\"server_instance_id\":\"s2\",\"sequence\":2}\n\n", 1},
		{"overflow", "event: resync_required\ndata: {\"type\":\"resync_required\",\"server_instance_id\":\"s1\",\"sequence\":2}\n\n", 1},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			manifests := 0
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/api/v1/manifest" {
					manifests++
					fmt.Fprint(w, `{"server_instance_id":"s1","entries":[]}`)
					return
				}
				w.Header().Set("Content-Type", "text/event-stream")
				fmt.Fprint(w, tc.events)
			}))
			defer srv.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()
			_ = NewSyncer(srv.URL, "").Run(ctx, func(Manifest) error { return nil })
			if manifests < 2 {
				t.Fatalf("manifest calls=%d, want resync fetch", manifests)
			}
		})
	}
}

func TestSyncerRetriesManifestOnConnectionRefused(t *testing.T) {
	var calls, resyncs atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/manifest" {
			call := calls.Add(1)
			if call == 1 {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			fmt.Fprint(w, `{"server_instance_id":"s1","entries":[]}`)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = fmt.Fprint(w, "event: inventory_changed\ndata: {\"server_instance_id\":\"s1\",\"sequence\":1}\n\n")
	}))
	defer server.Close()
	s := NewSyncer(server.URL, "")
	s.sleep = func(context.Context, time.Duration) error { return nil }
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go func() {
		time.Sleep(20 * time.Millisecond)
		cancel()
	}()
	err := s.Run(ctx, func(Manifest) error { resyncs.Add(1); return nil })
	if err != context.Canceled {
		t.Fatalf("Run error=%v, want context canceled", err)
	}
	if calls.Load() < 2 || resyncs.Load() == 0 {
		t.Fatalf("manifest calls=%d resyncs=%d, want retry and resync", calls.Load(), resyncs.Load())
	}
}

func TestSyncerRetriesSSEConnectFailure(t *testing.T) {
	var events, resyncs atomic.Int64
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/manifest" {
			fmt.Fprint(w, `{"server_instance_id":"s1","entries":[]}`)
			return
		}
		event := events.Add(1)
		if event == 1 {
			w.WriteHeader(http.StatusBadGateway)
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = fmt.Fprint(w, "event: inventory_changed\ndata: {\"server_instance_id\":\"s1\",\"sequence\":1}\n\n")
	}))
	defer server.Close()
	s := NewSyncer(server.URL, "")
	s.sleep = func(context.Context, time.Duration) error { return nil }
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		time.Sleep(20 * time.Millisecond)
		cancel()
	}()
	err := s.Run(ctx, func(Manifest) error { resyncs.Add(1); return nil })
	if err != context.Canceled {
		t.Fatalf("Run error=%v, want context canceled", err)
	}
	if events.Load() < 2 || resyncs.Load() == 0 {
		t.Fatalf("SSE attempts=%d resyncs=%d, want retry and resync", events.Load(), resyncs.Load())
	}
}

func TestSyncerStopsOnContextCancel(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	s := NewSyncer("http://127.0.0.1:1", "")
	s.sleep = func(ctx context.Context, _ time.Duration) error { return ctx.Err() }
	cancel()
	if err := s.Run(ctx, nil); err != context.Canceled {
		t.Fatalf("Run error=%v, want context canceled", err)
	}
}

func TestSyncerBackoffIsBounded(t *testing.T) {
	s := NewSyncer("", "")
	s.backoffBase = 200 * time.Millisecond
	s.backoffMax = 5 * time.Second
	for attempt := 0; attempt < 20; attempt++ {
		if delay := s.retryDelay(attempt); delay > s.backoffMax {
			t.Fatalf("attempt %d delay=%s exceeds max=%s", attempt, delay, s.backoffMax)
		}
	}
	if got := s.retryDelay(0); got != 200*time.Millisecond {
		t.Fatalf("initial delay=%s", got)
	}
	if got := s.retryDelay(10); got != 5*time.Second {
		t.Fatalf("bounded delay=%s", got)
	}
}
