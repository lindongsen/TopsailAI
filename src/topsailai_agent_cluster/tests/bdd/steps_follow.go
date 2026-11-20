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
	ctx.Step(`^a real cluster whose follow budget is shorter than the provider hold$`, startFollowBudgetCluster)
	ctx.Step(`^the standalone logs follow command runs until its own budget expires$`, runStandaloneFollowUntilBudget)
	ctx.Step(`^the stream reports that its budget expired$`, assertFollowBudgetExpired)
	ctx.Step(`^a real cluster whose provider holds the follow stream past the keypress$`, startFollowReleaseCluster)
	ctx.Step(`^the interactive REPL runs logs follow and the provider child is recorded$`, runInteractiveFollowRecordingChild)
	ctx.Step(`^the keypress releases the provider follow child$`, assertFollowChildReleased)
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

// followHoldMS keeps the provider stream open after its last record so the stop
// path has something to stop. It must exceed followPause, because the stopping
// keypress is delivered one pause after the stream is armed; a shorter hold
// would let the stream finish first and the scenario would assert on a clean end
// while appearing to prove a stop.
//
// It is deliberately not bounded by the adapter call timeout. A follow is bounded
// by its own budget (AGENT_CLUSTER_ENDPOINT_FOLLOW_TIMEOUT), so the 5000 ms
// one-shot timeout no longer applies here. The earlier wording claimed the hold
// had to stay below that timeout, which was true only while a follow shared the
// one-shot budget; keeping the claim would have made a future reader shorten the
// hold for a reason that no longer exists.
const followHoldMS = 3000

// followBudgetScenarioMS is the follow budget the timeout scenario configures. It
// is short so the scenario costs seconds instead of minutes, and it is paired with
// a hold above it so the stream is still open when the budget expires. A hold
// below the budget would let the provider finish first and the scenario would
// assert on a clean end instead of a timeout.
const followBudgetScenarioMS = 2000

// followBudgetHoldMS is the provider hold for the timeout scenario. It exceeds
// followBudgetScenarioMS so the budget is the binding constraint, and it stays
// well below the harness wait budget so a failure to expire is reported as a
// failed assertion rather than as a harness timeout.
const followBudgetHoldMS = 8000

// followBudgetWait bounds how long the timeout scenario waits for the command to
// end on its own. It is larger than the configured budget so a correct run has
// room to finish, and small enough that a stream which never expires fails the
// scenario quickly.
const followBudgetWait = 20 * time.Second

// followReleaseWait bounds how long the release scenario waits for the provider
// child to disappear after the keypress. The Cluster kills the process group and
// the kernel reaps it asynchronously, so the assertion polls instead of reading
// once.
const followReleaseWait = 10 * time.Second

// followReleaseHoldMS is the provider hold for the release scenario, and it must
// exceed followReleaseWait.
//
// This is the difference between a test with teeth and a test that certifies
// nothing. With a hold shorter than the wait, an un-killed child exits on its own
// inside the wait budget and the assertion passes without the keypress having
// released anything. Holding past the wait means the only way the pid can be gone
// when the assertion gives up is that the Cluster actually killed it.
const followReleaseHoldMS = 30000

// startFollowCluster starts a real cluster whose adapter can stream. The mock
// provider answers a follow with real stream frames, so the default adapter is
// enough; no provider-specific adapter has to be selected.
func startFollowCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		Faults: harness.FaultInjection{FollowHoldMS: followHoldMS},
	})
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

// startFollowBudgetCluster starts a real cluster whose follow budget is shorter
// than the provider hold, so the stream is still open when its own budget
// expires.
//
// The budget is Endpoint configuration, so it is set on the Endpoint process.
// Setting it on the Server would be silently ignored and the scenario would
// assert against the 30 minute default while appearing to prove the configured
// value.
func startFollowBudgetCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		EndpointEnvironment: map[string]string{
			"AGENT_CLUSTER_ENDPOINT_FOLLOW_TIMEOUT": fmt.Sprintf("%dms", followBudgetScenarioMS),
		},
		Faults: harness.FaultInjection{FollowHoldMS: followBudgetHoldMS},
	})
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

// runStandaloneFollowUntilBudget runs the standalone follow and lets it reach its
// own bound. No signal is sent, because an interrupt would take the operator-stop
// path and the scenario would assert on a code the stop path never emits.
func runStandaloneFollowUntilBudget() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	resourceID, err := tuiResourceID()
	if err != nil {
		return err
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIFollowUntilEnd(followBudgetWait, "logs", "endpoint-1", resourceID, "--follow")
	activeScenario.lastBody = []byte(stdout)
	activeScenario.lastStatus = code
	if err != nil {
		return fmt.Errorf("run standalone follow until its budget expires: %v; stderr=%s", err, stderr)
	}
	if code != 0 {
		return fmt.Errorf("standalone follow exit code=%d stderr=%s output=%s", code, stderr, stdout)
	}
	return nil
}

// assertFollowBudgetExpired proves an expired budget is reported as a timeout and
// not as a cancellation.
//
// The two codes are the whole point of the change: `cancelled` sent the operator
// looking for whoever stopped the stream, while nobody had. Asserting the absence
// of `cancelled` is what stops a regression from silently restoring the old
// wording, because the presence check alone would still pass if both codes were
// printed.
func assertFollowBudgetExpired() error {
	text := stripFollowSGR(string(activeScenario.lastBody))
	if !strings.Contains(text, "log.follow> follow ended: follow_timeout") {
		return fmt.Errorf("the expired follow budget was not reported as follow_timeout: %s", text)
	}
	if strings.Contains(text, "follow ended: cancelled") {
		return fmt.Errorf("the expired follow budget was reported as a cancellation, so the operator would look for a stop that never happened: %s", text)
	}
	if strings.Contains(text, "follow stopped") {
		return fmt.Errorf("the expired follow budget was reported as an operator stop: %s", text)
	}
	return nil
}

