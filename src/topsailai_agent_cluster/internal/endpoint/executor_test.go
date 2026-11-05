package endpoint

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

type timeoutAdapter struct {
	adapter.Adapter
	called chan struct{}
}

func (a timeoutAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{{Name: "agent.start", Version: "v1"}}}}, nil
}
func (a timeoutAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, Generation: "g1"}, nil
}
func (a timeoutAdapter) Execute(ctx context.Context, _ adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	close(a.called)
	<-ctx.Done()
	return adapter.ExecuteResult{}, ctx.Err()
}

func TestExecutorUsesCLITimeoutBudget(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	called := make(chan struct{})
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return timeoutAdapter{called: called}, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	e, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "budget-cli", EndpointID: "e1", Operation: "agent.start", LaunchProfileID: "a1", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{"x":1}`), ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli(), Budget: protocol.Budget{CLITimeoutMS: 10}, ProfileRevision: "v1"}
	_, _ = e.Execute(context.Background(), intent, "hash")
	select {
	case <-called:
	case <-time.After(time.Second):
		t.Fatal("adapter was not called")
	}
}

func TestStartRequiresMatchingProfileRevision(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return timeoutAdapter{called: make(chan struct{})}, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	e, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "profile-revision", EndpointID: "e1", Operation: "agent.start", LaunchProfileID: "a1", ProfileRevision: "wrong", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli()}
	receipt, err := e.Execute(context.Background(), intent, "hash-profile")
	if err != nil {
		t.Fatal(err)
	}
	if receipt.ErrorCode != "profile_revision_mismatch" || receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("receipt=%#v", receipt)
	}
}

type outputTestAdapter struct {
	adapter.Adapter
	output adapter.OutputResult
	err    error
}

func (a outputTestAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, Generation: "g1"}, nil
}
func (a outputTestAdapter) ReadOutput(context.Context, adapter.OutputRequest) (adapter.OutputResult, error) {
	return a.output, a.err
}

func TestEarlyRejectionPersistsTerminalReceipt(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return timeoutAdapter{called: make(chan struct{})}, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	e, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "early-rejection", EndpointID: "e1", Operation: "agent.start", LaunchProfileID: "a1", ProfileRevision: "wrong", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Payload: []byte(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
	receipt, err := e.Execute(context.Background(), intent, "early-hash")
	if err != nil {
		t.Fatal(err)
	}
	if receipt.Phase != protocol.PhaseReceiptRecorded || receipt.EffectCertainty != protocol.EffectNotApplied || receipt.FinishedAtMS == 0 {
		t.Fatalf("receipt=%#v", receipt)
	}
	entry, err := store.GetJournal(context.Background(), intent.CommandID)
	if err != nil {
		t.Fatal(err)
	}
	if entry.Phase != protocol.PhaseReceiptRecorded || entry.ReceiptJSON == "" {
		t.Fatalf("journal=%#v", entry)
	}
	second, err := e.Execute(context.Background(), intent, "early-hash")
	if err != nil || second.ErrorCode != receipt.ErrorCode {
		t.Fatalf("replay receipt=%#v err=%v", second, err)
	}
}

func TestReadOutputTruncatesAtMaxBytes(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return outputTestAdapter{output: adapter.OutputResult{Lines: []string{"abcdefghij"}}}, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	mapping, err := store.GetOrCreateResourceID(context.Background(), "a1", "provider", 1)
	if err != nil {
		t.Fatal(err)
	}
	e, _ := NewExecutor(store, registry)
	response, err := e.ReadOutput(context.Background(), protocol.OutputSnapshotRequest{ResourceID: mapping.ResourceID, Generation: "g1", MaxBytes: 4})
	if err != nil || len(response.Data) != 4 || !response.Truncated {
		t.Fatalf("response=%#v err=%v", response, err)
	}
}

func TestReadOutputUnsupportedReturnsError(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	_ = registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return outputTestAdapter{err: adapter.ErrUnsupported}, nil
	})
	_, _ = registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"})
	mapping, _ := store.GetOrCreateResourceID(context.Background(), "a1", "provider", 1)
	e, _ := NewExecutor(store, registry)
	response, err := e.ReadOutput(context.Background(), protocol.OutputSnapshotRequest{ResourceID: mapping.ResourceID, Generation: "g1", MaxBytes: 4})
	if err != nil || response.ErrorCode != "unsupported" {
		t.Fatalf("response=%#v err=%v", response, err)
	}
}

func TestExecutorRejectsUnsupportedCapabilityWithoutCallingAdapter(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	called := false
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return outputTestAdapter{Adapter: countingAdapter{called: &called}}, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	mapping, err := store.GetOrCreateResourceID(context.Background(), "a1", "provider", 1)
	if err != nil {
		t.Fatal(err)
	}
	e, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "unsupported", EndpointID: "e1", Operation: "missing", OperationVersion: "v1", Target: &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, Generation: "g1"}, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
	receipt, err := e.Execute(context.Background(), intent, "hash")
	if err != nil || receipt.ErrorCode != "unsupported" || called {
		t.Fatalf("receipt=%#v err=%v called=%v", receipt, err, called)
	}
}

type countingAdapter struct {
	adapter.Adapter
	called *bool
}

func (a countingAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{{Name: "send", Version: "v1"}}}}, nil
}
func (a countingAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	*a.called = true
	return adapter.InspectResult{Found: true, Generation: "g1"}, nil
}

func TestExecutorAdmissionHookRunsAfterDurableAdmission(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return timeoutAdapter{called: make(chan struct{})}, nil
	}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	e, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	hookCalled := false
	e.AdmissionHook = func(ctx context.Context, intent protocol.ImmutableIntent, _ string) error {
		entry, err := store.GetJournal(ctx, intent.CommandID)
		if err != nil {
			return err
		}
		if entry.Phase != protocol.PhaseEndpointAdmitted {
			t.Errorf("hook observed phase=%s, want endpoint_admitted", entry.Phase)
		}
		hookCalled = true
		return nil
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "admission-order", EndpointID: "e1", Operation: "agent.start", LaunchProfileID: "a1", ProfileRevision: "v1", OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", ExecuteBeforeAtMS: time.Now().Add(time.Second).UnixMilli()}
	_, _ = e.Execute(context.Background(), intent, "admission-order-hash")
	if !hookCalled {
		t.Fatal("admission hook was not called")
	}
}

type resumePreflightAdapter struct {
	adapter.Adapter
	inspection   adapter.InspectResult
	inspectErr   error
	executeCalls *int
}

func (a resumePreflightAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{{Name: protocol.OperationAgentResume, Version: "v1"}}}}, nil
}

func (a resumePreflightAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return a.inspection, a.inspectErr
}

func (a resumePreflightAdapter) Execute(_ context.Context, request adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	*a.executeCalls++
	return adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{CommandID: request.Intent.CommandID, Outcome: "submitted", DeliveryBoundary: protocol.DeliverySubmitted, EffectCertainty: protocol.EffectAcknowledged}}, nil
}

func TestResumePreflightRequiresAuthoritativeAbsence(t *testing.T) {
	tests := []struct {
		name       string
		inspection adapter.InspectResult
		inspectErr error
		wantCalls  int
		wantCode   string
	}{
		{name: "absent executes", inspection: adapter.InspectResult{Found: false}, wantCalls: 1},
		{name: "live rejects", inspection: adapter.InspectResult{Found: true, Generation: "g1"}, wantCode: "target_still_active"},
		{name: "observation failure rejects", inspectErr: errors.New("provider unavailable"), wantCode: "target_observation_failed"},
	}
	for _, testCase := range tests {
		t.Run(testCase.name, func(t *testing.T) {
			store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			mapping, err := store.GetOrCreateResourceID(context.Background(), "a1", "provider-session", 1)
			if err != nil {
				t.Fatal(err)
			}
			calls := 0
			registry := adapter.NewRegistry()
			if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
				return resumePreflightAdapter{inspection: testCase.inspection, inspectErr: testCase.inspectErr, executeCalls: &calls}, nil
			}); err != nil {
				t.Fatal(err)
			}
			if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "fixture"}); err != nil {
				t.Fatal(err)
			}
			executor, err := NewExecutor(store, registry)
			if err != nil {
				t.Fatal(err)
			}
			intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "resume-" + testCase.name, EndpointID: "e1", Operation: protocol.OperationAgentResume, OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Target: &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, Generation: "g1"}, Payload: []byte(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
			receipt, err := executor.Execute(context.Background(), intent, "hash-"+testCase.name)
			if err != nil {
				t.Fatal(err)
			}
			if calls != testCase.wantCalls || receipt.ErrorCode != testCase.wantCode {
				t.Fatalf("calls=%d receipt=%#v", calls, receipt)
			}
		})
	}
}
