package bdd

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/tests/harness"
)

// registerU20Steps registers positive human-readable lifecycle evidence checks.
func registerU20Steps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a command in state "([^"]*)"$`, prepareTUIState)
	ctx.Step(`^I run the tui show command in human readable mode$`, runHumanTUIStatus)
	ctx.Step(`^the output contains "([^"]*)"$`, assertHumanTUIWording)
	ctx.Step(`^a running session with a known generation$`, prepareStopSession)
	ctx.Step(`^I submit a stop command for that session$`, submitStopCommand)
	ctx.Step(`^the receipt reports delivery state signal_sent$`, assertSignalSentReceipt)
	ctx.Step(`^the receipt reports exit confirmed false$`, assertExitNotConfirmed)
}

func prepareTUIState(state string) error {
	activeScenario.tuiExpectedState = state
	activeScenario.world = &World{}
	faults := harness.FaultInjection{}
	operation := "message.send"
	switch state {
	case "admitted":
		faults.HoldPhase = state
		faults.HoldDir = activeTest.TempDir()
		activeScenario.holdDir = faults.HoldDir
	case "dispatched":
		faults.HoldPhase = state
		faults.HoldDir = activeTest.TempDir()
		activeScenario.holdDir = faults.HoldDir
		faults.DispatchDelayMS = 50
		faults.DelayMS = 1000
	case "endpoint_admitted":
		faults.HoldPhase = state
		faults.HoldDir = activeTest.TempDir()
		activeScenario.holdDir = faults.HoldDir
		faults.DelayMS = 1000
	case "effect_unknown":
		faults.CrashAfterInvocationStarted = true
	case "rejected":
		faults.UnsupportedCapability = "message.send"
	case "failed":
		faults.UnsupportedCapability = "message.send"
	}
	if err := activeScenario.world.StartRealCluster(faults); err != nil {
		return err
	}
	activeScenario.realCluster = activeScenario.world.realCluster
	if _, err := activeScenario.realCluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build TUI: %w", err)
	}
	commandID := fmt.Sprintf("bdd-tui-%d", time.Now().UnixNano())
	activeScenario.realCommandID = commandID
	if state == "admitted" {
		go func() {
			_, _ = activeScenario.world.SubmitRealCommandWithID(commandID, operation, "fixture-session", "fixture-generation", `{"text":"status"}`)
		}()
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			if _, err := activeScenario.world.RealCommandStatus(commandID); err == nil {
				return nil
			}
			time.Sleep(15 * time.Millisecond)
		}
		return fmt.Errorf("admitted command was not persisted")
	}
	if state == "dispatched" || state == "endpoint_admitted" {
		result := make(chan error, 1)
		go func() {
			_, submitErr := activeScenario.world.SubmitRealCommandWithID(commandID, operation, "fixture-session", "fixture-generation", `{"text":"status"}`)
			result <- submitErr
		}()
		if faults.HoldDir == "" {
			return fmt.Errorf("phase gate directory is empty for %s", state)
		}
		signalName := "reached-server-" + state
		if state == "endpoint_admitted" {
			signalName = "reached-endpoint-" + state
		}
		phase := filepath.Join(faults.HoldDir, signalName)
		deadline := time.Now().Add(10 * time.Second)
		for time.Now().Before(deadline) {
			if _, err := os.Stat(phase); err == nil {
				return nil
			}
			time.Sleep(15 * time.Millisecond)
		}
		return fmt.Errorf("phase gate %s was not reached", state)
	}

	id, err := activeScenario.world.SubmitRealCommandWithID(commandID, operation, "fixture-session", "fixture-generation", `{"text":"status"}`)
	if err != nil {
		return err
	}
	activeScenario.realCommandID = id
	status, pollErr := activeScenario.world.PollRealCommand(id, 10*time.Second)
	if pollErr != nil && state != "effect_unknown" {
		return pollErr
	}
	activeScenario.realCommandStatus = status
	return nil
}
func runHumanTUIStatus() error {
	if activeScenario.scenarioName == "tui show lists recent commands for a session" {
		return u21RunHumanShow()
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUI("status", activeScenario.realCommandID)
	activeScenario.lastBody, activeScenario.lastStatus = []byte(stdout), code
	if err != nil {
		return fmt.Errorf("run real human TUI status: %w; stderr=%s", err, stderr)
	}
	phase := activeScenario.tuiExpectedState
	if phase != "" {
		if err := os.WriteFile(filepath.Join(activeScenario.holdDir, "release-"+phase), []byte("release\n"), 0o600); err != nil {
			return err
		}
	}
	return nil
}

func assertHumanTUIWording(wording string) error {
	if !strings.Contains(string(activeScenario.lastBody), wording) {
		return fmt.Errorf("human TUI output %q does not contain %q", activeScenario.lastBody, wording)
	}
	return nil
}

func prepareStopSession() error {
	if activeScenario.world == nil {
		return fmt.Errorf("scenario world is not initialized")
	}
	if activeScenario.world.realCluster == nil {
		if err := activeScenario.world.StartRealCluster(harness.FaultInjection{}); err != nil {
			return err
		}
	}
	return nil
}

func submitStopCommand() error {
	id, err := activeScenario.world.SubmitRealCommand("agent.stop", "fixture-session", "fixture-generation", `{}`)
	if err != nil {
		return err
	}
	status, pollErr := activeScenario.world.PollRealCommand(id, 10*time.Second)
	if pollErr != nil {
		return pollErr
	}
	activeScenario.realCommandID = id
	activeScenario.realCommandStatus = status
	return nil
}

func assertSignalSentReceipt() error {
	value := stringValue(activeScenario.realCommandStatus, "delivery_boundary", "delivery_state")
	if value != string(protocol.DeliverySignalSent) {
		return fmt.Errorf("receipt delivery state=%q, want signal_sent: %#v", value, activeScenario.realCommandStatus)
	}
	return nil
}

func assertExitNotConfirmed() error {
	value, ok := activeScenario.realCommandStatus["exit_confirmed"]
	if !ok {
		return fmt.Errorf("receipt does not expose exit_confirmed: %#v", activeScenario.realCommandStatus)
	}
	if confirmed, ok := value.(bool); !ok || confirmed {
		return fmt.Errorf("exit_confirmed=%#v, want false", value)
	}
	return nil
}
