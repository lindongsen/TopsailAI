package bdd

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// registerRealTimeoutSteps registers bounded timeout and cancellation assertions over real processes.
func registerRealTimeoutSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster is started with a (\d+)ms receipt delay$`, func(delay int) error {
		return startRealFaultCluster(harness.FaultInjection{ReceiptDelayMS: delay})
	})
	ctx.Step(`^a real cluster is started with invocation crash enabled$`, func() error {
		return startRealFaultCluster(harness.FaultInjection{CrashAfterInvocationStarted: true})
	})
	ctx.Step(`^a real command is submitted for the fixture session$`, func() error {
		id, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"timeout"}`)
		activeScenario.realCommandID = id
		return err
	})
	ctx.Step(`^the real command is observed before its receipt arrives$`, func() error {
		status, err := activeScenario.world.RealCommandStatus(activeScenario.realCommandID)
		if err != nil {
			return err
		}
		activeScenario.realCommandStatus = status
		name := commandStatus(status)
		if name == "not_applied" || name == "expired" || name == "" {
			return fmt.Errorf("unexpected early status %#v", status)
		}
		return nil
	})
	ctx.Step(`^the early command status is awaiting confirmation rather than not applied$`, func() error {
		name := commandStatus(activeScenario.realCommandStatus)
		if name != "dispatched" && name != "endpoint_admitted" && name != "executing" {
			return fmt.Errorf("status=%q, want dispatched or later pre-receipt state", name)
		}
		return nil
	})
	ctx.Step(`^the real command eventually has unknown effect certainty$`, func() error {
		status, err := activeScenario.world.PollRealCommand(activeScenario.realCommandID, 10*time.Second)
		activeScenario.realCommandStatus = status
		if err != nil {
			return err
		}
		if commandEffectCertainty(status) != "unknown" && commandStatus(status) != "unknown" {
			return fmt.Errorf("status %#v is not unknown", status)
		}
		return nil
	})
	ctx.Step(`^the provider invocation count is one$`, func() error {
		count, err := activeScenario.world.ProviderInvocationCount()
		if err != nil {
			return err
		}
		if count != 1 {
			return fmt.Errorf("provider invocation count=%d, want 1", count)
		}
		return nil
	})
	ctx.Step(`^the delayed real command is first non-terminal$`, func() error {
		status, err := activeScenario.world.RealCommandStatus(activeScenario.realCommandID)
		if err != nil {
			return err
		}
		activeScenario.realCommandStatus = status
		if isTerminalCommandStatus(commandStatus(status), commandEffectCertainty(status)) {
			return fmt.Errorf("command was already terminal: %#v", status)
		}
		return nil
	})
	ctx.Step(`^the delayed real command eventually reaches a terminal state$`, func() error {
		status, err := activeScenario.world.PollRealCommand(activeScenario.realCommandID, 10*time.Second)
		activeScenario.realCommandStatus = status
		if err != nil {
			return err
		}
		if !isTerminalCommandStatus(commandStatus(status), commandEffectCertainty(status)) {
			return fmt.Errorf("not terminal: %#v", status)
		}
		return nil
	})
	ctx.Step(`^a real command is submitted and polled with a 100ms caller timeout$`, func() error {
		id, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"wait"}`)
		if err != nil {
			return err
		}
		activeScenario.realCommandID = id
		status, pollErr := activeScenario.world.PollRealCommandForCaller(id, 100*time.Millisecond)
		if pollErr == nil {
			return fmt.Errorf("short caller wait unexpectedly reached terminal state: %#v", status)
		}
		activeScenario.realCommandStatus = status
		return nil
	})
	ctx.Step(`^a later real query returns the durable execution result$`, func() error {
		status, err := activeScenario.world.PollRealCommand(activeScenario.realCommandID, 10*time.Second)
		activeScenario.realCommandStatus = status
		if err != nil {
			return err
		}
		if !isTerminalCommandStatus(commandStatus(status), commandEffectCertainty(status)) {
			return fmt.Errorf("not terminal: %#v", status)
		}
		return nil
	})
	ctx.Step(`^a real cluster is started with a (\d+)ms dispatch delay$`, func(delay int) error {
		return startRealFaultCluster(harness.FaultInjection{DispatchDelayMS: delay})
	})
	ctx.Step(`^a real command is admitted and cancellation is requested immediately$`, func() error {
		id := fmt.Sprintf("bdd-real-cancel-%d", time.Now().UnixNano())
		activeScenario.realCommandID = id
		done := make(chan error, 1)
		go func() {
			_, err := activeScenario.world.SubmitRealCommandWithID(id, "message.send", "fixture-session", "fixture-generation", `{"text":"cancel"}`)
			done <- err
		}()
		time.Sleep(50 * time.Millisecond)
		status, body, err := activeScenario.world.CancelRealCommand(id)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = status, body
		if status != http.StatusOK {
			return fmt.Errorf("cancel status=%d body=%s", status, body)
		}
		if err := <-done; err == nil {
			return fmt.Errorf("dispatch unexpectedly succeeded after cancellation")
		}
		return nil
	})
	ctx.Step(`^the real command is cancelled before provider execution$`, func() error {
		status, err := activeScenario.world.RealCommandStatus(activeScenario.realCommandID)
		if err != nil {
			return err
		}
		if commandStatus(status) != "cancelled_before_execution" {
			return fmt.Errorf("status=%#v", status)
		}
		count, err := activeScenario.world.ProviderInvocationCount()
		if err != nil {
			return err
		}
		if count != 0 {
			return fmt.Errorf("provider invocation count=%d, want 0", count)
		}
		return nil
	})
	ctx.Step(`^a real command send and cancellation race with a (\d+)ms dispatch delay$`, func(delay int) error {
		_ = delay
		id := fmt.Sprintf("bdd-real-race-%d", time.Now().UnixNano())
		activeScenario.realCommandID = id
		var wg sync.WaitGroup
		var sendErr error
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, sendErr = activeScenario.world.SubmitRealCommandWithID(id, "message.send", "fixture-session", "fixture-generation", `{"text":"race"}`)
		}()
		time.Sleep(50 * time.Millisecond)
		cancelStatus, cancelBody, err := activeScenario.world.CancelRealCommand(id)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = cancelStatus, cancelBody
		wg.Wait()
		if cancelStatus != http.StatusOK && cancelStatus != http.StatusConflict {
			return fmt.Errorf("cancel status=%d body=%s", cancelStatus, cancelBody)
		}
		if cancelStatus == http.StatusOK && sendErr == nil {
			return fmt.Errorf("both cancellation and dispatch succeeded")
		}
		return nil
	})
	ctx.Step(`^the real cancellation race has one winner and at most one provider invocation$`, func() error {
		count, err := activeScenario.world.ProviderInvocationCount()
		if err != nil {
			return err
		}
		if count != 0 && count != 1 {
			return fmt.Errorf("provider invocation count=%d, want 0 or 1", count)
		}
		status, err := activeScenario.world.RealCommandStatus(activeScenario.realCommandID)
		if err != nil {
			return err
		}
		name := commandStatus(status)
		if activeScenario.lastStatus == http.StatusConflict {
			if name != "dispatched" && name != "finished" && name != "executing" {
				return fmt.Errorf("dispatch winner status=%q, want dispatched or finished: %#v", name, status)
			}
			if count != 1 {
				return fmt.Errorf("dispatch winner provider invocation count=%d, want 1", count)
			}
			if strings.Contains(string(activeScenario.lastBody), "too_late_to_cancel") == false {
				return fmt.Errorf("dispatch winner lacks too_late_to_cancel: %s", activeScenario.lastBody)
			}
		} else if activeScenario.lastStatus == http.StatusOK {
			if name != "cancelled_before_execution" && name != "cancelled" {
				return fmt.Errorf("cancel winner status=%q, want cancelled: %#v", name, status)
			}
			if count != 0 {
				return fmt.Errorf("cancel winner provider invocation count=%d, want 0", count)
			}
		} else {
			return fmt.Errorf("unexpected race status=%d", activeScenario.lastStatus)
		}
		return nil
	})
}

func startRealFaultCluster(faults harness.FaultInjection) error {
	activeScenario.world = &World{}
	return activeScenario.world.StartRealCluster(faults)
}

// realCommandJSON is retained as a small decoding seam for future real-boundary assertions.
func realCommandJSON(status map[string]any) string {
	data, _ := json.Marshal(status)
	return strings.TrimSpace(string(data))
}
