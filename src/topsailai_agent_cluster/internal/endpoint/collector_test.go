package endpoint

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

type fakeAdapter struct {
	result adapter.DiscoverResult
	err    error
	delay  time.Duration
}

func (f fakeAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{}, nil
}
func (f fakeAdapter) Discover(ctx context.Context, _ adapter.DiscoverRequest) (adapter.DiscoverResult, error) {
	if f.delay > 0 {
		select {
		case <-time.After(f.delay):
		case <-ctx.Done():
			return adapter.DiscoverResult{}, ctx.Err()
		}
	}
	return f.result, f.err
}
func (f fakeAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{}, nil
}
func (f fakeAdapter) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	return adapter.ExecuteResult{}, adapter.ErrUnsupported
}
func (f fakeAdapter) ReadOutput(context.Context, adapter.OutputRequest) (adapter.OutputResult, error) {
	return adapter.OutputResult{}, adapter.ErrUnsupported
}
func (f fakeAdapter) QueryCommand(context.Context, adapter.CommandQuery) (adapter.CommandResult, error) {
	return adapter.CommandResult{}, adapter.ErrUnsupported
}
func (f fakeAdapter) Watch(context.Context) (<-chan adapter.Event, error) {
	return nil, adapter.ErrUnsupported
}
func (f fakeAdapter) Close() error { return nil }

func TestCollectIsolatesFailureAndPreservesSuccessfulData(t *testing.T) {
	good := fakeAdapter{result: adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded, Sessions: []protocol.Session{{ClusterSessionID: "s1", AdapterID: "good"}}}}
	bad := fakeAdapter{err: errors.New("provider unavailable")}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "bad", ProviderType: "fixture", Adapter: bad}, {AdapterID: "good", ProviderType: "fixture", Adapter: good}}, 50*time.Millisecond, nil)
	if err != nil {
		t.Fatal(err)
	}
	report, err := collector.Collect(context.Background(), 100)
	if err != nil {
		t.Fatal(err)
	}
	if report.CollectionStatus != protocol.CollectionPartial || report.ReportComplete {
		t.Fatalf("unexpected report: %#v", report)
	}
	if len(report.Sessions) != 1 || report.Sessions[0].ClusterSessionID != "s1" {
		t.Fatalf("healthy source was blocked: %#v", report.Sessions)
	}
}

func TestCollectDistinguishesUnknownFromSuccessfulEmpty(t *testing.T) {
	unknown, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: fakeAdapter{err: errors.New("first failure")}}}, time.Millisecond, nil)
	if err != nil {
		t.Fatal(err)
	}
	report, err := unknown.Collect(context.Background(), 100)
	if err != nil {
		t.Fatal(err)
	}
	if report.CollectionStatus != protocol.CollectionUnknown || len(report.Sessions) != 0 {
		t.Fatalf("first failure was treated as empty: %#v", report)
	}

	empty, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: fakeAdapter{result: adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded, Sessions: []protocol.Session{}}}}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	report, err = empty.Collect(context.Background(), 200)
	if err != nil {
		t.Fatal(err)
	}
	if report.CollectionStatus != protocol.CollectionSucceeded || !report.ReportComplete {
		t.Fatalf("successful empty was not known: %#v", report)
	}
}

func TestCollectTimeoutDoesNotBlockOtherSource(t *testing.T) {
	fast := fakeAdapter{result: adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded, Sessions: []protocol.Session{{ClusterSessionID: "fast", AdapterID: "fast"}}}}
	slow := fakeAdapter{delay: 100 * time.Millisecond, result: adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded}}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "slow", ProviderType: "fixture", Adapter: slow}, {AdapterID: "fast", ProviderType: "fixture", Adapter: fast}}, 5*time.Millisecond, nil)
	if err != nil {
		t.Fatal(err)
	}
	started := time.Now()
	report, err := collector.Collect(context.Background(), 100)
	if err != nil {
		t.Fatal(err)
	}
	if time.Since(started) > 50*time.Millisecond {
		t.Fatal("collector waited for slow source")
	}
	if len(report.Sessions) != 1 || report.Sessions[0].ClusterSessionID != "fast" {
		t.Fatalf("fast source missing: %#v", report)
	}
}

