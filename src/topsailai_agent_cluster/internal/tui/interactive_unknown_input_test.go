package tui

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// sessionScopeInput prefixes a session-scope navigation so every case starts in
// the scope where the send offer is available.
const sessionScopeInput = "cd host-one/endpoint-1/res-1\n"

// TestUnknownInputOffersSendInSessionScope proves an unrecognized line is offered
// as a message and that accepting the offer admits exactly one send command.
func TestUnknownInputOffersSendInSessionScope(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if !strings.Contains(output, "as a message?") {
		t.Fatalf("missing send offer: %q", output)
	}
	if !strings.Contains(output, "command submitted:") {
		t.Fatalf("missing submission evidence: %q", output)
	}
	if got := intentPayloadText(t, stub.intents[0]); got != "hello world" {
		t.Fatalf("payload text = %q, want the whole literal line", got)
	}
	if stub.intents[0].Operation != protocol.OperationMessageSend {
		t.Fatalf("operation = %q, want %q", stub.intents[0].Operation, protocol.OperationMessageSend)
	}
}

// TestUnknownInputKeepsFirstWordInPayload proves the offer sends the literal line
// rather than the words after the unrecognized word, so accepting the offer never
// silently drops text the operator typed.
func TestUnknownInputKeepsFirstWordInPayload(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, sessionScopeInput+"deploy the release now\nyes\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if got := intentPayloadText(t, stub.intents[0]); got != "deploy the release now" {
		t.Fatalf("payload text = %q, want the whole literal line", got)
	}
}

// TestUnknownInputDeclinedKeepsDiagnostic proves a declined offer reports the typo
// instead of admitting a command, so no mutating action is inferred from a refusal.
func TestUnknownInputDeclinedKeepsDiagnostic(t *testing.T) {
	for _, answer := range []string{"n", "", "no"} {
		t.Run("answer="+answer, func(t *testing.T) {
			stub := scopeStub()
			_, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\n"+answer+"\nquit\n", ColorPolicy{})
			if stub.admit != 0 {
				t.Fatalf("declined offer admitted %d commands", stub.admit)
			}
			assertActionableError(t, diagnostics, `error: unknown command "hello" (try help)`)
		})
	}
}

// TestUnknownInputUnreadableAnswerKeepsDiagnostic proves an incomplete answer
// cannot authorize a send, because a partial line is not a confirmation.
func TestUnknownInputUnreadableAnswerKeepsDiagnostic(t *testing.T) {
	stub := scopeStub()
	_, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\ny", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("partial answer admitted %d commands", stub.admit)
	}
	assertActionableError(t, diagnostics, `error: unknown command "hello" (try help)`)
}

// TestUnknownInputOutsideSessionScopeKeepsDiagnostic proves the offer is limited to
// session scope, where send is available; elsewhere the plain diagnostic is kept
// because an accepted offer could never be honoured.
func TestUnknownInputOutsideSessionScopeKeepsDiagnostic(t *testing.T) {
	cases := []struct {
		name  string
		input string
	}{
		{name: "workspace", input: "hello world\nquit\n"},
		{name: "endpoint", input: "cd host-one/endpoint-1\nhello world\nquit\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := scopeStub()
			output, diagnostics := runScope(t, stub, testCase.input, ColorPolicy{})
			if stub.admit != 0 {
				t.Fatalf("out-of-scope offer admitted %d commands", stub.admit)
			}
			if strings.Contains(output, "as a message?") {
				t.Fatalf("out-of-scope offer must not prompt: %q", output)
			}
			assertActionableError(t, diagnostics, `error: unknown command "hello" (try help)`)
		})
	}
}

// TestUnknownInputOfferRejectsJSONFlagPayload proves the offer never promises a
// payload the send command itself rejects, so the diagnostic is reported instead.
func TestUnknownInputOfferRejectsJSONFlagPayload(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"--json\nquit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("rejected payload admitted %d commands", stub.admit)
	}
	if strings.Contains(output, "as a message?") {
		t.Fatalf("rejected payload must not prompt: %q", output)
	}
	assertActionableError(t, diagnostics, `error: unknown command "--json" (try help)`)
}

// TestUnknownInputOfferSanitizesQuestion proves operator text cannot inject
// terminal control sequences into the trusted question writer.
func TestUnknownInputOfferSanitizesQuestion(t *testing.T) {
	stub := scopeStub()
	output, _ := runScope(t, stub, sessionScopeInput+"hello \x1b[31mred\x1b[0m\ny\nquit\n", ColorPolicy{})
	if strings.Contains(output, "\x1b[31m") {
		t.Fatalf("offer question leaked a control sequence: %q", output)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
}

// TestSendCommandStillAsksOnce proves the offer does not change the send command
// itself: one question, one admission.
func TestSendCommandStillAsksOnce(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"send hello world\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1", stub.admit)
	}
	if count := strings.Count(output, "Confirm send?"); count != 1 {
		t.Fatalf("send asked %d confirmations, want 1: %q", count, output)
	}
}

