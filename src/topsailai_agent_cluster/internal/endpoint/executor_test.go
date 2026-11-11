package endpoint

import (
	"context"
	"errors"
	"testing"
	"time"
	"unicode/utf8"

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
	return adapter.InspectResult{Found: true, ProviderGeneration: "g1"}, nil
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
	return adapter.InspectResult{Found: true, ProviderGeneration: "g1"}, nil
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
	response, err := e.ReadOutput(context.Background(), protocol.OutputSnapshotRequest{ResourceID: mapping.ResourceID, ProviderGeneration: "g1", MaxBytes: 4})
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
	response, err := e.ReadOutput(context.Background(), protocol.OutputSnapshotRequest{ResourceID: mapping.ResourceID, ProviderGeneration: "g1", MaxBytes: 4})
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
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "unsupported", EndpointID: "e1", Operation: "missing", OperationVersion: "v1", Target: &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, ProviderGeneration: "g1"}, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
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
	return adapter.InspectResult{Found: true, ProviderGeneration: "g1"}, nil
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
		{name: "live rejects", inspection: adapter.InspectResult{Found: true, Live: true, ProviderGeneration: "g1"}, wantCode: "target_still_active"},
		// A record the provider still lists but cannot prove live is exactly the
		// case resume exists for: the process is gone, the record remains. It must
		// execute, because refusing on Found would reject every resumable session.
		{name: "listed but unverified executes", inspection: adapter.InspectResult{Found: true, Live: false}, wantCalls: 1},
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
			intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "resume-" + testCase.name, EndpointID: "e1", Operation: protocol.OperationAgentResume, OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Target: &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, ProviderGeneration: "g1"}, Payload: []byte(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
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

// recordingOutputAdapter captures the adapter-level output request so the
// Endpoint forwarding boundary can be asserted without a live provider.
type recordingOutputAdapter struct {
	adapter.Adapter
	request adapter.OutputRequest
}

func (a *recordingOutputAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{Found: true, ProviderGeneration: "g1"}, nil
}

func (a *recordingOutputAdapter) ReadOutput(_ context.Context, request adapter.OutputRequest) (adapter.OutputResult, error) {
	a.request = request
	return adapter.OutputResult{Lines: []string{"line"}}, nil
}

// TestReadOutputForwardsBothBudgets proves the Endpoint forwards the requested
// line count unchanged and keeps the byte budget independent, because dropping
// either budget here makes the operator's `logs -n` request ineffective.
func TestReadOutputForwardsBothBudgets(t *testing.T) {
	cases := []struct {
		name         string
		maxBytes     int
		maxLines     int
		wantBytes    int
		wantMaxLines int
	}{
		{name: "line count is forwarded unchanged", maxBytes: 4096, maxLines: 250, wantBytes: 4096, wantMaxLines: 250},
		{name: "absent line count keeps provider default", maxBytes: 4096, maxLines: 0, wantBytes: 4096, wantMaxLines: 0},
		{name: "line count above provider maximum is clamped", maxBytes: 4096, maxLines: 20000, wantBytes: 4096, wantMaxLines: 10000},
		{name: "negative line count keeps provider default", maxBytes: 4096, maxLines: -5, wantBytes: 4096, wantMaxLines: 0},
		{name: "byte budget keeps its own default", maxBytes: 0, maxLines: 250, wantBytes: 64 << 10, wantMaxLines: 250},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			recorder := &recordingOutputAdapter{}
			registry := adapter.NewRegistry()
			if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
				return recorder, nil
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
			if _, err := e.ReadOutput(context.Background(), protocol.OutputSnapshotRequest{ResourceID: mapping.ResourceID, ProviderGeneration: "g1", MaxBytes: testCase.maxBytes, MaxLines: testCase.maxLines}); err != nil {
				t.Fatal(err)
			}
			if recorder.request.MaxBytes != testCase.wantBytes {
				t.Fatalf("MaxBytes=%d, want %d", recorder.request.MaxBytes, testCase.wantBytes)
			}
			if recorder.request.MaxLines != testCase.wantMaxLines {
				t.Fatalf("MaxLines=%d, want %d", recorder.request.MaxLines, testCase.wantMaxLines)
			}
		})
	}
}

