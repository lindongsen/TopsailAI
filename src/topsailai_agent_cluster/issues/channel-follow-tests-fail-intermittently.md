---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# `internal/channel` follow tests fail intermittently with transport errors

## Trigger

`make test-unit` failed twice while verifying an unrelated change to the message-count
reporting path. The failures were in `internal/channel`, which that change never touched.

## Observed behaviour

Two consecutive `make test-unit` runs failed with different tests each time:

| Run | Failing test | Reported error |
|---|---|---|
| 1 | `TestFollowDeliversAFullTailToASlowConsumer` | `a healthy consumer was reported as "endpoint_offline" after 18 of 300 records` |
| 1 | `TestFollowOverflowEndsStreamWithExplicitCode` | `end code="endpoint_offline"` |
| 2 | `TestFollowDeliversAFullTailToASlowConsumer` | `write tcp 127.0.0.1:58112->127.0.0.1:35417: write: connection reset by peer` |
| 2 | `TestRequestFollowOverflowSendsCancelFrame` | `write tcp 127.0.0.1:41208->127.0.0.1:37205: write: broken pipe` |

The error text is transport-level, and the failing test changes between runs, which is the
signature of a timing or resource race rather than a deterministic defect.

## Reproduction rate

Five consecutive runs of `go test ./internal/channel/ -count=1` on the working tree:

| Run | Result |
|---|---|
| 1 | pass |
| 2 | pass |
| 3 | fail |
| 4 | pass |
| 5 | fail |

Failures across those runs: `TestFollowOverflowEndsStreamWithExplicitCode` (2),
`TestRequestFollowOverflowSendsCancelFrame` (1), `TestRunHeartbeatKeepsAcknowledgedServerHealthy` (1).

## Proven pre-existing

The same five runs were executed in a detached worktree at HEAD `47e62683`, with no
working-tree changes present:

| Run | Result |
|---|---|
| 1 | fail |
| 2 | fail |
| 3 | pass |
| 4 | fail |
| 5 | fail |

Failures at HEAD: `TestFollowOverflowEndsStreamWithExplicitCode` (3),
`TestRequestFollowOverflowSendsCancelFrame` (3),
`TestFollowDeliversAFullTailToASlowConsumer` (1),
`TestRunHeartbeatKeepsAcknowledgedServerHealthy` (1).

HEAD fails 4 of 5 runs with the same test set, so the flakiness predates the change under
verification and is not caused by it.

## Impact

`make test-unit` cannot be used as a pass/fail gate while this is true. A genuine regression in
`internal/channel` would be indistinguishable from this noise, and the natural response to a
red suite is to re-run until green, which is exactly how a real defect gets waved through.

## Suspected cause (not yet investigated)

The failures all involve a follow stream ending with `endpoint_offline` or a write failing with
`connection reset by peer` / `broken pipe`. Both point at the peer being torn down while a
writer still holds the connection. Candidate sites are the follow terminal-frame path and the
heartbeat liveness sweep, which can close a peer that a test is still writing to.

This is a hypothesis, not a finding. It must be confirmed by reading the teardown path and by
observing which side closes first, not by inference from the error text.

## Fix direction (not yet decided)

- Determine whether the tests race the liveness sweep, in which case the test needs to
  synchronize after setup rather than assume the peer stays installed.
- Or determine whether the follow writer can outlive the connection it writes to, in which case
  the production path needs the writer to observe closure before writing.
- Do not widen timeouts to hide the race. A timeout change would make the suite green while
  leaving the underlying ordering defect in place.

## Verification limitation

The reproduction counts above are from one host under concurrent load from other agents working
in the same workspace, so the absolute failure rate is not a stable number. The comparison that
matters is the paired one: the working tree and HEAD fail at a similar rate with the same tests,
which is what establishes that the flakiness is pre-existing.
