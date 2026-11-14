package bdd

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/protocol"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
	"topsailai_agent_cluster/tests/harness"
)

// sweepSentinelID is an endpoint that every expiry scenario seeds and that no
// scenario asserts about. It is always degraded with a deadline that has already
// passed, so its absence from the endpoint list proves that at least one sweep
// completed and reached its final delete step.
//
// The marker exists because the Server's own log lines are not observable from a
// BDD scenario: the harness wires child stdout and stderr to the test process's
// streams, so a scenario cannot read them. Without a marker, "the sweep never
// ran" and "the sweep ran and deleted nothing" would be indistinguishable, which
// is exactly the ambiguity that hid the original defect.
//
// The sentinel is seeded already degraded rather than offline on purpose. An
// offline sentinel would only disappear after being degraded and then expired,
// so every scenario would depend on both transitions and a regression in either
// one would fail scenarios that have nothing to do with it. Seeding the final
// state keeps each scenario attributable to its own boundary.
const sweepSentinelID = "sweep-sentinel"

// sweepWait bounds how long a scenario waits for one completed sweep. The Server
// sweeps immediately at startup and then on a cadence derived from the retention
// window, so this only has to cover process start plus one sweep.
const sweepWait = 20 * time.Second

// expirySeed describes one pre-existing row set the Server must find when it
// opens its database.
//
// The rows are written directly rather than through the production write paths,
// because several states under test are ones the production code cannot produce
// on demand: a legacy offline row whose retention clock was never populated, and
// a degraded row whose deadline is already in the past. A row created through
// UpsertEndpoint would carry a populated clock, and a row degraded by the sweep
// would carry a deadline one full retention window in the future.
type expirySeed struct {
	endpointID        string
	connectionState   string
	offlineSinceMS    int64
	degradedSinceMS   int64
	expiresAtMS       int64
	updateAtMS        int64
	withInventory     bool
	commandID         string
	commandStatus     protocol.CommandStatus
	commandUpdateAtMS int64
}

