package tui

import (
	"context"
	"strings"
	"testing"
)

// TestAnswerPromptStyling pins the child answer prompt: it must carry the same
// bold-green styling as the REPL prompt when colour is enabled, and stay
// byte-identical to the previous plain form when colour is disabled.
func TestAnswerPromptStyling(t *testing.T) {
	plain := RenderAnswerPrompt(ColorPolicy{})
	if plain != "\nanswer> " {
		t.Fatalf("plain answer prompt=%q want the unchanged literal", plain)
	}
	colored := RenderAnswerPrompt(ColorPolicy{Enabled: true})
	if !strings.HasPrefix(colored, "\n"+ansiBoldGreen) || !strings.HasSuffix(colored, ansiReset+" ") {
		t.Fatalf("colored answer prompt=%q", colored)
	}
	// The terminal editor recognises exactly this wrapper, so the cursor column
	// accounting must see the same visible text as the plain prompt.
	stripped := strings.ReplaceAll(strings.ReplaceAll(colored, ansiBoldGreen, ""), ansiReset, "")
	if stripped != plain {
		t.Fatalf("stripped=%q plain=%q", stripped, plain)
	}
}

// TestConfirmationQuestionStyling proves the confirmation question is styled
// while the untrusted payload preview cannot inject its own styling. The sample is
// a stop question, because that is the wording the shared renderer still serves:
// the bare-send confirmation is a named prompt now, not a question row.
func TestConfirmationQuestionStyling(t *testing.T) {
	question := "stop session (Daily work) (provider-res-1)? Confirm stop? " + confirmationHint + " "
	var plain, colored strings.Builder
	if err := writeConfirmationQuestion(&plain, question, ColorPolicy{}); err != nil {
		t.Fatal(err)
	}
	if err := writeConfirmationQuestion(&colored, question, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	if plain.String() != question {
		t.Fatalf("plain question=%q want=%q", plain.String(), question)
	}
	if strings.Contains(plain.String(), "\x1b") {
		t.Fatalf("plain question carries ANSI: %q", plain.String())
	}
	text := colored.String()
	if !strings.Contains(text, ansiBoldCyan) || !strings.Contains(text, ansiDim+confirmationHint+ansiReset) {
		t.Fatalf("colored question missing styles: %q", text)
	}
	stripped := strings.NewReplacer(ansiBoldCyan, "", ansiDim, "", ansiReset, "").Replace(text)
	if stripped != question {
		t.Fatalf("stripped=%q want=%q", stripped, question)
	}
}

// TestConfirmationHintSplitUsesTrailingLiteral keeps a value that itself contains
// the hint from being mistaken for the answer hint.
func TestConfirmationHintSplitUsesTrailingLiteral(t *testing.T) {
	question := "stop session " + confirmationHint + "? Confirm stop? " + confirmationHint + " "
	var colored strings.Builder
	if err := writeConfirmationQuestion(&colored, question, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	stripped := strings.NewReplacer(ansiBoldCyan, "", ansiDim, "", ansiReset, "").Replace(colored.String())
	if stripped != question {
		t.Fatalf("stripped=%q want=%q", stripped, question)
	}
	if got := strings.Count(colored.String(), ansiDim+confirmationHint+ansiReset); got != 1 {
		t.Fatalf("dimmed hint count=%d want=1 output=%q", got, colored.String())
	}
}

// TestInteractiveSendConfirmationIsStyled drives the real REPL path and proves the
// bare-send confirmation is a coloured body followed by a styled named prompt,
// while the plain run stays free of ANSI. The prompt is asserted through the read
// argument, because the terminal editor owns that row and the caller must not
// write it a second time.
func TestInteractiveSendConfirmationIsStyled(t *testing.T) {
	for _, enabled := range []bool{true, false} {
		t.Run(map[bool]string{true: "color", false: "plain"}[enabled], func(t *testing.T) {
			stub := inputStub()
			var out, diagnostics strings.Builder
			calls := 0
			read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
				calls++
				switch calls {
				case 1:
					return "cd endpoint-1/session-1", false, nil
				case 2:
					// A bare send is the only form that still asks, because the
					// assembled block was never shown as a whole.
					return "send", false, nil
				case 3:
					return "hi", false, nil
				case 4:
					return "EOF", false, nil
				case 5:
					if history {
						t.Fatalf("confirmation read must not use history")
					}
					if want := RenderNamedPrompt(sendConfirmPrompt, ColorPolicy{Enabled: enabled}); prompt != want {
						t.Fatalf("confirmation prompt=%q want=%q", prompt, want)
					}
					return "y", false, nil
				default:
					return "quit", false, nil
				}
			}
			err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read, WaitTimeoutMS: 100, Color: ColorPolicy{Enabled: enabled}})
			if err != nil {
				t.Fatalf("RunInteractive: %v", err)
			}
			text := out.String()
			if enabled {
				if !strings.Contains(text, ansiMagenta+"hi"+ansiReset+"\n") {
					t.Fatalf("confirmation body not styled: %q", text)
				}
			} else {
				if !strings.Contains(text, "hi\n") {
					t.Fatalf("confirmation body missing: %q", text)
				}
				if strings.Contains(text, "\x1b") {
					t.Fatalf("plain run carries ANSI: %q", text)
				}
			}
		})
	}
}