// countingInspectAdapter counts live inspections so a test can prove the read path
// does not re-run the provider's full discovery when the persisted snapshot answers.
type countingInspectAdapter struct {
	adapter.Adapter
	inspections int
	generation  string
	found       bool
}

func (a *countingInspectAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	a.inspections++
	return adapter.InspectResult{Found: a.found, ProviderGeneration: a.generation}, nil
}

func (a *countingInspectAdapter) ReadOutput(context.Context, adapter.OutputRequest) (adapter.OutputResult, error) {
	return adapter.OutputResult{Lines: []string{"line"}}, nil
}

// TestReadOutputSkipsDiscoveryWhenSnapshotAnswers proves the read path revalidates
// from the persisted collection snapshot instead of re-running the provider's full
// discovery, which costs seconds per read. It also proves the fallback still
// inspects live when the snapshot cannot answer, so an unknown observation is never
// mistaken for a match.
func TestReadOutputSkipsDiscoveryWhenSnapshotAnswers(t *testing.T) {
	cases := []struct {
		name            string
		snapshot        *endpointstorage.SourceSnapshot
		generation      string
		wantInspections int
		wantError       bool
	}{
		{
			name:            "known fresh snapshot answers without discovery",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: "res_target", ProviderGeneration: "g1"}}},
			generation:      "g1",
			wantInspections: 0,
		},
		{
			name:            "known fresh snapshot rejects a mismatched generation without discovery",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: "res_target", ProviderGeneration: "g1"}}},
			generation:      "g2",
			wantInspections: 0,
			wantError:       true,
		},
		{
			name:            "stale snapshot falls back to one live inspection",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Stale: true, Sessions: []protocol.Session{{ClusterSessionID: "res_target", ProviderGeneration: "g1"}}},
			generation:      "g1",
			wantInspections: 1,
		},
		{
			name:            "unknown data falls back to one live inspection",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionFailed, LastAttemptAtMS: 1, DataKnown: false, Sessions: []protocol.Session{{ClusterSessionID: "res_target", ProviderGeneration: "g1"}}},
			generation:      "g1",
			wantInspections: 1,
		},
		{
			name:            "resource absent from snapshot falls back to one live inspection",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: "res_other", ProviderGeneration: "g1"}}},
			generation:      "g1",
			wantInspections: 1,
		},
		{
			name:            "no snapshot row falls back to one live inspection",
			snapshot:        nil,
			generation:      "g1",
			wantInspections: 1,
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			instance := &countingInspectAdapter{generation: "g1", found: true}
			registry := adapter.NewRegistry()
			if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
				return instance, nil
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
			if testCase.snapshot != nil {
				for index := range testCase.snapshot.Sessions {
					if testCase.snapshot.Sessions[index].ClusterSessionID == "res_target" {
						testCase.snapshot.Sessions[index].ClusterSessionID = mapping.ResourceID
					}
				}
				if err := store.ApplySourceSnapshot(context.Background(), *testCase.snapshot, 2); err != nil {
					t.Fatal(err)
				}
			}
			e, err := NewExecutor(store, registry)
			if err != nil {
				t.Fatal(err)
			}
			_, readErr := e.ReadOutput(context.Background(), protocol.OutputSnapshotRequest{ResourceID: mapping.ResourceID, ProviderGeneration: testCase.generation, MaxBytes: 4096})
			if testCase.wantError && readErr == nil {
				t.Fatal("expected a generation mismatch error")
			}
			if !testCase.wantError && readErr != nil {
				t.Fatalf("unexpected error: %v", readErr)
			}
			if instance.inspections != testCase.wantInspections {
				t.Fatalf("live inspections=%d, want %d", instance.inspections, testCase.wantInspections)
			}
		})
	}
}

// countingExecuteAdapter counts live inspections and executions so a test can prove
// the mutating path revalidates from the persisted snapshot instead of re-running the
// provider's full discovery, which costs seconds per command.
type countingExecuteAdapter struct {
	adapter.Adapter
	inspections int
	executions  int
	generation  string
	found       bool
}

func (a *countingExecuteAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{
		{Name: protocol.OperationMessageSend, Version: "v1"},
		{Name: protocol.OperationAgentResume, Version: "v1"},
	}}}, nil
}

func (a *countingExecuteAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	a.inspections++
	return adapter.InspectResult{Found: a.found, ProviderGeneration: a.generation}, nil
}

