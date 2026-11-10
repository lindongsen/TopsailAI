package bdd

import (
	"fmt"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// registerFollowSteps registers the output follow scenarios. They drive the real
// binaries over a real WebSocket, because the in-process transport cannot stream:
// it answers a follow with "unsupported", which is correct behaviour but proves
// nothing about a live stream.
func registerFollowSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a streaming provider for the TUI$`, startFollowCluster)
	ctx.Step(`^the interactive REPL runs logs follow in a real terminal$`, runInteractiveFollow)
	ctx.Step(`^the follow stream reports its target and mode$`, assertFollowArmed)
	ctx.Step(`^the streamed records arrive while the editor waits$`, assertFollowRecordsArrived)
	ctx.Step(`^the first keypress stops the follow stream$`, assertFollowStopped)
	ctx.Step(`^the standalone logs follow command runs until it is interrupted$`, runStandaloneFollow)
	ctx.Step(`^the streamed records arrive before the interrupt$`, assertFollowRecordsArrived)
	ctx.Step(`^the interrupt ends the stream cleanly$`, assertFollowInterruptedCleanly)
	ctx.Step(`^the interactive REPL runs logs follow and the operator presses enter$`, runInteractiveFollowEnter)
	ctx.Step(`^the enter key stops the follow stream$`, assertFollowStoppedByEnter)
	ctx.Step(`^the standalone logs follow command runs while the endpoint disconnects$`, runStandaloneFollowThenStopEndpoint)
	ctx.Step(`^the disconnect is reported as an interrupted stream$`, assertFollowInterruptedByDisconnect)
}

// followPause is the gap between scripted input chunks. The fixture writes five
// records 150 ms apart, so a pause longer than that lets the whole stream arrive
// before the keypress that stops it. A shorter pause would stop the stream before
// the first record and the scenario would pass while proving nothing.
const followPause = 1200 * time.Millisecond

// followScript navigates to the sole session and arms the stream. Two
// navigations are required: logs reads the endpoint and the session from the
// current scope, and both are empty at workspace scope.
var followScript = []string{"cd 1\n", "cd 1\n", "logs -f\n", "quit\n"}

// followEnterScript is the same navigation, but the stopping key is a bare
// enter. It proves the stop is not tied to a particular character.
var followEnterScript = []string{"cd 1\n", "cd 1\n", "logs -f\n", "\n"}

// startFollowCluster starts a real cluster whose adapter can stream. The generic
// fixture adapter cannot, so the TopsailAI adapter is selected explicitly.
func startFollowCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{ProviderType: "topsailai"})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	activeScenario.realCluster = cluster
	if _, err := cluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build CLI: %w", err)
	}
	return nil
}

// runInteractiveFollow drives the REPL through a PTY with a real TERM, delivering
// the script in paced chunks so the stream runs before the keypress.
func runInteractiveFollow() error {
	return runPacedFollow(followScript)
}

// runInteractiveFollowEnter arms the same stream and stops it with a bare enter.
func runInteractiveFollowEnter() error {
	return runPacedFollow(followEnterScript)
}

// runPacedFollow runs one paced REPL session and records its output.
func runPacedFollow(chunks []string) error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIInteractiveEditorPaced(chunks, followPause)
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

// runStandaloneFollow runs the standalone command and interrupts it once the
// first record appears. The standalone surface has no terminal, so an interrupt
// is its only stop signal.
func runStandaloneFollow() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIFollow("fixture follow", 10*time.Second, "logs", "endpoint-1", resourceID, "--follow")
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if err != nil && code == 0 {
		return fmt.Errorf("run standalone follow: %v; stderr=%s", err, stderr)
	}
	if code != 0 {
		return fmt.Errorf("standalone follow exit code=%d stderr=%s output=%s", code, stderr, stdout)
	}
	return nil
}

// stripFollowSGR removes the SGR sequences the follow status prefix carries when
// the terminal reports colour. The scenarios drive a real PTY with a real TERM, so
// the prefix is styled there; the assertions care about the words, not the styling,
// and a styled prefix must not make a correct message look absent.
func stripFollowSGR(text string) string {
	return strings.NewReplacer("\x1b[1;32m", "", "\x1b[2m", "", "\x1b[31m", "", "\x1b[0m", "").Replace(text)
}

// assertFollowArmed proves the command armed a stream instead of silently
// falling back to a snapshot. A snapshot fallback is the exact defect this
// scenario exists to catch.
func assertFollowArmed() error {
	text := stripFollowSGR(interactiveOutput())
	if strings.Contains(text, "follow is unavailable") {
		return fmt.Errorf("follow was rejected, so the shipped binary does not wire the streaming client: %s", text)
	}
	if !strings.Contains(text, "log.follow> res_") {
		return fmt.Errorf("the follow command did not report its target and mode: %s", text)
	}
	if !strings.Contains(text, "any key stops") {
		return fmt.Errorf("the follow command did not report that any key stops it: %s", text)
	}
	return nil
}

// assertFollowRecordsArrived proves records actually reached the terminal while
// the editor was waiting. Without this the scenario could pass on a stream that
// was armed but never produced anything.
func assertFollowRecordsArrived() error {
	text := string(activeScenario.lastBody)
	if !strings.Contains(text, "fixture follow") {
		return fmt.Errorf("no streamed record reached the terminal: %s", text)
	}
	return nil
}

// assertFollowStopped proves the keypress ended the stream through the watch
// seam, rather than the stream ending on its own.
func assertFollowStopped() error {
	text := stripFollowSGR(interactiveOutput())
	if !strings.Contains(text, "log.follow> follow stopped") {
		return fmt.Errorf("the first keypress did not stop the follow stream: %s", text)
	}
	if strings.Contains(text, "auto-refresh stopped") {
		return fmt.Errorf("the stop message used the auto-refresh wording instead of the follow wording: %s", text)
	}
	return nil
}

// assertFollowStoppedByEnter proves a bare enter stops the stream. If it did not,
// the editor would never return and the process would hit its own deadline, so a
// zero exit status is part of the evidence.
func assertFollowStoppedByEnter() error {
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("the REPL did not exit cleanly after the enter key, so the stream was probably never stopped: exit=%d output=%s", activeScenario.lastStatus, interactiveOutput())
	}
	text := stripFollowSGR(interactiveOutput())
	if !strings.Contains(text, "log.follow> follow stopped") {
		return fmt.Errorf("the enter key did not stop the follow stream: %s", text)
	}
	return nil
}

// assertFollowInterruptedCleanly proves an interrupt is a normal stop rather than
// a failure: the operator asked to stop watching, so the command reports the stop
// and exits successfully.
func assertFollowInterruptedCleanly() error {
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("the interrupt was reported as a failure: exit=%d output=%s", activeScenario.lastStatus, string(activeScenario.lastBody))
	}
	text := stripFollowSGR(string(activeScenario.lastBody))
	if !strings.Contains(text, "log.follow> follow stopped") {
		return fmt.Errorf("the interrupt did not report a clean stop: %s", text)
	}
	return nil
}

// runStandaloneFollowThenStopEndpoint runs a standalone follow and stops the
// Endpoint once the first record arrives, so the stream is interrupted by a
// disconnect instead of by the operator.
func runStandaloneFollowThenStopEndpoint() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIFollowThenStopEndpoint("fixture follow", 10*time.Second, "logs", "endpoint-1", resourceID, "--follow")
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if err != nil && code == 0 {
		return fmt.Errorf("run standalone follow with endpoint stop: %v; stderr=%s", err, stderr)
	}
	if code != 0 {
		return fmt.Errorf("standalone follow exit code=%d stderr=%s output=%s", code, stderr, stdout)
	}
	return nil
}

// assertFollowInterruptedByDisconnect proves a disconnect is reported as an
// interrupted stream, never as a clean finish.
//
// The Endpoint never delivered its terminal frame, so the only reason the CLI can
// report anything is the Server releasing the pending follow with
// endpoint_offline. Asserting that code proves the Server-inferred path is what
// the contract relies on, and asserting the absence of a clean end proves the
// client does not mistake a missing terminal frame for a finished stream.
func assertFollowInterruptedByDisconnect() error {
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("the disconnect was reported as a failure: exit=%d output=%s", activeScenario.lastStatus, string(activeScenario.lastBody))
	}
	text := stripFollowSGR(string(activeScenario.lastBody))
	if !strings.Contains(text, "log.follow> follow ended: endpoint_offline") {
		return fmt.Errorf("the disconnect did not report the Server-inferred endpoint_offline code: %s", text)
	}
	if strings.Contains(text, "follow ended\n") {
		return fmt.Errorf("the disconnect was reported as a clean finish: %s", text)
	}
	if strings.Contains(text, "follow stopped") {
		return fmt.Errorf("the disconnect was reported as an operator stop: %s", text)
	}
	return nil
}
