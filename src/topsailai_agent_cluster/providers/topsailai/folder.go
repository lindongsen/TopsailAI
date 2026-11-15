package main

import (
	"fmt"
	"strings"
	"unicode"
)

// validateFolder rejects a project path the Cluster would refuse.
//
// The Cluster validates an operator-supplied folder with protocol.ValidateFolder
// before it sends a launch request. This executable is an independent module, so it
// cannot import that package, and the same rule is therefore stated here: an omitted
// folder is accepted, a folder with leading or trailing whitespace is refused, and a
// folder containing a control character is refused.
//
// The rule is repeated rather than relaxed because the provider is the last place
// that sees the value before it reaches the provider CLI. Accepting a path the
// Cluster rejects would make the two sides disagree about which projects are
// launchable, and a control character in a path is the shape that corrupts a
// terminal or a log line downstream.
func validateFolder(folder string) error {
	if folder == "" {
		return nil
	}
	if strings.TrimSpace(folder) != folder {
		return fmt.Errorf("folder must not have leading or trailing whitespace")
	}
	for _, character := range folder {
		if unicode.IsControl(character) {
			return fmt.Errorf("folder must not contain control characters")
		}
	}
	return nil
}
