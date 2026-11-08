package bdd

import (
	"fmt"
	"strings"

	"github.com/cucumber/godog"
)

// registerQReturnsToWorkspaceSteps registers the scope-aware q scenarios. They
// drive the real binary through a PTY, because q is an interactive surface: a
// non-interactive caller never types a bare q, so only this layer can prove the
// shipped wiring navigates instead of exiting.
func registerQReturnsToWorkspaceSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^the interactive REPL enters a session and types q$`, runQFromSessionScope)
	ctx.Step(`^the REPL returns to workspace scope and keeps running$`, assertQReturnedToWorkspace)
}

// qScript enters the first session row, types the bare q, then leaves the REPL
// with the unambiguous quit spelling. The trailing quit is what proves q did not
// already exit: if q had exited, the quit line would never be read.
const qScript = "cd 1\nq\nquit\n"

// runQFromSessionScope drives the REPL through a PTY with the plain reader.
func runQFromSessionScope() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIInteractive(qScript, "--wait-timeout-ms", "3000")
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

// assertQReturnedToWorkspace proves q navigated back instead of leaving the REPL.
// The workspace prompt count is the discriminator: the REPL renders one prompt on
// entry and one after q, so a q that exited would leave a single prompt and the
// trailing quit would never run. The session prompt must also appear first, so the
// scenario cannot pass without actually being in session scope when q was typed.
func assertQReturnedToWorkspace() error {
	text := interactiveOutput()
	if !strings.Contains(text, "session[") {
		return fmt.Errorf("the REPL never entered session scope, so q was not typed there: %s", text)
	}
	if count := strings.Count(text, "workspace> "); count != 2 {
		return fmt.Errorf("the REPL rendered %d workspace prompts, want 2: q did not return to workspace scope or did not keep the REPL running: %s", count, text)
	}
	if strings.Contains(text, "unknown command") {
		return fmt.Errorf("q was rejected as an unknown command instead of navigating: %s", text)
	}
	return nil
}
