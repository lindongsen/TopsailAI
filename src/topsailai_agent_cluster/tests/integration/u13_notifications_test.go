//go:build integration

package integration_test

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"testing"
	"time"

	clientapi "topsailai_agent_cluster/internal/client"
	serverapi "topsailai_agent_cluster/internal/server"
)

type u13Manifest struct {
	ServerInstanceID string `json:"server_instance_id"`
	Entries          []struct {
		EndpointID       string `json:"endpoint_id"`
		SnapshotRevision int64  `json:"snapshot_revision"`
	} `json:"entries"`
}

// TestManifestReflectsLatestRevision verifies durable manifest and session-state revisions agree.
func TestManifestReflectsLatestRevision(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	defer c.stop(t)
	m := fetchU13Manifest(t, c)
	if len(m.Entries) != 1 || m.Entries[0].EndpointID != "endpoint-1" || m.Entries[0].SnapshotRevision < 1 {
		t.Fatalf("unexpected manifest: %+v", m)
	}
	var state struct {
		Data struct {
			SnapshotRevision int64 `json:"snapshot_revision"`
		} `json:"data"`
	}
	getU13(t, c, "/api/v1/endpoints/endpoint-1/session-state", &state)
	if m.Entries[0].SnapshotRevision != state.Data.SnapshotRevision {
		t.Fatalf("manifest revision=%d state revision=%d", m.Entries[0].SnapshotRevision, state.Data.SnapshotRevision)
	}
}

// TestSSEEventOnInventoryUpdate verifies the complete invalidation event envelope.
func TestSSEEventOnInventoryUpdate(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	defer c.stop(t)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, http.MethodGet, c.url("/api/v1/events"), nil)
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	data := readU13SSE(t, resp.Body)
	var event clientapi.Event
	if err := json.Unmarshal([]byte(data), &event); err != nil {
		t.Fatal(err)
	}
	if event.EndpointID != "endpoint-1" || event.SnapshotRevision < 1 || event.ServerInstanceID == "" || event.Sequence < 1 {
		t.Fatalf("incomplete event: %+v", event)
	}
}

// TestLostNotificationConvergesViaManifest verifies a reconnect baseline contains current state.
func TestLostNotificationConvergesViaManifest(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	m1 := fetchU13Manifest(t, c)
	c.stop(t)
	c = restartU12Cluster(t, c)
	defer c.stop(t)
	m2 := fetchU13Manifest(t, c)
	if m2.ServerInstanceID == m1.ServerInstanceID {
		t.Fatal("restart did not create a new server instance")
	}
	if len(m2.Entries) != 1 || m2.Entries[0].SnapshotRevision < m1.Entries[0].SnapshotRevision {
		t.Fatalf("manifest did not converge: before=%+v after=%+v", m1, m2)
	}
}

// TestQueueOverflowTriggersResync verifies overflow is represented by an explicit event.
func TestQueueOverflowTriggersResync(t *testing.T) {
	broker := serverapi.NewEventBroker(1)
	stream, cleanup := broker.Subscribe()
	defer cleanup()
	broker.Publish("endpoint-1", 1)
	broker.Publish("endpoint-1", 2)
	event := <-stream
	if event.Type != "resync_required" || event.ServerInstanceID == "" {
		t.Fatalf("unexpected overflow event: %+v", event)
	}
}

// TestServerRestartChangesInstanceID verifies Syncer observes restart and invokes reconciliation.
func TestServerRestartChangesInstanceID(t *testing.T) {
	c := startU12Cluster(t, nil, false)
	defer c.stop(t)
	first := fetchU13Manifest(t, c)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	resyncs := make(chan u13Manifest, 4)
	s := clientapi.NewSyncer(c.url(""), "secret")
	done := make(chan error, 1)
	go func() {
		done <- s.Run(ctx, func(manifest clientapi.Manifest) error {
			entries := make([]struct {
				EndpointID       string `json:"endpoint_id"`
				SnapshotRevision int64  `json:"snapshot_revision"`
			}, len(manifest.Entries))
			for i, entry := range manifest.Entries {
				entries[i].EndpointID = entry.EndpointID
				entries[i].SnapshotRevision = entry.SnapshotRevision
			}
			resyncs <- u13Manifest{ServerInstanceID: manifest.ServerInstanceID, Entries: entries}
			return nil
		})
	}()

	// Keep the Endpoint and listening addresses unchanged while restarting only the Server.
	oldServer := c.server
	if err := syscall.Kill(oldServer.Process.Pid, syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		candidate := exec.Command(oldServer.Path)
		candidate.Dir = moduleRoot(t)
		candidate.Env = append([]string(nil), oldServer.Env...)
		candidate.Stdout, candidate.Stderr = os.Stdout, os.Stderr
		if err := candidate.Start(); err == nil {
			c.server = candidate
			break
		}
		_, _ = candidate.Process.Wait()
		time.Sleep(50 * time.Millisecond)
	}
	if c.server == oldServer {
		t.Fatal("restarted Server did not start")
	}
	waitExit(t, oldServer, 30*time.Second)
	waitHTTP(t, c.url("/healthz"), "", http.StatusOK, 15*time.Second)
	second := fetchU13Manifest(t, c)
	if first.ServerInstanceID == second.ServerInstanceID {
		t.Fatal("server instance ID did not change")
	}

	select {
	case got := <-resyncs:
		if got.ServerInstanceID != second.ServerInstanceID {
			t.Fatalf("resync instance=%q restarted instance=%q", got.ServerInstanceID, second.ServerInstanceID)
		}
		if len(got.Entries) != len(second.Entries) || len(got.Entries) == 0 || got.Entries[0].SnapshotRevision != second.Entries[0].SnapshotRevision {
			t.Fatalf("resync manifest=%+v restarted manifest=%+v", got, second)
		}
	case err := <-done:
		t.Fatalf("Syncer stopped before restart resync: %v", err)
	case <-ctx.Done():
		t.Fatal("Syncer did not call onResync after Server restart")
	}
	cancel()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Syncer did not stop")
	}
}

func fetchU13Manifest(t *testing.T, c *u12Cluster) u13Manifest {
	var m u13Manifest
	getU13(t, c, "/api/v1/manifest", &m)
	return m
}
func getU13(t *testing.T, c *u12Cluster, path string, target any) {
	t.Helper()
	req, _ := http.NewRequest(http.MethodGet, c.url(path), nil)
	req.Header.Set("Authorization", "Bearer secret")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		t.Fatalf("GET %s: %s %s", path, resp.Status, b)
	}
	if err := json.NewDecoder(resp.Body).Decode(target); err != nil {
		t.Fatal(err)
	}
}
func readU13SSE(t *testing.T, r io.Reader) string {
	t.Helper()
	scanner := bufio.NewScanner(r)
	var data string
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "data:") {
			data = strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		}
		if line == "" && data != "" {
			return data
		}
	}
	t.Fatal("SSE stream ended without event")
	return ""
}

var _ = fmt.Sprint
var _ = httptest.NewServer
