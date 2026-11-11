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
	commandDone       chan struct{}
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
func NewWorld(t *testing.T) (*World, error) {
	t.Helper()
	root := t.TempDir()
	store, err := serverstorage.Open(context.Background(), filepath.Join(root, "server.db"))
	if err != nil {
		return nil, fmt.Errorf("open scenario store: %w", err)
	}
	broker := serverapi.NewEventBroker(16)
	transport := &bddTransport{}
	commands := &serverapi.CommandService{Store: store, Transport: transport}
	if err := store.UpsertEndpoint(context.Background(), protocol.Endpoint{EndpointID: "endpoint-1", InstanceID: "bdd-instance", DisplayName: "BDD Endpoint", ConnectionState: "online", ObservedAtMS: 1, CapabilityRevision: "c1"}, 1); err != nil {
		_ = store.Close()
		return nil, fmt.Errorf("seed scenario endpoint: %w", err)
	}
	server := httptest.NewServer(serverapi.NewHandlerWithCommandsAndBroker(store, "bdd-token", commands, broker))
	world := &World{Root: root, Store: store, Server: server, Client: server.Client(), Token: "bdd-token", Commands: commands, Transport: transport}
	t.Cleanup(func() {
		server.Close()
		if err := store.Close(); err != nil {
			t.Logf("close scenario store: %v", err)
		}
	})
	return world, nil
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
	if err := w.realCluster.RestartEndpointE(); err != nil {
		return err
	}
	return nil
}

// SubmitInventory submits an inventory report through the real Server HTTP API.
func (w *World) SubmitInventory(report protocol.InventoryReport) error {
	if w.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	status, body, err := w.realRequestE(http.MethodPut, "/api/v1/endpoints/endpoint-1/session-state", report)
	if err != nil {
		return err
	}
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
	return w.submitRealCommandWithToken(commandID, commandSubmission{Operation: operation, Target: target, Generation: generation, Payload: payload})
}

// commandSubmission describes one immutable command a scenario submits.
//
// The two version fields are separate because they are separate contract values:
// operation_version is what the Endpoint matches against the advertised
// capability version, while payload_schema_version is what the adapter uses to
// decode the payload. command.exec and agent.model.select declare "1" for both,
// so a helper that derived one from the other would look correct today and break
// the first time an operation versions them independently.
type commandSubmission struct {
	Operation            string
	Target               string
	Generation           string
	Payload              string
	OperationVersion     string
	PayloadSchemaVersion string
	EndpointToken        string
}

// SubmitRealCommandWithToken submits one immutable command that presents an
// Endpoint token and caller-selected contract versions.
//
// The Endpoint token is the second, independent credential the Endpoint verifies,
// so a scenario that proves authorization has to present one; the Server forwards
// it unchanged and never interprets it as permission.
func (w *World) SubmitRealCommandWithToken(submission commandSubmission) (string, error) {
	return w.submitRealCommandWithToken(fmt.Sprintf("bdd-real-%d", time.Now().UnixNano()), submission)
}

func (w *World) submitRealCommandWithToken(commandID string, submission commandSubmission) (string, error) {
	if w.realCluster == nil {
		return "", fmt.Errorf("real cluster is not running")
	}
	operationVersion := submission.OperationVersion
	if operationVersion == "" {
		operationVersion = "v1"
	}
	payloadSchemaVersion := submission.PayloadSchemaVersion
	if payloadSchemaVersion == "" {
		payloadSchemaVersion = "v1"
	}
	target, generation := submission.Target, submission.Generation
	if target != "" {
		resolvedTarget, resolvedGeneration, err := w.resolveRealTarget(target, generation)
		if err != nil {
			return "", err
		}
		target, generation = resolvedTarget, resolvedGeneration
	}
	var raw json.RawMessage
	if submission.Payload == "" {
		raw = json.RawMessage(`{}`)
	} else if !json.Valid([]byte(submission.Payload)) {
		return "", fmt.Errorf("invalid command payload")
	} else {
		raw = json.RawMessage(submission.Payload)
	}
	intent := map[string]any{"hash_version": "v1", "command_id": commandID, "endpoint_id": "endpoint-1", "launch_profile_id": "fixture-main", "operation": submission.Operation, "operation_version": operationVersion, "capability_revision": "v1", "payload_schema_version": payloadSchemaVersion, "payload": raw, "execute_before_at_ms": time.Now().Add(20 * time.Second).UnixMilli()}
	// agent.start is the only operation that carries a profile revision, and the
	// Endpoint compares it against the descriptor revision before the policy hook
	// runs. Omitting it would reject every start with profile_revision_mismatch,
	// so a start scenario would pass while proving nothing about authorization.
	if submission.Operation == protocol.OperationAgentStart {
		intent["profile_revision"] = "v1"
	}
	if target != "" {
		intent["target"] = map[string]any{"kind": "session", "resource_id": target, "provider_generation": generation}
	}
	status, body, err := w.realCluster.RequestWithEndpointTokenE(http.MethodPost, "/api/v1/commands", intent, submission.EndpointToken)
	if err != nil {
		return "", err
	}
	if status != http.StatusAccepted && status != http.StatusOK {
		return "", fmt.Errorf("submit command status=%d body=%s", status, body)
	}
	return commandID, nil
}

