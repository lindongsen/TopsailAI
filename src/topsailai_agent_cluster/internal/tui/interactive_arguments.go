package tui

import (
	"fmt"
	"strings"
	"unicode"
)

// splitInteractiveArguments groups quoted values without expanding shell syntax.
// Backslashes remain literal so Windows paths do not require shell escaping.
func splitInteractiveArguments(text string) ([]string, error) {
	var args []string
	var word strings.Builder
	var quote rune
	started := false
	for _, char := range text {
		if quote != 0 {
			if char == quote {
				quote = 0
			} else {
				word.WriteRune(char)
			}
			continue
		}
		if char == '\'' || char == '"' {
			quote = char
			started = true
			continue
		}
		if unicode.IsSpace(char) {
			if started {
				args = append(args, word.String())
				word.Reset()
				started = false
			}
			continue
		}
		started = true
		word.WriteRune(char)
	}
	if quote != 0 {
		return nil, fmt.Errorf("unterminated quote in command arguments")
	}
	if started {
		args = append(args, word.String())
	}
	return args, nil
}
