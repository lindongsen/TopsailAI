package bdd

import (
	"errors"
	"fmt"

	"github.com/cucumber/godog"
)

// registerCapabilitySteps registers the explicit unsupported-capability check.
//
// Only the steps that exercise the Cluster over its real HTTP boundary remain.
// The scenarios that drove the removed in-process TopsailAI adapter directly
// (its platform probe, and a stop submitted without a generation) were deleted
// together with that adapter: they asserted its Go interface rather than Cluster
// behaviour. The generation refusal they covered is still asserted through the
// operator CLI in features/tui.feature and by the Generic CLI Adapter unit tests,
// so deleting them removes a duplicate seam rather than the only check.
func registerCapabilitySteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^an unsupported capability is requested$`, func() error {
		if activeScenario.world == nil {
			return errors.New("scenario server is not initialized")
		}
		status, body, err := activeScenario.world.UnsupportedCapability()
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = status, body
		return nil
	})
	ctx.Step(`^the response is unsupported$`, func() error {
		if activeScenario.lastStatus != 501 || !containsText(activeScenario.lastBody, "unsupported") {
			return fmt.Errorf("expected unsupported response, status=%d body=%s", activeScenario.lastStatus, activeScenario.lastBody)
		}
		return nil
	})
}

// containsText reports whether body contains text as a byte substring.
func containsText(body []byte, text string) bool {
	for i := 0; i+len(text) <= len(body); i++ {
		if string(body[i:i+len(text)]) == text {
			return true
		}
	}
	return false
}
