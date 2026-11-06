package tui

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func runInputScenario(t *testing.T, stub InteractiveAPI, input string, limit int) (string, string) {
	t.Helper()
	var output, errorsOut strings.Builder
	if err := RunInteractive(context.Background(), stub, strings.NewReader(input), &output, &errorsOut, InteractiveOptions{LineLimit: limit, WaitTimeoutMS: 100}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	return output.String(), errorsOut.String()
}

func inputStub() *interactiveStub {
	return &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
	}
}

func TestReadLineBoundAndRecovery(t *testing.T) {
	stub := inputStub()
	input := strings.Repeat("x", 1<<20) + "\nhelp\nquit\n"
	output, errorsOut := runInputScenario(t, stub, input, 8192)
	wantError := "error: input line exceeds the maximum length\nusage: interactive command\nnext: Shorten the input line and retry.\n"
	if got, want := errorsOut, wantError; got != want {
		t.Fatalf("errors=%q want=%q", got, want)
	}
	if !strings.Contains(output, "Current scope:") || !strings.Contains(output, "list [endpoint]") {
		t.Fatalf("REPL did not continue after oversized input: %q", output)
	}
	if stub.admit != 0 {
		t.Fatalf("oversized input admitted %d commands", stub.admit)
	}
}

func TestSendPayloadObjectAndBytes(t *testing.T) {
	cases := []struct {
		name    string
		command string
		wantErr string
	}{
		{name: "malformed object", command: "send {", wantErr: "error: payload must be a JSON object or plain text\n"},
		// A bare send enters multi-line mode, so an immediately terminated block
		// is the empty-payload case and must still admit nothing.
		{name: "empty block", command: "send\nEOF", wantErr: "error: payload must not be empty\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := inputStub()
			input := fmt.Sprintf("cd endpoint-1/session-1\n%s\nquit\n", testCase.command)
			_, errorsOut := runInputScenario(t, stub, input, 8192)
			assertActionableError(t, errorsOut, strings.TrimSuffix(testCase.wantErr, "\n"))
			lines := strings.Split(strings.TrimSuffix(errorsOut, "\n"), "\n")
			if lines[1] != "usage: send [text]" {
				t.Fatalf("errors=%q want send usage", errorsOut)
			}
			if stub.admit != 0 {
				t.Fatalf("command %q admitted %d commands", testCase.command, stub.admit)
			}
		})
	}
}

func TestSendPayloadLengthRejectsBeforeAdmission(t *testing.T) {
	stub := inputStub()
	payload := `{"text":"` + strings.Repeat("x", 128) + `"}`
	var output, errorsOut strings.Builder
	state := interactiveState{}
	state.reset("endpoint-1", "session-1", "generation-1")
	err := interactiveSend(context.Background(), stub, &state, payload, make(chan lineReadResult), &output, &output, InteractiveOptions{LineLimit: 64})
	if err == nil || err.Error() != "payload exceeds the maximum length" {
		t.Fatalf("error=%v want payload length rejection", err)
	}
	if errorsOut.Len() != 0 {
		t.Fatalf("unexpected diagnostics=%q", errorsOut.String())
	}
	if stub.admit != 0 {
		t.Fatalf("oversized payload admitted %d commands", stub.admit)
	}
}

func TestConfirmationEOFNoAdmission(t *testing.T) {
	stub := inputStub()
	_, errorsOut := runInputScenario(t, stub, "cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\ny", 8192)
	assertActionableError(t, errorsOut, "error: confirmation requires a complete line")
	if stub.admit != 0 {
		t.Fatalf("partial confirmation admitted %d commands", stub.admit)
	}
}

