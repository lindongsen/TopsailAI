package bdd

import (
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// registerTUISteps registers real subprocess TUI scenarios.
func registerTUISteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a healthy provider for the TUI$`, startTUICluster)
	ctx.Step(`^the TUI list command is run without a TTY$`, runTUIList)
	ctx.Step(`^the TUI list JSON contains the endpoint, adapter, session, generation, and state$`, assertTUIList)
	ctx.Step(`^the TUI show command is run for the fixture session$`, runTUIShow)
	ctx.Step(`^the TUI show JSON contains the session and capability list$`, assertTUIShow)
	ctx.Step(`^the TUI unsupported action is run with confirmation$`, runUnsupportedTUIAction)
	ctx.Step(`^the TUI action is rejected as unsupported$`, assertUnsupportedTUIAction)
	ctx.Step(`^the TUI provider invocation count is zero$`, assertTUIProviderCountZero)
	ctx.Step(`^the TUI stop command is run without a generation$`, runTUIStopWithoutGeneration)
	ctx.Step(`^the TUI stop action is rejected because generation is required$`, assertTUIStopRejected)
	ctx.Step(`^the output shows a recognized lifecycle stage$`, assertRecognizedLifecycleStage)
	ctx.Step(`^the TUI status wording is evaluated$`, evaluateTUIStatusWording)
	ctx.Step(`^submitted is not displayed as ready$`, assertSubmittedNotReady)
	ctx.Step(`^signal sent without exit confirmation is displayed as stop request sent$`, assertSignalSentWording)
	ctx.Step(`^the TUI list JSON is run in a no-TTY subprocess$`, runTUIList)
	ctx.Step(`^the no-TTY TUI output is valid structured JSON$`, assertTUIListJSON)
}

func startTUICluster() error {
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	world := activeScenario.world
	faults := harness.FaultInjection{}
	if activeScenario.scenarioName == "unsupported TUI action is rejected without provider invocation" {
		faults.UnsupportedCapability = "execution.interrupt"
	}
	if err := world.StartRealCluster(faults); err != nil {
		return err
	}
	activeScenario.realCluster = world.realCluster
	if _, err := activeScenario.realCluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build TUI: %w", err)
	}
	return nil
}

func runTUIList() error {
	stdout, stderr, code, err := activeScenario.realCluster.RunTUI("--json", "list")
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if err != nil && code == 0 {
		return fmt.Errorf("run TUI list: %v; stderr=%s", err, stderr)
	}
	return nil
}

func assertTUIList() error {
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("TUI list exit code=%d body=%s", activeScenario.lastStatus, activeScenario.lastBody)
	}
	text := string(activeScenario.lastBody)
	for _, value := range []string{"endpoint-1", "fixture-main", "fixture-generation", "idle"} {
		if !strings.Contains(text, value) {
			return fmt.Errorf("TUI list missing %q: %s", value, text)
		}
	}
	if !strings.Contains(text, "res_") || !strings.Contains(text, "fixture-session") {
		return fmt.Errorf("TUI list does not preserve both opaque resource ID and provider session ID: %s", text)
	}
	return nil
}

func runTUIShow() error {
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUI("--json", "show", resourceID)
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if err != nil && code == 0 {
		return fmt.Errorf("run TUI show: %v; stderr=%s", err, stderr)
	}
	return nil
}

func assertTUIShow() error {
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("TUI show exit code=%d body=%s", activeScenario.lastStatus, activeScenario.lastBody)
	}
	var value map[string]any
	if err := json.Unmarshal(activeScenario.lastBody, &value); err != nil {
		return fmt.Errorf("decode TUI show JSON: %w", err)
	}
	text := string(activeScenario.lastBody)
	for _, field := range []string{"session", "capabilities", "fixture-generation"} {
		if !strings.Contains(text, field) {
			return fmt.Errorf("TUI show missing %q: %s", field, text)
		}
	}
	if !strings.Contains(text, "res_") || !strings.Contains(text, "fixture-session") {
		return fmt.Errorf("TUI show does not preserve both opaque resource ID and provider session ID: %s", text)
	}
	if _, ok := value["capabilities"]; !ok {
		return fmt.Errorf("TUI show has no capabilities field")
	}
	return nil
}

func runUnsupportedTUIAction() error {
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUI("--json", "--yes", "ctl", "endpoint-1", resourceID, "not_advertised")
	activeScenario.lastBody = append([]byte(stdout), []byte(stderr)...)
	activeScenario.lastStatus = code
	if err == nil || code == 0 {
		return fmt.Errorf("unsupported TUI action unexpectedly succeeded: stdout=%s stderr=%s", stdout, stderr)
	}
	return nil
}

func assertUnsupportedTUIAction() error {
	if activeScenario.lastStatus == 0 || !strings.Contains(strings.ToLower(string(activeScenario.lastBody)), "unsupported") {
		return fmt.Errorf("unsupported action evidence missing: %s", activeScenario.lastBody)
	}
	return nil
}

func assertTUIProviderCountZero() error {
	count, err := activeScenario.world.ProviderInvocationCount()
	if err != nil {
		return err
	}
	if count != 0 {
		return fmt.Errorf("provider invocation count=%d, want 0", count)
	}
	return nil
}

func runTUIStopWithoutGeneration() error {
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUI("--json", "--yes", "stop", "endpoint-1", resourceID)
	activeScenario.lastBody = append([]byte(stdout), []byte(stderr)...)
	activeScenario.lastStatus = code
	if err == nil || code == 0 {
		return fmt.Errorf("stop without generation unexpectedly succeeded: stdout=%s stderr=%s", stdout, stderr)
	}
	return nil
}

func assertTUIStopRejected() error {
	if activeScenario.lastStatus == 0 || !strings.Contains(strings.ToLower(string(activeScenario.lastBody)), "generation") {
		return fmt.Errorf("generation rejection evidence missing: %s", activeScenario.lastBody)
	}
	return nil
}

func evaluateTUIStatusWording() error {
	// Use the pure status mapper through the real command lifecycle evidence.
	id, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"status"}`)
	if err != nil {
		return err
	}
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI("status", id)
	if runErr != nil && code == 0 {
		return fmt.Errorf("run TUI status: %v; stderr=%s", runErr, stderr)
	}
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	return nil
}

