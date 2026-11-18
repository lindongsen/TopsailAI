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
//
// dropAcknowledgement makes the Server persist a receipt without telling the
// Endpoint it did. The rejection scenarios need it: an acknowledged receipt is
// settled immediately, so it is never re-sent and the Server never gets the chance
// to refuse it. Dropping the acknowledgement reproduces the only state in which a
// rejection can happen, which is a receipt the Endpoint still holds because it
// never learned the Server stored it.
func startReceiptCluster(secondServer, dropAcknowledgement bool) error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		ChannelDirection: "endpoint-initiated",
		SecondServer:     secondServer,
		EndpointLogFile:  true,
		Faults:           harness.FaultInjection{DropAck: dropAcknowledgement},
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	return nil
}

// assertSettledAsRejection fails unless the receipt was settled by a rejection
// carrying exactly the expected reason.
//
// The origin is asserted as well as the reason, because an acknowledgement stores
// no reason at all. A scenario that checked only the reason would read an empty
// string for an acknowledgement and therefore could not tell the two terminal
// outcomes apart, which is the whole subject of this feature.
func assertSettledAsRejection(commandID, wantReason string) error {
	cluster := activeScenario.world.realCluster
	if cluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	settlement, err := cluster.WaitReceiptSettledOriginE(commandID, receiptSettleWait)
	if err != nil {
		return err
	}
	if settlement.Origin != "rejection" {
		return fmt.Errorf("settlement origin for %q = %q, want %q", commandID, settlement.Origin, "rejection")
	}
	if settlement.Reason != wantReason {
		return fmt.Errorf("settlement reason for %q = %q, want %q", commandID, settlement.Reason, wantReason)
	}
	return nil
}

// registerEndpointServerRehomeReceiptSteps registers the receipt-settlement
// re-home scenarios.
func registerEndpointServerRehomeReceiptSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a second server for receipt settlement whose acknowledgement is lost$`, func() error {
		activeScenario.world = &World{}
		return startReceiptCluster(true, true)
	})
	ctx.Step(`^a real cluster with a receipt settlement journal whose acknowledgement is lost$`, func() error {
		activeScenario.world = &World{}
		return startReceiptCluster(false, true)
	})
	ctx.Step(`^a real cluster with a receipt settlement journal whose acknowledgement is delivered$`, func() error {
		activeScenario.world = &World{}
		return startReceiptCluster(false, false)
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
		return assertSettledAsRejection(activeScenario.realCommandID, "unknown_command")
	})
	ctx.Step(`^the endpoint settles the receipt as acknowledged$`, func() error {
		cluster := activeScenario.world.realCluster
		if cluster == nil {
			return fmt.Errorf("real cluster is not running")
		}
		settlement, err := cluster.WaitReceiptSettledOriginE(activeScenario.realCommandID, receiptSettleWait)
		if err != nil {
			return err
		}
		if settlement.Origin != "acknowledgement" {
			return fmt.Errorf("settlement origin for %q = %q, want %q", activeScenario.realCommandID, settlement.Origin, "acknowledgement")
		}
		// An acknowledgement carries no rejection reason, so the stored reason must
		// be absent rather than an empty string that a reader could mistake for a
		// rejection with an unnamed cause.
		if settlement.Reason != "" {
			return fmt.Errorf("settlement reason for %q = %q, want no reason because an acknowledgement carries none", activeScenario.realCommandID, settlement.Reason)
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
		//
		// The check is skipped when the cluster has no second Server, because there
		// is then no second log to read and the resend set is the only available
		// evidence.
		if cluster.SecondaryLogPath == "" {
			return nil
		}
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
		return assertSettledAsRejection(activeScenario.realCommandID, "revision_stale")
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
