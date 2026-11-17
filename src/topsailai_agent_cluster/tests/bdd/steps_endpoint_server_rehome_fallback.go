package bdd

import (
	"fmt"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// fallbackWait is the budget for one fallback transition.
//
// It is generous because the transition crosses a process boundary twice: the
// Endpoint must notice the failure, walk the address list, complete a TLS
// handshake and publish an inventory report. A tighter budget would turn a slow
// machine into a failure that reads like a defect.
const fallbackWait = 60 * time.Second

// unhealthyWait is the budget for the Endpoint to declare a frozen Server
// unhealthy.
//
// It is longer than fallbackWait because the decision itself takes time: the
// production rule is a 5s heartbeat period, a 3s acknowledgement timeout and a
// 30s window of consecutive failures, so the Endpoint cannot decide before 30s
// have passed. A budget shorter than that window would fail a correct build and
// read like a defect.
const unhealthyWait = 90 * time.Second

// switchBackWindow is how long a restored first Server is observed before
// concluding that it did not pull the Endpoint back.
//
// It must exceed the unhealthy window, because a build that switched back on a
// timer would most plausibly do so at that cadence. A shorter window would pass
// for a build that switches back a moment later, which is exactly the behaviour
// this scenario exists to forbid.
const switchBackWindow = 45 * time.Second

// heartbeatTimeoutLog is the Endpoint's own record that a heartbeat was not
// acknowledged in time.
//
// It is the only direct evidence that the Endpoint decided the Server was
// unhealthy rather than merely noticing a closed socket. A frozen Server keeps
// every socket open, so no read ever fails and no transport error is ever
// logged; the decision can only appear as a heartbeat failure.
const heartbeatTimeoutLog = "heartbeat acknowledgement timed out"

// startFallbackCluster starts a real cluster with a second independent Server
// behind its own proxy, a proxy in front of the primary Server, and the
// Endpoint's own log.
//
// Each option is required by the scenarios and none of them is a shortcut around
// the behaviour under test:
//
//   - the second Server is the fallback destination, and it must own its own
//     database so it cannot already know the primary Server's state;
//   - the primary proxy is the only way to force a real reconnect without
//     stopping the primary Server, and the reconnect is what advances its fence;
//   - the second proxy is the only way to make the second Server stop answering
//     while its process stays alive, which is the only shape that proves the
//     Endpoint decided the Server was unhealthy;
//   - the log is the only place a reconnect, a refused address or a heartbeat
//     timeout is observable.
func startFallbackCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		ChannelDirection:      "endpoint-initiated",
		SecondServer:          true,
		ChannelProxy:          true,
		SecondaryChannelProxy: true,
		EndpointLogFile:       true,
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	return nil
}

// registerEndpointServerRehomeFallbackSteps registers the fallback scenarios.
func registerEndpointServerRehomeFallbackSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster in the endpoint-initiated channel direction with a second server behind a proxy$`, func() error {
		activeScenario.world = &World{}
		return startFallbackCluster()
	})
	ctx.Step(`^the primary server stops$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The Endpoint is deliberately not restarted: a restarted Endpoint would
		// never have held the dead Server's generation and would prove nothing.
		return cluster.StopPrimaryServerE()
	})
	ctx.Step(`^the endpoint reports the refused primary address as a failed attempt$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The Endpoint's own log is the only place a failed attempt is observable.
		// Without this assertion the scenario would pass for a build that never
		// tried the primary address at all, because reaching the second Server is
		// true either way.
		//
		// The address is the one the Endpoint actually dialled, which is the proxy
		// address when a proxy sits in front of the primary Server. Asserting the
		// Server's own address would never match, because the Endpoint never dials
		// it in that shape.
		return cluster.WaitEndpointLogE(cluster.PrimaryDialAddress(), fallbackWait)
	})
	ctx.Step(`^the primary server stops and the endpoint re-homes to the second server$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		if err := cluster.StopPrimaryServerE(); err != nil {
			return err
		}
		if err := cluster.WaitSecondaryEndpointOnlineE(fallbackWait); err != nil {
			return err
		}
		// The offset is recorded here, at the last moment before the first Server
		// is restored, because the switch-back assertion must search only the bytes
		// written after the restore. The log is append-only for the life of the
		// process tree, so a plain substring search would match the reconnect that
		// produced this very re-home and pass before the event under test happened.
		offset, err := cluster.EndpointLogOffset()
		if err != nil {
			return err
		}
		activeScenario.rehomeLogOffset = offset
		return nil
	})
	ctx.Step(`^the primary server is restored and answers health checks$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// A restart keeps the database and therefore the Server's durable identity,
		// while the in-memory fence starts again at 1. Startup also marks every
		// persisted online row offline, so the primary Server reports the Endpoint
		// offline until a real link is installed. That is what makes "the primary
		// server reports the endpoint online" discriminating: it can only become
		// true through an actual reconnect.
		return cluster.StartPrimaryServerE()
	})
	ctx.Step(`^the second server stops answering without closing its connections$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// Freezing is the only shape that discriminates. Stopping the second Server
		// would close its sockets, the Endpoint's read would fail immediately, and a
		// build with no liveness detection would reconnect and pass. A frozen Server
		// keeps every socket open and discards every byte, so the Endpoint can only
		// recover by deciding the Server is unhealthy.
		return cluster.FreezeSecondaryE()
	})
	ctx.Step(`^the endpoint reports the second server as unhealthy$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The Endpoint's own log is the only direct evidence of the decision. A
		// frozen Server produces no transport error, so without this assertion the
		// scenario could only observe the eventual reconnect, which a build that
		// reconnects for an unrelated reason would also produce.
		return cluster.WaitEndpointLogE(heartbeatTimeoutLog, unhealthyWait)
	})
	ctx.Step(`^the primary server reports the endpoint online$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The primary Server is the only authority for whether the Endpoint came
		// back, so the assertion reads that Server's own endpoint list instead of
		// inferring connectivity from the Endpoint's log.
		return cluster.WaitEndpointOnlineE(unhealthyWait)
	})
	ctx.Step(`^the endpoint does not attempt a reconnect within the observation window$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The final online state cannot discriminate here: whether the Endpoint
		// never attempted a switch-back or attempted one and was refused, the second
		// Server still reports it online. Only the absence of a new reconnect line
		// proves that no attempt was made.
		return cluster.AssertNoReconnectAfterE(activeScenario.rehomeLogOffset, switchBackWindow)
	})
	ctx.Step(`^the second server still reports the endpoint online$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		return cluster.WaitSecondaryEndpointOnlineE(fallbackWait)
	})
}
