---
maintainer: AI
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectCode: AGENT_CLUSTER
programming_language: go
---

# Server read loop blocks the heartbeat acknowledgement

## Symptom

An Endpoint disconnects and reconnects repeatedly while the Server reports it as
online. The Server log shows no error. The Endpoint log shows
`markServerUnhealthy` followed by a reconnect, even though the Server process is
healthy and answering other Endpoints.

## Root cause

`internal/channel/server.go` `readLoop` performed every blocking operation
inline, in the same goroutine that reads frames:

| Operation | Call site | Blocking nature |
|---|---|---|
| `OnReceipt` -> `PersistReceiptAndAck` | `server.go` read loop | SQLite write plus network write |
| `OnFrame` -> `UpsertEndpoint` + `ReplaceInventoryCommitted` | `server.go` read loop | SQLite write, broker publish, network write |
| `deliverFollow` -> `cancelEndpointFollow` | `server.go` read loop | network write with a 2 second timeout |

While any of these ran, the loop could not reach the next `wsjson.Read`. A
heartbeat frame that had already arrived sat unread in the socket buffer, so its
acknowledgement could not be written. The Endpoint counts unacknowledged
heartbeats and closes the connection after 30 seconds, which is the reconnect
loop observed in the symptom.

## Amplifier

The persistence layer makes the stall long enough to matter:

- `maxOpenConnections = 1` in `internal/storage/server/db.go`: every read and
  write shares one connection, so they serialize completely.
- `journal_mode(DELETE)` with `synchronous(FULL)`: no WAL, so readers and writers
  exclude each other.
- `busy_timeout(5000)`: a writer waits up to 5 seconds, which already exceeds the
  Endpoint's 3 second acknowledgement wait.
- `transactionBudget = 30 * time.Second` in
  `internal/storage/server/transaction.go`: one transaction may legitimately hold
  the only connection for 30 seconds.

A single long transaction therefore delays the heartbeat acknowledgement by up to
30 seconds, which equals the Endpoint's unhealthy window. One long transaction is
enough to trigger a disconnect.

## Why it was not caught

The two halves were tested separately and their interaction never was:

- `internal/channel` tests drive `readLoop` with mock `OnFrame` and `OnReceipt`
  callbacks that return immediately, so no test ever made a hook slow.
- `internal/storage/server` tests exercise persistence directly and never drive a
  real read loop.

Neither suite could observe a slow hook delaying a heartbeat acknowledgement.

## Fix

The read loop now performs only non-blocking work and hands every business frame
to a bounded per-peer queue drained by one worker goroutine.

- `businessQueueDepth = 16` bounds the queue. An unbounded queue would let one
  slow peer grow Server memory without limit, the same reasoning that bounds the
  follow buffer.
- The heartbeat acknowledgement is written inside the read loop and the frame is
  never queued. Routing it through the worker would put it behind a database
  write, and queueing it would let a heartbeat every few seconds fill the bounded
  queue during a stall and disconnect the very peer the design protects.
- A full queue closes the connection instead of blocking the read loop or
  dropping the frame. A peer that cannot absorb its own inbound frames is already
  unhealthy, and reconnecting is the honest outcome; dropping would leave state
  silently inconsistent.
- One worker per peer preserves arrival order, which matters because a receipt
  and the inventory that follows it are causally related.
- `handleBusinessFrame` keeps `OnReceipt`, then `OnFrame`, then `deliverRefresh`
  in the original order, so a forced collection is still delivered only after the
  persistence hook ran.
- The worker refuses to write business state once a newer connection owns the
  Endpoint, so a superseded connection cannot overwrite current state with stale
  data.
- `remove`, `Close` and `ExpireStalePeers` all signal the worker to stop. The
  signal is not a join: waiting for a worker blocked in a database write would
  reintroduce the stall this design removes.

## Evidence

`internal/channel/server_business_queue_test.go` adds six tests:

| Test | Result |
|---|---|
| `TestServerHeartbeatAckIsNotBlockedByBusinessHandler` | PASS |
| `TestServerBusinessFramesKeepArrivalOrder` | PASS |
| `TestServerDeliversRefreshAfterPersistenceHook` | PASS |
| `TestServerFullBusinessQueueClosesPeer` | PASS |
| `TestServerSupersededWorkerDoesNotWriteBusinessState` | PASS |
| `TestServerBusinessWorkerDoesNotLeak` | PASS |

Reverse verification: temporarily making `enqueueBusiness` call
`handleBusinessFrame` inline, which restores the old synchronous shape, makes the
core regression test fail with
`heartbeat acknowledgement was blocked by the business handler: failed to read JSON message: failed to get reader: context deadline exceeded`
after 2.00s. Restoring the queue makes it pass. The test therefore detects the
defect rather than passing unconditionally.

`go build ./...` passes. `go test ./internal/channel/ -race -count=1` passes in
3.465s. `go test ./internal/endpoint/ -race -count=1 -skip
TestCollectionLoopKeepsErrorForGenuineFailure` passes in 10.676s; that skipped
test has a pre-existing data race inside the test itself, between the goroutine
writing a `bytes.Buffer` log sink and the test goroutine reading it without
synchronization, and it references none of the changed symbols.

## Deferred

- `ExpireStalePeers` still persists each expired peer serially. It runs on its own
  ticker goroutine, not on a read loop, so it cannot delay any live peer's
  heartbeat. It only delays marking later peers in the same sweep offline.
- `journal_mode(DELETE)` and `maxOpenConnections = 1` are amplifiers, not the root
  cause. Moving to WAL would shrink the worst case but carries its own durability
  trade-off and would not remove the 2 second network write in
  `cancelEndpointFollow`. It is a separate performance change.
