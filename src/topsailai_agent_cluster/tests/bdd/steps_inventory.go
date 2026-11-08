package bdd

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/tests/harness"
)

// registerInventorySteps registers real HTTP inventory assertions.
func registerInventorySteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^an isolated Agent Cluster server$`, func() error {
		world, err := NewWorld(activeTest)
		if err != nil {
			return err
		}
		activeScenario.world = world
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" submits a complete inventory with revision (\d+)$`, func(endpoint string, revision int64) error {
		report := validReport(endpoint, revision, false)
		resp, body, err := activeScenario.world.RequestE(http.MethodPut, "/api/v1/endpoints/"+endpoint+"/session-state", report)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" submits an empty complete inventory with revision (\d+)$`, func(endpoint string, revision int64) error {
		report := validReport(endpoint, revision, true)
		resp, body, err := activeScenario.world.RequestE(http.MethodPut, "/api/v1/endpoints/"+endpoint+"/session-state", report)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" submits an invalid inventory$`, func(endpoint string) error {
		resp, body, err := activeScenario.world.RequestE(http.MethodPut, "/api/v1/endpoints/"+endpoint+"/session-state", map[string]any{"schema_version": "v1"})
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^the inventory request succeeds$`, func() error {
		if activeScenario.lastStatus != http.StatusOK {
			return fmt.Errorf("want 200, got %d", activeScenario.lastStatus)
		}
		return nil
	})
	ctx.Step(`^the inventory request is rejected$`, func() error {
		if activeScenario.lastStatus < 400 {
			return fmt.Errorf("want rejection, got %d", activeScenario.lastStatus)
		}
		return nil
	})
	ctx.Step(`^the latest inventory for "([^"]*)" contains adapter "([^"]*)"$`, func(endpoint, adapterID string) error {
		resp, body, err := activeScenario.world.RequestE(http.MethodGet, "/api/v1/endpoints/"+endpoint+"/session-state", nil)
		if err != nil {
			return err
		}
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("get status %d", resp.StatusCode)
		}
		var envelope struct {
			Data protocol.InventoryReport `json:"data"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		for _, item := range envelope.Data.Adapters {
			if item.AdapterID == adapterID {
				return nil
			}
		}
		return fmt.Errorf("adapter %q not found", adapterID)
	})
	ctx.Step(`^the latest inventory for "([^"]*)" contains zero sessions$`, func(endpoint string) error {
		resp, body, err := activeScenario.world.RequestE(http.MethodGet, "/api/v1/endpoints/"+endpoint+"/session-state", nil)
		if err != nil {
			return err
		}
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("get status %d", resp.StatusCode)
		}
		var envelope struct {
			Data protocol.InventoryReport `json:"data"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		if len(envelope.Data.Sessions) != 0 {
			return fmt.Errorf("got %d sessions", len(envelope.Data.Sessions))
		}
		return nil
	})
}

// registerRealInventorySteps registers the real-process inventory smoke scenario.
func registerRealInventorySteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a healthy provider$`, func() error {
		activeScenario.world = &World{}
		if err := activeScenario.world.StartRealCluster(harness.FaultInjection{}); err != nil {
			return err
		}
		return nil
	})
	ctx.Step(`^the inventory is read through the real HTTP boundary$`, func() error {
		inventory, err := activeScenario.world.RealInventory()
		if err != nil {
			return err
		}
		activeScenario.lastBody, err = json.Marshal(inventory)
		return err
	})
	ctx.Step(`^the inventory contains at least one session from the real provider$`, func() error {
		var inventory protocol.InventoryReport
		if err := json.Unmarshal(activeScenario.lastBody, &inventory); err != nil {
			return err
		}
		if len(inventory.Sessions) == 0 {
			return fmt.Errorf("real inventory contains no sessions")
		}
		return nil
	})
	ctx.Step(`^the session carries a non-empty generation$`, func() error {
		var inventory protocol.InventoryReport
		if err := json.Unmarshal(activeScenario.lastBody, &inventory); err != nil {
			return err
		}
		for _, session := range inventory.Sessions {
			if strings.TrimSpace(session.Generation) != "" {
				return nil
			}
		}
		return fmt.Errorf("real inventory session has no generation")
	})
}

func validReport(endpoint string, revision int64, empty bool) protocol.InventoryReport {
	report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: endpoint + "-generation", SnapshotRevision: revision, ObservedAtMS: 1, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", ProviderType: "fixture", DisplayName: "Fixture", Version: "v1", Health: "healthy", CollectionStatus: protocol.CollectionSucceeded, DataKnown: true}}}
	if !empty {
		report.Sessions = []protocol.Session{{SessionID: "session-1", AgentID: "agent-1", Generation: "generation-1", AdapterID: "adapter-1", State: "idle", ObservedAtMS: 1}}
	}
	return report
}

