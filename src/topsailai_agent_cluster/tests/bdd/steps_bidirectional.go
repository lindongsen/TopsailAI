package bdd

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// startBidirectionalCluster starts the real Server and Endpoint with both sides
// dialing. The direction is passed through the harness so the scenario exercises
// the same process composition a deployment uses, not an in-process shortcut.
func startBidirectionalCluster(sharedCertificate bool) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		ChannelDirection:  "bidirectional",
		SharedCertificate: sharedCertificate,
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	return nil
}

// registerBidirectionalSteps registers the bidirectional convergence scenarios.
func registerBidirectionalSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster in the bidirectional channel direction$`, func() error {
		activeScenario.world = &World{}
		return startBidirectionalCluster(false)
	})
	ctx.Step(`^a real cluster in the bidirectional channel direction with one shared certificate$`, func() error {
		activeScenario.world = &World{}
		return startBidirectionalCluster(true)
	})
	ctx.Step(`^the endpoint is reported online through the real HTTP boundary$`, func() error {
		status, body, err := activeScenario.world.realRequestE(http.MethodGet, "/api/v1/endpoints", nil)
		if err != nil {
			return err
		}
		if status != http.StatusOK {
			return fmt.Errorf("endpoint list status=%d body=%s", status, body)
		}
		var envelope struct {
			Data []struct {
				EndpointID      string `json:"endpoint_id"`
				ConnectionState string `json:"connection_state"`
			} `json:"data"`
		}
		if err := json.Unmarshal(body, &envelope); err != nil {
			return err
		}
		for _, item := range envelope.Data {
			if item.EndpointID == "endpoint-1" {
				if item.ConnectionState != "online" {
					return fmt.Errorf("endpoint-1 connection_state=%q, want online", item.ConnectionState)
				}
				return nil
			}
		}
		return fmt.Errorf("endpoint-1 is missing from the endpoint list: %s", body)
	})
}