// TestNamedPromptStyling pins the shared named-prompt renderer used by every
// prompt that waits for operator input. With colour enabled the prompt carries the
// bold-green wrapper the terminal editor recognises; with colour disabled it is
// byte-identical to the previous plain literal, so a piped run stays clean.
func TestNamedPromptStyling(t *testing.T) {
	if got := RenderNamedPrompt("start.endpoint>", ColorPolicy{}); got != "start.endpoint> " {
		t.Fatalf("plain named prompt=%q want the unchanged literal", got)
	}
	colored := RenderNamedPrompt("start.endpoint>", ColorPolicy{Enabled: true})
	if colored != ansiBoldGreen+"start.endpoint>"+ansiReset+" " {
		t.Fatalf("colored named prompt=%q", colored)
	}
	stripped := strings.ReplaceAll(strings.ReplaceAll(colored, ansiBoldGreen, ""), ansiReset, "")
	if stripped != "start.endpoint> " {
		t.Fatalf("stripped=%q", stripped)
	}
}

// TestStyleNamedPromptOnlyStylesPlainNamedPrompts proves the caller-supplied
// prompt path styles a plain named prompt and leaves every other shape untouched,
// so a question row and an already styled prompt are never wrapped twice.
func TestStyleNamedPromptOnlyStylesPlainNamedPrompts(t *testing.T) {
	enabled := ColorPolicy{Enabled: true}
	cases := []struct {
		name   string
		prompt string
		want   string
	}{
		{"named", "ctl.action> ", ansiBoldGreen + "ctl.action>" + ansiReset + " "},
		{"named with dotted field", "ctl.session_id> ", ansiBoldGreen + "ctl.session_id>" + ansiReset + " "},
		{"operation action", "interrupt.action> ", ansiBoldGreen + "interrupt.action>" + ansiReset + " "},
		{"question row", "\nanswer> ", "\nanswer> "},
		{"already styled", ansiBoldGreen + "start.task>" + ansiReset + " ", ansiBoldGreen + "start.task>" + ansiReset + " "},
		{"not a named prompt", "select endpoint [1-2] or 'cancel': ", "select endpoint [1-2] or 'cancel': "},
		{"empty", "", ""},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			if got := styleNamedPrompt(testCase.prompt, enabled); got != testCase.want {
				t.Fatalf("styleNamedPrompt(%q)=%q want=%q", testCase.prompt, got, testCase.want)
			}
			// A disabled policy must never introduce styling.
			if got := styleNamedPrompt(testCase.prompt, ColorPolicy{}); got != testCase.prompt {
				t.Fatalf("disabled styleNamedPrompt(%q)=%q", testCase.prompt, got)
			}
		})
	}
}

// TestStartWizardPromptsAreStyled proves the start wizard writes its field prompt
// through the trusted writer with colour, because writing a styled prompt to the
// sanitizing writer silently strips the colour and leaves the wizard as the only
// unstyled prompt in the session.
func TestStartWizardPromptsAreStyled(t *testing.T) {
	for _, enabled := range []bool{true, false} {
		t.Run(map[bool]string{true: "colored", false: "plain"}[enabled], func(t *testing.T) {
			var safe, trusted strings.Builder
			if err := writeStartHelp(&safe, &trusted, startFieldEndpoint, interactiveState{}, ColorPolicy{Enabled: enabled}); err != nil {
				t.Fatal(err)
			}
			if strings.Contains(safe.String(), "\x1b") {
				t.Fatalf("sanitizing writer received styling: %q", safe.String())
			}
			prompt := trusted.String()
			if enabled {
				if prompt != ansiBoldGreen+"start.endpoint>"+ansiReset+" " {
					t.Fatalf("colored wizard prompt=%q", prompt)
				}
			} else if prompt != "start.endpoint> " {
				t.Fatalf("plain wizard prompt=%q", prompt)
			}
		})
	}
}

// TestReadPromptLineStylesCallerPrompt proves the shared read path styles a
// caller-supplied named prompt, so every prompt that waits for operator input is
// covered by one choke point instead of each caller opting in. It also proves the
// default answer prompt and the disabled policy keep their previous behaviour.
func TestReadPromptLineStylesCallerPrompt(t *testing.T) {
	cases := []struct {
		name   string
		policy ColorPolicy
		prompt []string
		want   string
	}{
		{"caller prompt colored", ColorPolicy{Enabled: true}, []string{"ctl.action> "}, ansiBoldGreen + "ctl.action>" + ansiReset + " "},
		{"caller prompt plain", ColorPolicy{}, []string{"ctl.action> "}, "ctl.action> "},
		{"default prompt colored", ColorPolicy{Enabled: true}, nil, "\n" + ansiBoldGreen + "answer>" + ansiReset + " "},
		{"default prompt plain", ColorPolicy{}, nil, "\nanswer> "},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var seen string
			read := func(_ context.Context, prompt string, _ bool, _ int) (string, bool, error) {
				seen = prompt
				return "answer", false, nil
			}
			ctx := context.WithValue(context.Background(), promptReaderKey{}, promptReaderConfig{read: read, limit: 8192, color: testCase.policy})
			if _, _, err := readPromptLine(ctx, testCase.prompt...); err != nil {
				t.Fatal(err)
			}
			if seen != testCase.want {
				t.Fatalf("prompt=%q want=%q", seen, testCase.want)
			}
		})
	}
}