// startFollowReleaseCluster starts a real cluster whose provider holds the stream
// open past the keypress, so the child is still alive when the operator stops it.
//
// The hold must exceed followReleaseWait, not merely followPause. A hold that only
// outlives the keypress still lets an un-killed child exit on its own inside the
// wait budget, and the release assertion would then pass without the keypress
// having released anything. Holding past the wait makes the kill the only
// explanation for the pid disappearing.
func startFollowReleaseCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		Faults: harness.FaultInjection{FollowHoldMS: followReleaseHoldMS},
	})
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

// runInteractiveFollowRecordingChild runs the paced REPL follow and captures the
// pid the provider recorded for its follow child.
//
// The pid is captured after the REPL exits, because the record is written before
// the stream starts and therefore survives the release. It is the only evidence
// that a child existed at all: once the process group is killed nothing else
// names it, so a release assertion without a captured pid would compare zero with
// zero and pass.
// followReleaseScript arms the stream and then stops it with a key that is not
// `quit`.
//
// The stopping key must not also end the REPL. If it did, the CLI process would
// exit immediately after the keypress and its death would close the HTTP
// connection, releasing the provider child regardless of what the keypress did.
// The release assertion would then pass on a build where the keypress cancels
// nothing, which is exactly the defect it exists to catch. A bare `q` stops the
// follow and then sits in the prompt buffer, so the REPL stays alive while the
// pid is checked.
var followReleaseScript = []string{"cd 1\n", "cd 1\n", "logs -f\n", "q"}

// runInteractiveFollowRecordingChild starts the REPL, waits for the stream to arm
// and for the provider to record its follow child, then captures that pid and
// proves the child is still running.
//
// The REPL is left running on purpose. The pid must be observed alive before the
// keypress, because a pid that was never alive cannot prove a release: the
// assertion would compare "gone" with "never existed" and pass.
func runInteractiveFollowRecordingChild() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	run, err := activeScenario.realCluster.StartTUIInteractivePaced(followReleaseScript, followPause)
	if err != nil {
		return fmt.Errorf("start interactive REPL: %w", err)
	}
	activeScenario.followRun = run
	if err := run.WaitForOutput("log.follow> res_", followBudgetWait); err != nil {
		run.Kill()
		return fmt.Errorf("the follow stream never armed: %w", err)
	}
	pid, err := waitForFollowChildPID(activeScenario.realCluster, followBudgetWait)
	if err != nil {
		run.Kill()
		return err
	}
	activeScenario.followChildPID = pid
	if !harness.ProcessAlive(pid) {
		run.Kill()
		return fmt.Errorf("the provider follow child %d was not running when the stream was armed, so a later release assertion would prove nothing", pid)
	}
	return nil
}

// waitForFollowChildPID polls the provider invocation record until a follow child
// pid appears.
//
// The record is written before the stream starts, so it can lag the armed marker
// by a scheduling interval. Polling is required because a single read races that
// write and would report "no child" for a stream that is in fact running.
func waitForFollowChildPID(cluster *harness.Cluster, wait time.Duration) (int, error) {
	deadline := time.Now().Add(wait)
	var last []map[string]any
	for time.Now().Before(deadline) {
		invocations, err := cluster.ProviderInvocationsE()
		if err != nil {
			return 0, err
		}
		last = invocations
		for _, invocation := range invocations {
			if invocation["kind"] != "follow_output" {
				continue
			}
			pid, ok := invocation["pid"].(float64)
			if !ok || pid <= 0 {
				return 0, fmt.Errorf("the follow invocation record carries no usable pid: %v", invocation)
			}
			return int(pid), nil
		}
		time.Sleep(20 * time.Millisecond)
	}
	return 0, fmt.Errorf("the provider recorded no follow_output invocation within %s, so no child was ever started: %v", wait, last)
}

// assertFollowChildReleased proves the keypress released the provider follow
// child while the REPL was still alive.
//
// Two conditions make this a real proof rather than a coincidence. The stream must
// have been stopped by the keypress, because a stream that ended on its own leaves
// a child that exited by itself and the assertion would pass without the keypress
// doing anything. And the REPL must still be running when the pid disappears,
// because a dead REPL releases everything it owned through process exit, which
// would hide a keypress that cancels nothing.
func assertFollowChildReleased() error {
	run := activeScenario.followRun
	if run == nil {
		return fmt.Errorf("the interactive REPL was never started, so nothing could be released")
	}
	if err := run.WaitForOutput("log.follow> follow stopped", followBudgetWait); err != nil {
		run.Kill()
		return fmt.Errorf("the keypress did not stop a live stream, so the release assertion would prove nothing: %w", err)
	}
	if activeScenario.followChildPID <= 0 {
		run.Kill()
		return fmt.Errorf("no provider follow child pid was captured, so nothing was released")
	}
	releaseErr := harness.WaitProcessGone(activeScenario.followChildPID, followReleaseWait)
	select {
	case <-run.Done():
		run.Kill()
		return fmt.Errorf("the REPL exited before the release was observed, so process exit rather than the keypress may have released the child")
	default:
	}
	run.Release()
	exitCode, waitErr := run.Wait(followBudgetWait)
	if waitErr != nil {
		return fmt.Errorf("the REPL did not exit after its input closed: %w", waitErr)
	}
	if exitCode != 0 {
		return fmt.Errorf("the REPL exit code=%d after the release; output=%s", exitCode, run.Output())
	}
	if releaseErr != nil {
		return fmt.Errorf("the keypress left the provider follow child running: %w", releaseErr)
	}
	return nil
}
