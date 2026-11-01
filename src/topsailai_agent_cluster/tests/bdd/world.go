package bdd

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"sync"
	"testing"
	"time"

	topsailai "topsailai_agent_cluster/internal/adapter/topsailai"
	"topsailai_agent_cluster/internal/protocol"
	serverapi "topsailai_agent_cluster/internal/server"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
	"topsailai_agent_cluster/tests/harness"
)

// Scenario contains isolated state shared by the steps of one scenario.
type Scenario struct {
	world             *World
	lastStatus        int
	lastBody          []byte
	capabilityAdapter *topsailai.Adapter
	capabilityErr     error
	capabilityCalls   int
	realCluster       *harness.Cluster
	realCommandID     string
	realCommandStatus map[string]any
	firstInventory    protocol.InventoryReport
	tuiExpectedState  string
	holdDir           string
	scenarioName      string
}

var activeScenario *Scenario
var activeTest *testing.T

// World owns isolated resources and the real HTTP server used by one scenario.
type World struct {
	Root        string
	Store       *serverstorage.Store
	Server      *httptest.Server
	Client      *http.Client
	Token       string
	Commands    *serverapi.CommandService
	Transport   *bddTransport
	events      chan []byte
	realCluster *harness.Cluster
}

// NewWorld creates a scenario-scoped server and SQLite database on a dynamic port.
func NewWorld(t *testing.T) *World {
	t.Helper()
	root := t.TempDir()
	store, err := serverstorage.Open(context.Background(), filepath.Join(root, "server.db"))
	if err != nil {
		t.Fatal(err)
	}
	broker := serverapi.NewEventBroker(16)
	transport := &bddTransport{}
	commands := &serverapi.CommandService{Store: store, Transport: transport}
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "bdd-instance", DisplayName: "BDD Endpoint", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(serverapi.NewHandlerWithCommandsAndBroker(store, "bdd-token", commands, broker))
	world := &World{Root: root, Store: store, Server: server, Client: server.Client(), Token: "bdd-token", Commands: commands, Transport: transport}
	t.Cleanup(func() {
		server.Close()
		if err := store.Close(); err != nil {
			t.Logf("close scenario store: %v", err)
		}
	})
	return world
}

// StartRealCluster starts the real Server, Endpoint, and Provider fixture processes.
func (w *World) StartRealCluster(faults harness.FaultInjection) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{DelayMS: faults.DelayMS, Faults: faults})
	if err != nil {
		return err
	}
	w.realCluster = cluster
	return nil
}

// StopRealCluster stops the real processes owned by this World.
func (w *World) StopRealCluster() {
	if w.realCluster != nil && activeTest != nil {
		w.realCluster.Stop(activeTest)
		w.realCluster = nil
	}
}

// RestartRealEndpoint restarts the Endpoint process while preserving its journal and configuration.
func (w *World) RestartRealEndpoint() error {
	if w.realCluster == nil || activeTest == nil {
		return fmt.Errorf("real cluster is not running")
	}
	w.realCluster.RestartEndpoint(activeTest)
	return nil
}

// SubmitInventory submits an inventory report through the real Server HTTP API.
func (w *World) SubmitInventory(report protocol.InventoryReport) error {
	if w.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	status, body := w.realCluster.Request(activeTest, http.MethodPut, "/api/v1/endpoints/endpoint-1/session-state", report)
	if status != http.StatusOK {
		return fmt.Errorf("inventory submission status=%d body=%s", status, body)
	}
	return nil
}

// SubmitRealCommand submits one immutable command through the real Server HTTP API.
func (w *World) SubmitRealCommand(operation, target, generation, payload string) (string, error) {
	return w.submitRealCommand(fmt.Sprintf("bdd-real-%d", time.Now().UnixNano()), operation, target, generation, payload)
}

// SubmitRealCommandWithOperation submits a real command with a caller-selected operation.
func (w *World) SubmitRealCommandWithOperation(operation, target, generation, payload string) (string, error) {
	return w.SubmitRealCommand(operation, target, generation, payload)
}

// SubmitRealCommandWithID submits a real command using a caller-selected ID for race tests.
func (w *World) SubmitRealCommandWithID(commandID, operation, target, generation, payload string) (string, error) {
	if commandID == "" {
		return "", fmt.Errorf("command ID is required")
	}
	return w.submitRealCommand(commandID, operation, target, generation, payload)
}

