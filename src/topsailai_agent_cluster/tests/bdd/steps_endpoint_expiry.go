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
// scenario asserts about. It is always old enough to expire, so its absence from
// the endpoint list proves that at least one sweep completed.
//
// The marker exists because the Server's own log lines are not observable from a
// BDD scenario: the harness wires child stdout and stderr to the test process's
// streams, so a scenario cannot read them. Without a marker, "the sweep never
// ran" and "the sweep ran and deleted nothing" would be indistinguishable, which
// is exactly the ambiguity that hid the original defect.
const sweepSentinelID = "sweep-sentinel"

// sweepWait bounds how long a scenario waits for one completed sweep. The Server
// sweeps immediately at startup and then on a cadence derived from the retention
// window, so this only has to cover process start plus one sweep.
const sweepWait = 20 * time.Second

// expirySeed describes one pre-existing row set the Server must find when it
// opens its database.
//
// The rows are written directly rather than through the production write paths,
// because the state under test is one the production code can no longer produce:
// a legacy offline row whose retention clock was never populated. A row created
// through UpsertEndpoint would carry a populated clock and would therefore never
// exercise the repair.
type expirySeed struct {
	endpointID        string
	offlineSinceMS    int64
	updateAtMS        int64
	withInventory     bool
	commandID         string
	commandStatus     protocol.CommandStatus
	commandUpdateAtMS int64
}

// registerEndpointExpirySteps registers the offline endpoint expiry lifecycle.
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
	ctx.Step(`^a real cluster whose server database holds a legacy offline endpoint "([^"]*)" with a terminal command and endpoint retention "([^"]*)" and command retention "([^"]*)"$`, func(endpointID, retention, commandRetention string) error {
		return startExpiryCluster(retention, commandRetention, []expirySeed{legacySeed(endpointID, true, "cmd-"+endpointID, protocol.StatusFinished)})
	})
	ctx.Step(`^a real cluster whose server database holds a legacy offline endpoint "([^"]*)" with an unconfirmed command and endpoint retention "([^"]*)" and command retention "([^"]*)"$`, func(endpointID, retention, commandRetention string) error {
		return startExpiryCluster(retention, commandRetention, []expirySeed{legacySeed(endpointID, true, "cmd-"+endpointID, protocol.StatusUnconfirmed)})
	})
	ctx.Step(`^the server completes at least one expiry sweep$`, waitForCompletedSweep)
	ctx.Step(`^endpoint "([^"]*)" is absent from the endpoint list$`, func(endpointID string) error {
		present, err := endpointListed(endpointID)
		if err != nil {
			return err
		}
		if present {
			return fmt.Errorf("endpoint %q is still listed, want it expired", endpointID)
		}
		return nil
	})
	ctx.Step(`^endpoint "([^"]*)" is present in the endpoint list$`, func(endpointID string) error {
		present, err := endpointListed(endpointID)
		if err != nil {
			return err
		}
		if !present {
			return fmt.Errorf("endpoint %q is not listed, want it retained", endpointID)
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
// which is the state the startup repair must make expirable.
func legacySeed(endpointID string, withInventory bool, commandID string, status protocol.CommandStatus) expirySeed {
	now := time.Now().UnixMilli()
	seed := expirySeed{endpointID: endpointID, offlineSinceMS: 0, updateAtMS: now - int64(2*time.Hour/time.Millisecond), withInventory: withInventory}
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
	return expirySeed{endpointID: endpointID, offlineSinceMS: 0, updateAtMS: now, withInventory: true}
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
// The sentinel carries a positive offline_since_at_ms on purpose. A sentinel
// with a zero clock would only become expirable through the startup backfill,
// so every scenario that waits for it would depend on the backfill and a
// backfill regression would fail scenarios that have nothing to do with it.
// Keeping the sentinel independently expirable is what lets each scenario
// attribute a failure to its own boundary.
func sentinelSeed() expirySeed {
	now := time.Now().UnixMilli()
	offlineSince := now - int64(2*time.Hour/time.Millisecond)
	return expirySeed{endpointID: sweepSentinelID, offlineSinceMS: offlineSince, updateAtMS: offlineSince}
}

// seedExpiryDatabase writes the seeded rows before the Server opens the file.
//
// It opens the database through the production storage layer so the schema comes
// from the real migration rather than a copy, then writes the rows directly
// because the production write paths cannot produce a legacy row.
func seedExpiryDatabase(path string, seeds []expirySeed) error {
	ctx := context.Background()
	store, err := serverstorage.Open(ctx, path)
	if err != nil {
		return fmt.Errorf("open seed database: %w", err)
	}
	defer func() { _ = store.Close() }()
	for _, seed := range seeds {
		if _, err := store.DB().ExecContext(ctx, `INSERT INTO endpoints(endpoint_id, instance_id, display_name, hostname, connection_state, offline_since_at_ms, observed_at_ms, capability_revision, create_at_ms, update_at_ms) VALUES(?, ?, ?, '', 'offline', ?, ?, 'c1', ?, ?)`, seed.endpointID, seed.endpointID+"-instance", seed.endpointID, seed.offlineSinceMS, seed.updateAtMS, seed.updateAtMS, seed.updateAtMS); err != nil {
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
		present, err := endpointListed(sweepSentinelID)
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

// endpointListed reports whether one endpoint appears in the Server's endpoint
// projection.
func endpointListed(endpointID string) (bool, error) {
	status, body, err := activeScenario.realCluster.RequestE(http.MethodGet, "/api/v1/endpoints", nil)
	if err != nil {
		return false, err
	}
	if status != http.StatusOK {
		return false, fmt.Errorf("list endpoints status=%d body=%s", status, body)
	}
	var envelope struct {
		Data []protocol.Endpoint `json:"data"`
	}
	if err := json.Unmarshal(body, &envelope); err != nil {
		return false, fmt.Errorf("decode endpoint list: %w", err)
	}
	for _, item := range envelope.Data {
		if item.EndpointID == endpointID {
			return true, nil
		}
	}
	return false, nil
}
