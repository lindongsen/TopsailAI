---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# `logf` ends by itself after the adapter timeout

## Trigger

Reported by the human on 2026-11-20, wording normalized, meaning preserved:

> `logf` exits by itself after running for a while. What is the reason?

The human then supplied the exact terminal line:

> `log.follow> follow ended: cancelled`

## Symptom

A follow stream stops on its own after a fixed period with no operator action. The terminal shows
`log.follow> follow ended: cancelled`, the standalone command exits `0`, and the session being
watched is still running and still producing output.

## Measured evidence

One read-only follow against a live session on `ac.topsail`:

```text
agent-cluster-cli logf ac.topsail res_89664d749d3a639b6bf23d255944363e
exit=0 elapsed=120s
log.follow> follow ended: cancelled
```

The Endpoint log records the same event with the cause:

```text
"msg":"output follow failed","error_code":"cancelled",
"error":"cancelled: context deadline exceeded"
```

`/opt/agent-cluster/logs/endpoint/ac.topsail.log` contains this entry repeatedly, at every hour of
2026-11-19 and 2026-11-20, always with `error_code":"cancelled"` and
`error":"cancelled: context deadline exceeded"`.

## Root cause

A follow is bounded by the Adapter's per-call timeout, which is the same budget every other Provider
call uses. The deployed value is `timeout_ms: 120000` in
`/opt/agent-cluster/conf/endpoint/node.conf`, so every follow ends after two minutes.

The chain, in order:

1. `Adapter.request` (`internal/adapter/genericcli/adapter.go:743`) sets
   `deadline = now + a.config.Timeout` and puts it in the Provider request as `deadline_at_ms`.
   `a.config.Timeout` is `time.Duration(local.TimeoutMS) * time.Millisecond`
   (`src/main/agent-cluster-endpoint/adapter_factory.go:140`).
2. `processRunner.invokeStream` (`internal/adapter/genericcli/runner.go:115`) bounds the child with
   `invocationContext(parent, r.config.timeout, request.DeadlineAtMS)`, so the Provider process is
   killed at that deadline.
3. The Provider CLI bounds its own follow by the same value:
   `followRequestContext` (`providers/topsailai/src/follow.go:74-78`) computes
   `remaining = deadline_at_ms - now - 250ms` and applies it as a context timeout.
4. When that context expires, `streamError` (`providers/topsailai/src/follow.go:106-110`) maps
   `context.DeadlineExceeded` to the code `cancelled`, and the Provider writes it in its terminal
   frame.
5. The Endpoint preserves the Provider's own code
   (`internal/endpoint/follow.go:121-127`), so the stream ends with `cancelled` rather than
   `provider_error`.
6. The TUI renders it as `log.follow> follow ended: cancelled`
   (`internal/tui/follow.go:130`).

The code is therefore correct at every layer. The defect is that a follow, which is by definition
open-ended, is bounded by a budget that was chosen for one-shot calls.

## Why the message is misleading

`cancelled` reads as "someone stopped it". Nobody did. The Provider maps its own deadline expiry to
`cancelled` because it cannot distinguish "the caller cancelled me" from "my own budget ran out", and
the Endpoint forwards that code unchanged. The operator therefore sees a stop they did not request,
with no hint that a timeout caused it.

## Why it is not the record budget

An earlier defect ended long follows at 128 records. That bound was removed:
`scanStream` (`internal/adapter/genericcli/runner.go:199-204`) deliberately does not accumulate a
record count, and `TestInvokeStreamCompletesAStreamLongerThanMaxRecords` pins that a healthy stream
longer than `max_records` completes. The current stop is time-based, not count-based, which is why it
happens after a fixed duration regardless of how much output arrived.

## Impact

- A follow cannot outlive the Adapter timeout, so watching a long-running agent is impossible without
  re-issuing `logf` every two minutes.
- The stop is reported as `cancelled`, so the operator cannot tell a timeout from a real cancellation
  and may investigate the wrong component.
- The standalone command exits `0`, so a script that follows output treats a truncated stream as a
  successful run.

## Candidate directions

Not yet decided; recorded for the human to choose.

1. Give follow its own budget, separate from the one-shot call timeout, and report the expiry as a
   distinct code such as `follow_timeout` so the message names the real cause.
2. Keep the Adapter timeout as the outer bound but have the Endpoint re-arm the stream, so a follow
   survives by reconnecting rather than by widening one call's budget.
3. Report the expiry honestly without changing the lifetime, so at minimum the operator reads
   `follow ended: timeout` instead of `cancelled`.

Direction 1 changes one budget and one code. Direction 2 adds reconnect state to a stream the protocol
currently treats as one bounded request. Direction 3 is the smallest change and fixes only the
diagnosis.

## Resolution

Resolved by `efbca422` ("fix: bound a follow by its own budget and report expiry as
follow_timeout"), which implements candidate direction 1. Verified on the deployed build
`f721174e`, which contains that commit.

### What changed

- A follow is bounded by `FollowTimeout`, not by the one-shot call `Timeout`. `budgetFor`
  (`internal/adapter/genericcli/adapter.go:841-853`) returns `FollowTimeout` for
  `follow_output` only; every other function keeps the one-shot budget, because a command or a
  read must not occupy a slot for as long as an operator happens to watch a tail.
- The default is 30 minutes (`internal/config/config.go:190`), configurable through
  `AGENT_CLUSTER_ENDPOINT_FOLLOW_TIMEOUT` or `--follow-timeout`
  (`internal/config/config.go:381,488`). A zero value falls back to the Adapter call timeout, so
  an Endpoint that configures nothing keeps the previous behaviour rather than an unbounded
  stream.
- Expiry is reported as `follow_timeout`, distinct from `cancelled`, at both layers that can
  observe it: `internal/endpoint/follow.go:118,125,132` and
  `providers/topsailai/src/follow.go:113-114`. `cancelled` now means only that a consumer
  stopped the stream, which is the distinction the "Why the message is misleading" section
  asked for.

### Verification

The deployed `node.conf` sets no `FOLLOW_*` key and the running Endpoint passes no
`--follow-timeout` flag, so the 30-minute default is in force.

A live follow against `ac.ai-dev` outlived the previous 120-second bound:

```text
agent-cluster-cli logf ac.ai-dev res_50da448edfd53f9b19032af9354c290e
exit=124 elapsed=150s bytes=82132
(no "follow ended" line: the stream was still running when the harness stopped it)
```

The stream produced no self-termination line and no follow failure was logged during that
window. The last `cancelled: context deadline exceeded` entry in
`/opt/agent-cluster/logs/endpoint/ac.topsail.log` is `2026-11-20T21:17:58`, before the deployed
build; no `follow_timeout` entry exists because no follow has yet reached the new 30-minute
bound.

### Remaining gap

The 30-minute lifetime is verified manually, not pinned by an automated test. The budget
selection is covered indirectly by the adapter tests, but no test asserts the end-to-end
lifetime. A future change that reintroduced the shared budget would be caught by
`TestStartFollowReportsBudgetExpiryAsFollowTimeout`
(`internal/endpoint/follow_provider_code_test.go`), which pins the code rather than the
duration.
