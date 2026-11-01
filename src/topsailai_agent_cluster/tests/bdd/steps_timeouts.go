package bdd

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/tests/harness"
)

// registerTimeoutSteps registers deadline and durable-query assertions.
func registerTimeoutSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^an expired command "([^"]*)" is submitted$`, func(id string) error {
		status, err := submitCommandWithExpiry(id, time.Now().Add(-time.Second))
		activeScenario.lastStatus = status
		return err
	})
	ctx.Step(`^the command effect is not applied$`, func() error {
		if activeScenario.lastStatus != http.StatusAccepted && activeScenario.lastStatus != http.StatusOK {
			return fmt.Errorf("status=%d", activeScenario.lastStatus)
		}
		if !bytes.Contains(activeScenario.lastBody, []byte("not_applied")) {
			return fmt.Errorf("missing not_applied: %s", activeScenario.lastBody)
		}
		return nil
	})
	ctx.Step(`^a command "([^"]*)" is submitted with a caller wait timeout$`, func(id string) error {
		activeScenario.world.Commands.DispatchDelay = 200 * time.Millisecond
		intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: id, EndpointID: "endpoint-1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: json.RawMessage(`{"text":"wait"}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
		ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
		defer cancel()
		resp, body, err := activeScenario.world.RequestContext(ctx, http.MethodPost, "/api/v1/commands", intent)
		if err == nil {
			return fmt.Errorf("caller timeout did not occur: status=%d body=%s", resp.StatusCode, body)
		}
		if !errors.Is(err, context.DeadlineExceeded) && !strings.Contains(strings.ToLower(err.Error()), "deadline exceeded") {
			return fmt.Errorf("caller error=%v, want deadline exceeded", err)
		}
		activeScenario.lastStatus = 0
		return nil
	})
	ctx.Step(`^the command remains queryable$`, func() error {
		resp, body, err := activeScenario.world.RequestE(http.MethodGet, "/api/v1/commands/bdd-wait-timeout", nil)
		if err != nil {
			return err
		}
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("query status=%d body=%s", resp.StatusCode, body)
		}
		var envelope struct {
			Data map[string]any `json:"data"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		status, _ := envelope.Data["status"].(string)
		if status == "not_applied" || status == "" {
			return fmt.Errorf("invalid durable status=%q body=%s", status, body)
		}
		if code, _ := envelope.Data["error_code"].(string); code == "not_applied" {
			return fmt.Errorf("invalid error_code=not_applied")
		}
		return nil
	})
	ctx.Step(`^a command "([^"]*)" is submitted$`, func(id string) error { _, err := submitCommand(id, "late"); return err })
	ctx.Step(`^a running cluster with one endpoint$`, func() error {
		world, err := NewWorld(activeTest)
		if err != nil {
			return err
		}
		activeScenario.world = world
		return nil
	})
	ctx.Step(`^I submit a command with a sufficient wait budget$`, func() error {
		if activeScenario.world.realCluster == nil {
			if err := activeScenario.world.StartRealCluster(harness.FaultInjection{}); err != nil {
				return err
			}
		}
		activeScenario.realCluster = activeScenario.world.realCluster
		if _, err := activeScenario.realCluster.BuildTUI(activeTest); err != nil {
			return fmt.Errorf("build TUI: %w", err)
		}
		resourceID, err := tuiResourceID()
		if err != nil {
			return err
		}
		generation, err := tuiGeneration(resourceID)
		if err != nil {
			return err
		}
		stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("--json", "--yes", "--wait-timeout-ms", "5000", "control", "endpoint-1", resourceID, `{"text":"wait"}`, generation)
		if runErr != nil || code != 0 {
			return fmt.Errorf("run TUI action: code=%d err=%v stderr=%s stdout=%s", code, runErr, stderr, stdout)
		}
		activeScenario.lastBody = []byte(stdout)
		return nil
	})
	ctx.Step(`^the tui reports a terminal state$`, func() error {
		var value map[string]any
		if err := json.Unmarshal(activeScenario.lastBody, &value); err != nil {
			return err
		}
		status, _ := value["status"].(string)
		if !isTerminalCommandStatus(status, "") {
			return fmt.Errorf("TUI did not report terminal status=%q body=%s", status, activeScenario.lastBody)
		}
		return nil
	})
	ctx.Step(`^a command that is rejected before invocation$`, func() error {
		intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "bdd-not-applied", EndpointID: "endpoint-1", Operation: "message.send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: []byte(`{"text":"rejected"}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
		hash, err := protocol.CanonicalHash(intent)
		if err != nil {
			return err
		}
		if err := activeScenario.world.Store.AdmitCommand(context.Background(), intent, hash, time.Now().UnixMilli()); err != nil {
			return err
		}
		return nil
	})
	ctx.Step(`^the receipt reports not applied$`, func() error {
		intent, err := activeScenario.world.Store.GetCommand(context.Background(), "bdd-not-applied")
		if err != nil {
			return err
		}
		return activeScenario.world.Store.ApplyReceipt(context.Background(), protocol.ExecutionReceipt{CommandID: intent.CommandID, RequestHash: intent.RequestHash, CommandRevision: 1, Phase: protocol.PhaseReceiptRecorded, DeliveryBoundary: protocol.DeliveryNotStarted, EffectCertainty: protocol.EffectNotApplied, Outcome: "rejected"}, time.Now().UnixMilli())
	})
	ctx.Step(`^the command status is not finished$`, func() error {
		commandID := activeScenario.realCommandID
		if commandID == "" {
			commandID = "bdd-not-applied"
		}
		var statusCode int
		var body []byte
		var err error
		if activeScenario.realCommandID != "" {
			statusCode, body, err = activeScenario.world.realRequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
			if err != nil {
				return err
			}
		} else {
			response, responseBody, err := activeScenario.world.RequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
			if err != nil {
				return err
			}
			statusCode, body = response.StatusCode, responseBody
		}
		if statusCode != http.StatusOK {
			return fmt.Errorf("query status=%d body=%s", statusCode, body)
		}
		var envelope struct {
			Data map[string]any `json:"data"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		if value, _ := envelope.Data["status"].(string); value == string(protocol.StatusFinished) {
			return fmt.Errorf("not_applied command was reported as finished")
		}
		return nil
	})
	ctx.Step(`^the command exposes an error code$`, func() error {
		commandID := activeScenario.realCommandID
		if commandID == "" {
			commandID = "bdd-not-applied"
		}
		var statusCode int
		var body []byte
		var err error
		if activeScenario.realCommandID != "" {
			statusCode, body, err = activeScenario.world.realRequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
			if err != nil {
				return err
			}
		} else {
			response, responseBody, err := activeScenario.world.RequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
			if err != nil {
				return err
			}
			statusCode, body = response.StatusCode, responseBody
		}
		if statusCode != http.StatusOK {
			return fmt.Errorf("query status=%d body=%s", statusCode, body)
		}
		var envelope struct {
			Data map[string]any `json:"data"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		if value, _ := envelope.Data["error_code"].(string); value == "" {
			return fmt.Errorf("missing error_code in response: %s", body)
		}
		return nil
	})
	ctx.Step(`^a later query returns the same command$`, func() error {
		resp, body, err := activeScenario.world.RequestE(http.MethodGet, "/api/v1/commands/bdd-late-result", nil)
		if err != nil {
			return err
		}
		if resp.StatusCode != http.StatusOK || !bytes.Contains(body, []byte("bdd-late-result")) {
			return fmt.Errorf("query status=%d body=%s", resp.StatusCode, body)
		}
		return nil
	})
}

func submitCommandWithExpiry(id string, expiry time.Time) (int, error) {
	return submitIntent(id, "expired", expiry)
}

func tuiGeneration(resourceID string) (string, error) {
	data, err := activeScenario.world.RealInventory()
	if err != nil {
		return "", err
	}
	sessions, ok := data["sessions"].([]any)
	if !ok {
		return "", fmt.Errorf("inventory has no sessions")
	}
	for _, raw := range sessions {
		session, ok := raw.(map[string]any)
		if ok && session["session_id"] == resourceID {
			generation, _ := session["generation"].(string)
			return generation, nil
		}
	}
	return "", fmt.Errorf("session %q not found", resourceID)
}
