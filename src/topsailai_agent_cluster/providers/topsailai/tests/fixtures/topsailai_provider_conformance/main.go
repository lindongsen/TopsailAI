// Command topsailai_provider_conformance emulates the TopsailAI business CLI for
// Provider CLI conformance runs.
//
// It exists because the Provider CLI is a separate executable that reaches the
// provider through a business CLI, and the conformance suite must drive the real
// Provider binary without a real TopsailAI installation. The document shapes here
// mirror what the Provider parses, including the workspace `filename` field the
// Provider needs to derive a stable provider resource key.
//
// This fixture lives in the Provider workspace because it stands in for the
// Provider's own dependency, the TopsailAI business CLI. It imports only the
// standard library, so it needs no Cluster package and cannot drift with the
// Cluster's internal types. The Cluster's own test doubles stay under the
// Cluster's tests/ tree, because they assert the Cluster contract rather than
// this Provider's behaviour.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	fixtureSessionID     = "fixture-session"
	fixtureRowKey        = "fixture.session.stdout"
	fixtureGeneration    = "fixture-generation"
	fixturePID           = 4242
	fixtureFollowRecords = 3
)

func main() {
	args := os.Args[1:]
	if len(args) == 0 {
		fail("missing subcommand")
	}
	switch args[0] {
	case "workspace":
		workspace(args[1:])
	case "project":
		project(args[1:])
	case "session":
		session(args[1:])
	case "runtime":
		runtime(args[1:])
	case "models":
		models(args[1:])
	default:
		fail("unsupported subcommand " + args[0])
	}
}

// workspace answers the inventory read the Provider uses for discovery,
// inspection and target authority.
//
// The row carries `filename` because the Provider derives its provider resource
// key from the session identity plus that row key. A row without it is rejected
// with "workspace row requires session_id and filename", which is a fixture gap
// rather than a Provider defect.
func workspace(args []string) {
	if len(args) == 0 || args[0] != "list" {
		fail("unsupported workspace subcommand")
	}
	emit(map[string]any{
		"items": []map[string]any{{
			"session_id":         fixtureSessionID,
			"filename":           fixtureRowKey,
			"session_name":       "fixture",
			"process_generation": fixtureGeneration,
			"state":              "idle",
			"agent_id":           "fixture-agent",
			"pid":                fixturePID,
			"project_workspace":  "/fixture",
		}},
		"total": 1,
	})
}

// project answers the two project reads the Provider performs.
func project(args []string) {
	if len(args) == 0 {
		fail("unsupported project subcommand")
	}
	switch args[0] {
	case "list":
		emit([]map[string]any{})
	case "list_sessions":
		// One row, because the history query is only meaningful when it has a
		// row to convert. The row carries `create_time`, which is the field the
		// Provider reads for `created_at_ms`; an empty array here would let a
		// stale field name pass conformance while silently zeroing the value.
		emit([]map[string]any{{
			"session_id":        fixtureSessionID,
			"session_name":      "fixture",
			"project_workspace": "/fixture",
			"task":              "fixture task",
			"status":            "Idle",
			"no":                1,
			"create_time":       "2026-11-09T10:00:00",
			"modified_time_raw": "2026-11-09T10:05:00",
		}})
	default:
		fail("unsupported project subcommand " + args[0])
	}
}

// session answers the existence pre-check and the conversation read.
func session(args []string) {
	if len(args) == 0 {
		fail("unsupported session subcommand")
	}
	switch args[0] {
	case "info":
		emit(map[string]any{
			"session_id":        fixtureSessionID,
			"session_name":      "fixture",
			"project_workspace": "/fixture",
		})
	case "history":
		emit(map[string]any{
			"ok":            true,
			"exit_code":     0,
			"action":        "history",
			"session_id":    fixtureSessionID,
			"message_count": 1,
			"messages": []map[string]any{{
				"role":        "user",
				"content":     "fixture message body",
				"create_time": "2026-11-09 10:00:00.000",
			}},
			"error_code": nil,
			"message":    nil,
		})
	default:
		fail("unsupported session subcommand " + args[0])
	}
}

