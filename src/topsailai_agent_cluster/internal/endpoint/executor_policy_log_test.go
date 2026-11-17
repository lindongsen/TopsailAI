package endpoint

// The command path refuses an operation through PolicyHook and records the
// refusal as a durable receipt, but it emitted no log line. An operator auditing
// "who tried what on this machine" therefore saw every refused read and no
// refused write, because only the read path logged where the decision was made.
//
// These tests pin three separate properties, and the third is the one that keeps
// the fix honest:
//
//  1. a policy refusal is logged at WARN with the operation, the command ID and
//     the reason;
//  2. a permitted command logs nothing, so the line means "refused" rather than
//     "a command ran";
//  3. a rejection that is not a policy refusal logs nothing, which is what stops
//     the log from being emitted inside recordEarlyRejection. That helper also
//     records unsupported, profile_required, target_still_active and generation
//     mismatches, and reporting those as policy refusals would send an operator
//     to the policy file for a defect that is not in it.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// captureExecutorLogs runs one command with a JSON logger attached and returns
// the decoded records.
//
// The records are decoded rather than matched as text so the assertion can prove
// the level as well as the fields. A text match on the message alone would pass
// for an INFO line, which is the defect the read path already had to fix.
func captureExecutorLogs(t *testing.T, executor *Executor, intent protocol.ImmutableIntent) []map[string]any {
	t.Helper()
	var buffer bytes.Buffer
	executor.Logger = slog.New(slog.NewJSONHandler(&buffer, &slog.HandlerOptions{Level: slog.LevelDebug}))
	if _, err := executor.Execute(context.Background(), intent, "policy-log-hash"); err != nil {
		t.Fatalf("execute: %v", err)
	}
	records := make([]map[string]any, 0)
	for _, line := range strings.Split(strings.TrimSpace(buffer.String()), "\n") {
		if line == "" {
			continue
		}
		record := make(map[string]any)
		if err := json.Unmarshal([]byte(line), &record); err != nil {
			t.Fatalf("decode log line %q: %v", line, err)
		}
		records = append(records, record)
	}
	return records
}

// TestPolicyRefusalIsLogged proves a refused write leaves the same kind of trace
// a refused read already leaves.
func TestPolicyRefusalIsLogged(t *testing.T) {
	executor, _, called, resourceID := newPolicyTestExecutor(t)
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return errors.New(`operation "command.exec" is not permitted: the presented token is not configured on this endpoint`)
	}
	intent := commandExecIntent("policy-logged", resourceID)

	records := captureExecutorLogs(t, executor, intent)
	if len(records) != 1 {
		t.Fatalf("one policy refusal must produce exactly one log record, got %d: %v", len(records), records)
	}
	if level := records[0]["level"]; level != "WARN" {
		t.Fatalf("the refusal must be logged at WARN, got %v", level)
	}
	if operation := records[0]["operation"]; operation != protocol.OperationCommandExec {
		t.Fatalf("the record must name the refused operation, got %v", operation)
	}
	if commandID := records[0]["command_id"]; commandID != intent.CommandID {
		t.Fatalf("the record must name the command, got %v want %q", commandID, intent.CommandID)
	}
	reason, _ := records[0]["error"].(string)
	if !strings.Contains(reason, "not permitted") {
		t.Fatalf("the record must carry the refusal reason, got %q", reason)
	}
	select {
	case <-called:
		t.Fatal("adapter was invoked despite the policy refusal")
	default:
	}
}

// TestPermittedCommandLogsNoRefusal is the paired negative case.
//
// Without it, a logger that emitted a record for every command would pass the
// test above while making the line useless for an audit.
func TestPermittedCommandLogsNoRefusal(t *testing.T) {
	executor, _, _, resourceID := newPolicyTestExecutor(t)
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error { return nil }
	intent := commandExecIntent("policy-permitted", resourceID)

	records := captureExecutorLogs(t, executor, intent)
	for _, record := range records {
		if message, _ := record["msg"].(string); strings.Contains(message, "refused") {
			t.Fatalf("a permitted command must not log a refusal, got %v", record)
		}
	}
}

// TestNonPolicyRejectionLogsNoRefusal keeps the log at the decision site.
//
// This is the test that fails if the line is moved into recordEarlyRejection,
// which is the tempting place because every rejection passes through it. An
// unsupported operation is a capability fact, not a policy decision, and an
// operator who reads it as a refusal would edit a policy file that is correct.
//
// The hook is permitted here on purpose. The policy check runs before the
// capability check, so a refused caller is refused as a policy decision and
// never reaches the unsupported rejection at all; that ordering is what stops a
// refusal from revealing which operations this machine serves. This test
// therefore proves the log site with a caller the policy allows, which is the
// only case where an unsupported rejection can still happen.
func TestNonPolicyRejectionLogsNoRefusal(t *testing.T) {
	executor, _, _, resourceID := newPolicyTestExecutor(t)
	// The fixture adapter advertises command.exec only, so this operation is
	// rejected as unsupported after the policy hook permits the caller.
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return nil
	}
	intent := commandExecIntent("policy-unsupported", resourceID)
	intent.Operation = "message.send"

	records := captureExecutorLogs(t, executor, intent)
	for _, record := range records {
		if message, _ := record["msg"].(string); strings.Contains(message, "refused") {
			t.Fatalf("an unsupported operation must not be logged as a policy refusal, got %v", record)
		}
	}
}

// TestPolicyRefusalToleratesANilLogger guards the default construction path.
//
// NewExecutor does not take a logger, so every existing caller and every test
// fixture builds an executor without one. A nil dereference at the refusal site
// would turn a correct refusal into a panic on the command path.
func TestPolicyRefusalToleratesANilLogger(t *testing.T) {
	executor, _, _, resourceID := newPolicyTestExecutor(t)
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return errors.New("not permitted")
	}
	intent := commandExecIntent("policy-nil-logger", resourceID)
	receipt, err := executor.Execute(context.Background(), intent, "policy-nil-hash")
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if receipt.ErrorCode != "policy_denied" {
		t.Fatalf("error code=%q, want policy_denied", receipt.ErrorCode)
	}
}