func assertSubmittedNotReady() error {
	if strings.Contains(strings.ToLower(string(activeScenario.lastBody)), "ready") {
		return fmt.Errorf("submitted status was overstated: %s", activeScenario.lastBody)
	}
	return nil
}

// assertRecognizedLifecycleStage accepts any stage at or after dispatch instead of
// one exact transient stage. The status read races the live command lifecycle, so
// pinning "request delivered" fails whenever the command advances past dispatch
// before the read completes. The exact wording of each stage is already pinned
// deterministically by the "tui renders each command state with distinct wording"
// outline, so this scenario only needs to prove the live read renders a real stage.
func assertRecognizedLifecycleStage() error {
	// The status label is the first output line; receipt details follow it. Matching
	// the whole body would pass vacuously because receipt fields such as
	// "outcome: failed" repeat stage words, so only the label line is inspected.
	lines := strings.SplitN(strings.TrimSpace(string(activeScenario.lastBody)), "\n", 2)
	label := strings.ToLower(strings.TrimSpace(lines[0]))
	stages := []string{
		"server received",
		"request delivered",
		"endpoint received",
		"executing",
		"effect unknown",
		"confirmed result",
		"failed",
		"delivery unconfirmed, effect unknown",
		// StatusLabel falls through to the raw status for terminal states it does
		// not map, so those spellings are legitimate output too.
		"expired",
		"cancelled_before_execution",
	}
	for _, stage := range stages {
		if label == stage {
			return nil
		}
	}
	return fmt.Errorf("status label %q is not a recognized lifecycle stage: %s", label, activeScenario.lastBody)
}

func assertSignalSentWording() error {
	if !strings.Contains(strings.ToLower(string(activeScenario.lastBody)), "stop request sent") {
		return fmt.Errorf("signal-sent wording missing: %s", activeScenario.lastBody)
	}
	return nil
}

// tuiResourceID returns the opaque resource ID currently published by the real inventory.
func tuiResourceID() (string, error) {
	data, err := activeScenario.world.RealInventory()
	if err != nil {
		return "", fmt.Errorf("read TUI inventory: %w", err)
	}
	sessions, ok := data["sessions"].([]any)
	if !ok || len(sessions) == 0 {
		return "", fmt.Errorf("TUI inventory contains no sessions")
	}
	session, ok := sessions[0].(map[string]any)
	if !ok {
		return "", fmt.Errorf("TUI inventory contains an invalid session")
	}
	resourceID, ok := session["session_id"].(string)
	if !ok || resourceID == "" || !strings.HasPrefix(resourceID, "res_") {
		return "", fmt.Errorf("TUI inventory contains no opaque resource ID")
	}
	return resourceID, nil
}

func assertTUIListJSON() error {
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("no-TTY list failed with exit code=%d", activeScenario.lastStatus)
	}
	var value any
	if err := json.Unmarshal(activeScenario.lastBody, &value); err != nil {
		return fmt.Errorf("no-TTY output is not JSON: %w", err)
	}
	return nil
}

// Keep the scenario package's bounded polling convention available to future TUI assertions.
var _ = time.Second
