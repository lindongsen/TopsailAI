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
