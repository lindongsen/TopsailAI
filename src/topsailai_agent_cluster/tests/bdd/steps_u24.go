package bdd

import (
	"fmt"
	"time"

	"github.com/cucumber/godog"
)

// registerU24Steps registers real capability-routing checks.
func registerU24Steps(ctx *godog.ScenarioContext) {
	ctx.Step(`^I submit a control command for that session$`, u24SubmitControl)
	ctx.Step(`^the command is not rejected as unsupported$`, u24AssertControlSupported)
}

func u24SubmitControl() error {
	if activeScenario.world == nil || activeScenario.world.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	id, err := activeScenario.world.SubmitRealCommand("execution.interrupt", "fixture-session", "fixture-generation", `{"text":"interrupt"}`)
	if err != nil {
		return err
	}
	activeScenario.realCommandID = id
	status, err := activeScenario.world.PollRealCommand(id, 10*time.Second)
	activeScenario.realCommandStatus = status
	return err
}

func u24AssertControlSupported() error {
	status := stringValue(activeScenario.realCommandStatus, "status", "Status")
	if status == "rejected" {
		return fmt.Errorf("control command was rejected: %#v", activeScenario.realCommandStatus)
	}
	count, err := activeScenario.world.ProviderInvocationCount()
	if err != nil {
		return err
	}
	if count < 1 {
		return fmt.Errorf("provider invocation count=%d, want at least 1", count)
	}
	invocations, err := activeScenario.world.realCluster.ProviderInvocationsE()
	if err != nil {
		return err
	}
	operation, _ := invocations[len(invocations)-1]["operation"].(string)
	if operation != "execution.interrupt" {
		return fmt.Errorf("provider operation=%q, want execution.interrupt", operation)
	}
	certainty := stringValue(activeScenario.realCommandStatus, "effect_certainty", "EffectCertainty")
	if certainty == "not_applied" {
		return fmt.Errorf("control effect certainty is not_applied: %#v", activeScenario.realCommandStatus)
	}
	return nil
}
