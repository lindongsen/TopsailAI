package tui

import (
	"context"
	"strings"
	"testing"
)

// echoTestEditor builds a real editor over injected input, so the echo is
// verified against the bytes the editor actually writes rather than against a
// stub that could omit the behaviour under test.
func echoTestEditor(input string, out *blockTestOutput, columns int) *TerminalEditor {
	return NewTerminalEditor(
		&editorTestInput{Reader: strings.NewReader(input)},
		out,
		func() int { return columns },
		func() (func() error, error) { return func() error { return nil }, nil },
	)
}

// TestReadLineWithEchoAppendsToTheAnswerRow proves the echo is written on the
// same row as the accepted answer, after the typed text, and before the row is
// terminated. A caller cannot do this itself, because the editor has already
// moved the cursor to the next row when it returns.
func TestReadLineWithEchoAppendsToTheAnswerRow(t *testing.T) {
	out := &blockTestOutput{height: 40}
	editor := echoTestEditor("1\r", out, 80)
	echoed := 0
	echo := func(answer string) string {
		echoed++
		if answer != "1" {
			t.Fatalf("echo received %q, want the accepted answer", answer)
		}
		return RenderAnswerEcho("ai-dev", ColorPolicy{})
	}
	got, overflow, err := editor.ReadLineWithEcho(context.Background(), "start.endpoint> ", true, 4096, echo)
	if err != nil || overflow || got != "1" {
		t.Fatalf("got=%q overflow=%v err=%v", got, overflow, err)
	}
	if echoed != 1 {
		t.Fatalf("echo called %d times, want exactly once", echoed)
	}
	rendered := out.String()
	// The echo must appear after the typed answer and before the row ends, which
	// is what makes it read as part of the same line.
	answerAt := strings.Index(rendered, "1")
	echoAt := strings.Index(rendered, "(ai-dev)")
	if answerAt < 0 || echoAt < 0 {
		t.Fatalf("answer or echo missing: %q", rendered)
	}
	if echoAt < answerAt {
		t.Fatalf("echo precedes the answer: %q", rendered)
	}
	if newline := strings.Index(rendered[answerAt:], "\r\n"); newline >= 0 && answerAt+newline < echoAt {
		t.Fatalf("echo landed after the row ended: %q", rendered)
	}
}

// TestReadLineWithEchoCarriesColour proves the echo is styled when colour is
// enabled, so it is distinguishable from the application's own prompt.
func TestReadLineWithEchoCarriesColour(t *testing.T) {
	out := &blockTestOutput{height: 40}
	editor := echoTestEditor("2\r", out, 80)
	echo := func(string) string { return RenderAnswerEcho("pause", ColorPolicy{Enabled: true}) }
	if _, _, err := editor.ReadLineWithEcho(context.Background(), "ctl.action> ", true, 4096, echo); err != nil {
		t.Fatalf("ReadLineWithEcho: %v", err)
	}
	rendered := out.String()
	if !strings.Contains(rendered, ansiMagenta) {
		t.Fatalf("echo carries no colour: %q", rendered)
	}
	if !strings.Contains(rendered, "(pause)") {
		t.Fatalf("echo label missing: %q", rendered)
	}
}

// TestReadLineWithEchoSkipsEmptyAndCancelledAnswers proves no echo is written
// when the answer selects nothing, so a cancel or a rejected answer never claims
// a selection that was not made.
func TestReadLineWithEchoSkipsEmptyAndCancelledAnswers(t *testing.T) {
	cases := []struct {
		name    string
		input   string
		wantErr bool
	}{
		// A bare return accepts an empty line without an error, so the wizard
		// decides what an empty answer means. The echo must stay silent either
		// way, because nothing was selected.
		{name: "empty answer", input: "\r", wantErr: false},
		{name: "interrupt", input: "\x03", wantErr: true},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			out := &blockTestOutput{height: 40}
			editor := echoTestEditor(testCase.input, out, 80)
			echoed := 0
			echo := func(string) string {
				echoed++
				return RenderAnswerEcho("ai-dev", ColorPolicy{})
			}
			got, _, err := editor.ReadLineWithEcho(context.Background(), "start.endpoint> ", true, 4096, echo)
			if testCase.wantErr && err == nil {
				t.Fatalf("expected an error, got answer %q", got)
			}
			if !testCase.wantErr && (err != nil || got != "") {
				t.Fatalf("got=%q err=%v, want an empty answer without an error", got, err)
			}
			if echoed != 0 {
				t.Fatalf("echo called %d times, want none", echoed)
			}
			if strings.Contains(out.String(), "(ai-dev)") {
				t.Fatalf("echo written for a non-selection: %q", out.String())
			}
		})
	}
}