// TestSendConfirmationBodyKeepsLineBreaks proves the bare-send confirmation body
// is the block itself, not a flattened preview. A multi-line block must keep its
// own rows, because a single flattened line hides exactly the line breaks the
// operator is approving, and the payload colour must never be confused with the
// application's own prompt.
func TestSendConfirmationBodyKeepsLineBreaks(t *testing.T) {
	block := "first line\n  indented second line\nthird line"
	var plain, colored strings.Builder
	if err := writeSendConfirmationBody(&plain, block, ColorPolicy{}); err != nil {
		t.Fatal(err)
	}
	if err := writeSendConfirmationBody(&colored, block, ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	if want := block + "\n"; plain.String() != want {
		t.Fatalf("plain body=%q want=%q", plain.String(), want)
	}
	if strings.Contains(plain.String(), "\x1b") {
		t.Fatalf("plain body carries ANSI: %q", plain.String())
	}
	text := colored.String()
	for _, line := range strings.Split(block, "\n") {
		if !strings.Contains(text, ansiMagenta+line+ansiReset+"\n") {
			t.Fatalf("line %q not styled in %q", line, text)
		}
	}
	stripped := strings.ReplaceAll(text, ansiReset, "")
	stripped = strings.ReplaceAll(stripped, ansiMagenta, "")
	if want := block + "\n"; stripped != want {
		t.Fatalf("stripped body=%q want=%q", stripped, want)
	}
}

// TestSendConfirmationBodyStripsPayloadStyling proves an operator payload cannot
// inject its own styling or move the cursor, because the body is written through
// the trusted writer that carries the payload colour.
func TestSendConfirmationBodyStripsPayloadStyling(t *testing.T) {
	var colored strings.Builder
	if err := writeSendConfirmationBody(&colored, "hi\x1b[31mRED\x1b[0m\x1b[2J", ColorPolicy{Enabled: true}); err != nil {
		t.Fatal(err)
	}
	text := colored.String()
	if strings.Contains(text, "\x1b[31m") {
		t.Fatalf("payload ANSI reached the terminal: %q", text)
	}
	if strings.Contains(text, "\x1b[2J") {
		t.Fatalf("payload cursor control reached the terminal: %q", text)
	}
	if !strings.Contains(text, ansiMagenta+"hiRED") {
		t.Fatalf("payload text lost: %q", text)
	}
}

// TestSendConfirmPromptKeepsHintWhenClipped proves a narrow terminal shortens the
// prompt name but never hides the accepted answers, because the hint is the only
// cue telling the operator what to type.
func TestSendConfirmPromptKeepsHintWhenClipped(t *testing.T) {
	styled := RenderNamedPrompt(sendConfirmPrompt, ColorPolicy{Enabled: true})
	// The hint always survives, even when it is wider than the budget: a prompt
	// that hides the accepted answers tells the operator nothing.
	for _, width := range []int{4, 6, 8, 10, 12} {
		clipped := clipStyledCellKeepHint(styled, width)
		if !strings.Contains(clipped, confirmationHint) {
			t.Fatalf("width=%d clipped=%q lost the answer hint", width, clipped)
		}
	}
	// Above the hint width the clip also respects the budget, so a narrow terminal
	// shortens the prompt name instead of overflowing the row.
	for _, width := range []int{8, 10, 12} {
		clipped := clipStyledCellKeepHint(styled, width)
		if got := styledDisplayWidth(clipped); got > width {
			t.Fatalf("width=%d clipped=%q width=%d", width, clipped, got)
		}
	}
	if got := clipStyledCellKeepHint(styled, 200); got != styled {
		t.Fatalf("wide clip changed the prompt: %q", got)
	}
}

// TestSendConfirmPromptKeepsHintThroughEditor proves the editor keeps the answer
// hint of the bare-send named prompt on a narrow terminal. The prompt is a named
// prompt rather than a question row, so this exercises the editor's own clip
// decision instead of the helper alone: a helper that preserves the hint is
// useless if the editor never calls it for this prompt.
func TestSendConfirmPromptKeepsHintThroughEditor(t *testing.T) {
	prompt := RenderNamedPrompt(sendConfirmPrompt, ColorPolicy{})
	for _, width := range []int{20, 24, 30, 80} {
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
