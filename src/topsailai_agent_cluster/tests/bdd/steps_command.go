package bdd

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
)

// registerCommandSteps registers command admission and idempotency assertions.
func registerCommandSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^the same command "([^"]*)" is submitted twice with the same intent$`, func(commandID string) error {
		for i := 0; i < 2; i++ {
			status, err := submitCommand(commandID, "same")
			if err != nil {
				return err
			}
			activeScenario.lastStatus = status
			if status != http.StatusAccepted && status != http.StatusOK {
				return fmt.Errorf("submission %d status %d", i+1, status)
			}
		}
		return nil
	})
	ctx.Step(`^both command submissions are accepted$`, func() error {
		if activeScenario.lastStatus != http.StatusAccepted && activeScenario.lastStatus != http.StatusOK {
			return fmt.Errorf("last status %d", activeScenario.lastStatus)
		}
		return nil
	})
	ctx.Step(`^command "([^"]*)" has one durable record$`, func(commandID string) error {
		resp, body := activeScenario.world.Request(activeTest, http.MethodGet, "/api/v1/commands/"+commandID, nil)
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("query status %d", resp.StatusCode)
		}
		if !strings.Contains(string(body), commandID) {
			return fmt.Errorf("command %q absent", commandID)
		}
		return nil
	})
	ctx.Step(`^command "([^"]*)" is submitted with payload "([^"]*)"$`, func(commandID, payload string) error {
		status, err := submitCommand(commandID, payload)
		activeScenario.lastStatus = status
		return err
	})
	ctx.Step(`^the second command submission is an intent conflict$`, func() error {
		if activeScenario.lastStatus != http.StatusConflict {
			return fmt.Errorf("want conflict, got %d", activeScenario.lastStatus)
		}
		return nil
	})
}

func submitCommand(commandID, payload string) (int, error) {
	return submitIntent(commandID, payload, time.UnixMilli(4102444800000))
}

func submitIntent(commandID, payload string, expiry time.Time) (int, error) {
	return submitIntentForScenario(activeScenario, commandID, payload, expiry)
}

func submitIntentForScenario(scenario *Scenario, commandID, payload string, expiry time.Time) (int, error) {
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: commandID, EndpointID: "endpoint-1", Operation: "send", OperationVersion: "v1", CapabilityRevision: "c1", PayloadSchemaVersion: "v1", Payload: json.RawMessage(fmt.Sprintf(`{"text":%q}`, payload)), ExecuteBeforeAtMS: expiry.UnixMilli()}
	resp, body := scenario.world.Request(activeTest, http.MethodPost, "/api/v1/commands", intent)
	scenario.lastStatus = resp.StatusCode
	scenario.lastBody = body
	return resp.StatusCode, nil
}
