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
					return `send {"text":"hi"}`, false, nil
				case 3:
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
