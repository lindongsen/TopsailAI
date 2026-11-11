---
maintainer: AI
author: DawsonLin
status: specification
---

# Feature: Live failures remain visible, bounded, and recoverable

## Background

Given environment, inventory, and basic command scenarios passed
And every process disruption targets an exact test-owned process ID or service instance
And the operator has a rollback path for policy and allowlist changes
And durable command status can be queried after reconnect

## Scenario RES-LIVE-001: Offline Endpoint rejects new mutating commands

Given a registered Endpoint is offline
When the CLI submits a new mutating command for it
Then the Server returns `endpoint_unavailable` or the documented offline result
And the command is not silently queued for later execution
And no provider side effect occurs after reconnect

## Scenario RES-LIVE-002: Unknown Endpoint is distinct from an offline Endpoint

Given one requested Endpoint ID was never registered
And another registered Endpoint is currently offline
When the CLI addresses each target
Then the unknown target returns `endpoint_not_found`
And the offline target returns `endpoint_unavailable` or `endpoint_offline`
And neither result is reported as `policy_denied`

## Scenario RES-LIVE-003: Disconnect interrupts follow rather than completing it

Given an authorized output follow is active
When the exact Endpoint channel disconnects
Then the Server terminates the pending follow with `endpoint_offline`
And the client reports an interrupted stream
And absence of the Endpoint terminal frame is never interpreted as clean completion
And the follow resource is released

## Scenario RES-LIVE-004: Crash before provider invocation can recover and execute once

Given an admitted command is durably recorded by the Endpoint before provider invocation
When the Endpoint crashes before invocation and later restarts
Then recovery may execute the retained command once if its authority and validity remain provable
And the provider invocation count is exactly one
And the final durable result is queryable

## Scenario RES-LIVE-005: Crash after invocation starts does not replay uncertain effects

Given provider invocation started but no reliable result was persisted
When the Endpoint crashes and reconnects
Then the command converges to unknown or unconfirmed effect evidence
And the provider operation is not replayed automatically
And a new operator decision requires a new command ID

## Scenario RES-LIVE-006: Lost result acknowledgement converges without re-execution

Given the Endpoint persisted a provider result
And its acknowledgement to the Server was lost
When the channel reconnects and the command is reconciled
Then the persisted result is returned
And the provider is not invoked again
And command identity and target remain unchanged

## Scenario RES-LIVE-007: Command expiry prevents late execution

Given an admitted mutating command expires before Endpoint invocation
When dispatch or recovery occurs after expiry
Then the Endpoint refuses execution
And effect certainty is `not_applied`
And the provider is not invoked

## Scenario RES-LIVE-008: Invocation timeout preserves unknown effects

Given the provider invocation exceeds its execution budget after delivery may have occurred
When the Endpoint terminates only the owned provider command process group
Then the command becomes unconfirmed or otherwise records unknown effect certainty
And it is not reported as definitely failed or not applied
And no automatic retry occurs

## Scenario RES-LIVE-009: Storage failure preserves the prior inventory

Given the Server has a valid committed inventory
And the next inventory write encounters a controlled storage failure
When the Endpoint submits the report
Then acknowledgement reports failure
And the prior document remains readable
And no inventory-changed success event is emitted
And retrying the same immutable revision is possible after storage recovery

## Scenario RES-LIVE-010: Reconnect reloads latest state without Session history replay

Given the CLI or Endpoint disconnects after a committed inventory update
When connectivity returns
Then the current latest state is reloaded
And missed invalidation notifications do not require replaying old Session payloads
And command status recovery remains independent of inventory refresh

## Scenario RES-LIVE-011: Cleanup removes only live-test resources

Given the suite created sessions, drive controllers, output follows, temporary policies, and command records eligible for cleanup
When cleanup runs through documented exact-target operations
Then all test-created transient resources are released or explicitly retained with a reason
And the unrelated sentinel session remains unchanged
And policy and allowlist configuration are restored and revalidated
And no process is terminated by broad name matching

## Scenario RES-LIVE-012: Final evidence and secret audit closes the run

Given all planned scenarios have a recorded result
When the operator reviews the report and temporary evidence
Then every FAIL, BLOCKED, UNSUPPORTED, and NOT RUN item has an explanation
And no clear Server token, Endpoint token, private key, full prompt, or sensitive conversation content is present
And temporary evidence follows the configured retention or deletion procedure
And the final report records component versions, topology, autonomous deviations, and unresolved risks