func (w *World) submitRealCommand(commandID, operation, target, generation, payload string) (string, error) {
	if w.realCluster == nil {
		return "", fmt.Errorf("real cluster is not running")
	}
	if target != "" {
		resolvedTarget, resolvedGeneration, err := w.resolveRealTarget(target, generation)
		if err != nil {
			return "", err
		}
		target, generation = resolvedTarget, resolvedGeneration
	}
	var raw json.RawMessage
	if payload == "" {
		raw = json.RawMessage(`{}`)
	} else if !json.Valid([]byte(payload)) {
		return "", fmt.Errorf("invalid command payload")
	} else {
		raw = json.RawMessage(payload)
	}
	intent := map[string]any{"hash_version": "v1", "command_id": commandID, "endpoint_id": "endpoint-1", "launch_profile_id": "fixture-main", "operation": operation, "operation_version": "v1", "capability_revision": "v1", "payload_schema_version": "v1", "payload": raw, "execute_before_at_ms": time.Now().Add(20 * time.Second).UnixMilli()}
	if target != "" {
		intent["target"] = map[string]any{"kind": "session", "resource_id": target, "generation": generation}
	}
	status, body := w.realCluster.Request(activeTest, http.MethodPost, "/api/v1/commands", intent)
	if status != http.StatusAccepted && status != http.StatusOK {
		return "", fmt.Errorf("submit command status=%d body=%s", status, body)
	}
	return commandID, nil
}

// resolveRealTarget translates the fixture provider key into the opaque resource ID published by inventory.
func (w *World) resolveRealTarget(target, generation string) (string, string, error) {
	if target != "fixture-session" {
		return target, generation, nil
	}
	report, err := w.RealInventory()
	if err != nil {
		return "", "", fmt.Errorf("resolve fixture resource: %w", err)
	}
	data, ok := report["sessions"].([]any)
	if !ok || len(data) == 0 {
		return "", "", fmt.Errorf("resolve fixture resource: inventory has no sessions")
	}
	session, ok := data[0].(map[string]any)
	if !ok {
		return "", "", fmt.Errorf("resolve fixture resource: invalid session record")
	}
	resourceID, ok := session["session_id"].(string)
	if !ok || resourceID == "" {
		return "", "", fmt.Errorf("resolve fixture resource: missing opaque resource ID")
	}
	if value, ok := session["generation"].(string); ok && value != "" {
		generation = value
	}
	return resourceID, generation, nil
}

// RealCommandStatus reads one command without changing its durable execution fact.
func (w *World) RealCommandStatus(commandID string) (map[string]any, error) {
	if w.realCluster == nil {
		return nil, fmt.Errorf("real cluster is not running")
	}
	status, body := w.realCluster.Request(activeTest, http.MethodGet, "/api/v1/commands/"+commandID, nil)
	if status != http.StatusOK {
		return nil, fmt.Errorf("command status=%d body=%s", status, body)
	}
	var envelope struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		return nil, err
	}
	return envelope.Data, nil
}

// CancelRealCommand requests atomic cancellation through the real Server boundary.
func (w *World) CancelRealCommand(commandID string) (int, []byte, error) {
	if w.realCluster == nil {
		return 0, nil, fmt.Errorf("real cluster is not running")
	}
	status, body := w.realCluster.Request(activeTest, http.MethodPost, "/api/v1/commands/"+commandID+"/cancel", nil)
	return status, body, nil
}

