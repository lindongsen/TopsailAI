package bdd

import (
	"context"
	"testing"

	"github.com/cucumber/godog"
)

// TestFeatures runs the strict real-boundary BDD suite.
func TestFeatures(t *testing.T) {
	activeTest = t
	suite := godog.TestSuite{
		ScenarioInitializer: InitializeScenario,
		Options: &godog.Options{Format: "progress", Paths: []string{
			"../../features/inventory.feature",
			"../../features/command_idempotency.feature",
			"../../features/notifications.feature",
			"../../features/capability.feature",
			"../../features/cancellation.feature",
			"../../features/timeouts.feature",
			"../../features/real_boundary.feature",
			"../../features/command_recovery.feature",
			"../../features/provider_response.feature",
			"../../features/tui.feature",
			"../../features/lifecycle.feature",
			"../../features/commands.feature",
			"../../features/unknown_input_offer.feature",
			"../../features/bidirectional_channel.feature",
			"../../features/output_follow.feature",
			"../../features/output_scope.feature",
		}, Strict: true, TestingT: t},
	}
	if suite.Run() != 0 {
		t.Fatal("godog suite failed")
	}
}

// InitializeScenario registers steps and resets the scenario world.
func InitializeScenario(ctx *godog.ScenarioContext) {
	scenario := &Scenario{}
	ctx.Before(func(goCtx context.Context, scenarioDef *godog.Scenario) (context.Context, error) {
		activeScenario = scenario
		activeScenario.scenarioName = scenarioDef.Name
		return goCtx, nil
	})
	registerInventorySteps(ctx)
	registerInventoryFreshnessSteps(ctx)
	registerRealInventorySteps(ctx)
	registerRealInventoryFreshnessSteps(ctx)
	registerRealCommandSteps(ctx)
	registerRealTimeoutSteps(ctx)
	registerRecoverySteps(ctx)
	registerCommandSteps(ctx)
	registerNotificationSteps(ctx)
	registerCapabilitySteps(ctx)
	registerCancellationSteps(ctx)
	registerTimeoutSteps(ctx)
	registerTUISteps(ctx)
	registerU20Steps(ctx)
	registerU21Steps(ctx)
	registerU22Steps(ctx)
	registerU24Steps(ctx)
	registerProviderResponseSteps(ctx)
	registerWatchSteps(ctx)
	registerUnknownInputOfferSteps(ctx)
	registerBidirectionalSteps(ctx)
	registerFollowSteps(ctx)
	registerOutputScopeSteps(ctx)
	registerQReturnsToWorkspaceSteps(ctx)
	ctx.After(func(goCtx context.Context, _ *godog.Scenario, _ error) (context.Context, error) {
		if activeScenario != nil && activeScenario.commandDone != nil {
			<-activeScenario.commandDone
			activeScenario.commandDone = nil
		}
		if activeScenario != nil && activeScenario.world != nil {
			activeScenario.world.StopRealCluster()
		}
		activeScenario = nil
		return goCtx, nil
	})
}
