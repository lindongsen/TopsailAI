---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# `deliverFollowEnd` busy-loops when the consumer neither drains nor closes

## Trigger

A follow reaches its terminal frame while the consumer has stopped reading but
has not closed the channel. The queue is full, so the terminal send cannot
proceed, and the consumer never removes an item.

## Observed behavior

`deliverFollowEnd` (`internal/channel/server.go`) loops without any wait:

```text
for {
    select { case events <- FollowEvent{End: end}: return; default: }
    select { case <-events: default: }
}
```

When the queue is full and the consumer is idle, the first `select` takes
`default`, the second `select` also takes `default` because the queue is empty
after the discard, and the loop repeats. The goroutine spins at full CPU with no
sleep, no backoff and no attempt count.

## Impact

- A single stuck consumer burns a core for as long as the goroutine lives.
- The spin is invisible in normal operation because the consumer's own context
  usually cancels the follow, which ends the goroutine. The failure therefore
  appears only under a consumer bug or a client that stops reading without
  disconnecting, which is exactly the case that is hardest to reproduce.
- Because the loop has no bound, it cannot report that it gave up. A future
  reader cannot distinguish "the end was delivered after discarding chunks" from
  "the end was never delivered".

## Root cause

The function was written to guarantee delivery by discarding queued chunks, which
is the right intent: dropping the terminal frame would present a truncated stream
as complete. The implementation of that intent assumed the consumer keeps
draining, so it never considered the case where the consumer is alive but idle.
There is no wait, no deadline and no exit condition other than a successful send.

## Proposed resolution

- Bound the loop by the follow's own context or an explicit deadline, so a stuck
  consumer cannot keep the goroutine alive indefinitely.
- Add a small backoff between discard attempts, or wait on the consumer's done
  channel, so the goroutine yields instead of spinning.
- On giving up, record the request ID and the fact that the terminal frame was
  not delivered, so the loss is observable rather than silent.
- Keep the existing guarantee for the ordinary overflow case: the terminal frame
  must still win over queued chunks whenever the consumer is draining at all.

## Verification

- A channel test fills the queue, stops the consumer, and asserts the goroutine
  exits within a bounded time instead of spinning.
- A test asserts the ordinary overflow path still delivers exactly one terminal
  frame with `consumer_overflow`.
- A test asserts a normal consumer receives the terminal frame without any
  discarded chunk.

## Resolution

Status: **invalid — the reported busy loop cannot occur.** No production code was
changed. The issue was closed by proving the premise false and by adding a
regression test that locks the real invariant.

### Why the premise is false

The loop is:

```go
for {
    select { case events <- FollowEvent{End: end}: return; default: }
    select { case <-events: default: }
}
```

The claim was that both selects can take `default` on the same iteration, so the
loop repeats without progress. That is impossible on a **buffered** channel, and
the follow event channel is always buffered:

- `RequestFollow` (`internal/channel/server.go:462`) is the only construction
  site, and it always uses `make(chan FollowEvent, followChunkBuffer)` with
  `followChunkBuffer = 64`.
- On a full queue the send takes `default` and the receive **succeeds**, removing
  one chunk.
- On a non-full queue the send **succeeds** and the loop returns.

The two `default` branches are mutually exclusive. Each iteration either returns
or removes exactly one chunk, so the loop terminates after at most
`followChunkBuffer` iterations. It cannot spin.

### Measured evidence

| Check | Result |
|---|---|
| Full queue, permanently idle consumer | returns immediately; 64 chunks queued, 1 discarded, end delivered |
| 5000 consecutive full-queue calls | 43.9 ms total, no CPU burn |
| 200 rounds with a concurrently draining consumer | all terminate well inside the 2 s bound |
| `go test -race` on the probe | clean |
| Reverse check: `followChunkBuffer = 0` | **the loop genuinely spins**; the test times out at 2 s |

The reverse check is the important one. It proves the test is sensitive to the
real failure mode: an unbuffered channel would let both selects default and turn
the loop into a true spin. The buffer is therefore a **correctness requirement**,
not a tuning choice, and the test now guards it.

### What was added

`internal/channel/follow_end_termination_test.go`:

- `TestDeliverFollowEndCannotSpinOnBufferedQueue` — full queue plus idle consumer
  must return, the terminal frame must be present, and exactly one chunk must be
  discarded.
- `TestDeliverFollowEndTerminatesUnderConcurrentDrain` — 200 rounds with a
  concurrently draining consumer, each bounded by 2 s.
- `TestFollowEventChannelIsAlwaysBuffered` — asserts `followChunkBuffer > 0` and
  that the channel returned by `RequestFollow` has that capacity.

### Why no sleep or backoff was added

The proposed resolution suggested a backoff between discard attempts. Adding one
would be actively harmful: the ordinary overflow path is the path that must report
data loss promptly, and a sleep would delay the terminal frame for every real
overflow while fixing nothing. The regression test documents this reasoning so a
future reader does not "fix" the non-bug again.

### Residual observation, not a defect

If a consumer stops reading forever without closing, the terminal frame remains
queued behind the surviving chunks and is never observed. That is a consumer bug,
not a Server defect: the goroutine has already exited, no CPU is consumed, and the
Server holds no reference to the queue. The consumer's own context cancellation
releases the pending entry, which is the documented behaviour.

### Prevention

- A busy-loop claim must be checked against the channel's buffering before any
  code is changed. `select` with `default` on a buffered channel cannot default on
  both branches when the buffer is full or empty.
- A proposed fix that adds latency to a hot error path must be justified by a
  reproduced defect, not by a code-reading hypothesis.
- Every new test must be reverse-verified. Here the reverse check (unbuffered
  channel) reproduced the claimed spin, which is what makes the test meaningful.
