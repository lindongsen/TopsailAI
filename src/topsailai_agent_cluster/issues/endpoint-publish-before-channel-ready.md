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

## Status

Open. Not fixed during the deployment unit: the task was installation, and `internal/endpoint/` was being
edited concurrently by another agent in the same workspace.