// models answers the model registry read.
func models(args []string) {
	if len(args) == 0 || args[0] != "list" {
		fail("unsupported models subcommand")
	}
	emit([]map[string]any{{
		"name":     "fixture-model-a",
		"protocol": "openai-compatible",
	}})
}

// runtime dispatches the runtime subcommands the Provider invokes.
func runtime(args []string) {
	if len(args) == 0 {
		fail("unsupported runtime subcommand")
	}
	switch args[0] {
	case "logs":
		logs(args[1:])
	case "send":
		delivery(args[1:], "pipe_written")
	case "btw":
		delivery(args[1:], "injection_queued")
	case "control":
		control(args[1:])
	default:
		fail("unsupported runtime subcommand " + args[0])
	}
}

// logs answers one snapshot or one follow.
//
// A follow answers plain text records and exits after the last record, because a
// conformance run only needs the started/record/end lifecycle. The BDD fixture
// keeps its process alive instead, which is a different requirement.
func logs(args []string) {
	lines, follow := 20, false
	for index := 0; index < len(args); index++ {
		switch args[index] {
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
	if follow {
		count := lines
		if count > fixtureFollowRecords {
			count = fixtureFollowRecords
		}
		for index := 1; index <= count; index++ {
			fmt.Printf("fixture follow record %d\n", index)
			time.Sleep(20 * time.Millisecond)
		}
		return
	}
	emit(map[string]any{
		"ok": true,
		"response": map[string]any{
			"lines": []string{"fixture output for " + fixtureSessionID},
		},
	})
}

// delivery answers one message submission with the provider delivery state.
func delivery(args []string, state string) {
	emit(map[string]any{
		"ok":             true,
		"action":         "send",
		"session_id":     fixtureSessionID,
		"delivery_state": state,
		"request_id":     "fixture-request",
	})
}

// control answers one control invocation with a correlated document.
//
// A `call_instruction` invocation is answered in the provider's own nested
// envelope, because that is the shape the Provider parses for a registered
// instruction: the report is a JSON string inside `response.result`, not a flat
// document. Only `agent.tokens` is answered with a report; every other
// instruction keeps the flat document, which the Provider reads as "the
// observation was unavailable". That distinction is deliberate: answering
// `agent.llm` with a report would change the current-model column that the
// catalog read reports, and this fixture exists to prove the wire contract, not
// to invent provider state.
func control(args []string) {
	action := ""
	payload := ""
	for index := 0; index < len(args); index++ {
		switch args[index] {
		case "-s":
			index++
		case "-a":
			if index+1 < len(args) {
				payload = args[index+1]
			}
			index++
		case "--json":
			continue
		default:
			if action == "" && !strings.HasPrefix(args[index], "-") {
				action = args[index]
			}
		}
	}
	if action == "" {
		fail("missing control action")
	}
	if action == "call_instruction" {
		if report, ok := instructionReport(payload); ok {
			emit(map[string]any{
				"ok": true,
				"response": map[string]any{
					"status": "ok",
					"result": report,
				},
			})
			return
		}
	}
	emit(map[string]any{
		"ok":             true,
		"action":         action,
		"session_id":     fixtureSessionID,
		"delivery_state": "control_acknowledged",
		"request_id":     "fixture-request",
	})
}

// instructionReport returns the report document for one registered instruction.
//
// The counts are unequal so the document cannot be mistaken for a symmetric
// one, but conformance only decodes this document and never asserts the two
// values. The order of the two positions is proven by the Provider's own unit
// tests and by the adapter mapping tests, not here. This fixture exists to prove
// that the wire shape is answerable at all, which is the part conformance owns.
func instructionReport(payload string) (string, bool) {
	var request struct {
		Instruction string `json:"instruction"`
	}
	if err := json.Unmarshal([]byte(payload), &request); err != nil {
		return "", false
	}
	if request.Instruction != "agent.tokens" {
		return "", false
	}
	report, err := json.Marshal(map[string]any{
		"ok":         true,
		"user2agent": map[string]any{"messages": 7},
		"agent2llm":  map[string]any{"messages": 3},
	})
	if err != nil {
		return "", false
	}
	return string(report), true
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