// registerEndpointExpirySteps registers the offline endpoint degradation and
// expiry lifecycle.
func registerEndpointExpirySteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster whose server database holds a legacy offline endpoint "([^"]*)" and an endpoint retention of "([^"]*)"$`, func(endpointID, retention string) error {
		return startExpiryCluster(retention, "", []expirySeed{legacySeed(endpointID, true, "", "")})
	})
	ctx.Step(`^a real cluster with an endpoint retention of "([^"]*)"$`, func(retention string) error {
		return startExpiryCluster(retention, "", nil)
	})
	ctx.Step(`^a real cluster whose server database holds a recent offline endpoint "([^"]*)" and an endpoint retention of "([^"]*)"$`, func(endpointID, retention string) error {
		return startExpiryCluster(retention, "", []expirySeed{recentSeed(endpointID)})
	})
	ctx.Step(`^a real cluster whose server database holds a degraded endpoint "([^"]*)" with a future deletion deadline and an endpoint retention of "([^"]*)"$`, func(endpointID, retention string) error {
		return startExpiryCluster(retention, "", []expirySeed{degradedSeed(endpointID, time.Hour, true, "", "")})
	})
	ctx.Step(`^a real cluster whose server database holds a degraded endpoint "([^"]*)" with a past deletion deadline and an endpoint retention of "([^"]*)"$`, func(endpointID, retention string) error {
		return startExpiryCluster(retention, "", []expirySeed{degradedSeed(endpointID, -time.Hour, true, "", "")})
	})
	ctx.Step(`^a real cluster whose server database holds a degraded endpoint "([^"]*)" with an unconfirmed command and a past deletion deadline and an endpoint retention of "([^"]*)"$`, func(endpointID, retention string) error {
		return startExpiryCluster(retention, "", []expirySeed{degradedSeed(endpointID, -time.Hour, true, "cmd-"+endpointID, protocol.StatusUnconfirmed)})
	})
	ctx.Step(`^a real cluster whose server database holds a legacy offline endpoint "([^"]*)" with a terminal command and endpoint retention "([^"]*)" and command retention "([^"]*)"$`, func(endpointID, retention, commandRetention string) error {
		return startExpiryCluster(retention, commandRetention, []expirySeed{legacySeed(endpointID, true, "cmd-"+endpointID, protocol.StatusFinished)})
	})
	ctx.Step(`^a real cluster whose server database holds a legacy offline endpoint "([^"]*)" with an unconfirmed command and endpoint retention "([^"]*)" and command retention "([^"]*)"$`, func(endpointID, retention, commandRetention string) error {
		return startExpiryCluster(retention, commandRetention, []expirySeed{legacySeed(endpointID, true, "cmd-"+endpointID, protocol.StatusUnconfirmed)})
	})
	ctx.Step(`^the server completes at least one expiry sweep$`, waitForCompletedSweep)
	ctx.Step(`^endpoint "([^"]*)" is absent from the endpoint list$`, func(endpointID string) error {
		_, present, err := endpointRecord(endpointID)
		if err != nil {
			return err
		}
		if present {
			return fmt.Errorf("endpoint %q is still listed, want it expired", endpointID)
		}
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" is present in the endpoint list$`, func(endpointID string) error {
		_, present, err := endpointRecord(endpointID)
		if err != nil {
			return err
		}
		if !present {
			return fmt.Errorf("endpoint %q is not listed, want it retained", endpointID)
		}
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" is (online|offline|degraded) in the endpoint list$`, func(endpointID, wantState string) error {
		record, present, err := endpointRecord(endpointID)
		if err != nil {
			return err
		}
		if !present {
			return fmt.Errorf("endpoint %q is not listed, want connection_state=%q", endpointID, wantState)
		}
		if record.ConnectionState != wantState {
			return fmt.Errorf("endpoint %q connection_state=%q, want %q", endpointID, record.ConnectionState, wantState)
		}
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" is listed with a deletion date$`, func(endpointID string) error {
		record, present, err := endpointRecord(endpointID)
		if err != nil {
			return err
		}
		if !present {
			return fmt.Errorf("endpoint %q is not listed, want a deletion date", endpointID)
		}
		if record.ExpiresAtMS <= 0 {
			return fmt.Errorf("endpoint %q expires_at_ms=%d, want a positive deletion date", endpointID, record.ExpiresAtMS)
		}
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" is not listed with a deletion date$`, func(endpointID string) error {
		record, present, err := endpointRecord(endpointID)
		if err != nil {
			return err
		}
		if !present {
			return fmt.Errorf("endpoint %q is not listed, want it listed without a deletion date", endpointID)
		}
		if record.ExpiresAtMS != 0 {
			return fmt.Errorf("endpoint %q expires_at_ms=%d, want no deletion date", endpointID, record.ExpiresAtMS)
		}
		return nil
	})
	ctx.Step(`^the inventory for "([^"]*)" is not found$`, func(endpointID string) error {
		status, body, err := activeScenario.realCluster.RequestE(http.MethodGet, "/api/v1/endpoints/"+endpointID+"/session-state", nil)
		if err != nil {
			return err
		}
		if status != http.StatusNotFound {
			return fmt.Errorf("inventory for %q status=%d body=%s, want 404", endpointID, status, body)
		}
		return nil
	})
	ctx.Step(`^the inventory for "([^"]*)" is present$`, func(endpointID string) error {
		status, body, err := activeScenario.realCluster.RequestE(http.MethodGet, "/api/v1/endpoints/"+endpointID+"/session-state", nil)
		if err != nil {
			return err
		}
		if status != http.StatusOK {
			return fmt.Errorf("inventory for %q status=%d body=%s, want 200", endpointID, status, body)
		}
		return nil
	})
	ctx.Step(`^command "([^"]*)" is still readable through the command API$`, func(commandID string) error {
		status, body, err := activeScenario.realCluster.RequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
		if err != nil {
			return err
		}
		if status != http.StatusOK {
			return fmt.Errorf("command %q status=%d body=%s, want it retained", commandID, status, body)
		}
		return nil
	})
	ctx.Step(`^command "([^"]*)" is no longer readable through the command API$`, func(commandID string) error {
		status, body, err := activeScenario.realCluster.RequestE(http.MethodGet, "/api/v1/commands/"+commandID, nil)
		if err != nil {
			return err
		}
		if status != http.StatusNotFound {
			return fmt.Errorf("command %q status=%d body=%s, want it purged", commandID, status, body)
		}
		return nil
	})
}

