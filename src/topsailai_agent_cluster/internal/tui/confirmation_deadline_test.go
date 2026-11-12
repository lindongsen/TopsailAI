package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// confirmationStub builds a session-scoped stub with every mutating capability enabled.
func confirmationStub() *interactiveStub {
	return &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-1"}},
		reports:   map[string]protocol.InventoryReport{"endpoint-1": testInventory()},
	}
}

// TestConfirmationReadHasNoCommandDeadline proves the human answer is not bounded by the
// command deadline: the confirmation read context must carry no deadline at all.
func TestConfirmationReadHasNoCommandDeadline(t *testing.T) {
	cases := []struct {
		name    string
		command string
		block   []string
		op      string
	}{
		{name: "stop", command: "stop", op: protocol.OperationAgentStop},
		// A bare send is the only form that still asks, so it is the form that
		// exercises the confirmation read.
		{name: "send", command: "send", block: []string{"hi", "EOF"}, op: protocol.OperationMessageSend},
		// btw is deliberately absent: it submits directly, so it never reads a
		// confirmation and cannot exercise the deadline rule under test.
		{name: "interrupt", command: `interrupt {"action":"soft_interrupt"}`, op: protocol.OperationExecutionInterrupt},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := confirmationStub()
			var out, diagnostics strings.Builder
			calls := 0
			read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
				calls++
				if calls == 1 {
					return "cd endpoint-1/session-1", false, nil
				}
				if calls == 2 {
					return testCase.command, false, nil
				}
				if blockIndex := calls - 3; blockIndex < len(testCase.block) {
					return testCase.block[blockIndex], false, nil
				}
				if calls == 3+len(testCase.block) {
					if history {
						t.Fatalf("confirmation read must not use history: prompt=%q", prompt)
					}
					if deadline, ok := ctx.Deadline(); ok {
						t.Fatalf("confirmation read inherited a command deadline: %v", deadline)
					}
					if err := ctx.Err(); err != nil {
						t.Fatalf("confirmation read context already failed: %v", err)
					}
					return "y", false, nil
				}
				return "quit", false, nil
			}
			err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read, WaitTimeoutMS: 100})
			if err != nil {
				t.Fatalf("RunInteractive: %v", err)
			}
			if len(stub.intents) != 1 || stub.intents[0].Operation != testCase.op {
				t.Fatalf("intents=%+v", stub.intents)
			}
			if diagnostics.Len() != 0 {
				t.Fatalf("unexpected diagnostics=%q", diagnostics.String())
			}
		})
	}
}

// TestConfirmationPromptFailureKeepsReplAlive proves a failed confirmation read cancels only
// the current operation and the next prompt still works.
func TestConfirmationPromptFailureKeepsReplAlive(t *testing.T) {
	stub := confirmationStub()
	var out, diagnostics strings.Builder
	calls := 0
	readFailure := errors.New("terminal read failed")
	read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
		calls++
		switch calls {
		case 1:
			return "cd endpoint-1/session-1", false, nil
		case 2:
			return "stop", false, nil
		case 3:
			return "", false, readFailure
		case 4:
			if !strings.HasSuffix(out.String(), "session[endpoint-1/-]> ") {
				t.Fatalf("REPL did not reprompt after the failed confirmation: %q", out.String())
			}
			return "help", false, nil
		default:
			return "quit", false, nil
		}
	}
	err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read, WaitTimeoutMS: 100})
	if err != nil {
		t.Fatalf("RunInteractive returned after a recoverable prompt failure: %v", err)
	}
	if stub.admit != 0 {
		t.Fatalf("failed confirmation admitted %d commands", stub.admit)
	}
	if !strings.Contains(diagnostics.String(), "terminal read failed") {
		t.Fatalf("missing diagnostic for the failed confirmation: %q", diagnostics.String())
	}
	if calls < 5 {
		t.Fatalf("REPL stopped after the failure: calls=%d", calls)
	}
}

// TestRepeatedPromptFailuresTerminateRepl bounds tolerated failures so an unusable input
// source still ends the session instead of looping forever.
func TestRepeatedPromptFailuresTerminateRepl(t *testing.T) {
	stub := confirmationStub()
	var out, diagnostics strings.Builder
	readFailure := errors.New("terminal read failed")
	calls := 0
	read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
		calls++
		switch calls {
		case 1:
			return "cd endpoint-1/session-1", false, nil
		case 2, 4, 6:
			return "stop", false, nil
		default:
			return "", false, readFailure
		}
	}
	err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read, WaitTimeoutMS: 100})
	if !errors.Is(err, readFailure) {
		t.Fatalf("err=%v want the prompt failure after the tolerance bound", err)
	}
	if calls != 7 {
		t.Fatalf("calls=%d want=7 (three consecutive confirmation failures)", calls)
	}
	if stub.admit != 0 {
		t.Fatalf("failed confirmations admitted %d commands", stub.admit)
	}
}

// TestDisambiguationPromptHasNoCommandDeadline proves the hostname conflict prompt is also a
// human answer and therefore must not inherit the command deadline.
func TestDisambiguationPromptHasNoCommandDeadline(t *testing.T) {
	stub := &interactiveStub{
		endpoints: []protocol.Endpoint{{EndpointID: "endpoint-a", Hostname: "host"}, {EndpointID: "endpoint-b", Hostname: "host"}},
		reports: map[string]protocol.InventoryReport{
			"endpoint-a": testInventory(),
			"endpoint-b": testInventory(),
		},
	}
	var out, diagnostics strings.Builder
	calls := 0
	read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
		calls++
		switch calls {
		case 1:
			return "cd host", false, nil
		case 2:
			if !strings.Contains(out.String(), "select endpoint") {
				t.Fatalf("disambiguation question was not written before the read: %q", out.String())
			}
			if history {
				t.Fatalf("disambiguation read must not use history: prompt=%q", prompt)
			}
			if deadline, ok := ctx.Deadline(); ok {
				t.Fatalf("disambiguation prompt inherited a command deadline: %v", deadline)
			}
			return "1", false, nil
		default:
			return "quit", false, nil
		}
	}
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if !strings.Contains(out.String(), "endpoint[host/endpoint-a]>") {
		t.Fatalf("disambiguation did not enter the chosen endpoint: %q", out.String())
	}
}
