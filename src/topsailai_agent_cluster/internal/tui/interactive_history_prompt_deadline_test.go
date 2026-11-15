package tui

import (
	"context"
	"errors"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestHistoryEndpointPromptHasNoCommandDeadline proves the endpoint prompt waits
// for a human without a command budget.
//
// The prompt is the one history step a person controls, so bounding it with the
// command deadline would expire while the operator is still reading the list. The
// bounded budget belongs to the provider read that follows, because only that read
// is command work.
func TestHistoryEndpointPromptHasNoCommandDeadline(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{{ProviderSessionID: "wa-past"}}, historyReport())
	var out, diagnostics strings.Builder
	calls := 0
	read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
		calls++
		switch calls {
		case 1:
			return "history", false, nil
		case 2:
			if deadline, ok := ctx.Deadline(); ok {
				t.Fatalf("history endpoint prompt inherited a command deadline: %v", deadline)
			}
			if err := ctx.Err(); err != nil {
				t.Fatalf("history endpoint prompt context already failed: %v", err)
			}
			return "1", false, nil
		}
		return "quit", false, nil
	}
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read}); err != nil {
		t.Fatalf("RunInteractive: %v", err)
	}
	if len(stub.historyCalls) != 1 || stub.historyCalls[0] != "endpoint-1" {
		t.Fatalf("history calls=%v, want [endpoint-1]", stub.historyCalls)
	}
}

// TestHistoryEndpointPromptFailureKeepsTheSessionAlive proves a failed answer
// cancels only the history command.
//
// A prompt failure is classified as recoverable here, so an unusable or expired
// answer reports a diagnostic and returns to the prompt. Without that
// classification the REPL treats the failure as a wizard abort and terminates the
// whole session, which is what a slow answer used to do.
func TestHistoryEndpointPromptFailureKeepsTheSessionAlive(t *testing.T) {
	stub := historyScenarioStub([]protocol.HistoryRow{{ProviderSessionID: "wa-past"}}, historyReport())
	var out, diagnostics strings.Builder
	calls := 0
	read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
		calls++
		switch calls {
		case 1:
			return "history", false, nil
		case 2:
			return "", false, errors.New("answer stream failed")
		case 3:
			return "list", false, nil
		}
		return "quit", false, nil
	}
	if err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read}); err != nil {
		t.Fatalf("a failed history prompt ended the session: %v", err)
	}
	if len(stub.historyCalls) != 0 {
		t.Fatalf("a failed prompt reached the API: %v", stub.historyCalls)
	}
	if !strings.Contains(diagnostics.String(), "answer stream failed") {
		t.Fatalf("a failed prompt reported no diagnostic: %q", diagnostics.String())
	}
}