// TestReadLineWithEchoSkipsOverflow proves an over-long answer echoes nothing,
// because the wizard rejects it and re-asks rather than accepting it.
func TestReadLineWithEchoSkipsOverflow(t *testing.T) {
	out := &blockTestOutput{height: 40}
	editor := echoTestEditor("abcdefgh\r", out, 80)
	echoed := 0
	echo := func(string) string {
		echoed++
		return RenderAnswerEcho("ai-dev", ColorPolicy{})
	}
	_, overflow, err := editor.ReadLineWithEcho(context.Background(), "start.endpoint> ", true, 5, echo)
	if err != nil || !overflow {
		t.Fatalf("overflow=%v err=%v, want an overflow", overflow, err)
	}
	if echoed != 0 {
		t.Fatalf("echo called %d times, want none", echoed)
	}
}

// TestReadLineWithEchoPlacesEchoOnTheLastRow proves a wrapped answer echoes at
// the end of its final row, which is where the cursor actually is. A single-row
// fixture cannot express this failure mode.
func TestReadLineWithEchoPlacesEchoOnTheLastRow(t *testing.T) {
	value := strings.Repeat("abcdefghij", 3)
	out := &blockTestOutput{height: 40}
	editor := echoTestEditor(value+"\r", out, 20)
	echo := func(string) string { return RenderAnswerEcho("tail", ColorPolicy{}) }
	if _, _, err := editor.ReadLineWithEcho(context.Background(), "workspace> ", true, 4096, echo); err != nil {
		t.Fatalf("ReadLineWithEcho: %v", err)
	}
	rendered := out.String()
	echoAt := strings.LastIndex(rendered, "(tail)")
	if echoAt < 0 {
		t.Fatalf("echo missing: %q", rendered)
	}
	// The editor terminates the row after the echo, so the echo must be followed
	// by the row end rather than by more answer text.
	if tail := rendered[echoAt:]; !strings.HasPrefix(tail, "(tail)\r\r\n") {
		t.Fatalf("echo is not terminated by the row end: %q", tail)
	}
	// The echo must sit on the row that carries the end of the answer, so no row
	// terminator may appear between the last answer characters and the echo.
	rowStart := strings.LastIndex(rendered[:echoAt], "\r\n")
	if rowStart < 0 {
		t.Fatalf("no row terminator before the echo: %q", rendered)
	}
	if row := rendered[rowStart+2 : echoAt]; !strings.Contains(row, "ij") {
		t.Fatalf("echo is not on the answer's last row: row=%q", row)
	}
}

// TestReadLineWithoutEchoWritesNoEcho proves the plain read is unchanged, so the
// new seam cannot leak into a caller that did not ask for it.
func TestReadLineWithoutEchoWritesNoEcho(t *testing.T) {
	out := &blockTestOutput{height: 40}
	editor := echoTestEditor("1\r", out, 80)
	if _, _, err := editor.ReadLine(context.Background(), "start.endpoint> ", true, 4096); err != nil {
		t.Fatalf("ReadLine: %v", err)
	}
	if strings.Contains(out.String(), "(") {
		t.Fatalf("plain read wrote an echo: %q", out.String())
	}
}

