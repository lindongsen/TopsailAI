package bdd

import (
	"fmt"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// rehomeWait is the budget for one re-home transition. It is generous because a
// re-home crosses a process boundary: the Endpoint must notice the transport
// failure, walk to the next address, complete a TLS handshake and publish an
// inventory report. A tighter budget would turn a slow machine into a failure
// that reads like a defect.
const rehomeWait = 60 * time.Second

// startRehomeCluster starts a real cluster with a second independent Server, a
// channel proxy in front of the primary Server, and the Endpoint's own log.
//
// All three are required by the connection-layer scenarios and none of them is a
// shortcut around the behaviour under test:
//
//   - the second Server is the destination of the re-home, and it must own its own
//     database so it cannot already know the primary Server's state;
//   - the proxy is the only way to force a real reconnect without stopping the
//     primary Server, and the reconnect is what advances its fence;
//   - the log is the only place a reconnect or a superseded rejection is
//     observable, so without it the discriminating assertion cannot be made.
func startRehomeCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		ChannelDirection: "endpoint-initiated",
		SecondServer:     true,
		ChannelProxy:     true,
		EndpointLogFile:  true,
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	return nil
}

// registerEndpointServerRehomeConnectionSteps registers the connection-layer
// re-home scenarios.
func registerEndpointServerRehomeConnectionSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster in the endpoint-initiated channel direction with a second server$`, func() error {
		activeScenario.world = &World{}
		return startRehomeCluster()
	})
	ctx.Step(`^the endpoint holds a generation higher than the second server will assign$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The precondition is proven, not assumed. Without it the second Server
		// would hand out the same generation the Endpoint already holds, and the
		// scenario would pass even with the connection-layer fix absent.
		return cluster.AdvanceFenceE(rehomeWait)
	})
	ctx.Step(`^the endpoint re-homes to the second server$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// Closing the proxy removes the primary Server's path entirely, so the
		// Endpoint must walk to the next configured address on its own. The
		// Endpoint is deliberately not restarted: a restarted Endpoint would never
		// have held the dead Server's generation and would prove nothing.
		cluster.ChannelProxy.Close()
		return nil
	})
	ctx.Step(`^the second server reports the endpoint online$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		return cluster.WaitSecondaryEndpointOnlineE(rehomeWait)
	})
	ctx.Step(`^the second server accepts an inventory report from the endpoint$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// A connection that cannot serve inventory would look online and be
		// useless, so the re-home must be proven to carry data, not only a socket.
		return cluster.WaitSecondaryInventoryE(rehomeWait)
	})
	ctx.Step(`^the endpoint does not report a superseded connection$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		return cluster.AssertNoSupersededRejectionE()
	})
	ctx.Step(`^the server restarts and assigns a lower generation again$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// A restart keeps the database and therefore the Server's durable identity,
		// while the in-memory fence starts again at 1. That combination is exactly
		// the case a restarted Server presents to an Endpoint that still holds a
		// higher generation.
		return cluster.RestartServerE()
	})
	ctx.Step(`^the endpoint reconnects to the restarted server$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The reconnect is observed from the Endpoint's own log, because the
		// Server's endpoint list would report the Endpoint online from the
		// persisted row even while no link exists.
		return cluster.WaitEndpointLogE("endpoint channel reconnected", rehomeWait)
	})
}
