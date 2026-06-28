// Package main provides ANSI color helpers for the ACS chat CLI.
package main

import (
	"fmt"
	"os"
	"strings"
)

var globalColorEnabled = true

// initColor initializes color support from CLI args and environment.
func initColor(args []string) {
	for _, a := range args {
		if a == "--no-color" {
			globalColorEnabled = false
			return
		}
	}
	if os.Getenv("NO_COLOR") != "" {
		globalColorEnabled = false
	}
}

// DisableColors disables ANSI color output.
func DisableColors() {
	globalColorEnabled = false
}

// colorize wraps text with ANSI codes if color is enabled.
func colorize(text, code string) string {
	if !globalColorEnabled {
		return text
	}
	return "\033[" + code + "m" + text + "\033[0m"
}

func red(text string) string     { return colorize(text, "31") }
func green(text string) string   { return colorize(text, "32") }
func yellow(text string) string  { return colorize(text, "33") }
func blue(text string) string    { return colorize(text, "34") }
func magenta(text string) string { return colorize(text, "35") }
func cyan(text string) string    { return colorize(text, "36") }
func dim(text string) string     { return colorize(text, "90") }
func bold(text string) string    { return colorize(text, "1") }

// stripANSI removes ANSI escape sequences from a string.
func stripANSI(s string) string {
	var b strings.Builder
	inEscape := false
	for _, r := range s {
		if inEscape {
			if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') {
				inEscape = false
			}
			continue
		}
		if r == '\033' {
			inEscape = true
			continue
		}
		b.WriteRune(r)
	}
	return b.String()
}

// getEnv returns the value of an environment variable or a default.
func getEnv(key, defaultValue string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return defaultValue
}

// getEnvInt returns the integer value of an environment variable or a default.
func getEnvInt(key string, defaultValue int) int {
	v := os.Getenv(key)
	if v == "" {
		return defaultValue
	}
	var n int
	if _, err := fmt.Sscanf(v, "%d", &n); err != nil {
		return defaultValue
	}
	return n
}
