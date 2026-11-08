package bdd

import (
	"fmt"
	"strings"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// registerProviderResponseSteps registers the provider raw return display scenarios.
// These scenarios drive the interactive REPL, because the two-part output is an
// interactive surface: the non-interactive CLI renders JSON only.
func registerProviderResponseSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a healthy provider for the interactive REPL$`, startInteractiveCluster)
	ctx.Step(`^a real cluster whose provider fails execution$`, startInteractiveFailingCluster)
	ctx.Step(`^a session scope send is driven through the interactive REPL$`, driveInteractiveSend)
	ctx.Step(`^the interactive output shows the service receipt section$`, assertInteractiveReceiptSection)
	ctx.Step(`^the interactive output shows the provider raw return section$`, assertInteractiveProviderSection)
	ctx.Step(`^the interactive output carries the provider document verbatim$`, assertProviderDocumentVerbatim)
	ctx.Step(`^the service receipt section appears before the provider raw return section$`, assertReceiptBeforeProvider)
	ctx.Step(`^the interactive output shows the provider diagnostic$`, assertInteractiveProviderDiagnostic)
}

// interactiveSendScript navigates to the first session row, sends one literal
// message and quits. An explicit send submits directly, so no answer line is
// needed. Row navigation is used because the startup list already rendered the
// visible numbering.
const interactiveSendScript = "cd 1\nsend bdd provider response probe\nquit\n"

// startInteractiveCluster starts a real cluster whose provider succeeds.
func startInteractiveCluster() error {
	return startInteractiveClusterWith(harness.FaultInjection{})
}

// startInteractiveFailingCluster starts a real cluster whose provider fails
// execution while keeping discovery healthy, so the session is still visible.
func startInteractiveFailingCluster() error {
	return startInteractiveClusterWith(harness.FaultInjection{ProviderFailAdapterID: "fixture-main"})
}

// startInteractiveClusterWith starts the real cluster and builds the CLI binary.
func startInteractiveClusterWith(faults harness.FaultInjection) error {
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	world := activeScenario.world
	if err := world.StartRealCluster(faults); err != nil {
		return err
	}
	activeScenario.realCluster = world.realCluster
	if _, err := activeScenario.realCluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build CLI: %w", err)
	}
	return nil
}

// driveInteractiveSend runs the scripted REPL session and records its output.
// The wait budget is shortened so a command whose effect stays unknown does not
// consume the default ten second local wait.
func driveInteractiveSend() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIInteractive(interactiveSendScript, "--wait-timeout-ms", "3000")
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if err != nil && code == 0 {
		return fmt.Errorf("run interactive REPL: %v; stderr=%s", err, stderr)
	}
	if code != 0 {
		return fmt.Errorf("interactive REPL exit code=%d stderr=%s output=%s", code, stderr, stdout)
	}
	return nil
}

// interactiveOutput returns the recorded REPL output.
func interactiveOutput() string {
	return string(activeScenario.lastBody)
}

// assertInteractiveReceiptSection proves this service's own receipt is rendered.
func assertInteractiveReceiptSection() error {
	text := interactiveOutput()
	for _, value := range []string{"command submitted:", "delivery_boundary:", "effect_certainty:"} {
		if !strings.Contains(text, value) {
			return fmt.Errorf("interactive output is missing the service receipt field %q: %s", value, text)
		}
	}
	return nil
}

// assertInteractiveProviderSection proves the provider's own document is rendered
// under its own labelled section, separate from this service's receipt. The
// document itself is provider-specific, so only the section and a non-empty body
// are asserted here; the verbatim content is asserted by its own step.
func assertInteractiveProviderSection() error {
	text := interactiveOutput()
	index := strings.Index(text, "provider_response:")
	if index < 0 {
		return fmt.Errorf("interactive output is missing the provider raw return section: %s", text)
	}
	body := strings.TrimSpace(text[index+len("provider_response:"):])
	if body == "" {
		return fmt.Errorf("provider raw return section is empty: %s", text)
	}
	return nil
}

// assertProviderDocumentVerbatim proves the provider's own document appears
// unmodified, so the section carries provider evidence rather than a re-rendered
// summary. The fixture provider's success document is the expected content.
func assertProviderDocumentVerbatim() error {
	text := interactiveOutput()
	if !strings.Contains(text, `"effect_certainty":"acknowledged"`) {
		return fmt.Errorf("interactive output does not carry the provider document verbatim: %s", text)
	}
	return nil
}

// assertReceiptBeforeProvider proves the two parts are ordered: the service
// receipt first, then the provider's raw return.
func assertReceiptBeforeProvider() error {
	text := interactiveOutput()
	receipt := strings.Index(text, "command submitted:")
	provider := strings.Index(text, "provider_response:")
	if receipt < 0 || provider < 0 {
		return fmt.Errorf("interactive output is missing one of the two sections: %s", text)
	}
	if receipt > provider {
		return fmt.Errorf("provider raw return appears before the service receipt: %s", text)
	}
	return nil
}

// assertInteractiveProviderDiagnostic proves a failed provider invocation still
// surfaces the provider's own diagnostic instead of discarding it.
func assertInteractiveProviderDiagnostic() error {
	text := interactiveOutput()
	if !strings.Contains(text, "fixture execution failure") {
		return fmt.Errorf("interactive output is missing the provider diagnostic: %s", text)
	}
	return nil
}
