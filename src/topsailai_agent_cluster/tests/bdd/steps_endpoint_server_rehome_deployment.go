package bdd

import (
	"fmt"
	"strings"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// deploymentWait is the budget for one deployment-shape transition.
//
// It is generous because every scenario here crosses a process boundary: the
// Endpoint must start, complete a TLS handshake and publish an inventory report,
// and in the re-home cases it must also notice a transport failure and walk to
// the next address. A tighter budget would turn a slow machine into a failure
// that reads like a defect.
const deploymentWait = 60 * time.Second

// inFlightHoldMS is how long the mock provider holds one execute call.
//
// It must be long enough that the re-home happens while the call is still open,
// and short enough that the Endpoint's own execute budget is what ends the call
// rather than the adapter timeout. The Endpoint's budget is the intent deadline,
// which the in-flight scenario sets to 6s, so the hold sits above it: the call is
// still open when the deadline passes, which is exactly the state the scenario
// must observe.
const inFlightHoldMS = 9000

// inFlightDeadline is the command deadline for the in-flight scenario.
//
// It is shorter than inFlightHoldMS on purpose. The Endpoint's execute budget is
// the intent deadline, so a deadline shorter than the hold is what makes the
// command still executing when the deadline passes, instead of the provider
// finishing first and the scenario proving nothing about an in-flight command.
const inFlightDeadline = 6 * time.Second

// startDeploymentCluster starts a real cluster for one deployment shape.
//
// Each option is required by the shape it serves and none of them is a shortcut
// around the behaviour under test:
//
//   - NoEndpointDialAddress omits the address entirely, which is the only way to
//     prove an Endpoint with no configured Server waits instead of dialling;
//   - UnreachableFirstAddress puts a dead address first, which is the only way to
//     prove the walk continues past a failure rather than stopping at it;
//   - SecondServer gives the re-home scenarios a destination that owns its own
//     database, so it cannot already know the primary Server's state.
func startDeploymentCluster(options harness.ClusterOptions) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	cluster, err := harness.StartCluster(activeTest, options)
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	return nil
}