// TestUnknownInputOfferAsksOnce proves accepting the offer does not repeat the
// confirmation the operator already gave.
func TestUnknownInputOfferAsksOnce(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	if count := strings.Count(output, "as a message?"); count != 1 {
		t.Fatalf("offer asked %d questions, want 1: %q", count, output)
	}
	if count := strings.Count(output, "Confirm send?"); count != 0 {
		t.Fatalf("offer repeated the send confirmation %d times: %q", count, output)
	}
}

// TestUnknownInputOfferRevalidatesSelection proves the offer still fails closed when
// the pinned session generation changed, so the offer cannot bypass selection checks.
func TestUnknownInputOfferRevalidatesSelection(t *testing.T) {
	stub := refreshScopeStub()
	stub.fresh["endpoint-1"] = scopeInventory("res-1", "generation-2")
	_, diagnostics := runScope(t, stub, sessionScopeInput+"refresh\nhello world\ny\nquit\n", ColorPolicy{})
	if stub.admit != 0 {
		t.Fatalf("changed generation admitted %d commands", stub.admit)
	}
	if !strings.Contains(diagnostics, "selected session generation changed") {
		t.Fatalf("missing generation diagnostic: %q", diagnostics)
	}
}

// intentPayloadText decodes the text field of one admitted message payload.
func intentPayloadText(t *testing.T, intent protocol.ImmutableIntent) string {
	t.Helper()
	var payload struct {
		Text string `json:"text"`
	}
	if err := json.Unmarshal(intent.Payload, &payload); err != nil {
		t.Fatalf("decode payload %q: %v", string(intent.Payload), err)
	}
	return payload.Text
}

// TestUnknownInputOfferUsesInjectedReader proves the offer works through the
// injected prompt reader, which is the terminal editor path, not only the stream
// fallback.
func TestUnknownInputOfferUsesInjectedReader(t *testing.T) {
	stub := scopeStub()
	// Two trailing "quit" answers keep the terminator independent of the quit
	// policy: in workspace scope the first one exits, and in a narrower scope a
	// quit that navigates back to workspace is followed by one that exits. The
	// offer assertions do not depend on which of the two ends the loop.
	answers := []string{"cd host-one/endpoint-1/res-1", "hello world", "y", "quit", "quit"}
	index := 0
	read := func(context.Context, string, bool, int) (string, bool, error) {
		if index >= len(answers) {
			return "", false, nil
		}
		answer := answers[index]
		index++
		return answer, false, nil
	}
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &output, &diagnostics, InteractiveOptions{ReadLine: read, WaitTimeoutMS: 100}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1; diagnostics=%q", stub.admit, diagnostics.String())
	}
	if got := intentPayloadText(t, stub.intents[0]); got != "hello world" {
		t.Fatalf("payload text = %q, want the whole literal line", got)
	}
}

// offerVisibleText strips the offer's own styling so a row can be matched by its
// visible text. Only the styles this package emits are removed, so a payload
// sequence that survived sanitization would still be visible to the assertion.
func offerVisibleText(row string) string {
	return strings.NewReplacer(ansiMagenta, "", ansiBoldCyan, "", ansiDim, "", ansiReset, "").Replace(row)
}

// offerRows extracts the message row and the question row from the offer output.
// The message row carries the literal text; the question row carries the offer
// marker and the answer hint. Both are returned as raw rows so a caller can
// inspect their styling, and their visible text is available through
// offerVisibleText.
func offerRows(t *testing.T, output, message string) (messageRow, questionRow string) {
	t.Helper()
	for _, row := range strings.Split(output, "\n") {
		visible := offerVisibleText(row)
		if strings.Contains(visible, confirmationHint) {
			questionRow = row
			continue
		}
		if visible == message {
			messageRow = row
		}
	}
	if messageRow == "" || questionRow == "" {
		t.Fatalf("offer rows missing: message=%q question=%q output=%q", messageRow, questionRow, output)
	}
	return messageRow, questionRow
}

