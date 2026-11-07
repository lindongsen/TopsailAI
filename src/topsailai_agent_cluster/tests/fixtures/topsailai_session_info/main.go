// Command topsailai-session-info-fixture emulates the provider's single-session
// inspection entry point.
//
// The adapter resolves this executable as a sibling of the configured provider
// executable and reads project_workspace and pwd from its JSON document. The
// directory is supplied through AGENT_CLUSTER_TEST_SESSION_DIR so an integration
// test can point a session at a temporary directory it owns.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		fail("missing session identifier")
	}
	sessionID := args[0]
	directory := os.Getenv("AGENT_CLUSTER_TEST_SESSION_DIR")
	if directory == "" {
		executable, err := os.Executable()
		if err != nil {
			fail(err.Error())
		}
		directory = filepath.Dir(executable)
	}
	document := map[string]any{
		"session_id":        sessionID,
		"project_workspace": directory,
		"pwd":               directory,
	}
	if err := json.NewEncoder(os.Stdout).Encode(document); err != nil {
		fail(err.Error())
	}
}

// fail reports an unsupported invocation on stderr and exits non-zero.
func fail(message string) {
	fmt.Fprintln(os.Stderr, message)
	os.Exit(2)
}
