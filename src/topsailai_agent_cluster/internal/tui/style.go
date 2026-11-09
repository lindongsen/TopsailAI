package tui

import (
	"io"
	"strings"
	"unicode/utf8"
)

const (
	ansiBoldCyan  = "\x1b[1;36m"
	ansiCyan      = "\x1b[36m"
	ansiBoldGreen = "\x1b[1;32m"
	ansiGreen     = "\x1b[32m"
	ansiDim       = "\x1b[2m"
	ansiYellow    = "\x1b[33m"
	ansiRed       = "\x1b[31m"
	// ansiMagenta marks operator-supplied payload text, so a message body is
	// never confused with the application's own question. It is deliberately
	// outside the state palette (green running, yellow unknown, red failed), so
	// a payload can never read as a status.
	ansiMagenta = "\x1b[35m"
	ansiReset   = "\x1b[0m"
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
	return "\n" + RenderNamedPrompt(answerPrompt, policy)
}

// RenderNamedPrompt returns a named prompt such as "start.endpoint> " with the
// same bold-green styling as the REPL prompt. The wrapper is the exact form the
// terminal editor recognises, so the cursor column accounting stays identical to
// the plain prompt. With colour disabled the plain prompt is returned unchanged,
// so a redirected or --no-color run stays byte-identical.
func RenderNamedPrompt(name string, policy ColorPolicy) string {
	name = strings.TrimSuffix(name, " ")
	if !policy.Enabled {
		return name + " "
	}
	return ansiBoldGreen + name + ansiReset + " "
}

// styleNamedPrompt applies RenderNamedPrompt to a caller-supplied prompt, but only
// when that prompt is a plain named prompt. A question row (leading newline) and an
// already styled prompt are returned unchanged, because their own renderer owns the
// styling and re-wrapping them would nest escape sequences.
func styleNamedPrompt(prompt string, policy ColorPolicy) string {
	if !policy.Enabled || prompt == "" {
		return prompt
	}
	if strings.Contains(prompt, "\x1b") || strings.HasPrefix(prompt, "\n") {
		return prompt
	}
	if !strings.HasSuffix(prompt, "> ") {
		return prompt
	}
	return RenderNamedPrompt(prompt, policy)
}

// styledConfirmationQuestion returns the confirmation question with its own
// styling applied. The question text is bold cyan and the trailing answer hint is
// dimmed; with colour disabled the exact plain question is returned, so redirected
// output stays byte-identical. Callers must sanitize every provider or payload
// value they interpolate, because this function carries trusted styling.
func styledConfirmationQuestion(question string, policy ColorPolicy) string {
	if !policy.Enabled {
		return question
	}
	// The hint is the trailing literal, so a payload that itself contains
	// "[y/N]" must not be mistaken for it.
	index := strings.LastIndex(question, confirmationHint)
	if index < 0 {
		return ansiBoldCyan + question + ansiReset
	}
	return ansiBoldCyan + question[:index] + ansiReset +
		ansiDim + confirmationHint + ansiReset +
		question[index+len(confirmationHint):]
}

// writeConfirmationQuestion writes a trusted confirmation question.
func writeConfirmationQuestion(w io.Writer, question string, policy ColorPolicy) error {
	_, err := io.WriteString(w, styledConfirmationQuestion(question, policy))
	return err
}

// RenderConfirmationPrompt returns the confirmation question as a terminal-editor
// prompt, so the question row itself becomes the input row and the cursor waits
// after the answer hint. The leading newline is the editor's question-row marker:
// it ends the previous row and redraws the question on a row of its own, which is
// why no separate answer prompt is printed for this question.
func RenderConfirmationPrompt(question string, policy ColorPolicy) string {
	return "\n" + styledConfirmationQuestion(question, policy)
}

// sgrSequenceSize returns the byte length of a colour-only SGR sequence at the
// start of value, or zero when value does not start with one. Only the styling
// this package emits is recognised, so a cursor-control sequence is never treated
// as zero-width.
func sgrSequenceSize(value string) int {
	if len(value) < 3 || value[0] != 0x1b || value[1] != '[' {
		return 0
	}
	for index := 2; index < len(value); index++ {
		switch {
		case value[index] == 'm':
			return index + 1
		case value[index] >= '0' && value[index] <= '9':
		case value[index] == ';' || value[index] == ':':
		default:
			return 0
		}
	}
	return 0
}

// styledDisplayWidth returns the terminal column count of value, ignoring the
// colour-only SGR sequences this package emits. A styled prompt must be measured
// by its visible text, because escape bytes occupy no column and counting them
// would misplace the cursor.
func styledDisplayWidth(value string) int {
	width := 0
	for index := 0; index < len(value); {
		if size := sgrSequenceSize(value[index:]); size > 0 {
			index += size
			continue
		}
		r, size := utf8.DecodeRuneInString(value[index:])
		width += runeDisplayWidth(r)
		index += size
	}
	return width
}

// clipStyledCell clips a styled value to width visible columns. Escape sequences
// are preserved and never counted, and a truncated value ends with a reset so the
// terminal cannot inherit a style from the clipped tail.
func clipStyledCell(value string, width int) string {
	if styledDisplayWidth(value) <= width {
		return value
	}
	if width <= 3 {
		return strings.Repeat(".", width)
	}
	limit := width - 3
	var out strings.Builder
	used := 0
	styled := false
	for index := 0; index < len(value); {
		if size := sgrSequenceSize(value[index:]); size > 0 {
			out.WriteString(value[index : index+size])
			styled = true
			index += size
			continue
		}
		r, size := utf8.DecodeRuneInString(value[index:])
		runeWidth := runeDisplayWidth(r)
		if used+runeWidth > limit {
			break
		}
		out.WriteRune(r)
		used += runeWidth
		index += size
	}
	out.WriteString("...")
	if styled {
		out.WriteString(ansiReset)
	}
	return out.String()
}

// clipStyledCellKeepHint clips a styled question to width visible columns while
// keeping the trailing answer hint. The hint is the only cue telling the operator
// what to type, so a narrow terminal must shorten the question instead of hiding
// the hint. Escape sequences are preserved and never counted.
func clipStyledCellKeepHint(value string, width int) string {
	if styledDisplayWidth(value) <= width {
		return value
	}
	index := strings.LastIndex(value, confirmationHint)
	if index < 0 {
		return clipStyledCell(value, width)
	}
	head, tail := value[:index], value[index:]
	tailWidth := styledDisplayWidth(tail)
	if tailWidth >= width {
		return tail
	}
	return clipStyledCell(head, width-tailWidth) + tail
}

// sanitizeInlineText flattens untrusted text into one terminal-safe line before
// it is interpolated into a trusted styled question. Terminal escape sequences
// are stripped and control characters become a replacement rune, so a payload
// preview can never inject styling or move the cursor.
func sanitizeInlineText(value string) string {
	clean := sanitizeTerminal([]byte(value))
	return strings.NewReplacer("\n", " ", "\r", " ", "\t", " ").Replace(clean)
}

// SanitizeInlineText exposes sanitizeInlineText so a caller outside this package
// can flatten an untrusted identifier before interpolating it into a trusted
// line. It is the same rule the renderers use, so a caller cannot invent a
// weaker one.
func SanitizeInlineText(value string) string {
	return sanitizeInlineText(value)
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
