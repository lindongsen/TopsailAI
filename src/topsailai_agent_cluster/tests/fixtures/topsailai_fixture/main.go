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
	"strings"
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
	case "session":
		session(args[1:])
	case "runtime":
		runtime(args[1:])
	case "models":
		// The adapter reads `models list --json` and decodes a bare array of
		// registry entries. Two entries are enough to prove row numbering and
		// selection, and neither carries `enabled`, because the provider omits
		// that field for an enabled entry.
		recordInvocation(args)
		emit([]map[string]any{
			{"id": "fixture-model-a", "name": "fixture-model-a", "protocol": "openai-compatible"},
			{"id": "fixture-model-b", "name": "fixture-model-b", "protocol": "openai-compatible"},
		})
	default:
		fail("unsupported subcommand " + args[0])
	}
}

// session answers the two persisted-data reads the adapter uses to fetch a
// conversation: an existence pre-check and the history read itself.
//
// Both are answered from configuration rather than from a live process, because
// the real provider reads persisted messages. That is the property the adapter
// depends on, so a fixture that required a running session would prove nothing
// about the case the command exists for.
func session(args []string) {
	if len(args) == 0 {
		fail("unsupported session subcommand")
	}
	switch args[0] {
	case "info":
		sessionInfo(args[1:])
	case "history":
		sessionHistory(args[1:])
	default:
		fail("unsupported session subcommand " + args[0])
	}
}

// sessionInfo answers one existence pre-check.
//
// A missing session reports session_not_found on stdout and exits non-zero, and a
// configured storage fault reports lookup_failed the same way. The two are
// deliberately distinct: the adapter must never present a storage fault as a
// deleted session, so the fixture has to be able to produce both.
func sessionInfo(args []string) {
	sessionID := firstPositional(args)
	if sessionID == "" {
		fail("missing session identifier")
	}
	if failure := os.Getenv("AGENT_CLUSTER_TEST_MESSAGES_FAILURE"); failure != "" {
		emit(map[string]any{"session_id": sessionID, "error_code": failure, "message": "fixture storage failure"})
		os.Exit(1)
	}
	if !fixtureSessionExists(sessionID) {
		emit(map[string]any{"session_id": sessionID, "error_code": "session_not_found", "message": "Session not found: " + sessionID})
		os.Exit(1)
	}
	emit(map[string]any{"session_id": sessionID, "session_name": "fixture", "project_workspace": "/fixture"})
}

// sessionHistory answers one conversation read.
//
// The document mirrors the provider envelope, including the successful empty
// document a missing session produces. That empty success is exactly why the
// adapter runs the existence pre-check first, so the fixture reproduces it rather
// than hiding it.
func sessionHistory(args []string) {
	sessionID := firstPositional(args)
	if sessionID == "" {
		fail("missing session identifier")
	}
	maxChars := 0
	for index := 0; index < len(args); index++ {
		if args[index] == "--max-chars" && index+1 < len(args) {
			if parsed, err := strconv.Atoi(args[index+1]); err == nil && parsed > 0 {
				maxChars = parsed
			}
			index++
		}
	}
	if !fixtureSessionExists(sessionID) {
		emit(map[string]any{"ok": true, "exit_code": 0, "action": "history", "session_id": sessionID, "message_count": 0, "messages": []map[string]any{}, "error_code": nil, "message": nil})
		return
	}
	count := 2
	if raw := os.Getenv("AGENT_CLUSTER_TEST_MESSAGES_COUNT"); raw != "" {
		if parsed, err := strconv.Atoi(raw); err == nil && parsed >= 0 {
			count = parsed
		}
	}
	body := "fixture message body"
	if raw := os.Getenv("AGENT_CLUSTER_TEST_MESSAGES_BODY"); raw != "" {
		body = raw
	}
	messages := make([]map[string]any, 0, count)
	for index := 0; index < count; index++ {
		role := "user"
		if index%2 == 1 {
			role = "assistant"
		}
		messages = append(messages, map[string]any{
			"role":        role,
			"content":     truncateFixtureContent(body, maxChars),
			"create_time": "2026-11-09 10:00:0" + strconv.Itoa(index%10) + ".000",
		})
	}
	emit(map[string]any{"ok": true, "exit_code": 0, "action": "history", "session_id": sessionID, "message_count": count, "messages": messages, "error_code": nil, "message": nil})
}

