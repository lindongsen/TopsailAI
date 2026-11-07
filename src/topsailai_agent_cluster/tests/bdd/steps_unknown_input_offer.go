package bdd

import (
	"fmt"
	"strings"

	"github.com/cucumber/godog"
)

// registerUnknownInputOfferSteps registers the session-scope send offer scenarios.
// They drive the real binary through a PTY against a real cluster, because the
// offer is an interactive surface: a non-interactive caller always passes the
// command word explicitly, so no prompt can appear there.
func registerUnknownInputOfferSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^unrecognized session input is offered as a send and accepted$`, runOfferAccepted)
	ctx.Step(`^unrecognized session input is offered as a send and declined$`, runOfferDeclined)
	ctx.Step(`^unrecognized workspace input is entered$`, runWorkspaceUnknownInput)
	ctx.Step(`^the offer names the whole literal line$`, assertOfferNamesLiteralLine)
	ctx.Step(`^exactly one send command is admitted$`, assertOneSendAdmitted)
	ctx.Step(`^the offer does not repeat the send confirmation$`, assertOfferDoesNotRepeatConfirmation)
	ctx.Step(`^the unknown command diagnostic is reported$`, assertUnknownCommandDiagnostic)
	ctx.Step(`^no send command is admitted$`, assertNoSendAdmitted)
	ctx.Step(`^no send offer is shown$`, assertNoOfferShown)
}

// offerLiteralLine is the text typed without a command word. It carries two words
// so a payload that dropped the first word would be visible in the assertion.
const offerLiteralLine = "hello world"

// runOfferAccepted navigates to the first session row, types the literal line,
// accepts the offer and quits.
func runOfferAccepted() error {
	return runOfferScript("cd 1\n" + offerLiteralLine + "\ny\nquit\n")
}

// runOfferDeclined types the same line and refuses the offer.
func runOfferDeclined() error {
	return runOfferScript("cd 1\n" + offerLiteralLine + "\nn\nquit\n")
}

// runWorkspaceUnknownInput types the literal line in workspace scope, where send
// is unavailable, so no offer may appear.
func runWorkspaceUnknownInput() error {
	return runOfferScript(offerLiteralLine + "\nquit\n")
}

// runOfferScript drives the REPL and records its combined terminal output.
func runOfferScript(script string) error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	stdout, stderr, code, err := activeScenario.realCluster.RunTUIInteractive(script, "--wait-timeout-ms", "3000")
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

// assertOfferNamesLiteralLine proves the question carries the whole typed line, so
// the operator can see exactly what would be sent before answering.
func assertOfferNamesLiteralLine() error {
	text := interactiveOutput()
	if !strings.Contains(text, "as a message?") {
		return fmt.Errorf("the send offer was not shown: %s", text)
	}
	if !strings.Contains(text, "send "+offerLiteralLine+" as a message?") {
		return fmt.Errorf("the offer does not name the whole literal line: %s", text)
	}
	return nil
}

// assertOneSendAdmitted proves accepting the offer admits exactly one command.
func assertOneSendAdmitted() error {
	if count := strings.Count(interactiveOutput(), "command submitted:"); count != 1 {
		return fmt.Errorf("admitted %d commands, want 1: %s", count, interactiveOutput())
	}
	return nil
}

// assertOfferDoesNotRepeatConfirmation proves the accepted offer is not followed by
// the send confirmation, because the offer already named the text and the action.
func assertOfferDoesNotRepeatConfirmation() error {
	text := interactiveOutput()
	if count := strings.Count(text, "as a message?"); count != 1 {
		return fmt.Errorf("the offer asked %d questions, want 1: %s", count, text)
	}
	if strings.Contains(text, "Confirm send?") {
		return fmt.Errorf("the offer repeated the send confirmation: %s", text)
	}
	return nil
}

// assertUnknownCommandDiagnostic proves the typo is still reported, so a refusal
// never swallows the operator's mistake.
func assertUnknownCommandDiagnostic() error {
	text := interactiveOutput()
	if !strings.Contains(text, `unknown command "hello" (try help)`) {
		return fmt.Errorf("the unknown command diagnostic is missing: %s", text)
	}
	return nil
}

// assertNoSendAdmitted proves a refusal or an out-of-scope line admits nothing.
func assertNoSendAdmitted() error {
	if count := strings.Count(interactiveOutput(), "command submitted:"); count != 0 {
		return fmt.Errorf("admitted %d commands, want 0: %s", count, interactiveOutput())
	}
	return nil
}

// assertNoOfferShown proves the offer is limited to session scope, where send is
// available; elsewhere an accepted offer could never be honoured.
func assertNoOfferShown() error {
	if strings.Contains(interactiveOutput(), "as a message?") {
		return fmt.Errorf("the send offer was shown outside session scope: %s", interactiveOutput())
	}
	return nil
}