// legacySeed builds an offline row whose retention clock was never populated,
// which is the state the startup repair must make degradable.
func legacySeed(endpointID string, withInventory bool, commandID string, status protocol.CommandStatus) expirySeed {
	now := time.Now().UnixMilli()
	seed := expirySeed{endpointID: endpointID, connectionState: "offline", offlineSinceMS: 0, updateAtMS: now - int64(2*time.Hour/time.Millisecond), withInventory: withInventory}
	if commandID != "" {
		seed.commandID = commandID
		seed.commandStatus = status
		// A retained command is recent while its endpoint is old, because the two
		// retention clocks are independent. That independence is the property the
		// scenario asserts, so the fixture must not collapse the two ages.
		seed.commandUpdateAtMS = now - int64(time.Minute/time.Millisecond)
		if status == protocol.StatusUnconfirmed {
			// An uncertain command is old enough to purge by age, so the scenario
			// proves the status allowlist and not merely the cutoff.
			seed.commandUpdateAtMS = seed.updateAtMS
		}
	}
	return seed
}

// recentSeed builds an offline row that went offline just now, so it must survive
// a retention window that has not elapsed.
func recentSeed(endpointID string) expirySeed {
	now := time.Now().UnixMilli()
	return expirySeed{endpointID: endpointID, connectionState: "offline", offlineSinceMS: 0, updateAtMS: now, withInventory: true}
}

// degradedSeed builds a row that the sweep has already degraded, with a deletion
// deadline offset from now. A negative offset puts the deadline in the past, so
// the next sweep must delete the row; a positive offset keeps it listed.
//
// The deadline is seeded directly rather than derived from a retention window,
// because the property under test is the deadline comparison itself. Deriving it
// would make the scenario depend on the degrade step as well, and a regression in
// that step would fail a scenario about expiry.
func degradedSeed(endpointID string, deadlineOffset time.Duration, withInventory bool, commandID string, status protocol.CommandStatus) expirySeed {
	now := time.Now().UnixMilli()
	degradedSince := now - int64(2*time.Hour/time.Millisecond)
	seed := expirySeed{
		endpointID:      endpointID,
		connectionState: "degraded",
		offlineSinceMS:  degradedSince,
		degradedSinceMS: degradedSince,
		expiresAtMS:     now + int64(deadlineOffset/time.Millisecond),
		updateAtMS:      degradedSince,
		withInventory:   withInventory,
	}
	if commandID != "" {
		seed.commandID = commandID
		seed.commandStatus = status
		seed.commandUpdateAtMS = degradedSince
	}
	return seed
}

// startExpiryCluster starts a real cluster whose Server database already holds
// the seeded rows, then waits for the Endpoint to connect normally.
func startExpiryCluster(retention, commandRetention string, seeds []expirySeed) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	environment := map[string]string{"AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY": retention}
	if commandRetention != "" {
		environment["AGENT_CLUSTER_SERVER_COMMAND_RETENTION"] = commandRetention
	}
	// The sentinel is appended to every scenario so the sweep marker is present
	// regardless of what the scenario itself seeds.
	all := append([]expirySeed{sentinelSeed()}, seeds...)
	options := harness.ClusterOptions{
		Environment:  environment,
		SeedServerDB: func(path string) error { return seedExpiryDatabase(path, all) },
	}
	cluster, err := harness.StartCluster(activeTest, options)
	if err != nil {
		return err
	}
	activeScenario.world = &World{realCluster: cluster}
	activeScenario.realCluster = cluster
	return nil
}

// sentinelSeed builds the always-expirable marker row.
//
// The sentinel is degraded with a deadline in the past, so the sweep's final
// delete step removes it. Its absence therefore proves the sweep ran to
// completion, and no scenario has to wait for the degrade transition to observe
// that.
func sentinelSeed() expirySeed {
	now := time.Now().UnixMilli()
	degradedSince := now - int64(2*time.Hour/time.Millisecond)
	return expirySeed{
		endpointID:      sweepSentinelID,
		connectionState: "degraded",
		offlineSinceMS:  degradedSince,
		degradedSinceMS: degradedSince,
		expiresAtMS:     now - int64(time.Hour/time.Millisecond),
		updateAtMS:      degradedSince,
	}
}

