---
maintainer: AI
author: DawsonLin
status: resolved
created: 2026-11-17
---

# Endpoint command execution blocked the heartbeat acknowledgement

## Symptom

An Endpoint running a long command declared the Server unhealthy and tore the link down while the
Server was answering every heartbeat on time. The Server showed the Endpoint as `online` throughout,
because its own `LastSeen` kept advancing, while the Endpoint log showed repeated reconnects.

## Root cause

`channelLoop` is the only reader of the connection, and every business handler ran inline in it:

```go
// internal/endpoint/service.go, before the fix
case channel.FrameCommand:
    s.executeFrame(ctx, frame)   // synchronous, no goroutine
```

`executeFrame` reaches a Provider CLI invocation whose deadline the shipped configuration sets to
120s (`conf/node.endpoint.conf.example:49`, `timeout_ms: 120000`). While that call ran, the loop could
not read any frame, so a heartbeat acknowledgement that had already arrived sat unread in the socket.

The heartbeat sender waits at most 3s per acknowledgement (`defaultHeartbeatAckTimeout`) and declares
the Server unhealthy after 30s of consecutive failures (`defaultUnhealthyWindow`). A command longer
than 30s therefore guaranteed the unhealthy decision, and the Endpoint closed a connection the Server
was serving correctly.

The same shape existed for every other handler: `launchFrame`, `historyFrame`, `messagesFrame`,
`metricsFrame`, `metricsBatchFrame`, `detailFrame`, `modelCatalogFrame`, `outputFrame`,
`publishRefresh` and `settleRejectedReceipt` all ran inline.

## Why it was not caught

`heartbeat_ack_loop_test.go` drives the loop with an acknowledgement frame and proves the loop records
it, but no scenario held a business handler open while acknowledgements arrived. The two paths were
tested separately, so the interaction that broke liveness was never exercised.

## Fix

Business handlers are dispatched outside the read loop through `dispatchBusiness`, which tracks the
goroutine with the service wait group so shutdown still waits for in-flight work. The read loop now
only performs pure in-memory bookkeeping: heartbeat acknowledgement, inventory acknowledgement,
receipt acknowledgement and follow cancellation.

Concurrency was verified safe before the change:

- `coder/websocket` documents that all methods may be called concurrently except `Reader` and `Read`,
  so concurrent `SendFrame` is safe and needs no write lock.
- `Executor.lockFor` guards its map with `e.mu`, and the per-target lock keeps two commands for the
  same resource serialized.
- The Endpoint store uses `SetMaxOpenConns(1)`, so concurrent journal writes are serialized.
- The adapter scheduler already bounds concurrency per class and refuses rather than queues, so no
  second limiter was added in the service layer.
- `pendingReceipts`, `activeFollows` and `pendingInventory` are each guarded by their own mutex.

`startFollow` already used this exact pattern, so the fix reuses the existing convention instead of
introducing a second one.

## Evidence

`internal/endpoint/channel_loop_independence_test.go` holds one command open and requires the loop to
keep recording acknowledgements:

- Before the fix: `read loop consumed 0 of 3 heartbeat acknowledgements while a command was running`.
- After the fix: the same scenario passes, and `-race` reports no race in the new tests.

## Remaining work

The Server has the symmetric shape. `internal/channel/server.go` `readLoop` calls `OnFrame` and
`OnReceipt` inline, and both write SQLite, so a slow inventory commit delays the heartbeat
acknowledgement the Server owes the Endpoint. That direction is not fixed here and needs its own
logical unit.

## Resolution

Fixed on 2026-11-17 in commit `cd197c1a`.

### What changed

`internal/endpoint/service.go` gained `dispatchBusiness`
(`internal/endpoint/service.go:513`), which runs one business handler outside the
channel read loop. Every request frame that can block now goes through it, so the
read loop performs only non-blocking work and keeps recording heartbeat
acknowledgements while a slow handler runs.

The pattern is the one `startFollow` already used, so the fix reuses an existing
convention rather than introducing a second one. `dispatchBusiness` appears 13
times in `service.go`, covering the request frames the issue counted plus the ones
added since.

### Why the read loop must stay non-blocking

The heartbeat acknowledgement is received by the same loop that dispatches business
frames. A handler that blocks the loop therefore delays the acknowledgement, and
`awaitHeartbeatAck` waits 3 seconds with a 30-second cumulative budget before
`markServerUnhealthy` closes the connection. The largest single blocker was
`FrameInventoryRefresh`, whose collector budget is 30 seconds
(`src/main/agent-cluster-endpoint/main.go:194`), three times the metrics budget the
issue originally focused on.

### Evidence

`internal/endpoint/channel_loop_independence_test.go` holds one command open and
requires the loop to keep recording acknowledgements:

- Before the fix: `read loop consumed 0 of 3 heartbeat acknowledgements while a command was running`.
- After the fix: the same scenario passes, and `-race` reports no race in the new tests.

### The mechanism was real but never observed

The issue's rationale is operator latency plus a latent risk, not observed
disconnects. The Endpoint logs contain zero `heartbeat acknowledgement timed out`
and zero `server unhealthy` entries; the 226 reconnects recorded were transport
failures (`failed to read frame header` 38, `use of closed network connection` 8).
The fix is therefore justified by the mechanism and by the measured blocking, not
by an event that never happened.

### Remaining work

The Server has the symmetric shape, recorded separately in
`issues/server-read-loop-blocks-heartbeat-ack.md` and fixed by the bounded
per-peer business queue (`businessQueueDepth = 16`).