func TestConfirmationAcceptedOnlyByCompleteLine(t *testing.T) {
	cases := []struct {
		name    string
		answer  string
		admit   int
		wantErr string
	}{
		{name: "y", answer: "y\n", admit: 1},
		{name: "yes", answer: "yes\n", admit: 1},
		{name: "no", answer: "n\n", admit: 0},
		{name: "empty", answer: "\n", admit: 0},
		{name: "partial uppercase eof", answer: "Y", admit: 0, wantErr: "error: confirmation requires a complete line\n"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := inputStub()
			input := "cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\n" + testCase.answer
			output, errorsOut := runInputScenario(t, stub, input, 8192)
			if stub.admit != testCase.admit {
				t.Fatalf("admissions=%d want=%d output=%q errors=%q", stub.admit, testCase.admit, output, errorsOut)
			}
			if testCase.wantErr != "" {
				assertActionableError(t, errorsOut, strings.TrimSuffix(testCase.wantErr, "\n"))
			} else if errorsOut != "" {
				t.Fatalf("unexpected diagnostics=%q", errorsOut)
			}
		})
	}
}

func TestConfirmationRevalidatesGeneration(t *testing.T) {
	stub := inputStub()
	stub.changeAfter = 3
	_, errorsOut := runInputScenario(t, stub, "cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n", 8192)
	if stub.admit != 0 {
		t.Fatalf("generation change admitted %d commands", stub.admit)
	}
	if !strings.Contains(errorsOut, "selected session generation changed; use the session again") {
		t.Fatalf("missing generation error: %q", errorsOut)
	}
}

type inputCapabilitySequenceStub struct {
	interactiveStub
	revisions []string
	calls     int
}

func (s *inputCapabilitySequenceStub) GetCapabilities(context.Context, string) (protocol.CapabilityDescriptor, error) {
	index := s.calls
	if index >= len(s.revisions) {
		index = len(s.revisions) - 1
	}
	s.calls++
	return protocol.CapabilityDescriptor{Revision: s.revisions[index], Capabilities: []protocol.Capability{{Name: protocol.OperationMessageSend}}}, nil
}

func TestConfirmationRevalidatesCapabilityRevision(t *testing.T) {
	stub := &inputCapabilitySequenceStub{
		interactiveStub: *inputStub(),
		revisions:       []string{"r1", "r2"},
	}
	_, errorsOut := runInputScenario(t, stub, "cd endpoint-1/session-1\nsend {\"text\":\"hi\"}\ny\nquit\n", 8192)
	if stub.admit != 0 {
		t.Fatalf("capability change admitted %d commands", stub.admit)
	}
	assertActionableError(t, errorsOut, "error: capability changed after confirmation; send cancelled")
}

func TestInteractiveRejectsJSONOptions(t *testing.T) {
	for _, command := range []string{"list --json", "list -json", "show --json", "show -unknown"} {
		stub := inputStub()
		_, errorsOut := runInputScenario(t, stub, command+"\nquit\n", 8192)
		if !strings.Contains(errorsOut, "available only in non-interactive mode") || !strings.Contains(errorsOut, "JSON output is available only with the standalone command") {
			t.Fatalf("command %q errors=%q", command, errorsOut)
		}
	}
}

// TestMessagePayloadAcceptsPlainTextAndJSONObject pins the interactive message contract.
func TestMessagePayloadAcceptsPlainTextAndJSONObject(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want string
	}{
		{"plain", "hello world", `{"text":"hello world"}`},
		{"plain-with-quotes", `say "hi"`, `{"text":"say \"hi\""}`},
		{"plain-leading-space", " padded", `{"text":" padded"}`},
		{"json-object", `{"text":"hello"}`, `{"text":"hello"}`},
		{"json-object-extra-field", `{"text":"hi","meta":1}`, `{"text":"hi","meta":1}`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := MessagePayload(tc.in)
			if err != nil {
				t.Fatalf("MessagePayload(%q) error=%v", tc.in, err)
			}
			if string(got) != tc.want {
				t.Fatalf("MessagePayload(%q)=%s want %s", tc.in, got, tc.want)
			}
		})
	}
}

// TestMessagePayloadRejectsMalformedJSONObject keeps brace input strict.
func TestMessagePayloadRejectsMalformedJSONObject(t *testing.T) {
	for _, in := range []string{"{", `{"text":}`, `{"a":1`, "{not json}"} {
		if _, err := MessagePayload(in); err == nil {
			t.Fatalf("MessagePayload(%q) accepted malformed input", in)
		}
	}
}
