package endpoint

import (
	"context"
	"errors"
	"fmt"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
	endpointstorage "topsailai_agent_cluster/internal/storage/endpoint"
)

// TestCollectKeepsThePreviousSnapshotWhenCapacityIsRefused proves a local
// scheduling collision never degrades a healthy inventory.
//
// The Endpoint's own periodic collection competes with operator reads for the
// same adapter capacity. Before this behaviour, one refused discovery marked the
// source as failed, which set ReportComplete to false and made every operator
// command refuse with "inventory is unavailable" while the Endpoint was merely
// busy with its own reporting.
func TestCollectKeepsThePreviousSnapshotWhenCapacityIsRefused(t *testing.T) {
	busy := fakeAdapter{err: fmt.Errorf("%w: discovery", adapter.ErrBusy)}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: busy}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	collector.sources["a"] = sourceSnapshotWithSession("a", "s1", 100)
	report, err := collector.Collect(context.Background(), 200)
	if err != nil {
		t.Fatalf("a capacity refusal must not abort the cycle: %v", err)
	}
	if !report.ReportComplete {
		t.Fatalf("a capacity refusal degraded a healthy inventory: %#v", report)
	}
	if len(report.Sessions) != 1 || report.Sessions[0].ClusterSessionID != "s1" {
		t.Fatalf("the previous observation was dropped: %#v", report.Sessions)
	}
	if report.Adapters[0].CollectionStatus != protocol.CollectionSucceeded {
		t.Fatalf("the source was marked failed: %#v", report.Adapters[0])
	}
}

// TestCollectReportsUnknownWhenCapacityIsRefusedBeforeAnyObservation proves a
// skipped first cycle is unknown rather than a complete empty inventory.
//
// Publishing an empty complete report would claim the provider holds no sessions
// when it was never asked, which is the opposite of what happened.
func TestCollectReportsUnknownWhenCapacityIsRefusedBeforeAnyObservation(t *testing.T) {
	busy := fakeAdapter{err: fmt.Errorf("%w: discovery", adapter.ErrBusy)}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: busy}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	report, err := collector.Collect(context.Background(), 200)
	if err != nil {
		t.Fatalf("a capacity refusal must not abort the cycle: %v", err)
	}
	if report.ReportComplete {
		t.Fatalf("a skipped cycle claimed a complete inventory: %#v", report)
	}
	if report.CollectionStatus != protocol.CollectionUnknown {
		t.Fatalf("a skipped cycle was reported as %q, want unknown", report.CollectionStatus)
	}
	if len(report.Sessions) != 0 {
		t.Fatalf("a skipped cycle invented sessions: %#v", report.Sessions)
	}
}

// TestCollectStillFailsOnARealProviderError proves the capacity exemption is
// narrow: a genuine provider failure still degrades the inventory.
func TestCollectStillFailsOnARealProviderError(t *testing.T) {
	broken := fakeAdapter{err: errors.New("provider unavailable")}
	collector, err := NewCollector(context.Background(), []Binding{{AdapterID: "a", ProviderType: "fixture", Adapter: broken}}, time.Second, nil)
	if err != nil {
		t.Fatal(err)
	}
	collector.sources["a"] = sourceSnapshotWithSession("a", "s1", 100)
	report, err := collector.Collect(context.Background(), 200)
	if err != nil {
		t.Fatal(err)
	}
	if report.ReportComplete {
		t.Fatalf("a real provider failure was treated as a skipped cycle: %#v", report)
	}
	if report.Adapters[0].CollectionStatus != protocol.CollectionFailed {
		t.Fatalf("a real provider failure was not recorded: %#v", report.Adapters[0])
	}
}

// sourceSnapshotWithSession builds a healthy snapshot holding one session, so a
// test can prove a later cycle preserved it instead of degrading it.
func sourceSnapshotWithSession(adapterID, sessionID string, atMS int64) endpointstorage.SourceSnapshot {
	lastSuccess := atMS
	return endpointstorage.SourceSnapshot{
		AdapterID:        adapterID,
		ProviderType:     "fixture",
		Health:           "healthy",
		Sessions:         []protocol.Session{{ClusterSessionID: sessionID, AdapterID: adapterID}},
		ReportComplete:   true,
		CollectionStatus: protocol.CollectionSucceeded,
		LastAttemptAtMS:  atMS,
		LastSuccessAtMS:  &lastSuccess,
		DataKnown:        true,
	}
}
