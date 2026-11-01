package bdd

import (
	"fmt"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// registerRecoverySteps registers real-process command recovery scenarios.
func registerRecoverySteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster is started for recovery before invocation crash$`, func() error {
		return startRealFaultCluster(harness.FaultInjection{CrashBeforeInvocation: true, DispatchDelayMS: 2000})
	})
	ctx.Step(`^a real command is submitted before invocation crash$`, func() error {
		id := fmt.Sprintf("bdd-recovery-pre-%d", time.Now().UnixNano())
		activeScenario.realCommandID = id
		done := make(chan error, 1)
		go func() {
			_, err := activeScenario.world.SubmitRealCommandWithID(id, "message.send", "fixture-session", "fixture-generation", `{"text":"recovery"}`)
			done <- err
		}()
		activeScenario.world.realCluster.WaitForBeforeInvocationCrash(activeTest, 10*time.Second)
		if err := activeScenario.world.RestartRealEndpoint(); err != nil {
			return err
		}
		if err := <-done; err != nil {
			return err
		}
		return nil
	})
	ctx.Step(`^the recovered command eventually finishes from accepted journal with one provider invocation$`, func() error {
		status, err := activeScenario.world.PollRealCommand(activeScenario.realCommandID, 10*time.Second)
		if err != nil {
			return err
		}
		if commandStatus(status) != "finished" {
			return fmt.Errorf("recovered command status=%#v", status)
		}
		return requireInvocationCount(1)
	})
	ctx.Step(`^a real cluster is started for invocation recovery$`, func() error {
		return startRealFaultCluster(harness.FaultInjection{CrashAfterInvocationStarted: true})
	})
	ctx.Step(`^the crashed command reaches unknown certainty before endpoint restart$`, func() error {
		id, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"uncertain"}`)
		if err != nil {
			return err
		}
		activeScenario.realCommandID = id
		status, err := activeScenario.world.PollRealCommand(id, 10*time.Second)
		if err != nil {
			return err
		}
		if commandEffectCertainty(status) != "unknown" && commandStatus(status) != "unknown" {
			return fmt.Errorf("expected unknown certainty, got %#v", status)
		}
		return nil
	})
	ctx.Step(`^restarting the endpoint preserves unknown certainty without a second invocation$`, func() error {
		if err := activeScenario.world.RestartRealEndpoint(); err != nil {
			return err
		}
		status, err := activeScenario.world.RealCommandStatus(activeScenario.realCommandID)
		if err != nil {
			return err
		}
		if commandEffectCertainty(status) != "unknown" && commandStatus(status) != "unknown" {
			return fmt.Errorf("restart changed uncertainty: %#v", status)
		}
		return requireInvocationCount(1)
	})
	ctx.Step(`^a real cluster is started with receipt acknowledgements dropped$`, func() error {
		return startRealFaultCluster(harness.FaultInjection{DropAck: true})
	})
	ctx.Step(`^the provider invocation count remains one$`, func() error {
		return requireInvocationCount(1)
	})
	ctx.Step(`^a real command is submitted and its receipt converges after acknowledgement loss$`, func() error {
		id, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"ack-loss"}`)
		if err != nil {
			return err
		}
		activeScenario.realCommandID = id
		status, err := activeScenario.world.PollRealCommand(id, 10*time.Second)
		if err != nil {
			return err
		}
		if !isTerminalCommandStatus(commandStatus(status), commandEffectCertainty(status)) {
			return fmt.Errorf("receipt did not converge: %#v", status)
		}
		return requireInvocationCount(1)
	})
	ctx.Step(`^a real command finishes before the endpoint is restarted$`, func() error {
		id, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"restart"}`)
		if err != nil {
			return err
		}
		activeScenario.realCommandID = id
		status, err := activeScenario.world.PollRealCommand(id, 10*time.Second)
		if err != nil {
			return err
		}
		if commandStatus(status) != "finished" {
			return fmt.Errorf("command did not finish: %#v", status)
		}
		activeScenario.realCommandStatus = status
		return nil
	})
	ctx.Step(`^restarting the endpoint preserves the finished command without replay$`, func() error {
		if err := activeScenario.world.RestartRealEndpoint(); err != nil {
			return err
		}
		status, err := activeScenario.world.RealCommandStatus(activeScenario.realCommandID)
		if err != nil {
			return err
		}
		if commandStatus(status) != "finished" {
			return fmt.Errorf("restart changed command: %#v", status)
		}
		return requireInvocationCount(1)
	})
}

func requireInvocationCount(want int) error {
	count, err := activeScenario.world.ProviderInvocationCount()
	if err != nil {
		return err
	}
	if count != want {
		return fmt.Errorf("provider invocation count=%d, want %d", count, want)
	}
	return nil
}
