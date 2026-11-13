package genericcli

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// custodyAdapter builds an adapter whose mapper already owns one live session.
func custodyAdapter(t *testing.T, provider *fakeRunner) *Adapter {
	t.Helper()
	binding := mustAdapter(t, provider)
	binding.config.Mapper.(*fakeMapper).mappings["session-id"] = adapter.ResourceMapping{
		AdapterID: "a", ResourceKind: protocol.ResourceSession, ProviderResourceKey: "provider-session", ResourceID: "session-id",
	}
	return binding
}

func operationResultResponse(request providercli.Request) providercli.Response {
	return providercli.Response{
		Version: request.Version, RequestID: request.RequestID, OK: true,
		Result: &providercli.OperationResult{
			DeliveryBoundary: providercli.DeliverySubmitted,
			EffectCertainty:  providercli.EffectAcknowledged,
			ProviderOutcome:  "submitted",
		},
	}
}

// TestExecuteForwardsLiveGenerationAndCustodyFields proves one live mutation
// carries the real expected generation and preserves every custody field the
// Provider needs to correlate and bound the invocation.
func TestExecuteForwardsLiveGenerationAndCustodyFields(t *testing.T) {
	provider := newFakeProvider(t)
	binding := custodyAdapter(t, provider)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		return operationResultResponse(request), nil
	}
	deadline := time.Now().Add(2 * time.Second).UnixMilli()
	payload := json.RawMessage(`{"text":"hello"}`)
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "command-1", Operation: protocol.OperationMessageSend, OperationVersion: "v1",
		Target:  &protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: "session-id", ProviderGeneration: "generation-1"},
		Payload: payload, ExecuteBeforeAtMS: deadline,
	}})
	if err != nil || result.Receipt.Outcome != "submitted" {
		t.Fatalf("execute = %+v, %v", result, err)
	}
	request := provider.requests[len(provider.requests)-1]
	if request.Function != providercli.FunctionExecute {
		t.Fatalf("function = %q", request.Function)
	}
	if request.InvocationID != "command-1" {
		t.Fatalf("invocation_id = %q", request.InvocationID)
	}
	if request.Operation == nil || request.Operation.Name != protocol.OperationMessageSend || request.Operation.Version != "v1" {
		t.Fatalf("operation = %+v", request.Operation)
	}
	if request.Target == nil || request.Target.ProviderResourceKey != "provider-session" || request.Target.ExpectedGeneration != "generation-1" {
		t.Fatalf("target = %+v", request.Target)
	}
	if string(request.Payload) != string(payload) {
		t.Fatalf("payload = %s, want %s", request.Payload, payload)
	}
	if request.DeadlineAtMS <= 0 || request.DeadlineAtMS > deadline {
		t.Fatalf("deadline_at_ms = %d, want positive and not after %d", request.DeadlineAtMS, deadline)
	}
	if request.Budget.MaxStdoutBytes <= 0 || request.Budget.MaxStderrBytes <= 0 || request.Budget.MaxRecords <= 0 {
		t.Fatalf("budget = %+v", request.Budget)
	}
}

// TestExecuteAllowsFrozenNonLiveExceptionsWithoutGeneration proves each Unit 1R
// exception reaches the Provider with an empty expected generation, because its
// authority comes from an exact non-live record check instead of process
// generation evidence.
func TestExecuteAllowsFrozenNonLiveExceptionsWithoutGeneration(t *testing.T) {
	for _, operation := range []string{
		protocol.OperationAgentResume,
		protocol.OperationAgentDriveStop,
		protocol.OperationWorkspaceClean,
	} {
		t.Run(operation, func(t *testing.T) {
			provider := newFakeProvider(t)
			binding := custodyAdapter(t, provider)
			provider.invoke = func(request providercli.Request) (providercli.Response, error) {
				return operationResultResponse(request), nil
			}
			_, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "command-1", Operation: operation, OperationVersion: "v1",
				Target:  &protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: "session-id"},
				Payload: json.RawMessage(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli(),
			}})
			if err != nil {
				t.Fatalf("execute %s = %v", operation, err)
			}
			request := provider.requests[len(provider.requests)-1]
			if request.Target == nil || request.Target.ExpectedGeneration != "" {
				t.Fatalf("target = %+v, want empty expected generation", request.Target)
			}
		})
	}
}

// TestExecuteRejectsMissingGenerationBeforeProviderInvocation proves a live or
// unknown operation without generation evidence is rejected locally, so the
// Provider process is never started for a target it cannot verify.
func TestExecuteRejectsMissingGenerationBeforeProviderInvocation(t *testing.T) {
	for _, operation := range []string{
		protocol.OperationMessageSend,
		protocol.OperationAgentStop,
		"future.mutation",
	} {
		t.Run(operation, func(t *testing.T) {
			provider := newFakeProvider(t)
			binding := custodyAdapter(t, provider)
			before := len(provider.requests)
			_, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
				CommandID: "command-1", Operation: operation, OperationVersion: "v1",
				Target:  &protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: "session-id"},
				Payload: json.RawMessage(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli(),
			}})
			if err == nil {
				t.Fatalf("%s without generation was accepted", operation)
			}
			if len(provider.requests) != before {
				t.Fatalf("Provider requests = %d, want %d", len(provider.requests), before)
			}
		})
	}
}

// TestExecutePreservesStructuredProviderRejection proves a Provider rejection
// keeps its own effect certainty and code, so the Endpoint can build the Cluster
// receipt from Provider evidence instead of a flattened generic failure.
func TestExecutePreservesStructuredProviderRejection(t *testing.T) {
	provider := newFakeProvider(t)
	binding := custodyAdapter(t, provider)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		return providercli.Response{
			Version: request.Version, RequestID: request.RequestID, OK: false,
			Error: &providercli.ProviderError{Code: "generation_mismatch", Message: "stale", EffectCertainty: providercli.EffectNotApplied},
		}, nil
	}
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "command-1", Operation: protocol.OperationMessageSend, OperationVersion: "v1",
		Target:  &protocol.CommandTarget{Kind: protocol.ResourceSession, ResourceID: "session-id", ProviderGeneration: "generation-1"},
		Payload: json.RawMessage(`{"text":"hello"}`), ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli(),
	}})
	if err == nil {
		t.Fatal("Provider rejection was reported as success")
	}
	if result.Receipt.ErrorCode != "generation_mismatch" || result.Receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("receipt = %+v", result.Receipt)
	}
}
