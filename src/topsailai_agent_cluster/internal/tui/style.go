package tui

import (
	"io"
	"strings"
)

const (
	ansiBoldCyan  = "\x1b[1;36m"
	ansiCyan      = "\x1b[36m"
	ansiBoldGreen = "\x1b[1;32m"
	ansiGreen     = "\x1b[32m"
	ansiDim       = "\x1b[2m"
	ansiYellow    = "\x1b[33m"
	ansiRed       = "\x1b[31m"
	ansiReset     = "\x1b[0m"
)

// ColorPolicy controls trusted application styling.
type ColorPolicy struct{ Enabled bool }

// ResolveColorPolicy applies the complete color eligibility policy.
func ResolveColorPolicy(outputTTY, noColorPresent, noColorFlag, termDumb, platformSupported bool) ColorPolicy {
	return ColorPolicy{Enabled: outputTTY && !noColorPresent && !noColorFlag && !termDumb && platformSupported}
}

// ColorPolicyProvider lets an output boundary report the colour policy it was
// resolved with, so a renderer reached through a generic writer still honours
// --no-color and a redirected stream. It mirrors TableLayoutProvider: the
// boundary owns the presentation decision, and a renderer never probes global
// terminal state.
type ColorPolicyProvider interface {
	ColorPolicy() ColorPolicy
}

// OutputColorPolicy obtains the boundary-provided colour policy. A writer that
// does not report one keeps colour disabled, so an unknown boundary never
// receives escape sequences it did not ask for.
func OutputColorPolicy(out io.Writer) ColorPolicy {
	if provider, ok := out.(ColorPolicyProvider); ok {
		return provider.ColorPolicy()
	}
	return ColorPolicy{}
}

// writeStyled writes text with one ANSI style. An empty style means the text
// carries no colour, so it is written plain instead of emitting a bare reset.
func writeStyled(w io.Writer, style, text string, policy ColorPolicy) error {
	if !policy.Enabled || style == "" {
		_, err := io.WriteString(w, text)
		return err
	}
	_, err := io.WriteString(w, style+text+ansiReset)
	return err
}

// answerPrompt is the history-free child question shown after a confirmation.
const answerPrompt = "answer> "

// confirmationHint is the trailing answer hint of every confirmation question.
const confirmationHint = "[y/N]"

// RenderAnswerPrompt returns the reset-safe answer prompt for a child read.
// The leading newline keeps the question on its own row; the bold-green
// wrapper is the exact form the terminal editor recognises, so the cursor
// column accounting stays identical to the plain prompt.
func RenderAnswerPrompt(policy ColorPolicy) string {
	if !policy.Enabled {
		return "\n" + answerPrompt
	}
	return "\n" + ansiBoldGreen + strings.TrimSuffix(answerPrompt, " ") + ansiReset + " "
}

// writeConfirmationQuestion writes a trusted confirmation question. The
// question text is styled and the trailing answer hint is dimmed; with colour
// disabled the exact plain question is written, so redirected output stays
// byte-identical. Callers must sanitize every provider or payload value they
// interpolate, because this writer carries trusted styling.
func writeConfirmationQuestion(w io.Writer, question string, policy ColorPolicy) error {
	if !policy.Enabled {
		_, err := io.WriteString(w, question)
		return err
	}
	// The hint is the trailing literal, so a payload that itself contains
	// "[y/N]" must not be mistaken for it.
	index := strings.LastIndex(question, confirmationHint)
	if index < 0 {
		return writeStyled(w, ansiBoldCyan, question, policy)
	}
	if err := writeStyled(w, ansiBoldCyan, question[:index], policy); err != nil {
		return err
	}
	if err := writeStyled(w, ansiDim, confirmationHint, policy); err != nil {
		return err
	}
	_, err := io.WriteString(w, question[index+len(confirmationHint):])
	return err
}

// sanitizeInlineText flattens untrusted text into one terminal-safe line before
// it is interpolated into a trusted styled question. Terminal escape sequences
// are stripped and control characters become a replacement rune, so a payload
// preview can never inject styling or move the cursor.
func sanitizeInlineText(value string) string {
	clean := sanitizeTerminal([]byte(value))
	return strings.NewReplacer("\n", " ", "\r", " ", "\t", " ").Replace(clean)
}

// RenderPrompt writes a trusted, reset-safe REPL prompt.
func RenderPrompt(w io.Writer, scope ScopeState, invalidated bool, policy ColorPolicy) error {
	prompt := scope.Kind.String()
	switch scope.Kind {
	case ScopeEndpoint:
		endpoint := scope.Hostname
		if endpoint == "" {
			endpoint = scope.EndpointID
		}
		prompt += "[" + sanitizePromptPart(endpoint)
		if scope.Hostname != "" {
			prompt += "/" + sanitizePromptPart(scope.EndpointID)
		}
		prompt += "]"
	case ScopeSession:
		hostname := scope.Hostname
		if hostname == "" {
			hostname = scope.EndpointID
		}
		sessionID := scope.ProviderSessionID
		if sessionID == "" {
			sessionID = "-"
		}
		prompt += "[" + sanitizePromptPart(hostname) + "/" + sanitizePromptPart(sessionID)
		if invalidated {
			prompt += "!"
		}
		prompt += "]"
	}
	prompt += ">"
	if err := writeStyled(w, ansiBoldGreen, prompt, policy); err != nil {
		return err
	}
	_, err := io.WriteString(w, " ")
	return err
}

func sanitizePromptPart(value string) string {
	value = escapeCell(value)
	return strings.ReplaceAll(value, "/", "∕")
}

func shortResourceID(value string) string {
	if len(value) <= 12 {
		return value
	}
	return value[:12]
}
