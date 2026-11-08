---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# A follow that ends while the channel is offline never delivers its terminal frame

## Trigger

An output follow is active and the Endpoint loses its channel to the Server
before the follow ends. This happens on Endpoint shutdown, on a network drop, and
on a Server restart while a stream is running.

## Observed behavior

During BDD teardown the Endpoint log records:

```text
send output follow end deferred until the channel is ready  error="endpoint is offline"
```

`Service.sendFollowEnd` (`internal/endpoint/follow.go`) builds the
`FrameOutputEnd` frame and calls `SendFrame`. When the channel is offline the
send fails with `channel.ErrOffline`, and `logTransportError` classifies that as a
connectivity state rather than a failure, so it logs at WARN and returns. The
frame is not queued, not retried and not persisted.

The Server side never receives the terminal frame. The waiting consumer is
released by its own cancellation path instead, which is why the CLI still prints
`follow stopped` and the operator sees a plausible result.

## Impact

The "exactly one `output_end` per stream" contract is proven only for a normal
stop. On disconnect the contract is satisfied by the consumer's local
cancellation, not by the Endpoint, so the two paths are not equivalent:

- A consumer that distinguishes "clean end" from "interrupted" cannot tell which
  happened, because the Endpoint never stated either.
- The Server's pending-follow entry is released by `remove(peer)` with
  `endpoint_offline`, so the Server does report a reason, but that reason is
  inferred from the disconnect rather than reported by the Endpoint.
- Any future consumer that relies on the Endpoint's own terminal code, for
  example to decide whether to retry or to report truncation, gets nothing.

The behaviour is currently safe because the client fails closed, but the contract
as documented is stronger than what is implemented.

## Root cause

`sendFollowEnd` treats a transport failure as a logging concern. It has no
durable place to put the terminal frame, and the Endpoint deliberately keeps no
follow journal, so there is nothing to replay when the channel returns. The
design assumed the terminal frame is always deliverable, which is false exactly
when the stream is most likely to be interrupted.

## Proposed resolution

- Decide explicitly whether the terminal frame is best-effort or guaranteed, and
  document that decision where the follow contract is described.
- If it must be guaranteed, retain the terminal frame in the Endpoint's bounded
  deduplication journal keyed by `request_id`, and flush it on reconnect before
  any new frame for that request. Bound the retention by the same window already
  used for command deduplication.
- If it stays best-effort, make the Server's inferred `endpoint_offline` reason
  the documented contract, and state that a disconnect always terminates a
  follow with that code rather than with the Endpoint's own code.
- Either way, stop logging this case only at WARN without recording that a
  terminal frame was lost; the loss is a contract event, not routine noise.

## Verification

- An Endpoint test starts a follow, takes the channel offline, ends the follow,
  then brings the channel back and asserts the terminal frame is delivered (if
  guaranteed) or that the loss is recorded with the request ID (if best-effort).
- A BDD scenario kills the Endpoint mid-follow and asserts the CLI reports an
  interrupted stream with a stable code, not a clean end.
- A regression test asserts a normal stop still delivers exactly one terminal
  frame, so the disconnect handling cannot mask the ordinary path.