// fixtureSessionExists reports whether the fixture treats a session as recorded.
//
// The default set includes a session the workspace document never lists, so a test
// can read a conversation for a session that is absent from the inventory. That is
// the stopped-session case the command exists for.
func fixtureSessionExists(sessionID string) bool {
	configured := os.Getenv("AGENT_CLUSTER_TEST_MESSAGES_SESSIONS")
	if configured == "" {
		configured = "fixture-session,stopped-session"
	}
	for _, candidate := range strings.Split(configured, ",") {
		if strings.TrimSpace(candidate) == sessionID {
			return true
		}
	}
	return false
}

// firstPositional returns the first argument that is not a flag or a flag value.
func firstPositional(args []string) string {
	for index := 0; index < len(args); index++ {
		switch args[index] {
		case "--json":
			continue
		case "--max-chars":
			index++
			continue
		}
		if !strings.HasPrefix(args[index], "-") {
			return args[index]
		}
	}
	return ""
}

// truncateFixtureContent applies the provider's per-message character bound.
//
// The provider shortens an oversized body and marks it with an ellipsis, so the
// fixture does the same. A fixture that ignored the bound would let the adapter's
// forwarding of --max-chars go unproven.
func truncateFixtureContent(content string, maxChars int) string {
	if maxChars <= 0 {
		return content
	}
	runes := []rune(content)
	if len(runes) <= maxChars {
		return content
	}
	return string(runes[:maxChars]) + "..."
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
	action, session, payload := "", "", ""
	for index := 1; index < len(args); index++ {
		switch args[index] {
		case "-s":
			if index+1 < len(args) {
				session = args[index+1]
				index++
			}
		case "-a":
			if index+1 < len(args) {
				payload = args[index+1]
				index++
			}
		case "--json":
		default:
			if action == "" {
				action = args[index]
			}
		}
	}
	if action == "" {
		fail("missing control action")
	}
	// Record the argv before answering, so a scenario can prove which payload
	// reached the provider. The payload is the only place a resolved profile
	// name differs from a row number, and the parser above discards it.
	recordInvocation(args)
	// The registered-instruction surface answers with the instruction's own
	// result, which is what the adapter reads to report the current model. The
	// answer is a registry name so it maps onto a rendered row; an unlisted name
	// would prove only the degrade path.
	if action == "call_instruction" {
		emit(map[string]any{
			"ok":             true,
			"action":         action,
			"session_id":     session,
			"delivery_state": "control_acknowledged",
			"request_id":     "fixture-request",
			"response": map[string]any{
				"request_id": "fixture-request",
				"status":     "ok",
				"result":     fixtureCurrentModel(payload),
			},
		})
		return
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

// fixtureCurrentModel returns the current model for one registered instruction.
//
// Only the current-model read has an answer; every other instruction returns an
// empty result, because the fixture must not invent a value for a read it does
// not model. The name is the first registry entry, so a scenario can assert the
// CURRENT column marks exactly that row.
func fixtureCurrentModel(payload string) string {
	var request struct {
		Instruction string `json:"instruction"`
	}
	if err := json.Unmarshal([]byte(payload), &request); err != nil {
		return ""
	}
	if request.Instruction != "agent.llm" {
		return ""
	}
	return "fixture-model-a"
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

// recordInvocation appends one JSON line describing the argv the adapter invoked,
// when a test asks for it. The provider fixture already records its invocations,
// and the model write path needs the same evidence: a scenario must prove the
// resolved profile name reached the provider instead of a row number, and the
// argv is the only place that difference is observable.
func recordInvocation(args []string) {
	logPath := os.Getenv("AGENT_CLUSTER_TEST_PROVIDER_INVOCATION_LOG")
	if logPath == "" {
		return
	}
	file, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		fail(err.Error())
	}
	defer func() { _ = file.Close() }()
	if err := json.NewEncoder(file).Encode(map[string]any{"argv": args}); err != nil {
		fail(err.Error())
	}
}