func TestIncompleteResultPreservesPreviousSourceData(t *testing.T) {
	state := struct{ incomplete bool }{}
	adapter := fakeAdapterFunc{discover: func(context.Context) (adapter.DiscoverResult, error) {
		if state.incomplete {
			return adapter.DiscoverResult{Complete: false, CollectionStatus: protocol.CollectionPartial}, nil
		}
		return adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded, Sessions: []protocol.Session{{ClusterSessionID: "stable", AdapterID: "a"}}}, nil
	}}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: adapter}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := collector.Collect(context.Background(), 100); err != nil {
		t.Fatal(err)
	}
	state.incomplete = true
	report, err := collector.Collect(context.Background(), 200)
	if err != nil {
		t.Fatal(err)
	}
	if report.CollectionStatus != protocol.CollectionPartial || report.ReportComplete {
		t.Fatalf("unexpected incomplete report: %#v", report)
	}
	if len(report.Sessions) != 1 || report.Sessions[0].ClusterSessionID != "stable" {
		t.Fatalf("incomplete result cleared old data: %#v", report.Sessions)
	}
	if len(report.Adapters) != 1 || !report.Adapters[0].Stale || report.Adapters[0].LastSuccessAtMS == nil || *report.Adapters[0].LastSuccessAtMS != 100 {
		t.Fatalf("stale evidence not retained: %#v", report.Adapters)
	}
}

type fakeAdapterFunc struct {
	discover func(context.Context) (adapter.DiscoverResult, error)
}

func (f fakeAdapterFunc) Describe(context.Context) (adapter.Descriptor, error) {
	return adapter.Descriptor{}, nil
}
func (f fakeAdapterFunc) Discover(ctx context.Context, _ adapter.DiscoverRequest) (adapter.DiscoverResult, error) {
	return f.discover(ctx)
}
func (f fakeAdapterFunc) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{}, nil
}
func (f fakeAdapterFunc) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	return adapter.ExecuteResult{}, adapter.ErrUnsupported
}
func (f fakeAdapterFunc) ReadOutput(context.Context, adapter.OutputRequest) (adapter.OutputResult, error) {
	return adapter.OutputResult{}, adapter.ErrUnsupported
}
func (f fakeAdapterFunc) QueryCommand(context.Context, adapter.CommandQuery) (adapter.CommandResult, error) {
	return adapter.CommandResult{}, adapter.ErrUnsupported
}
func (f fakeAdapterFunc) Watch(context.Context) (<-chan adapter.Event, error) {
	return nil, adapter.ErrUnsupported
}
func (f fakeAdapterFunc) Close() error { return nil }

func TestCollectorUsesAdapterFreshnessWhenProvided(t *testing.T) {
	result := adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded, DataKnown: true, Stale: true, LastAttemptAtMS: 700, LastSuccessAtMS: 650}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: fakeAdapter{result: result}}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	report, err := collector.Collect(context.Background(), 900)
	if err != nil {
		t.Fatal(err)
	}
	item := report.Adapters[0]
	if item.LastAttemptAtMS != 700 || item.LastSuccessAtMS == nil || *item.LastSuccessAtMS != 650 || !item.DataKnown || !item.Stale {
		t.Fatalf("collector did not preserve adapter freshness: %#v", item)
	}
}

func TestCollectorFallsBackWhenAdapterFreshnessZero(t *testing.T) {
	result := adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: fakeAdapter{result: result}}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	report, err := collector.Collect(context.Background(), 900)
	if err != nil {
		t.Fatal(err)
	}
	item := report.Adapters[0]
	if item.LastAttemptAtMS != 900 || item.LastSuccessAtMS == nil || *item.LastSuccessAtMS != 900 || !item.DataKnown || item.Stale {
		t.Fatalf("collector fallback incorrect: %#v", item)
	}
}

func TestValidateReportRejectsInvalidInventory(t *testing.T) {
	if err := ValidateReport(protocol.InventoryReport{}); err == nil {
		t.Fatal("invalid report accepted")
	}
	valid := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: "g", SnapshotRevision: 1, ObservedAtMS: 1, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded}
	if err := ValidateReport(valid); err != nil {
		t.Fatalf("valid report rejected: %v", err)
	}
}
