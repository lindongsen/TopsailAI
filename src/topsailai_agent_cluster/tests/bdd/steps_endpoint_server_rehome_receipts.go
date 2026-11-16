package bdd

import (
	"fmt"
	"time"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// receiptSettleWait is the budget for one settlement decision.
//
// It is generous because the decision is made on the Endpoint's own channel loop
// after a reconnect, and a reconnect crosses a process boundary: the Endpoint must
// notice the transport failure, walk to the next address, complete a TLS handshake
// and only then reconcile the Server identity and re-send receipts.
const receiptSettleWait = 60 * time.Second

// startReceiptCluster starts a real cluster whose Endpoint writes its own log.
//
// The log is required by every scenario in this feature, because the absence of a
// settlement row is only meaningful once the rejection was actually received. A
// scenario that asserted only on the table would pass for a build that never
// reconnected at all.
func startReceiptCluster(secondServer bool) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		ChannelDirection: "endpoint-initiated",
		SecondServer:     secondServer,
		EndpointLogFile:  true,
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	return nil
}

// registerEndpointServerRehomeReceiptSteps registers the receipt-settlement
// re-home scenarios.
func registerEndpointServerRehomeReceiptSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a second server for receipt settlement$`, func() error {
		activeScenario.world = &World{}
		return startReceiptCluster(true)
	})
	ctx.Step(`^a real cluster with a receipt settlement journal$`, func() error {
		activeScenario.world = &World{}
		return startReceiptCluster(false)
	})
	ctx.Step(`^a command has been executed and its receipt recorded$`, func() error {
		commandID, err := activeScenario.world.SubmitRealCommand("message.send", "fixture-session", "fixture-generation", `{"text":"settle"}`)
		if err != nil {
			return err
		}
		activeScenario.realCommandID = commandID
		// The receipt must exist in the Endpoint journal before the scenario acts on
		// it, so the command is driven to a terminal state first. A scenario that
		// acted earlier would assert on a journal row that had not been written yet.
		status, err := activeScenario.world.PollRealCommand(commandID, 10*time.Second)
		if status != nil {
			activeScenario.realCommandStatus = status
		}
		if err != nil {
			return err
		}
		if statusName := commandStatus(status); !isTerminalCommandStatus(statusName, commandEffectCertainty(status)) {
			return fmt.Errorf("command is not terminal: %#v", status)
		}
		return nil
	})
	ctx.Step(`^the endpoint re-homes to a second server that never admitted the command$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// Stopping the primary Server is the re-home trigger here. The Endpoint is
		// deliberately not restarted: a restarted Endpoint would start with an empty
		// journal and would prove nothing about settling a receipt it still holds.
		if err := cluster.StopServerE(); err != nil {
			return err
		}
		return cluster.WaitSecondaryEndpointOnlineE(receiptSettleWait)
	})
	ctx.Step(`^the endpoint settles the receipt as unknown command$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		reason, err := cluster.WaitReceiptSettledE(activeScenario.realCommandID, receiptSettleWait)
		if err != nil {
			return err
		}
		if reason != "unknown_command" {
			return fmt.Errorf("settlement reason for %q = %q, want %q", activeScenario.realCommandID, reason, "unknown_command")
		}
		return nil
	})
	ctx.Step(`^the endpoint no longer re-sends the settled receipt$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The resend set must be empty, so the receipt cannot be sent again.
		count, err := cluster.RecordedReceiptCountE()
		if err != nil {
			return err
		}
		if count != 0 {
			return fmt.Errorf("recorded receipts after settlement = %d, want 0", count)
		}
		// The resend set alone is not enough. A build that never settled anything
		// would still empty the set once the second Server refused the receipt, so
		// the second Server's own log is the only evidence that the receipt was
		// never sent at all. This is what distinguishes bulk settlement from the
		// per-receipt rejection path, which reaches the same final state.
		rejections, err := cluster.CountSecondaryLogOccurrences("store command receipt")
		if err != nil {
			return err
		}
		if rejections != 0 {
			return fmt.Errorf("the second Server received %d receipt(s) for a command it never admitted, so the Endpoint sent a receipt it already knew could not be applied", rejections)
		}
		return nil
	})
	ctx.Step(`^the server restarts and the endpoint reconnects to the same server$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		offset, err := cluster.EndpointLogOffset()
		if err != nil {
			return err
		}
		// A restart keeps the database and therefore the Server's durable identity,
		// while the in-memory fence starts again at 1.
		if err := cluster.RestartServerE(); err != nil {
			return err
		}
		// The reconnect is observed from the Endpoint's own log, and only in the bytes
		// written after the restart. Without this the following "settles no receipt"
		// assertion would pass for a build that never reconnected at all.
		return cluster.WaitEndpointLogAfterE(offset, "endpoint channel reconnected", receiptSettleWait)
	})
	ctx.Step(`^the endpoint settles no receipt$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		return cluster.AssertReceiptNotSettledE(activeScenario.realCommandID, receiptSettleWait)
	})
	ctx.Step(`^the server stores a newer revision of that receipt$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// The Endpoint always submits revision 1, so a stale revision can only be
		// produced by raising what the Server already stores. The Server is stopped
		// first, because writing to a live SQLite file from a second process would
		// contend with the Server's own writes.
		if err := cluster.StopServerE(); err != nil {
			return err
		}
		if err := cluster.RewriteStoredReceiptE(activeScenario.realCommandID, 2, ""); err != nil {
			return err
		}
		// The rewrite is proven to have landed before the Endpoint's reaction is
		// asserted, so a failed rewrite cannot be mistaken for a correct rejection.
		revision, err := cluster.StoredReceiptRevisionE(activeScenario.realCommandID)
		if err != nil {
			return err
		}
		if revision != 2 {
			return fmt.Errorf("stored revision after rewrite = %d, want 2", revision)
		}
		return cluster.RestartServerE()
	})
	ctx.Step(`^the endpoint settles the receipt as revision stale$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		reason, err := cluster.WaitReceiptSettledE(activeScenario.realCommandID, receiptSettleWait)
		if err != nil {
			return err
		}
		if reason != "revision_stale" {
			return fmt.Errorf("settlement reason for %q = %q, want %q", activeScenario.realCommandID, reason, "revision_stale")
		}
		return nil
	})
	ctx.Step(`^the server stores a different receipt at the same revision$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		offset, err := cluster.EndpointLogOffset()
		if err != nil {
			return err
		}
		activeScenario.rehomeLogOffset = offset
		if err := cluster.StopServerE(); err != nil {
			return err
		}
		// The revision is left at 1 and only the content changes, which is the one
		// shape that produces an integrity conflict rather than a stale revision.
		if err := cluster.RewriteStoredReceiptE(activeScenario.realCommandID, 1, "conflicting-outcome"); err != nil {
			return err
		}
		revision, err := cluster.StoredReceiptRevisionE(activeScenario.realCommandID)
		if err != nil {
			return err
		}
		if revision != 1 {
			return fmt.Errorf("stored revision after rewrite = %d, want 1", revision)
		}
		return cluster.RestartServerE()
	})
	ctx.Step(`^the endpoint reports the rejection as kept pending$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		// This is the load-bearing assertion for the conflict scenario. "Settles no
		// receipt" alone would pass for a build that never received a rejection, so
		// the rejection itself must be observed, and only in the bytes written after
		// the restart.
		return cluster.WaitEndpointLogAfterE(activeScenario.rehomeLogOffset, "receipt rejection kept pending", receiptSettleWait)
	})
}
