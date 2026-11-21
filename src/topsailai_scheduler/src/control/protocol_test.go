package control

import (
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"topsailai_scheduler/runtime"
)

// TestDecodeRequestAcceptsKnownOps verifies that each documented operation
// decodes, including its optional fields.
func TestDecodeRequestAcceptsKnownOps(t *testing.T) {
	cases := map[string]string{
		"launch": `{"op":"launch","task_id":"data/work","wait":true}`,
		"status": `{"op":"status"}`,
		"stop":   `{"op":"stop","task_id":"data/work","force":true}`,
	}
	for name, line := range cases {
		t.Run(name, func(t *testing.T) {
			request, err := DecodeRequest([]byte(line))
			if err != nil {
				t.Fatalf("DecodeRequest failed: %v", err)
			}
			if request.Op != name {
				t.Errorf("expected op %q, got %q", name, request.Op)
			}
		})
	}
}

// TestDecodeRequestRejectsUnknownOp verifies that an unknown operation is
// rejected with the accepted names, so a client typo is diagnosable.
func TestDecodeRequestRejectsUnknownOp(t *testing.T) {
	_, err := DecodeRequest([]byte(`{"op":"restart"}`))
	if err == nil {
		t.Fatal("expected an unknown op to be rejected")
	}
	if !strings.Contains(err.Error(), OpLaunch) {
		t.Errorf("expected the accepted ops in the message, got %q", err.Error())
	}
}

// TestDecodeRequestRejectsMissingOp verifies that a request without an operation
// is rejected rather than silently ignored.
func TestDecodeRequestRejectsMissingOp(t *testing.T) {
	if _, err := DecodeRequest([]byte(`{"task_id":"x"}`)); err == nil {
		t.Fatal("expected a missing op to be rejected")
	}
}

// TestDecodeRequestRejectsMalformedJSON verifies that unparseable input is
// rejected instead of producing a zero request.
func TestDecodeRequestRejectsMalformedJSON(t *testing.T) {
	if _, err := DecodeRequest([]byte(`{"op":`)); err == nil {
		t.Fatal("expected malformed JSON to be rejected")
	}
}

// TestCodeForError verifies that every contract error maps to its stable wire
// code, so a client can branch on the code instead of the message.
func TestCodeForError(t *testing.T) {
	cases := map[string]struct {
		err  error
		want string
	}{
		"nil":           {nil, ""},
		"not found":     {runtime.ErrTaskNotFound, CodeTaskNotFound},
		"not running":   {runtime.ErrTaskNotRunning, CodeTaskNotRunning},
		"disabled":      {runtime.ErrTaskDisabled, CodeTaskDisabled},
		"shutting down": {runtime.ErrShuttingDown, CodeShuttingDown},
		"other":         {errors.New("boom"), CodeInternal},
		"wrapped error": {errors.Join(runtime.ErrTaskNotFound), CodeTaskNotFound},
	}
	for name, testCase := range cases {
		t.Run(name, func(t *testing.T) {
			if got := CodeForError(testCase.err); got != testCase.want {
				t.Errorf("expected %q, got %q", testCase.want, got)
			}
		})
	}
}

// TestNewSuccessEncodesData verifies that a successful response carries the
// encoded payload and no error fields.
func TestNewSuccessEncodesData(t *testing.T) {
	response, err := NewSuccess(runtime.StopResult{TaskID: "data/work", PID: 42, Forced: true})
	if err != nil {
		t.Fatalf("NewSuccess failed: %v", err)
	}
	if !response.OK {
		t.Error("expected OK")
	}
	if response.Code != "" || response.Error != "" {
		t.Errorf("expected no error fields, got %q and %q", response.Code, response.Error)
	}

	var decoded runtime.StopResult
	if err := json.Unmarshal(response.Data, &decoded); err != nil {
		t.Fatalf("decode data: %v", err)
	}
	if decoded.PID != 42 || !decoded.Forced {
		t.Errorf("unexpected decoded result %+v", decoded)
	}
}

// TestNewFailureCarriesCodeAndMessage verifies that a failure keeps both the
// stable code and the human-readable message.
func TestNewFailureCarriesCodeAndMessage(t *testing.T) {
	response := NewFailure(CodeTaskNotFound, errors.New("no such task"))
	if response.OK {
		t.Error("expected OK to be false")
	}
	if response.Code != CodeTaskNotFound {
		t.Errorf("expected code %q, got %q", CodeTaskNotFound, response.Code)
	}
	if response.Error != "no such task" {
		t.Errorf("unexpected message %q", response.Error)
	}
	if len(response.Data) != 0 {
		t.Errorf("expected no data on failure, got %s", response.Data)
	}
}

// TestNewFailureWithoutError verifies that a nil error still produces a usable
// response instead of panicking.
func TestNewFailureWithoutError(t *testing.T) {
	response := NewFailure(CodeInternal, nil)
	if response.OK || response.Code != CodeInternal {
		t.Errorf("unexpected response %+v", response)
	}
	if response.Error != "" {
		t.Errorf("expected an empty message, got %q", response.Error)
	}
}
