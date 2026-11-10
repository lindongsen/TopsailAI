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

// offerQuestionMarker prefixes the offer's question row, which is also the input
// row. It separates the application's question from the message row above it.
const offerQuestionMarker = ">>> "

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

// assertOfferNamesLiteralLine proves the message row carries the whole typed line
// on its own row before the question, so the operator can see exactly what would
// be sent before answering.
func assertOfferNamesLiteralLine() error {
	text := interactiveOutput()
	if !strings.Contains(text, "as a message?") {
		return fmt.Errorf("the send offer was not shown: %s", text)
	}
	messageRow, questionRow, found := offerRowsIn(text)
	if !found {
		return fmt.Errorf("the offer does not render the message and the question on separate rows: %s", text)
	}
	if messageRow != offerLiteralLine {
		return fmt.Errorf("the message row does not carry the whole literal line: %q", messageRow)
	}
	if !strings.HasPrefix(questionRow, offerQuestionMarker) {
		return fmt.Errorf("the question row does not carry the %q marker: %q", offerQuestionMarker, questionRow)
	}
	if strings.Index(text, messageRow) > strings.Index(text, questionRow) {
		return fmt.Errorf("the message row must precede the question row: %s", text)
	}
	return nil
}

// offerRowsIn finds the message row and the question row of the offer. The
// message row carries only the literal text; the question row carries the marker
// and the answer hint. Rows are compared by visible text, so the styled and plain
// forms are both accepted.
func offerRowsIn(text string) (messageRow, questionRow string, found bool) {
	for _, row := range strings.Split(text, "\n") {
		visible := stripOfferStyles(row)
		if strings.Contains(visible, "[y/N]") {
			questionRow = visible
			continue
		}
		if strings.TrimRight(visible, " ") == offerLiteralLine {
			messageRow = visible
		}
	}
	return messageRow, questionRow, messageRow != "" && questionRow != ""
}

// stripOfferStyles removes the offer's own SGR styling so a row can be matched by
// its visible text. Only the styles this CLI emits are removed, so a payload
// sequence that survived sanitization would still be visible. The trailing
// carriage return of a pty row is dropped as well, because a pty ends every row
// with CRLF while the visible text carries no carriage return.
func stripOfferStyles(row string) string {
	stripped := strings.NewReplacer("\x1b[35m", "", "\x1b[1;36m", "", "\x1b[2m", "", "\x1b[0m", "").Replace(row)
	return strings.TrimSuffix(stripped, "\r")
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
	if strings.Contains(text, "send.confirm[y/N]>") {
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