// resolveRealTarget translates a fixture provider session key into the opaque
// resource ID published by inventory.
//
// Two fixture keys are resolved. fixture-session is the live row. stopped-session
// is the row the provider lists without proving a live process, and it exists
// because agent.resume authorizes on the absence of a live target: a resume
// scenario that used the live row would be refused by target validation before
// the policy hook ever ran, so it would prove nothing about authorization.
func (w *World) resolveRealTarget(target, generation string) (string, string, error) {
	if target != "fixture-session" && target != "stopped-session" {
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
	session, ok := findInventorySession(data, target)
	if !ok {
		return "", "", fmt.Errorf("resolve fixture resource: inventory has no session %q", target)
	}
	resourceID, ok := session["cluster_session_id"].(string)
	if !ok || resourceID == "" {
		return "", "", fmt.Errorf("resolve fixture resource: missing opaque resource ID")
	}
	if value, ok := session["provider_generation"].(string); ok && value != "" {
		generation = value
	}
	return resourceID, generation, nil
}

// findInventorySession locates one reported session by its provider session key.
//
// The live fixture row is also the first row, so a report that omits
// provider_session_id keeps resolving fixture-session to the first row exactly as
// before. The stopped row is only ever found by its provider key, because it is
// deliberately not the first row.
func findInventorySession(sessions []any, providerSessionID string) (map[string]any, bool) {
	for _, entry := range sessions {
		session, ok := entry.(map[string]any)
		if !ok {
			continue
		}
		if value, ok := session["provider_session_id"].(string); ok && value == providerSessionID {
			return session, true
		}
	}
	if providerSessionID != "fixture-session" {
		return nil, false
	}
	session, ok := sessions[0].(map[string]any)
	return session, ok
}

// realRequestE performs a real-cluster request without terminating the BDD test process.
func (w *World) realRequestE(method, path string, payload any) (int, []byte, error) {
	if w.realCluster == nil {
		return 0, nil, fmt.Errorf("real cluster is not running")
	}
	return w.realCluster.RequestE(method, path, payload)
}

// RealCommandStatus reads one command without changing its durable execution fact.
func (w *World) RealCommandStatus(commandID string) (map[string]any, error) {
	if w.realCluster == nil {
		return nil, fmt.Errorf("real cluster is not running")
	}
	status, body, err := w.realRequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
	if err != nil {
		return nil, err
	}
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
	status, body, err := w.realRequestE(http.MethodPost, "/api/v1/commands/"+commandID+"/cancel", nil)
	if err != nil {
		return 0, nil, err
	}
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
		status, body, err := w.realRequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
		if err != nil {
			return nil, err
		}
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

// isTerminalCommandStatus reports whether a durable outcome has been reached. Pre-execution
// states are never terminal even though their effect certainty is unknown: a command that is
// still admitted, dispatched, or endpoint_admitted has not produced any provider effect yet, so
// waiting for a terminal state must keep waiting instead of returning a premature receipt.
func isTerminalCommandStatus(status, certainty string) bool {
	switch status {
	case "finished", "rejected", "expired", "cancelled_before_execution", "cancelled", "failed", "too_late_to_cancel", "unconfirmed":
		return true
	case "admitted", "dispatched", "endpoint_admitted":
		return false
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
		status, body, err := w.realRequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
		if err != nil {
			return nil, err
		}
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

// isStrictTerminalCommandStatus reports a confirmed terminal result. An unconfirmed
// delivery is terminal but its effect is unknown, so it is deliberately excluded here:
// a caller waiting for a confirmed result must not treat "we do not know" as success.
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
	invocations, err := w.realCluster.ProviderInvocationsE()
	if err != nil {
		return 0, err
	}
	return len(invocations), nil
}

// RealInventory reads the latest inventory through the real Server HTTP boundary.
func (w *World) RealInventory() (map[string]any, error) {
	if w.realCluster == nil {
		return nil, fmt.Errorf("real cluster is not running")
	}
	status, body, err := w.realRequestE(http.MethodGet, "/api/v1/endpoints/endpoint-1/session-state", nil)
	if err != nil {
		return nil, err
	}
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

// RequestE performs an authenticated scenario HTTP request and returns failures to the step.
func (w *World) RequestE(method, path string, body any) (*http.Response, []byte, error) {
	var payload []byte
	if body != nil {
		var err error
		payload, err = json.Marshal(body)
		if err != nil {
			return nil, nil, fmt.Errorf("marshal scenario request: %w", err)
		}
	}
	req, err := http.NewRequestWithContext(context.Background(), method, w.URL(path), bytes.NewReader(payload))
	if err != nil {
		return nil, nil, fmt.Errorf("create scenario request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+w.Token)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := w.Client.Do(req)
	if err != nil {
		return nil, nil, fmt.Errorf("send scenario request: %w", err)
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, nil, fmt.Errorf("read scenario response: %w", err)
	}
	return resp, data, nil
}

// Request preserves the legacy test API for non-step callers.
func (w *World) Request(t *testing.T, method, path string, body any) (*http.Response, []byte) {
	t.Helper()
	resp, data, err := w.RequestE(method, path, body)
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
func (w *World) UnsupportedCapability() (int, []byte, error) {
	report := validReport("endpoint-1", 1, true)
	if _, _, err := w.RequestE(http.MethodPut, "/api/v1/endpoints/endpoint-1/session-state", report); err != nil {
		return 0, nil, err
	}
	resp, body, err := w.RequestE(http.MethodGet, "/api/v1/endpoints/endpoint-1/capabilities?name=unsupported.example", nil)
	if err != nil {
		return 0, nil, err
	}
	return resp.StatusCode, body, nil
}

// Eventually polls a bounded assertion until it succeeds or the scenario expires.
func Eventually(check func() bool) error {
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if check() {
			return nil
		}
		time.Sleep(25 * time.Millisecond)
	}
	return fmt.Errorf("condition was not satisfied before scenario deadline")
}
