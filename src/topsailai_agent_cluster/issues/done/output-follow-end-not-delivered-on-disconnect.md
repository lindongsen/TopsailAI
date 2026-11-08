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

## Resolution

Status: resolved as **best-effort**, decided by the human.

> 同意 尽力而为 就可以了

The guaranteed option was rejected. It would require a durable record type, a
reconnect flush order and a retention bound on the command deduplication journal,
which is a larger change than the contract needs. The current behaviour is
already safe because the client fails closed, so the value of this change is a
truthful contract and a truthful log, not a delivery guarantee.

### What changed

`Service.sendFollowEnd` (`internal/endpoint/follow.go`) no longer calls the
shared `logTransportError`. It calls a dedicated `logFollowEndLost`, which logs
`output follow terminal frame lost` with `request_id`, `error_code` and `error`,
at WARN for `channel.ErrOffline` and ERROR for any other transport failure.

The shared helper was deliberately left unchanged. `logTransportError` is used by
inventory publish and receipt resend, which really do retry, so its "deferred
until the channel is ready" wording is correct for them and false only for the
follow terminal frame. Changing the shared helper would have made the two
retrying paths lie instead.

The documented contract is now the Server-inferred `endpoint_offline` reason: a
disconnect always terminates a follow with that code, never with the Endpoint's
own code. Consumers must treat a stream that ends without a terminal frame as
interrupted, never as complete. See the new section
`## Implemented output follow terminal frame delivery` in
`docs/agent-cluster-protocol.md`.

### Verification evidence

| Check | Result |
|---|---|
| `go build ./...` | clean |
| `go vet ./...` | clean |
| `gofmt -l internal/ tests/ src/` | only pre-existing `internal/tui/refresh_test.go`, untouched |
| `go test ./... -count=1` | pass |
| BDD full suite | pass, 247.35s; new scenario PASS in 5.46s |
| `internal/endpoint` coverage | 79.3%; `sendFollowEnd` 100%, `logFollowEndLost` 100% |
| reverse check, unit | 4 tests fail with the loss logger disabled; the normal-stop regression guard still passes |
| reverse check, BDD | **the new scenario still passes without the fix** |

### Honest limitation

The new BDD scenario asserts that the CLI reports `follow ended:
endpoint_offline`. The Server already produced that code before this change,
because `failPendingFollow` (`internal/channel/server.go`) releases pending
follows with `endpoint_offline` on disconnect. Reverting the fix and re-running
the scenario confirmed it still passes.

The scenario is therefore a **contract guard**, not a defect detector: it prevents
a future change from reporting a disconnect as a clean end. The unit tests are the
actual defect detectors, and they do fail when the loss logger is disabled.

### Prevention

- A transport failure on a non-retrying path must not reuse the wording of a
  retrying path. The log must state what actually happens to the frame.
- When a contract says "exactly one terminal frame", verify the disconnect path
  separately from the normal path; the normal path alone does not prove it.
- A new BDD scenario must be reverse-verified. If it passes without the fix, it
  is a guard and must be labelled as one rather than cited as proof.
