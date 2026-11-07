package protocol

import (
	"fmt"
	"strings"
	"unicode"
)

// CommandExecPayloadVersion is the payload schema version of command.exec.
const CommandExecPayloadVersion = "1"

// CommandExecMaxArgv bounds the argv array length of one command.exec request.
const CommandExecMaxArgv = 64

// CommandExecMaxTokenBytes bounds one argv token of a command.exec request.
const CommandExecMaxTokenBytes = 4096

// CommandExecRequest carries one argv array. It never carries a command string,
// because the Endpoint must not parse or split a string: doing so would
// reintroduce shell semantics that the allowlist cannot reason about.
type CommandExecRequest struct {
	Argv []string `json:"argv"`
}

// Validate rejects an argv array that cannot be matched or executed safely.
func (r CommandExecRequest) Validate() error {
	if len(r.Argv) == 0 {
		return fmt.Errorf("argv is required")
	}
	if len(r.Argv) > CommandExecMaxArgv {
		return fmt.Errorf("argv must not exceed %d tokens", CommandExecMaxArgv)
	}
	for index, token := range r.Argv {
		if token == "" {
			return fmt.Errorf("argv token %d is empty", index)
		}
		if len(token) > CommandExecMaxTokenBytes {
			return fmt.Errorf("argv token %d must not exceed %d bytes", index, CommandExecMaxTokenBytes)
		}
		for _, character := range token {
			if unicode.IsControl(character) {
				return fmt.Errorf("argv token %d must not contain control characters", index)
			}
		}
	}
	return nil
}

// CommandExecResult is one bounded snapshot of an executed command. It is not a
// stream and not a follow: the caller receives the output observed at
// ObservedAtMS together with truncation evidence.
type CommandExecResult struct {
	Argv         []string `json:"argv"`
	ExitCode     int      `json:"exit_code"`
	Stdout       string   `json:"stdout"`
	Stderr       string   `json:"stderr"`
	Truncated    bool     `json:"truncated"`
	ObservedAtMS int64    `json:"observed_at_ms"`
	ErrorCode    string   `json:"error_code,omitempty"`
}

// Describe renders the argv array for diagnostics without exposing output.
func (r CommandExecResult) Describe() string {
	return strings.Join(r.Argv, " ")
}
