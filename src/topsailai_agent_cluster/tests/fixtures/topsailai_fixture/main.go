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
	"strconv"
	"time"
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
				"pid":                4242,
			}},
			"total": 1,
		})
	case "project":
		emit([]map[string]any{})
	case "runtime":
		runtime(args[1:])
	default:
		fail("unsupported subcommand " + args[0])
	}
}

// runtime dispatches the runtime subcommands the adapter invokes.
func runtime(args []string) {
	if len(args) == 0 {
		fail("unsupported runtime subcommand")
	}
	if args[0] == "logs" {
		logs(args[1:])
		return
	}
	control(args)
}

// logs answers one runtime logs invocation. The adapter rejects --json together
// with --follow, so a follow answers plain text records and a snapshot answers
// the JSON envelope the adapter decodes.
func logs(args []string) {
	session, lines, follow := "", 20, false
	for index := 0; index < len(args); index++ {
		switch args[index] {
		case "-s":
			if index+1 < len(args) {
				session = args[index+1]
				index++
			}
		case "-n":
			if index+1 < len(args) {
				if parsed, err := strconv.Atoi(args[index+1]); err == nil && parsed > 0 {
					lines = parsed
				}
				index++
			}
		case "--follow":
			follow = true
		}
	}
	if session == "" {
		fail("missing session selector")
	}
	if follow {
		followRecords(session, lines)
		return
	}
	emit(map[string]any{
		"ok": true,
		"response": map[string]any{
			"lines": []string{"fixture output for " + session},
		},
	})
}

// followRecords writes complete records one at a time and then stays alive.
//
// The records are written incrementally so a test can observe a live stream
// instead of one burst at exit, and the process deliberately outlives the last
// record so a stream that ends on its own can never be mistaken for a stream the
// operator stopped. The lifetime is capped so a failed test cannot leave an
// orphan process behind.
func followRecords(session string, lines int) {
	if lines > 5 {
		lines = 5
	}
	for index := 1; index <= lines; index++ {
		fmt.Printf("fixture follow %s record %d\n", session, index)
		time.Sleep(150 * time.Millisecond)
	}
	time.Sleep(30 * time.Second)
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
	// The provider reports control delivery as control_acknowledged, which the
	// adapter maps to an acknowledged submitted boundary. Emitting a bare
	// "acknowledged" would fall through the adapter's switch to unknown, so the
	// fixture would silently disagree with the contract it stands in for.
	emit(map[string]any{
		"ok":             true,
		"action":         action,
		"session_id":     session,
		"delivery_state": "control_acknowledged",
		"request_id":     "fixture-request",
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
