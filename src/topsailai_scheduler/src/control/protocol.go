// Package control exposes the runtime control contract over a local socket.
//
// The daemon implements runtime.Controller. This package only translates a
// request into a call on that interface and encodes the reply, so a new
// transport such as HTTP can be added without touching scheduling logic and
// every transport behaves identically.
//
// The wire format is one JSON object per line in each direction. A line is used
// rather than a length prefix because it is readable with ordinary tools and
// needs no framing code on either side.
package control

import (
	"encoding/json"
	"errors"
	"fmt"

	"topsailai_scheduler/runtime"
)

// Operation names accepted by the server.
const (
	// OpLaunch starts one run of a task now.
	OpLaunch = "launch"
	// OpStatus reports the current state of every task.
	OpStatus = "status"
	// OpStop actively stops a running task.
	OpStop = "stop"
)

// Error codes returned to a client. They are stable strings so a caller can
// branch on the code instead of matching message text.
const (
	// CodeInvalidRequest means the request could not be decoded.
	CodeInvalidRequest = "invalid_request"
	// CodeTaskNotFound means no task with the requested id is known.
	CodeTaskNotFound = "task_not_found"
	// CodeTaskNotRunning means the task has no in-flight run to stop.
	CodeTaskNotRunning = "task_not_running"
	// CodeTaskDisabled means the task exists but is disabled.
	CodeTaskDisabled = "task_disabled"
	// CodeShuttingDown means the scheduler is stopping.
	CodeShuttingDown = "shutting_down"
	// CodeInternal means the daemon failed for another reason.
	CodeInternal = "internal"
)

// Request is one control request.
type Request struct {
	// Op is the operation to perform.
	Op string `json:"op"`
	// TaskID is the task the operation applies to.
	TaskID string `json:"task_id,omitempty"`
	// Wait blocks a launch until the run finishes.
	Wait bool `json:"wait,omitempty"`
	// Force asks the provider for an immediate stop instead of a graceful one.
	Force bool `json:"force,omitempty"`
}

// Response is one control reply.
//
// Data carries the operation result and is omitted on failure, so a client can
// decode it only after checking OK.
type Response struct {
	// OK reports whether the operation succeeded.
	OK bool `json:"ok"`
	// Code is the stable error code, empty on success.
	Code string `json:"code,omitempty"`
	// Error is the human-readable error, empty on success.
	Error string `json:"error,omitempty"`
	// Data is the operation result, encoded per operation.
	Data json.RawMessage `json:"data,omitempty"`
}

// NewSuccess builds a successful response carrying data.
func NewSuccess(data any) (Response, error) {
	encoded, err := json.Marshal(data)
	if err != nil {
		return Response{}, fmt.Errorf("encode response data: %w", err)
	}
	return Response{OK: true, Data: encoded}, nil
}

// NewFailure builds a failed response.
func NewFailure(code string, err error) Response {
	message := ""
	if err != nil {
		message = err.Error()
	}
	return Response{OK: false, Code: code, Error: message}
}

// CodeForError maps a contract error to its stable wire code.
//
// The mapping lives here, next to the codes, so every transport reports the
// same code for the same condition.
func CodeForError(err error) string {
	switch {
	case err == nil:
		return ""
	case errors.Is(err, runtime.ErrTaskNotFound):
		return CodeTaskNotFound
	case errors.Is(err, runtime.ErrTaskNotRunning):
		return CodeTaskNotRunning
	case errors.Is(err, runtime.ErrTaskDisabled):
		return CodeTaskDisabled
	case errors.Is(err, runtime.ErrShuttingDown):
		return CodeShuttingDown
	default:
		return CodeInternal
	}
}

// DecodeRequest parses one request line.
func DecodeRequest(line []byte) (Request, error) {
	var request Request
	if err := json.Unmarshal(line, &request); err != nil {
		return Request{}, fmt.Errorf("decode request: %w", err)
	}
	switch request.Op {
	case OpLaunch, OpStatus, OpStop:
		return request, nil
	case "":
		return Request{}, fmt.Errorf("request has no op: want %s, %s or %s", OpLaunch, OpStatus, OpStop)
	default:
		return Request{}, fmt.Errorf("unknown op %q: want %s, %s or %s",
			request.Op, OpLaunch, OpStatus, OpStop)
	}
}
