package endpoint

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// TestRefusedCallerLearnsNothingAboutTheTarget proves the policy check runs
// before every target check, so a refused caller cannot use the receipt code to
// enumerate which resources exist on this machine.
//
// The three cases below are the exact leak the issue recorded: the same refused
// token receives target_not_found, target_generation_mismatch and policy_denied
// depending on the target, which answers a question the caller was never
// authorized to ask. After the ordering fix all three must answer policy_denied.
func TestRefusedCallerLearnsNothingAboutTheTarget(t *testing.T) {
	cases := []struct {
		name   string
		target func(resourceID string) *protocol.CommandTarget
	}{
		{
			name: "a resource that does not exist",
			target: func(string) *protocol.CommandTarget {
				return &protocol.CommandTarget{Kind: "session", ResourceID: "res_does_not_exist", ProviderGeneration: "g1"}
			},
		},
		{
			name: "a resource that exists with the wrong generation",
			target: func(resourceID string) *protocol.CommandTarget {
				return &protocol.CommandTarget{Kind: "session", ResourceID: resourceID, ProviderGeneration: "stale-generation"}
			},
		},
		{
			name: "a resource that exists with the correct generation",
			target: func(resourceID string) *protocol.CommandTarget {
				return &protocol.CommandTarget{Kind: "session", ResourceID: resourceID, ProviderGeneration: "g1"}
			},
		},
		{
			name: "a target with no generation at all",
			target: func(resourceID string) *protocol.CommandTarget {
				return &protocol.CommandTarget{Kind: "session", ResourceID: resourceID}
			},
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			executor, store, called, resourceID := newPolicyTestExecutor(t)
			executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
				return errors.New("this token may not exercise this operation")
			}
			intent := commandExecIntent("policy-order-"+testCase.name, resourceID)
			intent.Target = testCase.target(resourceID)

			receipt, err := executor.Execute(context.Background(), intent, "policy-order-hash")
			if err != nil {
				t.Fatalf("execute: %v", err)
			}
			if receipt.ErrorCode != "policy_denied" {
				t.Fatalf("a refused caller must learn only that it was refused, got error code %q for target %+v", receipt.ErrorCode, *intent.Target)
			}
			if receipt.EffectCertainty != protocol.EffectNotApplied {
				t.Fatalf("effect certainty=%q, want not_applied", receipt.EffectCertainty)
			}
			select {
			case <-called:
				t.Fatal("the adapter was invoked for a refused caller")
			default:
			}
			assertTerminalRejection(t, store, intent.CommandID, "policy_denied")
		})
	}
}

// TestAuthorizedCallerKeepsThePreciseTargetCode proves the ordering fix does not
// blunt the authorized path. An authorized caller must still receive the exact
// reason its target was rejected, because that is the information it needs to
// correct the request.
//
// Without this case, refusing every command would also satisfy the test above.
func TestAuthorizedCallerKeepsThePreciseTargetCode(t *testing.T) {
	cases := []struct {
		name     string
		target   func(resourceID string) *protocol.CommandTarget
		wantCode string
	}{
		{
			name: "a resource that does not exist",
			target: func(string) *protocol.CommandTarget {
				return &protocol.CommandTarget{Kind: "session", ResourceID: "res_does_not_exist", ProviderGeneration: "g1"}
			},
			wantCode: "target_not_found",
		},
		{
			name: "a resource that exists with the wrong generation",
			target: func(resourceID string) *protocol.CommandTarget {
				return &protocol.CommandTarget{Kind: "session", ResourceID: resourceID, ProviderGeneration: "stale-generation"}
			},
			wantCode: "target_generation_mismatch",
		},
		{
			name: "a target with no generation at all",
			target: func(resourceID string) *protocol.CommandTarget {
				return &protocol.CommandTarget{Kind: "session", ResourceID: resourceID}
			},
			wantCode: "generation_required",
		},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			executor, store, _, resourceID := newPolicyTestExecutor(t)
			executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
				return nil
			}
			intent := commandExecIntent("policy-authorized-"+testCase.name, resourceID)
			intent.Target = testCase.target(resourceID)

			receipt, err := executor.Execute(context.Background(), intent, "policy-authorized-hash")
			if err != nil {
				t.Fatalf("execute: %v", err)
			}
			if receipt.ErrorCode != testCase.wantCode {
				t.Fatalf("an authorized caller must keep the precise target code, got %q want %q", receipt.ErrorCode, testCase.wantCode)
			}
			assertTerminalRejection(t, store, intent.CommandID, testCase.wantCode)
		})
	}
}

// TestRefusedCallerIsRefusedBeforeTheAdapterIsDescribed proves the refusal
// happens before the adapter is consulted at all, not merely before the target
// checks.
//
// A caller refused by policy must not be able to learn whether this Endpoint has
// a configured adapter, which capability revision it advertises, or whether the
// requested operation is supported. Those are all facts about the machine, and
// the read path's stated rule is that a refusal reveals nothing about it.
func TestRefusedCallerIsRefusedBeforeTheAdapterIsDescribed(t *testing.T) {
	executor, store, called, resourceID := newPolicyTestExecutor(t)
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return errors.New("this token may not exercise this operation")
	}
	// An operation the fixture adapter does not advertise. Before the ordering
	// fix this answered "unsupported", which told a refused caller exactly which
	// operations this machine serves.
	intent := commandExecIntent("policy-order-unsupported", resourceID)
	intent.Operation = protocol.OperationAgentStop
	intent.OperationVersion = "v1"

	receipt, err := executor.Execute(context.Background(), intent, "policy-order-unsupported-hash")
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if receipt.ErrorCode != "policy_denied" {
		t.Fatalf("a refused caller must not learn which operations are supported, got error code %q", receipt.ErrorCode)
	}
	select {
	case <-called:
		t.Fatal("the adapter was invoked for a refused caller")
	default:
	}
	assertTerminalRejection(t, store, intent.CommandID, "policy_denied")
}

// TestRefusalDoesNotOverwriteAnAlreadyRecordedOutcome proves the policy check
// stays after the journal's terminal and recovery returns.
//
// Moving it earlier than those returns would re-decide a command that already
// executed, so a replay carrying a token that is now refused would replace a
// real receipt with a refusal. The stored outcome must win, because the effect
// already happened.
func TestRefusalDoesNotOverwriteAnAlreadyRecordedOutcome(t *testing.T) {
	executor, _, called, resourceID := newPolicyTestExecutor(t)
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return nil
	}
	intent := commandExecIntent("policy-order-replay", resourceID)
	first, err := executor.Execute(context.Background(), intent, "policy-order-replay-hash")
	if err != nil {
		t.Fatalf("first execute: %v", err)
	}
	select {
	case <-called:
	case <-time.After(time.Second):
		t.Fatal("the adapter was not invoked for the permitted first attempt")
	}

	// The same command is replayed after the token was refused.
	executor.PolicyHook = func(context.Context, protocol.ImmutableIntent) error {
		return errors.New("this token may not exercise this operation")
	}
	second, err := executor.Execute(context.Background(), intent, "policy-order-replay-hash")
	if err != nil {
		t.Fatalf("replay execute: %v", err)
	}
	if second.ErrorCode == "policy_denied" {
		t.Fatalf("a replay must return the recorded outcome, not a fresh refusal: first=%#v second=%#v", first, second)
	}
	if second.Phase != first.Phase || second.ErrorCode != first.ErrorCode {
		t.Fatalf("replay receipt=%#v, want the recorded outcome %#v", second, first)
	}
}