// TestUnknownInputOfferRendersMessageBeforeQuestion proves the offer shows the
// message on its own row before the question row, so the operator reads exactly
// what would be sent before reading the question.
func TestUnknownInputOfferRendersMessageBeforeQuestion(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runScope(t, stub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{})
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics: %q", diagnostics)
	}
	messageRow, questionRow := offerRows(t, output, "hello world")
	if messageRow != "hello world" {
		t.Fatalf("message row=%q want the literal text", messageRow)
	}
	if questionRow != sendOfferMarker+"send the text above as a message? "+confirmationHint+" " {
		t.Fatalf("question row=%q", questionRow)
	}
	if strings.Index(output, messageRow) > strings.Index(output, questionRow) {
		t.Fatalf("message row must precede the question row: %q", output)
	}
}

// TestUnknownInputOfferDropsUnknownCommandPrefix proves the offer no longer
// repeats the unknown-command diagnostic inline, because the message row and the
// question row already say what would happen.
func TestUnknownInputOfferDropsUnknownCommandPrefix(t *testing.T) {
	stub := scopeStub()
	output, _ := runScope(t, stub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{})
	if strings.Contains(output, "unknown command hello;") {
		t.Fatalf("offer still carries the unknown-command prefix: %q", output)
	}
	if strings.Contains(output, "unknown command hello") {
		t.Fatalf("offer still names the unknown command: %q", output)
	}
}

// TestUnknownInputOfferUsesDistinctColours proves the message row and the
// question row carry different colours, so a payload can never be read as the
// application's own question.
func TestUnknownInputOfferUsesDistinctColours(t *testing.T) {
	stub := scopeStub()
	output, _ := runScope(t, stub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{Enabled: true})
	messageRow, questionRow := offerRows(t, output, "hello world")
	if !strings.Contains(messageRow, ansiMagenta) {
		t.Fatalf("message row is not magenta: %q", messageRow)
	}
	if !strings.Contains(questionRow, ansiBoldCyan) {
		t.Fatalf("question row is not bold cyan: %q", questionRow)
	}
	if strings.Contains(questionRow, ansiMagenta) {
		t.Fatalf("question row reuses the message colour: %q", questionRow)
	}
	if ansiMagenta == ansiBoldCyan {
		t.Fatal("the two offer colours must differ")
	}
}

// TestUnknownInputOfferPlainFormMatchesColouredForm proves colour-disabled output
// is the plain form of the coloured output, so a redirected run stays readable
// and carries no escape sequence.
func TestUnknownInputOfferPlainFormMatchesColouredForm(t *testing.T) {
	plainStub := scopeStub()
	plain, _ := runScope(t, plainStub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{})
	coloredStub := scopeStub()
	colored, _ := runScope(t, coloredStub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{Enabled: true})
	plainMessage, plainQuestion := offerRows(t, plain, "hello world")
	coloredMessage, coloredQuestion := offerRows(t, colored, "hello world")
	if strings.Contains(plainMessage+plainQuestion, "\x1b") {
		t.Fatalf("plain offer carries ANSI: %q %q", plainMessage, plainQuestion)
	}
	if offerVisibleText(coloredMessage) != plainMessage {
		t.Fatalf("colored message row=%q plain=%q", offerVisibleText(coloredMessage), plainMessage)
	}
	if offerVisibleText(coloredQuestion) != plainQuestion {
		t.Fatalf("colored question row=%q plain=%q", offerVisibleText(coloredQuestion), plainQuestion)
	}
}

// TestUnknownInputOfferSanitizesMessageRow proves operator text cannot inject
// styling into the message row, which is written through the trusted writer.
func TestUnknownInputOfferSanitizesMessageRow(t *testing.T) {
	stub := scopeStub()
	output, _ := runScope(t, stub, sessionScopeInput+"hello \x1b[31mred\x1b[0m\ny\nquit\n", ColorPolicy{Enabled: true})
	messageRow, _ := offerRows(t, output, "hello red")
	if strings.Contains(messageRow, "\x1b[31m") {
		t.Fatalf("message row leaked a payload sequence: %q", messageRow)
	}
	if !strings.Contains(messageRow, ansiMagenta) {
		t.Fatalf("message row lost its own colour: %q", messageRow)
	}
}

// TestUnknownInputOfferTerminatesQuestionRow proves the question row is closed
// before the receipt, so the offer never shares a row with the command evidence.
func TestUnknownInputOfferTerminatesQuestionRow(t *testing.T) {
	stub := scopeStub()
	output, _ := runScope(t, stub, sessionScopeInput+"hello world\ny\nquit\n", ColorPolicy{})
	_, questionRow := offerRows(t, output, "hello world")
	if strings.Contains(questionRow, "command submitted:") {
		t.Fatalf("receipt shares the question row: %q", questionRow)
	}
}

