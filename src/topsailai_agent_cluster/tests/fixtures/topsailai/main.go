// Command topsailai-fixture emulates the provider CLI surface the adapter reads.
//
// It answers only the subcommands the adapter invokes, so an integration test can
// exercise discovery, control and command execution without a real provider
// installation. It is built beside topsailai_session_info because the adapter
// resolves that entry point as a sibling of the configured executable.
package main

import (
	"encoding/json"
	"fmt"
	"os"
)

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		fail("missing subcommand")
	}
	switch args[0] {
	case "workspace":
		emit(map[string]any{
			"items": []map[string]any{{
				"session_id":         "fixture-session",
				"session_name":       "fixture",
				"process_generation": "fixture-generation",
				"state":              "idle",
				"agent_id":           "fixture-agent",
			}},
			"total": 1,
		})
	case "project":
		emit([]map[string]any{})
	case "runtime":
		control(args[1:])
	default:
		fail("unsupported subcommand " + args[0])
	}
}

// control answers one runtime control invocation with a correlated document.
func control(args []string) {
	if len(args) == 0 || args[0] != "control" {
		fail("unsupported runtime subcommand")
	}
	action, session := "", ""
	for index := 1; index < len(args); index++ {
		switch args[index] {
		case "-s":
			if index+1 < len(args) {
				session = args[index+1]
				index++
			}
		case "-a", "--json":
			if args[index] == "-a" {
				index++
			}
		default:
			if action == "" {
				action = args[index]
			}
		}
	}
	if action == "" {
		fail("missing control action")
	}
	emit(map[string]any{
		"ok":               true,
		"action":           action,
		"session_id":       session,
		"delivery_state":   "acknowledged",
		"effect_certainty": "acknowledged",
	})
}

// emit writes one JSON document to stdout.
func emit(document any) {
	if err := json.NewEncoder(os.Stdout).Encode(document); err != nil {
		fail(err.Error())
	}
}

// fail reports an unsupported invocation on stderr and exits non-zero.
func fail(message string) {
	fmt.Fprintln(os.Stderr, message)
	os.Exit(2)
}
