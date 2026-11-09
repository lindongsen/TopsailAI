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
// while the untrusted payload preview cannot inject its own styling.
func TestConfirmationQuestionStyling(t *testing.T) {
	question := "send " + sanitizeInlineText("hi\x1b[31mRED\x1b[0m") + "? Confirm send? " + confirmationHint + " "
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
	if strings.Contains(text, "\x1b[31m") {
		t.Fatalf("payload ANSI reached the terminal: %q", text)
	}
	stripped := strings.NewReplacer(ansiBoldCyan, "", ansiDim, "", ansiReset, "").Replace(text)
	if stripped != question {
		t.Fatalf("stripped=%q want=%q", stripped, question)
	}
}

// TestConfirmationHintSplitUsesTrailingLiteral keeps a payload that itself
// contains the hint from being mistaken for the answer hint.
func TestConfirmationHintSplitUsesTrailingLiteral(t *testing.T) {
	question := "send " + confirmationHint + "? Confirm send? " + confirmationHint + " "
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

// TestInteractiveSendConfirmationIsStyled drives the real REPL path and proves
// both the confirmation question and the answer prompt are styled, while the
// plain run stays free of ANSI.
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
					// assembled block is never echoed as a whole.
					return "send", false, nil
				case 3:
					return "hi", false, nil
				case 4:
					return "EOF", false, nil
				case 5:
					if history {
						t.Fatalf("confirmation read must not use history")
					}
					if prompt != RenderAnswerPrompt(ColorPolicy{Enabled: enabled}) {
						t.Fatalf("answer prompt=%q", prompt)
					}
					if enabled {
						if !strings.HasPrefix(prompt, "\n"+ansiBoldGreen+"answer>"+ansiReset+" ") {
							t.Fatalf("answer prompt not styled: %q", prompt)
						}
					} else if prompt != "\nanswer> " {
						t.Fatalf("plain answer prompt=%q", prompt)
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
			stripped := strings.NewReplacer(ansiBoldCyan, "", ansiDim, "", ansiReset, "").Replace(text)
			if !strings.Contains(stripped, "Confirm send? "+confirmationHint) {
				t.Fatalf("confirmation question missing: %q", text)
			}
			if enabled {
				if !strings.Contains(text, ansiBoldCyan+"send ") || !strings.Contains(text, ansiDim+confirmationHint+ansiReset) {
					t.Fatalf("confirmation question not styled: %q", text)
				}
			} else if strings.Contains(text, "\x1b") {
				t.Fatalf("plain run carries ANSI: %q", text)
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