// TestUnknownInputOfferQuestionRowIsTheInputRow proves the offer no longer prints
// a separate answer prompt: the question row itself is the input row, so the
// cursor waits after the answer hint instead of on a second prompt row.
func TestUnknownInputOfferQuestionRowIsTheInputRow(t *testing.T) {
	stub := scopeStub()
	// Two trailing "quit" answers keep the terminator independent of the quit
	// policy, exactly as in TestUnknownInputOfferUsesInjectedReader.
	answers := []string{"cd host-one/endpoint-1/res-1", "hello world", "y", "quit", "quit"}
	index := 0
	var prompts []string
	read := func(_ context.Context, prompt string, _ bool, _ int) (string, bool, error) {
		prompts = append(prompts, prompt)
		if index >= len(answers) {
			return "", false, nil
		}
		answer := answers[index]
		index++
		return answer, false, nil
	}
	var output, diagnostics strings.Builder
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &output, &diagnostics, InteractiveOptions{ReadLine: read, WaitTimeoutMS: 100}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if stub.admit != 1 {
		t.Fatalf("admitted %d commands, want 1; diagnostics=%q", stub.admit, diagnostics.String())
	}
	// The offer read is the third prompt: the scope navigation, the literal line,
	// then the offer question.
	if len(prompts) < 3 {
		t.Fatalf("prompts=%q want at least three reads", prompts)
	}
	offerPrompt := prompts[2]
	if !strings.HasPrefix(offerPrompt, "\n") {
		t.Fatalf("offer prompt=%q must carry the question-row marker", offerPrompt)
	}
	// The raw bytes are logged so the rendered form can be inspected without
	// re-deriving it from the assertions. The question row is the prompt itself,
	// so it is not part of the output writer.
	t.Logf("offer prompt bytes=%q", offerPrompt)
	t.Logf("output bytes=%q", output.String())
	visible := offerVisibleText(strings.TrimPrefix(offerPrompt, "\n"))
	if visible != sendOfferMarker+"send the text above as a message? "+confirmationHint+" " {
		t.Fatalf("offer prompt visible text=%q", visible)
	}
	if strings.Contains(visible, answerPrompt) {
		t.Fatalf("offer prompt still carries the answer prompt: %q", visible)
	}
	if strings.Contains(output.String(), "\n"+answerPrompt) {
		t.Fatalf("offer printed a separate answer prompt: %q", output.String())
	}
}

// TestUnknownInputOfferQuestionRowKeepsHintOnNarrowTerminal proves the question
// row may use the whole row width, so a narrow terminal keeps the trailing answer
// hint instead of clipping it away.
func TestUnknownInputOfferQuestionRowKeepsHintOnNarrowTerminal(t *testing.T) {
	question := sendOfferMarker + "send the text above as a message? " + confirmationHint + " "
	prompt := RenderConfirmationPrompt(question, ColorPolicy{})
	for _, width := range []int{40, 44, 60, 80} {
		var out strings.Builder
		editor := NewTerminalEditor(&editorTestInput{Reader: strings.NewReader("\r")}, &out, func() int { return width }, func() (func() error, error) { return func() error { return nil }, nil })
		if _, _, err := editor.ReadLine(context.Background(), prompt, false, 32); err != nil {
			t.Fatalf("width=%d ReadLine: %v", width, err)
		}
		if !strings.Contains(out.String(), confirmationHint) {
			t.Fatalf("width=%d clipped the answer hint: %q", width, out.String())
		}
	}
}

// TestStyledPromptMeasurementIgnoresEscapeBytes proves a styled prompt is measured
// and clipped by visible columns, so escape bytes never shift the cursor or eat
// the visible text.
func TestStyledPromptMeasurementIgnoresEscapeBytes(t *testing.T) {
	plain := sendOfferMarker + "send the text above as a message? " + confirmationHint + " "
	styled := styledConfirmationQuestion(plain, ColorPolicy{Enabled: true})
	if styledDisplayWidth(styled) != displayWidth(plain) {
		t.Fatalf("styled width=%d plain width=%d", styledDisplayWidth(styled), displayWidth(plain))
	}
	if got := styledDisplayWidth(styled); got != len(plain) {
		t.Fatalf("styled width=%d want the visible length %d", got, len(plain))
	}
	// A clip keeps the visible prefix and never counts the escape bytes as columns.
	clipped := clipStyledCell(styled, 20)
	if got := styledDisplayWidth(clipped); got != 20 {
		t.Fatalf("clipped width=%d want 20: %q", got, clipped)
	}
	if !strings.HasSuffix(clipped, ansiReset) {
		t.Fatalf("clipped value must end with a reset: %q", clipped)
	}
	// A value that already fits is returned unchanged, so styling is preserved.
	if clipStyledCell(styled, 200) != styled {
		t.Fatal("a fitting styled value must not be rewritten")
	}
}