// registerInventoryFreshnessSteps registers source-isolation and freshness assertions.
func registerInventoryFreshnessSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^endpoint "([^"]*)" submits a report with one successful and one failed source$`, func(endpoint string) error {
		now := time.Now().UnixMilli()
		report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: endpoint + "-generation", SnapshotRevision: 1, ObservedAtMS: now, ReportComplete: false, CollectionStatus: protocol.CollectionPartial, Adapters: []protocol.AdapterSummary{
			{AdapterID: "source-good", ProviderType: "fixture", CollectionStatus: protocol.CollectionSucceeded, DataKnown: true, LastAttemptAtMS: now, LastSuccessAtMS: &now},
			{AdapterID: "source-bad", ProviderType: "fixture", CollectionStatus: protocol.CollectionFailed, DataKnown: false, LastAttemptAtMS: now},
		}, Sessions: []protocol.Session{{SessionID: "good-session", AdapterID: "source-good", Generation: "good-generation", State: "idle"}}}
		resp, body, err := activeScenario.world.RequestE(http.MethodPut, "/api/v1/endpoints/"+endpoint+"/session-state", report)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^the successful source remains complete and the failed source is marked failed$`, func() error {
		var envelope struct {
			Data protocol.InventoryReport `json:"data"`
		}
		if err := json.Unmarshal(activeScenario.lastBody, &envelope); err != nil {
			return err
		}
		if envelope.Data.CollectionStatus != protocol.CollectionPartial || envelope.Data.ReportComplete {
			return fmt.Errorf("unexpected aggregate state: %#v", envelope.Data)
		}
		for _, item := range envelope.Data.Adapters {
			if item.AdapterID == "source-good" && item.CollectionStatus != protocol.CollectionSucceeded {
				return fmt.Errorf("successful source changed: %#v", item)
			}
			if item.AdapterID == "source-bad" && item.CollectionStatus != protocol.CollectionFailed {
				return fmt.Errorf("failed source missing: %#v", item)
			}
		}
		if len(envelope.Data.Sessions) != 1 || envelope.Data.Sessions[0].AdapterID != "source-good" {
			return fmt.Errorf("successful source data was not retained: %#v", envelope.Data.Sessions)
		}
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" first submits a successful source report$`, func(endpoint string) error {
		now := time.Now().UnixMilli()
		activeScenario.lastBody = nil
		report := validReport(endpoint, 1, false)
		report.ObservedAtMS = now
		report.Adapters[0].LastAttemptAtMS = now
		report.Adapters[0].LastSuccessAtMS = &now
		report.Adapters[0].DataKnown = true
		report.Adapters[0].Stale = false
		resp, body, err := activeScenario.world.RequestE(http.MethodPut, "/api/v1/endpoints/"+endpoint+"/session-state", report)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^the same source later submits a failed stale report$`, func() error {
		var prior struct {
			Data protocol.InventoryReport `json:"data"`
		}
		if err := json.Unmarshal(activeScenario.lastBody, &prior); err != nil {
			return err
		}
		previous := prior.Data.Adapters[0].LastSuccessAtMS
		attempt := time.Now().UnixMilli()
		report := prior.Data
		report.SnapshotRevision++
		report.ObservedAtMS = attempt
		report.ReportComplete = false
		report.CollectionStatus = protocol.CollectionFailed
		report.Adapters[0].CollectionStatus = protocol.CollectionFailed
		report.Adapters[0].DataKnown = true
		report.Adapters[0].Stale = true
		report.Adapters[0].LastAttemptAtMS = attempt
		report.Adapters[0].LastSuccessAtMS = previous
		resp, body, err := activeScenario.world.RequestE(http.MethodPut, "/api/v1/endpoints/endpoint-1/session-state", report)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^the latest inventory retains the sessions and marks the source stale with unchanged success time$`, func() error {
		resp, body, err := activeScenario.world.RequestE(http.MethodGet, "/api/v1/endpoints/endpoint-1/session-state", nil)
		if err != nil {
			return err
		}
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("get status=%d", resp.StatusCode)
		}
		var envelope struct {
			Data protocol.InventoryReport `json:"data"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		if len(envelope.Data.Sessions) != 1 {
			return fmt.Errorf("sessions lost: %#v", envelope.Data.Sessions)
		}
		item := envelope.Data.Adapters[0]
		if !item.Stale || !item.DataKnown || item.LastAttemptAtMS <= 0 || item.LastSuccessAtMS == nil {
			return fmt.Errorf("stale metadata missing: %#v", item)
		}
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" submits a first failure with no known data$`, func(endpoint string) error {
		now := time.Now().UnixMilli()
		report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: endpoint + "-generation", SnapshotRevision: 1, ObservedAtMS: now, ReportComplete: false, CollectionStatus: protocol.CollectionUnknown, Adapters: []protocol.AdapterSummary{{AdapterID: "unknown-source", ProviderType: "fixture", CollectionStatus: protocol.CollectionUnknown, LastAttemptAtMS: now, DataKnown: false}}}
		resp, body, err := activeScenario.world.RequestE(http.MethodPut, "/api/v1/endpoints/"+endpoint+"/session-state", report)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^the source is marked unknown rather than an empty successful list$`, func() error {
		var envelope struct {
			Data protocol.InventoryReport `json:"data"`
		}
		if err := json.Unmarshal(activeScenario.lastBody, &envelope); err != nil {
			return err
		}
		if envelope.Data.CollectionStatus != protocol.CollectionUnknown || len(envelope.Data.Sessions) != 0 {
			return fmt.Errorf("unknown source became empty success: %#v", envelope.Data)
		}
		if len(envelope.Data.Adapters) != 1 || envelope.Data.Adapters[0].DataKnown {
			return fmt.Errorf("source data_known was not false: %#v", envelope.Data.Adapters)
		}
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" submits a truncated partial report$`, func(endpoint string) error {
		now := time.Now().UnixMilli()
		report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: endpoint + "-generation", SnapshotRevision: 1, ObservedAtMS: now, ReportComplete: false, CollectionStatus: protocol.CollectionPartial, Adapters: []protocol.AdapterSummary{{AdapterID: "partial-source", ProviderType: "fixture", CollectionStatus: protocol.CollectionPartial, LastAttemptAtMS: now, DataKnown: true}}, Sessions: []protocol.Session{{SessionID: "partial-session", AdapterID: "partial-source", Generation: "partial-generation"}}}
		resp, body, err := activeScenario.world.RequestE(http.MethodPut, "/api/v1/endpoints/"+endpoint+"/session-state", report)
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = resp.StatusCode, body
		return nil
	})
	ctx.Step(`^the report is marked incomplete rather than successful$`, func() error {
		var envelope struct {
			Data protocol.InventoryReport `json:"data"`
		}
		if err := json.Unmarshal(activeScenario.lastBody, &envelope); err != nil {
			return err
		}
		if envelope.Data.ReportComplete || envelope.Data.CollectionStatus != protocol.CollectionPartial {
			return fmt.Errorf("partial report was marked complete: %#v", envelope.Data)
		}
		return nil
	})
}

