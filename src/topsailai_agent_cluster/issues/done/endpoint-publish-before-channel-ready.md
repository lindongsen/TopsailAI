---
maintainer: AI
author: DawsonLin
---

# Endpoint logs a spurious `publish inventory` error before the channel is ready

## Trigger

Observed while deploying the Debian package to the `topsailai-dev` container: every `start` and `restart`
of `agent-cluster-endpoint` writes an ERROR line to the endpoint log even though the endpoint connects and
publishes successfully moments later.

## Observed behavior

```text
22:39:18.174 ERROR publish inventory endpoint is offline
22:39:18.577 INFO  begin accepted command recovery
22:39:18.577 INFO  accepted command recovery channel ready
22:39:18.577 INFO  accepted command recovery loaded
```

Reproduced on demand: the log held 11 lines before `agent-clusterctl restart` and 15 after, with exactly one
new ERROR. The subsequent inventory commits succeed (`snapshot_revision` advances 1 -> 2 -> 3,
`collection_status: succeeded`), so the endpoint is healthy.

## Root cause

`internal/endpoint/service.go` `collectionLoop` calls `publish()` once immediately, before the channel has
finished connecting:

```go
publish()
ticker := time.NewTicker(s.interval)
```

`publish()` calls `s.channel.SendFrame(...)`, which returns `channel.ErrOffline`
(`internal/channel/fencing.go`) while the connection is not yet established. The error is logged at ERROR
level via `s.logError("publish inventory", err)`.

The sibling loop `recoverAcceptedCommands` already handles this correctly: it calls `waitForChannelReady(ctx)`
before doing channel work. `collectionLoop` has no equivalent gate.

## Impact

- A healthy startup is indistinguishable from a real publish failure in the log, which is exactly the signal
  an operator uses to diagnose a broken endpoint.
- Any log-based health check or alerting on ERROR lines will fire on every restart.
- No functional damage: the next tick publishes normally and the Server commits the report.

## Suggested fix

Gate the initial publish on channel readiness, or classify `channel.ErrOffline` during startup as a
non-error (retry on the next tick) instead of logging it at ERROR. The first option matches the existing
`waitForChannelReady` pattern already used by `recoverAcceptedCommands`.

## Resolution

Fixed on 2026-11-07. `collectionLoop` now gates the initial publish on
`waitForChannelReady`, the same readiness signal `recoverAcceptedCommands` already uses. The loop waits
for the authenticated transport instead of collecting and sending into an offline channel, so startup no
longer logs an `ErrOffline` ERROR that is indistinguishable from a real publish failure. Cancellation
before readiness returns without publishing and without logging an ERROR. A transport without the
`ReadyChannel` seam keeps the previous immediate-publish behaviour, so no existing caller changes.

Regression tests in `internal/endpoint/collection_readiness_test.go` cover the suppressed initial
publish, cancellation before readiness, the no-seam fallback and continued ticks after readiness. Two of
the four tests were proven to fail against the unfixed code, so the guard is effective rather than
vacuous.

## Status

Resolved. Live confirmation on a deployed Endpoint restart remains a manual check and is not claimed as
executed; the unit tests prove the gate and the absence of the ERROR line but do not reproduce a real TLS
handshake delay.
