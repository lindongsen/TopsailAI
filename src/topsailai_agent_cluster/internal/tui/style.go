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

func writeStyled(w io.Writer, style, text string, policy ColorPolicy) error {
	if !policy.Enabled {
		_, err := io.WriteString(w, text)
		return err
	}
	_, err := io.WriteString(w, style+text+ansiReset)
	return err
}

// RenderPrompt writes a trusted, reset-safe REPL prompt.
func RenderPrompt(w io.Writer, scope ScopeState, invalidated bool, policy ColorPolicy) error {
	prompt := "cluster"
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
		endpoint := scope.Hostname
		if endpoint == "" {
			endpoint = scope.EndpointID
		}
		prompt += "[" + sanitizePromptPart(endpoint)
		if scope.Hostname != "" {
			prompt += "/" + sanitizePromptPart(scope.EndpointID)
		}
		label := scope.SessionName
		if label == "" {
			label = scope.ProviderSessionID
		}
		if label == "" {
			label = shortResourceID(scope.SessionID)
		}
		prompt += "/" + sanitizePromptPart(label)
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
	value = strings.ReplaceAll(value, "/", "∕")
	return clipCell(value, 36)
}

func shortResourceID(value string) string {
	if len(value) <= 12 {
		return value
	}
	return value[:12]
}