// seedExpiryDatabase writes the seeded rows before the Server opens the file.
//
// It opens the database through the production storage layer so the schema comes
// from the real migration rather than a copy, then writes the rows directly
// because the production write paths cannot produce a legacy row or a degraded
// row whose deadline has already passed.
func seedExpiryDatabase(path string, seeds []expirySeed) error {
	ctx := context.Background()
	store, err := serverstorage.Open(ctx, path)
	if err != nil {
		return fmt.Errorf("open seed database: %w", err)
	}
	defer func() { _ = store.Close() }()
	for _, seed := range seeds {
		if _, err := store.DB().ExecContext(ctx, `INSERT INTO endpoints(endpoint_id, instance_id, display_name, hostname, connection_state, offline_since_at_ms, degraded_since_at_ms, expires_at_ms, observed_at_ms, capability_revision, create_at_ms, update_at_ms) VALUES(?, ?, ?, '', ?, ?, ?, ?, ?, 'c1', ?, ?)`, seed.endpointID, seed.endpointID+"-instance", seed.endpointID, seed.connectionState, seed.offlineSinceMS, seed.degradedSinceMS, seed.expiresAtMS, seed.updateAtMS, seed.updateAtMS, seed.updateAtMS); err != nil {
			return fmt.Errorf("seed endpoint %q: %w", seed.endpointID, err)
		}
		if seed.withInventory {
			report := protocol.InventoryReport{SchemaVersion: "v1", SourceGeneration: seed.endpointID + "-generation", SnapshotRevision: 1, ObservedAtMS: seed.updateAtMS, ReportComplete: true, CollectionStatus: protocol.CollectionSucceeded, Adapters: []protocol.AdapterSummary{{AdapterID: "adapter-1", ProviderType: "fixture", DisplayName: "Fixture", Version: "v1", Health: "healthy", CollectionStatus: protocol.CollectionSucceeded, DataKnown: true}}}
			if err := store.ReplaceInventory(ctx, seed.endpointID, report, seed.updateAtMS); err != nil {
				return fmt.Errorf("seed inventory for %q: %w", seed.endpointID, err)
			}
		}
		if seed.commandID != "" {
			if _, err := store.DB().ExecContext(ctx, `INSERT INTO commands(command_id, request_hash, endpoint_id, operation, target_json, intent_json, status, phase, delivery_boundary, effect_certainty, deadline_at_ms, receipt_json, create_at_ms, update_at_ms) VALUES(?, ?, ?, 'message.send', NULL, '{}', ?, ?, ?, ?, 0, NULL, ?, ?)`, seed.commandID, "hash-"+seed.commandID, seed.endpointID, string(seed.commandStatus), string(protocol.PhaseReceiptRecorded), string(protocol.DeliverySubmitted), string(protocol.EffectAcknowledged), seed.commandUpdateAtMS, seed.commandUpdateAtMS); err != nil {
				return fmt.Errorf("seed command %q: %w", seed.commandID, err)
			}
		}
	}
	return nil
}

// waitForCompletedSweep waits until the sentinel endpoint is gone, which proves a
// sweep ran and reached its delete step.
func waitForCompletedSweep() error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	deadline := time.Now().Add(sweepWait)
	var lastErr error
	for time.Now().Before(deadline) {
		_, present, err := endpointRecord(sweepSentinelID)
		if err != nil {
			lastErr = err
		} else if !present {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	if lastErr != nil {
		return fmt.Errorf("no expiry sweep completed within %s: %w", sweepWait, lastErr)
	}
	return fmt.Errorf("no expiry sweep completed within %s: sentinel endpoint %q is still listed", sweepWait, sweepSentinelID)
}

// endpointRecord returns one endpoint from the Server's endpoint projection and
// reports whether it was present.
func endpointRecord(endpointID string) (protocol.Endpoint, bool, error) {
	status, body, err := activeScenario.realCluster.RequestE(http.MethodGet, "/api/v1/endpoints", nil)
	if err != nil {
		return protocol.Endpoint{}, false, err
	}
	if status != http.StatusOK {
		return protocol.Endpoint{}, false, fmt.Errorf("list endpoints status=%d body=%s", status, body)
	}
	var envelope struct {
		Data []protocol.Endpoint `json:"data"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		return protocol.Endpoint{}, false, fmt.Errorf("decode endpoint list: %w", err)
	}
	for _, item := range envelope.Data {
		if item.EndpointID == endpointID {
			return item, true, nil
		}
	}
	return protocol.Endpoint{}, false, nil
}
