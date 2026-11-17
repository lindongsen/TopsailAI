package endpoint

import (
	"context"
	"errors"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// TestPartialDiscoveryPublishesObservedRows proves a degraded cycle keeps the rows
// it observed instead of discarding them.
//
// The defect this guards is the reason one unattributable provider row made a whole
// node look broken: the collector treated an incomplete cycle as a failure, so every
// healthy row observed in the same cycle disappeared and the node rendered as
// failed/stale. A partial cycle must publish its rows and stay visibly incomplete.
func TestPartialDiscoveryPublishesObservedRows(t *testing.T) {
	degraded := fakeAdapter{result: adapter.DiscoverResult{
		Complete:         false,
		CollectionStatus: protocol.CollectionPartial,
		Sessions:         []protocol.Session{{ClusterSessionID: "healthy", AdapterID: "a"}},
	}}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: degraded}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	report, err := collector.Collect(context.Background(), 100)
	if err != nil {
		t.Fatal(err)
	}
	if report.ReportComplete {
		t.Fatalf("a degraded cycle claimed a complete inventory: %#v", report)
	}
	if report.CollectionStatus != protocol.CollectionPartial {
		t.Fatalf("collection status = %q, want partial", report.CollectionStatus)
	}
	if len(report.Sessions) != 1 || report.Sessions[0].ClusterSessionID != "healthy" {
		t.Fatalf("observed rows were discarded: %#v", report.Sessions)
	}
	if report.Adapters[0].CollectionStatus != protocol.CollectionPartial {
		t.Fatalf("adapter status = %q, want partial", report.Adapters[0].CollectionStatus)
	}
	if report.Adapters[0].Stale {
		t.Fatal("a partial cycle published fresh rows as stale")
	}
}

// TestPartialDiscoveryWithoutRowsStaysFailed proves the exemption is narrow.
//
// A cycle that observed nothing is a failure, not a partial success. Without this
// assertion the new branch could swallow a genuine provider outage and report an
// empty inventory as merely incomplete.
func TestPartialDiscoveryWithoutRowsStaysFailed(t *testing.T) {
	empty := fakeAdapter{result: adapter.DiscoverResult{Complete: false, CollectionStatus: protocol.CollectionPartial}}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: empty}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	report, err := collector.Collect(context.Background(), 100)
	if err != nil {
		t.Fatal(err)
	}
	if report.Adapters[0].CollectionStatus != protocol.CollectionFailed {
		t.Fatalf("adapter status = %q, want failed", report.Adapters[0].CollectionStatus)
	}
	if report.ReportComplete {
		t.Fatalf("an empty degraded cycle claimed completeness: %#v", report)
	}
}

// TestCollectionFailureIsLogged proves the failure reaches a durable log seam.
//
// The error otherwise lives only in the source cache, where the next successful
// cycle overwrites it, so a transient provider failure leaves no trace anywhere.
// That is why the recurring ai-dev failure stayed undiagnosed.
func TestCollectionFailureIsLogged(t *testing.T) {
	type logged struct {
		adapterID   string
		errorCode   string
		errorMsg    string
		lastSuccess int64
	}
	var entries []logged
	broken := fakeAdapter{err: errors.New("provider unavailable")}
	collector, err := NewCollectorWithOptions(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: broken}}, time.Second, nil, CollectorOptions{
		LogCollectionFailure: func(adapterID, errorCode, errorMessage string, lastSuccessAtMS int64) {
			entries = append(entries, logged{adapterID: adapterID, errorCode: errorCode, errorMsg: errorMessage, lastSuccess: lastSuccessAtMS})
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := collector.Collect(context.Background(), 100); err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("logged %d failures, want 1", len(entries))
	}
	if entries[0].adapterID != "a" {
		t.Fatalf("adapter_id = %q, want a", entries[0].adapterID)
	}
	if entries[0].errorMsg != "provider unavailable" {
		t.Fatalf("error_message = %q, want the provider error", entries[0].errorMsg)
	}
}

// TestPartialDiscoveryIsLogged proves a degraded cycle is also reported.
//
// A partial cycle is the case that used to be silent: it produced rows, so nothing
// looked wrong, while the rows that failed to map were never mentioned anywhere.
func TestPartialDiscoveryIsLogged(t *testing.T) {
	var messages []string
	degraded := fakeAdapter{result: adapter.DiscoverResult{
		Complete:         false,
		CollectionStatus: protocol.CollectionPartial,
		Sessions:         []protocol.Session{{ClusterSessionID: "healthy", AdapterID: "a"}},
	}}
	collector, err := NewCollectorWithOptions(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: degraded}}, time.Second, nil, CollectorOptions{
		LogCollectionFailure: func(adapterID, errorCode, errorMessage string, lastSuccessAtMS int64) {
			messages = append(messages, errorMessage)
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := collector.Collect(context.Background(), 100); err != nil {
		t.Fatal(err)
	}
	if len(messages) != 1 {
		t.Fatalf("logged %d degraded cycles, want 1", len(messages))
	}
}
