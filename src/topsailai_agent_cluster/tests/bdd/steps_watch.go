package bdd

import (
	"fmt"
	"strings"

	"github.com/cucumber/godog"
)

// registerWatchSteps registers the auto-refresh scenarios. They drive the real
// binary through a PTY with a real TERM, because auto-refresh needs the raw-mode
// editor: a plain reader cannot observe a tick between keypresses. Unit tests
// inject the tick-capable reader directly, so only this layer can prove the
// shipped wiring actually provides it.
func registerWatchSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^the interactive REPL runs watch in a real terminal$`, runInteractiveWatch)
	ctx.Step(`^the auto-refresh loop reports its interval and mode$`, assertWatchArmed)
	ctx.Step(`^the first keypress stops the auto-refresh loop$`, assertWatchStopped)
	ctx.Step(`^the REPL keeps running after the loop stops$`, assertREPLSurvivedWatch)
}

// watchScript arms the loop and then sends one keypress, which must stop it
// before that key is applied. The remaining input completes the quit command.
const watchScript = "watch\nquit\n"

// runInteractiveWatch drives the REPL with the raw-mode editor active.
func runInteractiveWatch() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIInteractiveEditor(watchScript)
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

// assertWatchArmed proves the loop started instead of being rejected. A rejection
// here is the exact defect this scenario exists to catch: the command is
// implemented but unreachable because the binary never wires the tick reader.
func assertWatchArmed() error {
	text := interactiveOutput()
	if strings.Contains(text, "auto-refresh requires a terminal") {
		return fmt.Errorf("watch was rejected in a real terminal, so the shipped binary does not wire the tick-capable reader: %s", text)
	}
	if !strings.Contains(text, "auto-refresh: 5s projection (any key stops)") {
		return fmt.Errorf("auto-refresh did not report its default interval and mode: %s", text)
	}
	return nil
}

// assertWatchStopped proves the first keypress ended the loop.
func assertWatchStopped() error {
	text := interactiveOutput()
	if !strings.Contains(text, "auto-refresh stopped") {
		return fmt.Errorf("the first keypress did not stop the auto-refresh loop: %s", text)
	}
	return nil
}

// assertREPLSurvivedWatch proves the keypress that stopped the loop was then
// applied normally, so stopping the loop does not swallow the operator's input.
func assertREPLSurvivedWatch() error {
	text := interactiveOutput()
	if !strings.Contains(text, "workspace>") {
		return fmt.Errorf("the REPL did not return to a usable prompt after the loop stopped: %s", text)
	}
	return nil
}