func (a *countingExecuteAdapter) Execute(_ context.Context, request adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	a.executions++
	return adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{CommandID: request.Intent.CommandID, Outcome: "submitted", DeliveryBoundary: protocol.DeliverySubmitted, EffectCertainty: protocol.EffectAcknowledged}}, nil
}

// TestExecuteSkipsDiscoveryWhenSnapshotAnswers proves a mutating command revalidates
// its target generation from the Endpoint's own persisted collection snapshot instead
// of re-running the provider's full discovery. The discovery is the dominant cost of
// `send` (measured 11-13 s against a 0.7 s provider send), so paying it per command
// makes every send look hung. The fallback still inspects live whenever the snapshot
// cannot answer, so an unknown observation is never mistaken for a match.
func TestExecuteSkipsDiscoveryWhenSnapshotAnswers(t *testing.T) {
	cases := []struct {
		name            string
		snapshot        *endpointstorage.SourceSnapshot
		generation      string
		wantInspections int
		wantExecutions  int
		wantCode        string
	}{
		{
			name:            "known fresh snapshot answers without discovery",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: "res_target", ProviderGeneration: "g1"}}},
			generation:      "g1",
			wantInspections: 0,
			wantExecutions:  1,
		},
		{
			name:            "known fresh snapshot rejects a mismatched generation without discovery",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: "res_target", ProviderGeneration: "g1"}}},
			generation:      "g2",
			wantInspections: 0,
			wantCode:        "target_generation_mismatch",
		},
		{
			name:            "stale snapshot falls back to one live inspection",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Stale: true, Sessions: []protocol.Session{{ClusterSessionID: "res_target", ProviderGeneration: "g1"}}},
			generation:      "g1",
			wantInspections: 1,
			wantExecutions:  1,
		},
		{
			name:            "unknown data falls back to one live inspection",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionFailed, LastAttemptAtMS: 1, DataKnown: false, Sessions: []protocol.Session{{ClusterSessionID: "res_target", ProviderGeneration: "g1"}}},
			generation:      "g1",
			wantInspections: 1,
			wantExecutions:  1,
		},
		{
			name:            "resource absent from snapshot falls back to one live inspection",
			snapshot:        &endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: "res_other", ProviderGeneration: "g1"}}},
			generation:      "g1",
			wantInspections: 1,
			wantExecutions:  1,
		},
		{
			name:            "no snapshot row falls back to one live inspection",
			snapshot:        nil,
			generation:      "g1",
			wantInspections: 1,
			wantExecutions:  1,
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
			if err != nil {
				t.Fatal(err)
			}
			defer store.Close()
			instance := &countingExecuteAdapter{generation: "g1", found: true}
			registry := adapter.NewRegistry()
			if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
				return instance, nil
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
			if testCase.snapshot != nil {
				for index := range testCase.snapshot.Sessions {
					if testCase.snapshot.Sessions[index].ClusterSessionID == "res_target" {
						testCase.snapshot.Sessions[index].ClusterSessionID = mapping.ResourceID
					}
				}
				if err := store.ApplySourceSnapshot(context.Background(), *testCase.snapshot, 2); err != nil {
					t.Fatal(err)
				}
			}
			e, err := NewExecutor(store, registry)
			if err != nil {
				t.Fatal(err)
			}
			intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "send-" + testCase.name, EndpointID: "e1", Operation: protocol.OperationMessageSend, OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Target: &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, ProviderGeneration: testCase.generation}, Payload: []byte(`{"message":"hi"}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
			receipt, err := e.Execute(context.Background(), intent, "hash-"+testCase.name)
			if err != nil {
				t.Fatal(err)
			}
			if receipt.ErrorCode != testCase.wantCode {
				t.Fatalf("error code=%q, want %q", receipt.ErrorCode, testCase.wantCode)
			}
			if instance.inspections != testCase.wantInspections {
				t.Fatalf("live inspections=%d, want %d", instance.inspections, testCase.wantInspections)
			}
			if instance.executions != testCase.wantExecutions {
				t.Fatalf("provider executions=%d, want %d", instance.executions, testCase.wantExecutions)
			}
		})
	}
}

// TestResumeStillInspectsLive proves the resume preflight keeps its authoritative
// absence proof even when a fresh snapshot exists: a cached snapshot can lag one
// collection cycle, so trusting it would let resume target an already-active session.
func TestResumeStillInspectsLive(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	instance := &countingExecuteAdapter{generation: "g1", found: false}
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return instance, nil
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
	snapshot := endpointstorage.SourceSnapshot{AdapterID: "a1", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, LastAttemptAtMS: 1, DataKnown: true, ReportComplete: true, Sessions: []protocol.Session{{ClusterSessionID: mapping.ResourceID, ProviderGeneration: "g1"}}}
	if err := store.ApplySourceSnapshot(context.Background(), snapshot, 2); err != nil {
		t.Fatal(err)
	}
	e, err := NewExecutor(store, registry)
	if err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "resume-live", EndpointID: "e1", Operation: protocol.OperationAgentResume, OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Target: &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, ProviderGeneration: "g1"}, Payload: []byte(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
	if _, err := e.Execute(context.Background(), intent, "hash-resume-live"); err != nil {
		t.Fatal(err)
	}
	if instance.inspections != 1 {
		t.Fatalf("live inspections=%d, want 1", instance.inspections)
	}
	if instance.executions != 1 {
		t.Fatalf("provider executions=%d, want 1", instance.executions)
	}
}

// TestReadOutputTruncatesOnRuneBoundary proves the snapshot route never returns
// half a character. A raw byte slice at the budget would cut the third byte of a
// three-byte rune and leave the caller with bytes that no longer decode, which is
// exactly what the follow route was already fixed to avoid.
func TestReadOutputTruncatesOnRuneBoundary(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return outputTestAdapter{output: adapter.OutputResult{Lines: []string{"中中中"}}}, nil
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
	response, err := e.ReadOutput(context.Background(), protocol.OutputSnapshotRequest{ResourceID: mapping.ResourceID, ProviderGeneration: "g1", MaxBytes: 4})
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	if !response.Truncated {
		t.Fatalf("truncated=false, want a truncated snapshot")
	}
	if !utf8.ValidString(response.Data) {
		t.Fatalf("data=%q is not valid UTF-8", response.Data)
	}
	if response.Data != "中" {
		t.Fatalf("data=%q, want exactly one whole rune", response.Data)
	}
	if len(response.Data) > 4 {
		t.Fatalf("data length=%d exceeds the 4-byte budget", len(response.Data))
	}
}

// TestReadOutputKeepsWholeRunesWhenBudgetFallsInsideARune proves the truncation
// backs off to the previous rune boundary instead of dropping the whole payload,
// so a budget that lands mid-character still returns the characters that fit.
// "中文abc" is nine bytes, so a five-byte budget lands inside the second rune and
// only the first whole rune fits.
func TestReadOutputKeepsWholeRunesWhenBudgetFallsInsideARune(t *testing.T) {
	store, err := endpointstorage.Open(context.Background(), t.TempDir()+"/endpoint.db")
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return outputTestAdapter{output: adapter.OutputResult{Lines: []string{"中文abc"}}}, nil
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
	response, err := e.ReadOutput(context.Background(), protocol.OutputSnapshotRequest{ResourceID: mapping.ResourceID, ProviderGeneration: "g1", MaxBytes: 5})
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	if !utf8.ValidString(response.Data) {
		t.Fatalf("data=%q is not valid UTF-8", response.Data)
	}
	if response.Data != "中" {
		t.Fatalf("data=%q, want the single whole rune that fits in 5 bytes", response.Data)
	}
}

// unverifiedTargetAdapter describes every operation that can address a session,
// so the empty-generation guard can be exercised for each of them without a live
// provider.
type unverifiedTargetAdapter struct {
	adapter.Adapter
	inspection    adapter.InspectResult
	inspectionErr error
	executeCalls  *int
}

func (a unverifiedTargetAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{AdapterID: "a1", Capabilities: protocol.CapabilityDescriptor{Revision: "v1", Capabilities: []protocol.Capability{
		{Name: protocol.OperationMessageSend, Version: "v1"},
		{Name: protocol.OperationAgentStop, Version: "v1"},
		{Name: protocol.OperationAgentResume, Version: "v1"},
		{Name: protocol.OperationWorkspaceClean, Version: "v1"},
	}}}, nil
}

func (a unverifiedTargetAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return a.inspection, a.inspectionErr
}

func (a unverifiedTargetAdapter) Execute(_ context.Context, request adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	*a.executeCalls++
	return adapter.ExecuteResult{Receipt: protocol.ExecutionReceipt{CommandID: request.Intent.CommandID, Outcome: "submitted", DeliveryBoundary: protocol.DeliverySubmitted, EffectCertainty: protocol.EffectAcknowledged}}, nil
}

// TestUnverifiedTargetRejectsEveryOperationExceptResume proves the admission rule
// for a session the provider lists without a generation. Such a session is
// visible and resumable, but every operation that addresses a live process must
// fail closed, because an empty generation cannot prove which process it would
// reach. Resume is the sole exception: it addresses the provider session by
// handle and exists precisely for the case where the process is gone.
//
// The guard must run before generation revalidation. Revalidation compares the
// requested generation with the observed one, and two empty strings compare
// equal, so without the guard an unverified session would pass the comparison and
// reach the provider as if it were live.
func TestUnverifiedTargetRejectsEveryOperationExceptResume(t *testing.T) {
	tests := []struct {
		name      string
		operation string
		wantCalls int
		wantCode  string
	}{
		{name: "send rejects", operation: protocol.OperationMessageSend, wantCode: "generation_required"},
		{name: "stop rejects", operation: protocol.OperationAgentStop, wantCode: "generation_required"},
		{name: "resume executes", operation: protocol.OperationAgentResume, wantCalls: 1},
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
				// The provider lists the record but proves no live process, which is
				// exactly what an unverified session looks like.
				return unverifiedTargetAdapter{inspection: adapter.InspectResult{Found: true, Live: false}, executeCalls: &calls}, nil
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
			intent := protocol.ImmutableIntent{HashVersion: "v1", CommandID: "unverified-" + testCase.name, EndpointID: "e1", Operation: testCase.operation, OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1", Target: &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID, ProviderGeneration: ""}, Payload: []byte(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli()}
			receipt, err := executor.Execute(context.Background(), intent, "hash-"+testCase.name)
			if err != nil {
				t.Fatal(err)
			}
			if calls != testCase.wantCalls || receipt.ErrorCode != testCase.wantCode {
				t.Fatalf("calls=%d receipt=%#v, want calls=%d code=%q", calls, receipt, testCase.wantCalls, testCase.wantCode)
			}
		})
	}
}

// TestWorkspaceCleanGenerationlessAdmission proves cleanup is the only
// destructive operation that may address an expired row without a live process
// generation. The provider must still confirm that the exact mapped row exists;
// an absent row or failed observation is rejected before Execute.
func TestWorkspaceCleanGenerationlessAdmission(t *testing.T) {
	tests := []struct {
		name          string
		inspection    adapter.InspectResult
		inspectionErr error
		wantCalls     int
		wantCode      string
	}{
		{name: "exact expired row executes", inspection: adapter.InspectResult{Found: true, Live: false}, wantCalls: 1},
		{name: "missing row rejects", inspection: adapter.InspectResult{Found: false}, wantCode: "target_not_found"},
		{name: "inspection failure rejects", inspectionErr: errors.New("provider unavailable"), wantCode: "target_observation_failed"},
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
				return unverifiedTargetAdapter{
					inspection: testCase.inspection, inspectionErr: testCase.inspectionErr,
					executeCalls: &calls,
				}, nil
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
			intent := protocol.ImmutableIntent{
				HashVersion: "v1", CommandID: "clean-" + testCase.name,
				EndpointID: "e1", Operation: protocol.OperationWorkspaceClean,
				OperationVersion: "v1", CapabilityRevision: "v1", PayloadSchemaVersion: "v1",
				Target:  &protocol.CommandTarget{Kind: "session", ResourceID: mapping.ResourceID},
				Payload: []byte(`{}`), ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
			}
			receipt, err := executor.Execute(context.Background(), intent, "hash-"+testCase.name)
			if err != nil {
				t.Fatal(err)
			}
			if calls != testCase.wantCalls || receipt.ErrorCode != testCase.wantCode {
				t.Fatalf("calls=%d receipt=%#v, want calls=%d code=%q", calls, receipt, testCase.wantCalls, testCase.wantCode)
			}
		})
	}
}