// registerEndpointServerRehomeDeploymentSteps registers the deployment-shape
// re-home scenarios.
func registerEndpointServerRehomeDeploymentSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster where the server dials the endpoint$`, func() error {
		activeScenario.world = &World{}
		return startDeploymentCluster(harness.ClusterOptions{
			ChannelDirection:      "server-initiated",
			NoEndpointDialAddress: true,
			// The absence of an address is only observable in the Endpoint's own
			// log, so this scenario must capture it. Reaching online is true whether
			// the address was omitted or merely pointed at a Server that answered.
			EndpointLogFile: true,
		})
	})
	ctx.Step(`^the endpoint reports online without a configured server address$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The assertion reads the Server's own endpoint list, because a process
		// that started and never connected would otherwise look like a pass. The
		// Endpoint has no address at all in this shape, so the only way it can
		// appear online is that the Server dialled it.
		return cluster.WaitEndpointOnlineE(deploymentWait)
	})
	ctx.Step(`^the server accepts an inventory report from the endpoint$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// A connection that cannot serve inventory would look online and be
		// useless, so the shape is proven by a published report rather than by the
		// connection state alone.
		return harness.WaitInventoryE(cluster.URL("/api/v1/endpoints/endpoint-1/session-state"), "secret", deploymentWait)
	})
	ctx.Step(`^the endpoint reports that no server address is configured$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The Endpoint's own log is the only place the absence of an address is
		// observable. Reaching online is true whether the address was omitted or
		// merely pointed at a Server that happened to answer, so without this
		// assertion the scenario would pass for a build that still configured one.
		return cluster.WaitEndpointLogE("channel address is not configured", deploymentWait)
	})
	ctx.Step(`^a real cluster whose first configured address is unreachable$`, func() error {
		activeScenario.world = &World{}
		return startDeploymentCluster(harness.ClusterOptions{
			ChannelDirection:        "endpoint-initiated",
			UnreachableFirstAddress: true,
			// The failed attempt is only observable in the Endpoint's own log, so
			// this scenario must capture it. Without the log the assertion could
			// only prove that the working Server was reached, which is true whether
			// or not the dead address was ever tried.
			EndpointLogFile: true,
		})
	})
	ctx.Step(`^the endpoint reports online through the second address$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		return cluster.WaitEndpointOnlineE(deploymentWait)
	})
	ctx.Step(`^the endpoint reports the unreachable address as a failed attempt$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The Endpoint's own log is the only place a failed attempt is observable.
		// Without this assertion the scenario would pass for a build that never
		// tried the dead address at all, because reaching the working Server is
		// true either way.
		return cluster.WaitEndpointLogE("127.0.0.1:1", deploymentWait)
	})
	ctx.Step(`^a real cluster with a second server and a failing provider$`, func() error {
		activeScenario.world = &World{}
		return startDeploymentCluster(harness.ClusterOptions{
			ChannelDirection: "endpoint-initiated",
			SecondServer:     true,
			ChannelProxy:     true,
			EndpointLogFile:  true,
			// The fault is an execute failure, not a discovery failure. A discovery
			// failure would leave the second Server with no inventory at all, so the
			// scenario would fail while resolving its target and would prove nothing
			// about a provider fault surviving the re-home. ProviderFailAdapterID
			// keeps discovery working and makes the execute call itself fail, which
			// is the fault this scenario exists to observe.
			Faults: harness.FaultInjection{ProviderFailAdapterID: "fixture-main"},
		})
	})
	ctx.Step(`^the endpoint re-homes to the second server and reports online$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The precondition is proven before the re-home, because a re-home between
		// two fresh Servers compares generation 1 against generation 1 and would
		// pass even with the connection-layer fix absent.
		if err := cluster.AdvanceFenceE(deploymentWait); err != nil {
			return err
		}
		if cluster.ChannelProxy == nil {
			return fmt.Errorf("cluster has no channel proxy, so the primary Server cannot be removed")
		}
		// Closing the proxy removes the primary Server's path entirely, so the
		// Endpoint must walk to the next configured address on its own. The
		// Endpoint is deliberately not restarted: a restarted Endpoint would never
		// have held the dead Server's generation and would prove nothing.
		cluster.ChannelProxy.Close()
		if err := cluster.WaitSecondaryEndpointOnlineE(deploymentWait); err != nil {
			return err
		}
		// Every later read must address the Server that now owns the Endpoint. The
		// primary Server still runs, so a read that kept addressing it would return
		// the pre-move world and the scenario would fail while resolving its target
		// instead of proving anything about the provider fault.
		activeScenario.world.rehomedToSecondary = true
		return nil
	})
	ctx.Step(`^a command submitted after the re-home fails with the provider error$`, func() error {
		commandID, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"fault"}`)
		if err != nil {
			return err
		}
		activeScenario.realCommandID = commandID
		command, err := activeScenario.world.PollRealCommand(commandID, deploymentWait)
		if err != nil {
			return err
		}
		// A provider that reports not_applied is a rejection, not a failure: the
		// Server stores StatusRejected for that certainty, so asserting "failed"
		// would fail against a correct build and say nothing about the provider.
		status := stringValue(command, "status", "Status")
		if status != "rejected" {
			return fmt.Errorf("command status = %q, want %q, because the provider reported the effect was not applied", status, "rejected")
		}
		// The provider's own code is the only field that names the provider as the
		// cause. CommandRecord carries no provider_outcome field, so asserting one
		// would read an empty string and pass for a build that never reported the
		// fault at all.
		code := stringValue(command, "error_code", "ErrorCode")
		if code != "provider_error" {
			return fmt.Errorf("command error code = %q, want %q, so the provider failure was not reported", code, "provider_error")
		}
		return nil
	})
	ctx.Step(`^the failure names the provider rather than the connection$`, func() error {
		command, err := activeScenario.world.PollRealCommand(activeScenario.realCommandID, deploymentWait)
		if err != nil {
			return err
		}
		// The distinction is the whole point of the scenario: a re-home that broke
		// the connection would also produce a failure, so a scenario that only
		// asserted "the command failed" would pass for a broken transport and prove
		// nothing about the provider fault surviving the move.
		//
		// The provider's own words live in provider_response, not in an error
		// message field: CommandRecord carries ErrorCode and ProviderResponse, and
		// the adapter stores the provider's stderr there on a failed invocation. A
		// scenario that read an error_message field would read an empty string and
		// fail against a correct build.
		response := stringValue(command, "provider_response", "ProviderResponse")
		if response == "" {
			return fmt.Errorf("command carries no provider response, so the failure cannot be attributed to the provider")
		}
		if !strings.Contains(response, "mock execution failure") {
			return fmt.Errorf("provider response %q does not carry the provider's own failure text, so the failure cannot be attributed to the provider", response)
		}
		for _, transportFailure := range []string{"superseded", "connection refused", "endpoint_offline", "endpoint_unavailable"} {
			if strings.Contains(response, transportFailure) {
				return fmt.Errorf("provider response %q names a transport failure, so the command failed because of the re-home rather than the provider", response)
			}
		}
		return nil
	})
	ctx.Step(`^a real cluster with a second server and a slow provider$`, func() error {
		activeScenario.world = &World{}
		return startDeploymentCluster(harness.ClusterOptions{
			ChannelDirection: "endpoint-initiated",
			SecondServer:     true,
			ChannelProxy:     true,
			EndpointLogFile:  true,
			DelayMS:          inFlightHoldMS,
			// The adapter timeout is raised above the intent deadline so the
			// deadline is what ends the call. The adapter budget is
			// min(configured timeout, remaining deadline), so a configured timeout
			// below the deadline would end the call first and this scenario would
			// measure a timeout instead of a command still in flight.
			AdapterTimeoutMS: 20000,
			// The invocation is recorded before the hold, because the Endpoint
			// cancels this call at its own deadline. Without this the mock writes
			// its record only after the work finishes, so a cancelled call leaves
			// no trace and "the provider was invoked exactly once" would compare
			// zero with zero and pass while proving nothing.
			Faults: harness.FaultInjection{RecordBeforeDelay: true},
		})
	})
	ctx.Step(`^a command is submitted with a deadline shorter than the provider hold$`, func() error {
		commandID, err := activeScenario.world.SubmitRealCommandWithToken(commandSubmission{
			Operation:     "message.send",
			Target:        "fixture-session",
			Generation:    "fixture-generation",
			Payload:       `{"text":"in-flight"}`,
			ExecuteBefore: time.Now().Add(inFlightDeadline),
		})
		if err != nil {
			return err
		}
		activeScenario.realCommandID = commandID
		return nil
	})
	ctx.Step(`^the endpoint re-homes while the command is still executing$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		if err := cluster.AdvanceFenceE(deploymentWait); err != nil {
			return err
		}
		if cluster.ChannelProxy == nil {
			return fmt.Errorf("cluster has no channel proxy, so the primary Server cannot be removed")
		}
		cluster.ChannelProxy.Close()
		return cluster.WaitSecondaryEndpointOnlineE(deploymentWait)
	})
	ctx.Step(`^the command converges to unconfirmed with unknown effect$`, func() error {
		command, err := activeScenario.world.PollRealCommand(activeScenario.realCommandID, deploymentWait)
		if err != nil {
			return err
		}
		status := stringValue(command, "status", "Status")
		if status != "unconfirmed" {
			return fmt.Errorf("command status = %q, want %q, because the deadline passed while the provider call was still open", status, "unconfirmed")
		}
		certainty := stringValue(command, "effect_certainty", "EffectCertainty")
		if certainty != "unknown" {
			return fmt.Errorf("effect certainty = %q, want %q, because a command that was still executing when its deadline passed cannot claim its effect", certainty, "unknown")
		}
		return nil
	})
}