// TestWriteAnswerEchoFallbackWritesOneLine proves the non-TTY fallback reports
// the selection instead of dropping it, and that a nil writer stays silent.
func TestWriteAnswerEchoFallbackWritesOneLine(t *testing.T) {
	var out strings.Builder
	if err := writeAnswerEchoFallback(&out, RenderAnswerEcho("ai-dev", ColorPolicy{})); err != nil {
		t.Fatalf("writeAnswerEchoFallback: %v", err)
	}
	if got, want := out.String(), " (ai-dev)\n"; got != want {
		t.Fatalf("fallback = %q, want %q", got, want)
	}
	if err := writeAnswerEchoFallback(nil, " (ai-dev)"); err != nil {
		t.Fatalf("nil writer must stay silent: %v", err)
	}
	if err := writeAnswerEchoFallback(&out, ""); err != nil {
		t.Fatalf("empty suffix must stay silent: %v", err)
	}
	if got, want := out.String(), " (ai-dev)\n"; got != want {
		t.Fatalf("silent cases wrote output: %q", got)
	}
}

// TestRenderAnswerEchoSanitizesProviderData proves a display name carrying an
// escape sequence cannot inject styling into the terminal.
func TestRenderAnswerEchoSanitizesProviderData(t *testing.T) {
	got := RenderAnswerEcho("evil\x1b[31mred", ColorPolicy{})
	if strings.Contains(got, "\x1b[31m") {
		t.Fatalf("escape sequence survived: %q", got)
	}
	if !strings.Contains(got, "evil") {
		t.Fatalf("label lost: %q", got)
	}
	if got := RenderAnswerEcho("", ColorPolicy{}); got != "" {
		t.Fatalf("empty label = %q, want no echo", got)
	}
}

// TestReadLineWithEchoCountsThePromptOnASingleRow proves the echo is placed
// after the answer on a one-row block, where the prompt shares that row.
//
// The rows the editor renders hold text only; the prompt is written beside row
// zero. A width taken from the text alone therefore lands the echo inside the
// prompt, overwriting it. This asserts the cursor movement itself, because a
// byte-order assertion cannot see the difference: the echo still follows the
// answer in the stream while the cursor is in the wrong column.
func TestReadLineWithEchoCountsThePromptOnASingleRow(t *testing.T) {
	out := &blockTestOutput{height: 40}
	editor := echoTestEditor("1\r", out, 80)
	prompt := "start.endpoint> "
	echo := func(string) string { return RenderAnswerEcho("ai-dev", ColorPolicy{}) }
	if _, _, err := editor.ReadLineWithEcho(context.Background(), prompt, true, 4096, echo); err != nil {
		t.Fatalf("ReadLineWithEcho: %v", err)
	}
	// The answer is one column wide and the prompt is sixteen, so the echo must
	// start at column seventeen of the answer row.
	want := "\r\x1b[17C (ai-dev)"
	if !strings.Contains(out.String(), want) {
		t.Fatalf("echo sequence missing %q in %q", want, out.String())
	}
}

// TestReadLineWithEchoCountsOnlyTheLastRowOfAWrappedAnswer proves a wrapped
// answer counts the last row alone, because the prompt sits on the first row
// and the echo belongs after the text on the final row.
func TestReadLineWithEchoCountsOnlyTheLastRowOfAWrappedAnswer(t *testing.T) {
	out := &blockTestOutput{height: 40}
	// A narrow terminal forces the answer onto several rows.
	editor := echoTestEditor("abcdefghij\r", out, 12)
	echo := func(string) string { return RenderAnswerEcho("row", ColorPolicy{}) }
	if _, _, err := editor.ReadLineWithEcho(context.Background(), "p> ", true, 4096, echo); err != nil {
		t.Fatalf("ReadLineWithEcho: %v", err)
	}
	rendered := out.String()
	// The prompt is three columns wide and must not be added to a continuation
	// row, so the echo never moves by the prompt width plus a continuation row.
	if strings.Contains(rendered, "\x1b[13C (row)") {
		t.Fatalf("prompt width leaked into a continuation row: %q", rendered)
	}
	if !strings.Contains(rendered, "(row)") {
		t.Fatalf("echo missing: %q", rendered)
	}
}
