package bdd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
)

// registerCancellationSteps registers cancellation behavior through HTTP.
func registerCancellationSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a command "([^"]*)" is admitted$`, func(id string) error {
		scenario := activeScenario
		scenario.world.Commands.DispatchDelay = 2 * time.Second
		done := make(chan struct{})
		go func() { _, _ = submitCommandForScenario(scenario, id, "cancel"); close(done) }()
		time.Sleep(25 * time.Millisecond)
		return nil
	})
	ctx.Step(`^the command "([^"]*)" is cancelled before dispatch$`, func(id string) error {
		resp, body := activeScenario.world.Request(activeTest, http.MethodPost, "/api/v1/commands/"+id+"/cancel", nil)
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^the command cancellation succeeds$`, func() error {
		if activeScenario.lastStatus != http.StatusOK {
			return fmt.Errorf("status=%d", activeScenario.lastStatus)
		}
		return nil
	})
	ctx.Step(`^the command "([^"]*)" is cancelled before execution$`, func(id string) error {
		if !bytes.Contains(activeScenario.lastBody, []byte("cancelled_before_execution")) {
			return fmt.Errorf("command %s was not cancelled", id)
		}
		return nil
	})
	ctx.Step(`^a command "([^"]*)" is admitted and dispatched$`, func(id string) error {
		activeScenario.world.Commands.DispatchDelay = 0
		_, err := submitCommand(id, "late")
		return err
	})
	ctx.Step(`^the command "([^"]*)" is cancelled after dispatch$`, func(id string) error {
		resp, body := activeScenario.world.Request(activeTest, http.MethodPost, "/api/v1/commands/"+id+"/cancel", nil)
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^cancellation is too late$`, func() error {
		if activeScenario.lastStatus != http.StatusConflict || !bytes.Contains(activeScenario.lastBody, []byte("too_late_to_cancel")) {
			return fmt.Errorf("unexpected cancellation: %d %s", activeScenario.lastStatus, activeScenario.lastBody)
		}
		return nil
	})
	ctx.Step(`^the provider invocation count is zero$`, func() error {
		if activeScenario.world.Transport.Count() != 0 {
			return fmt.Errorf("transport calls=%d", activeScenario.world.Transport.Count())
		}
		return nil
	})
	ctx.Step(`^cancellation and dispatch race for command "([^"]*)"$`, func(id string) error {
		activeScenario.world.Commands.DispatchDelay = 10 * time.Millisecond
		done := make(chan struct{})
		var sendStatus int
		var sendErr error
		go func() { sendStatus, sendErr = submitCommand(id, "race"); close(done) }()
		time.Sleep(time.Millisecond)
		resp, body := activeScenario.world.Request(activeTest, http.MethodPost, "/api/v1/commands/"+id+"/cancel", nil)
		cancelStatus, cancelBody := resp.StatusCode, body
		<-done
		activeScenario.lastStatus, activeScenario.lastBody = cancelStatus, cancelBody
		if cancelStatus != http.StatusOK && cancelStatus != http.StatusConflict {
			return fmt.Errorf("race cancellation status=%d body=%s", cancelStatus, cancelBody)
		}
		if cancelStatus == http.StatusOK && sendErr == nil && (sendStatus == http.StatusAccepted || sendStatus == http.StatusOK) {
			return fmt.Errorf("both cancellation and dispatch succeeded: send_status=%d", sendStatus)
		}
		return nil
	})
	ctx.Step(`^exactly one cancellation boundary wins$`, func() error {
		if activeScenario.lastStatus != http.StatusOK && activeScenario.lastStatus != http.StatusConflict {
			return fmt.Errorf("unexpected race status=%d", activeScenario.lastStatus)
		}
		resp, body := activeScenario.world.Request(activeTest, http.MethodGet, "/api/v1/commands/bdd-cancel-race", nil)
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("final query status=%d body=%s", resp.StatusCode, body)
		}
		var envelope struct {
			Data map[string]any `json:"data"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		status, _ := envelope.Data["status"].(string)
		if activeScenario.lastStatus == http.StatusOK && status != string(protocol.StatusCancelled) {
			return fmt.Errorf("cancel winner final status=%q", status)
		}
		if activeScenario.lastStatus == http.StatusConflict && status == string(protocol.StatusCancelled) {
			return fmt.Errorf("dispatch winner was reported cancelled: body=%s", body)
		}
		return nil
	})
	_ = json.Valid
}

func submitCommandForScenario(scenario *Scenario, commandID, payload string) (int, error) {
	return submitIntentForScenario(scenario, commandID, payload, time.UnixMilli(4102444800000))
}
