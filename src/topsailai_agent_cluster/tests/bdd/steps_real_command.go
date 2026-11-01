package bdd

import (
	"fmt"
	"time"

	"github.com/cucumber/godog"
)

// registerRealCommandSteps registers one real command provider-boundary smoke test.
func registerRealCommandSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a send command is submitted for the fixture session$`, func() error {
		commandID, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"hello"}`)
		if err != nil {
			return err
		}
		activeScenario.realCommandID = commandID
		return nil
	})
	ctx.Step(`^the command reaches a terminal state$`, func() error {
		status, err := activeScenario.world.PollRealCommand(activeScenario.realCommandID, 10*time.Second)
		if status != nil {
			activeScenario.realCommandStatus = status
		}
		if err != nil {
			return err
		}
		if statusName := commandStatus(status); !isTerminalCommandStatus(statusName, commandEffectCertainty(status)) {
			return fmt.Errorf("command is not terminal: %#v", status)
		}
		return nil
	})
	ctx.Step(`^the provider was invoked exactly once$`, func() error {
		count, err := activeScenario.world.ProviderInvocationCount()
		if err != nil {
			return err
		}
		if count != 1 {
			return fmt.Errorf("provider invocation count=%d, want 1 status=%#v", count, activeScenario.realCommandStatus)
		}
		return nil
	})
}

func commandStatus(status map[string]any) string {
	return stringValue(status, "status", "Status")
}

func commandEffectCertainty(status map[string]any) string {
	return stringValue(status, "effect_certainty", "EffectCertainty")
}