// registerRealInventoryFreshnessSteps registers real Endpoint collector freshness scenarios.
func registerRealInventoryFreshnessSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with two adapters where adapter-a succeeds and adapter-b fails$`, func() error {
		activeScenario.world = &World{}
		return activeScenario.world.StartRealCluster(harness.FaultInjection{TwoAdapters: true, ProviderFailAdapterID: "adapter-b", CollectionDelayMS: 100})
	})
	ctx.Step(`^the real Endpoint publishes the isolated adapter inventory$`, func() error {
		inventory, err := waitRealInventory(realInventoryWait, func(report protocol.InventoryReport) bool { return len(report.Adapters) == 2 })
		if err != nil {
			return err
		}
		activeScenario.lastBody, err = json.Marshal(inventory)
		return err
	})
	ctx.Step(`^adapter-a retains its sessions while adapter-b is marked failed$`, func() error {
		var report protocol.InventoryReport
		if err := json.Unmarshal(activeScenario.lastBody, &report); err != nil {
			return err
		}
		var good, bad bool
		for _, item := range report.Adapters {
			switch item.AdapterID {
			case "adapter-a":
				good = item.DataKnown && item.CollectionStatus == protocol.CollectionSucceeded
			case "adapter-b":
				bad = !item.DataKnown || item.Stale || item.CollectionStatus == protocol.CollectionFailed
			}
		}
		if !good || !bad || len(report.Sessions) == 0 || report.Sessions[0].AdapterID != "adapter-a" {
			return fmt.Errorf("sources were not isolated: %#v", report)
		}
		return nil
	})
	ctx.Step(`^a real cluster whose provider fails after the first discovery$`, func() error {
		activeScenario.world = &World{}
		return activeScenario.world.StartRealCluster(harness.FaultInjection{ProviderFailAfterN: 1, CollectionDelayMS: 100})
	})
	ctx.Step(`^the real Endpoint refreshes inventory after provider failure$`, func() error {
		// The successful collection and the failing collection are two consecutive
		// cycles, so the non-stale document exists only for one collection delay.
		// Polling for that transient state raced the poll interval and failed under
		// load even with a generous budget, because the window had already closed.
		// The durable stale document carries the same evidence: a recorded success
		// time, retained sessions and a later failed attempt. Waiting for that
		// durable state asserts the behaviour without racing a transient window.
		stale, err := waitRealInventory(realInventoryWait, func(report protocol.InventoryReport) bool {
			return len(report.Adapters) == 1 && report.Adapters[0].Stale && report.Adapters[0].DataKnown &&
				report.Adapters[0].CollectionStatus == protocol.CollectionFailed &&
				report.Adapters[0].LastSuccessAtMS != nil && len(report.Sessions) > 0
		})
		if err != nil {
			return err
		}
		activeScenario.firstInventory = stale
		return nil
	})
	ctx.Step(`^the real source retains its sessions and is automatically marked stale$`, func() error {
		report, err := activeScenario.world.RealInventory()
		if err != nil {
			return err
		}
		var decoded protocol.InventoryReport
		data, _ := json.Marshal(report)
		if err := json.Unmarshal(data, &decoded); err != nil {
			return err
		}
		if len(decoded.Adapters) != 1 {
			return fmt.Errorf("want one adapter, got %#v", decoded.Adapters)
		}
		item := decoded.Adapters[0]
		// A recorded success time that is strictly older than the failed attempt is
		// the durable proof that a successful collection happened first and its data
		// was kept. Without it, "stale" could describe a source that never succeeded.
		if !item.Stale || !item.DataKnown || item.CollectionStatus != protocol.CollectionFailed || item.LastSuccessAtMS == nil {
			return fmt.Errorf("automatic stale snapshot missing: %#v", item)
		}
		if *item.LastSuccessAtMS >= item.LastAttemptAtMS {
			return fmt.Errorf("success time did not precede the failed attempt: %#v", item)
		}
		if len(decoded.Sessions) == 0 {
			return fmt.Errorf("automatic stale snapshot did not retain sessions: %#v", decoded)
		}
		for _, session := range decoded.Sessions {
			if session.SessionID == "" || session.AdapterID != item.AdapterID {
				return fmt.Errorf("retained session is not attributable to the stale source: %#v", session)
			}
		}
		return nil
	})
	ctx.Step(`^a real cluster whose provider fails before the first discovery$`, func() error {
		activeScenario.world = &World{}
		return activeScenario.world.StartRealCluster(harness.FaultInjection{ProviderAlwaysFail: true, CollectionDelayMS: 100, ProviderFailAdapterID: "fixture-main"})
	})
	ctx.Step(`^the real Endpoint publishes the failed first inventory$`, func() error {
		_, err := waitRealInventory(realInventoryWait, func(report protocol.InventoryReport) bool {
			return len(report.Adapters) == 1 && !report.Adapters[0].DataKnown
		})
		return err
	})
	ctx.Step(`^the real source is automatically unknown rather than a successful empty list$`, func() error {
		report, err := activeScenario.world.RealInventory()
		if err != nil {
			return err
		}
		data, _ := json.Marshal(report)
		var decoded protocol.InventoryReport
		if err := json.Unmarshal(data, &decoded); err != nil {
			return err
		}
		if decoded.CollectionStatus != protocol.CollectionUnknown || decoded.ReportComplete || len(decoded.Sessions) != 0 || decoded.Adapters[0].DataKnown || decoded.Adapters[0].Stale {
			return fmt.Errorf("first failure was not unknown: %#v", decoded)
		}
		return nil
	})
}

// realInventoryWait bounds how long a real-cluster scenario waits for the Endpoint
// collection cycle to reach an expected state. The Endpoint collects on its own
// interval and the provider fault injection adds a discovery round, so under
// full-parallel package load the cycle can take several seconds. A short fixed
// budget expired before the expected state appeared and produced a flaky failure
// that was not a logic defect. The budget is generous because the poll returns as
// soon as the condition holds, so a healthy run is not slowed down.
const realInventoryWait = 30 * time.Second

// waitRealInventory polls the persisted inventory until match accepts it or the
// budget expires. The timeout error reports the elapsed time and the last observed
// document so a failure can be diagnosed without re-running the suite.
func waitRealInventory(timeout time.Duration, match func(protocol.InventoryReport) bool) (protocol.InventoryReport, error) {
	started := time.Now()
	deadline := started.Add(timeout)
	var last protocol.InventoryReport
	var lastErr error
	observed := false
	for time.Now().Before(deadline) {
		value, err := activeScenario.world.RealInventory()
		if err == nil {
			data, _ := json.Marshal(value)
			var report protocol.InventoryReport
			if json.Unmarshal(data, &report) == nil {
				last, observed, lastErr = report, true, nil
				if match(report) {
					return report, nil
				}
			}
		} else {
			lastErr = err
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !observed {
		return protocol.InventoryReport{}, fmt.Errorf("real inventory did not reach expected state within %s: no readable inventory, last error: %v", timeout, lastErr)
	}
	return protocol.InventoryReport{}, fmt.Errorf("real inventory did not reach expected state within %s: last observed adapters=%#v collection_status=%q report_complete=%t sessions=%d",
		timeout, last.Adapters, last.CollectionStatus, last.ReportComplete, len(last.Sessions))
}