// PollRealCommand polls a real command until it reaches a terminal state or the timeout expires.
func (w *World) PollRealCommand(commandID string, timeout time.Duration) (map[string]any, error) {
	if w.realCluster == nil {
		return nil, fmt.Errorf("real cluster is not running")
	}
	deadline := time.Now().Add(timeout)
	var last map[string]any
	for time.Now().Before(deadline) {
		status, body := w.realCluster.Request(activeTest, http.MethodGet, "/api/v1/commands/"+commandID, nil)
		if status == http.StatusOK {
			var envelope struct {
				Data map[string]any `json:"data"`
			}
			if err := json.Unmarshal(body, &envelope); err != nil {
				return nil, err
			}
			last = envelope.Data
			value := stringValue(last, "status", "Status")
			certainty := stringValue(last, "effect_certainty", "EffectCertainty")
			boundary := stringValue(last, "delivery_boundary", "delivery_state", "DeliveryBoundary")
			if boundary == string(protocol.DeliverySignalSent) || isTerminalCommandStatus(value, certainty) {
				return last, nil
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	if last == nil {
		return nil, fmt.Errorf("command %q was not observable before timeout", commandID)
	}
	return last, fmt.Errorf("command %q polling timed out", commandID)
}

func stringValue(values map[string]any, keys ...string) string {
	for _, key := range keys {
		if value, ok := values[key].(string); ok {
			return value
		}
	}
	return ""
}

func isTerminalCommandStatus(status, certainty string) bool {
	switch status {
	case "finished", "rejected", "expired", "cancelled_before_execution", "cancelled", "failed", "too_late_to_cancel":
		return true
	case "executing":
		return certainty == "unknown"
	}
	return certainty == "unknown"
}

// PollRealCommandForCaller waits only for a terminal durable result, excluding unknown execution state.
func (w *World) PollRealCommandForCaller(commandID string, timeout time.Duration) (map[string]any, error) {
	if w.realCluster == nil {
		return nil, fmt.Errorf("real cluster is not running")
	}
	deadline := time.Now().Add(timeout)
	var last map[string]any
	for time.Now().Before(deadline) {
		status, body := w.realCluster.Request(activeTest, http.MethodGet, "/api/v1/commands/"+commandID, nil)
		if status == http.StatusOK {
			var envelope struct {
				Data map[string]any `json:"data"`
			}
			if err := json.Unmarshal(body, &envelope); err != nil {
				return nil, err
			}
			last = envelope.Data
			if isStrictTerminalCommandStatus(commandStatus(last), commandEffectCertainty(last)) {
				return last, nil
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	if last == nil {
		return nil, fmt.Errorf("command %q was not observable before timeout", commandID)
	}
	return last, fmt.Errorf("command %q polling timed out", commandID)
}

func isStrictTerminalCommandStatus(status, certainty string) bool {
	switch status {
	case "finished", "rejected", "expired", "cancelled_before_execution", "cancelled", "failed", "too_late_to_cancel":
		return true
	case "executing":
		return certainty != "unknown" && certainty != ""
	default:
		return false
	}
}

// ProviderInvocationCount returns the number of fixture invocations recorded by the real cluster.
func (w *World) ProviderInvocationCount() (int, error) {
	if w.realCluster == nil {
		return 0, fmt.Errorf("real cluster is not running")
	}
	return len(w.realCluster.ProviderInvocations(activeTest)), nil
}

// RealInventory reads the latest inventory through the real Server HTTP boundary.
func (w *World) RealInventory() (map[string]any, error) {
	if w.realCluster == nil {
		return nil, fmt.Errorf("real cluster is not running")
	}
	status, body := w.realCluster.Request(activeTest, http.MethodGet, "/api/v1/endpoints/endpoint-1/session-state", nil)
	if status != http.StatusOK {
		return nil, fmt.Errorf("inventory status=%d body=%s", status, body)
	}
	var envelope struct {
		Data map[string]any `json:"data"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		return nil, err
	}
	return envelope.Data, nil
}

// bddTransport records dispatches at the real Server transport boundary.
type bddTransport struct {
	mu    sync.Mutex
	count int
}

// Send records one admitted command without invoking a provider.
func (t *bddTransport) Send(context.Context, protocol.TransportEnvelope) error {
	t.mu.Lock()
	t.count++
	t.mu.Unlock()
	return nil
}

// Count returns the number of commands handed to the transport.
func (t *bddTransport) Count() int { t.mu.Lock(); defer t.mu.Unlock(); return t.count }

// URL builds an endpoint relative to the scenario's dynamically allocated listener.
func (w *World) URL(path string) string { return w.Server.URL + path }

// Request performs an authenticated real HTTP request against the scenario server.
func (w *World) Request(t *testing.T, method, path string, body any) (*http.Response, []byte) {
	t.Helper()
	var payload []byte
	if body != nil {
		var err error
		payload, err = json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
	}
	req, err := http.NewRequestWithContext(context.Background(), method, w.URL(path), bytes.NewReader(payload))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer "+w.Token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := w.Client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return resp, data
}

// RequestContext performs an authenticated HTTP request with a caller-controlled context.
func (w *World) RequestContext(ctx context.Context, method, path string, body any) (*http.Response, []byte, error) {
	var payload []byte
	if body != nil {
		var err error
		payload, err = json.Marshal(body)
		if err != nil {
			return nil, nil, err
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, w.URL(path), bytes.NewReader(payload))
	if err != nil {
		return nil, nil, err
	}
	req.Header.Set("Authorization", "Bearer "+w.Token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := w.Client.Do(req)
	if err != nil {
		return nil, nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	return resp, data, err
}

// UnsupportedCapability requests an unsupported capability through the real HTTP boundary.
func (w *World) UnsupportedCapability() (int, []byte) {
	report := validReport("endpoint-1", 1, true)
	_, _ = w.Request(activeTest, http.MethodPut, "/api/v1/endpoints/endpoint-1/session-state", report)
	resp, body := w.Request(activeTest, http.MethodGet, "/api/v1/endpoints/endpoint-1/capabilities?name=unsupported.example", nil)
	return resp.StatusCode, body
}

// Eventually polls a bounded assertion until it succeeds or the scenario expires.
func Eventually(t *testing.T, check func() bool) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if check() {
			return
		}
		time.Sleep(25 * time.Millisecond)
	}
	t.Fatal("condition was not satisfied before scenario deadline")
}
