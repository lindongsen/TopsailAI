---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# The initial follow tail overflows the consumer buffer and kills the stream

## Trigger

An operator sends a message in interactive session scope. `autoFollowAfterSend`
(`internal/tui/interactive_ops.go:449`) arms a live tail through
`armFollowStream` (`internal/tui/interactive_ops.go:74`) with the REPL budget
resolved by `interactiveOutputBounds` (`internal/tui/navigation.go:167`), whose
default is `DefaultInteractiveMaxLines = 300` (`internal/tui/interactive.go:31`).

The provider prints its initial tail of up to 300 lines as fast as it can
(`cli/cli_topsailai/runtime_operations.py:171-172`, one `emit` per tail line), and
the adapter turns each line into its own chunk
(`internal/adapter/topsailai/adapter.go:683`).

## Observed behaviour

The stream ends with `follow ended: consumer_overflow` and no further output
arrives. The operator must type `logs -f` again to see anything new.

## Root cause

The burst and the buffering are unrelated quantities, and the consumer does not
drain during the burst.

The initial tail is delivered as **one frame per line**, end to end:

| Stage | Site | Granularity |
|---|---|---|
| Provider tail | `runtime_operations.py:171-172` | one `emit` per line |
| Adapter | `internal/adapter/topsailai/adapter.go:683` | `Lines: []string{record.Line}` |
| Endpoint relay | `internal/endpoint/follow.go:71` | one `FrameOutputChunk` per chunk |
| Server buffer | `internal/channel/server.go:80` | `followChunkBuffer = 64` |
| Server writer | `internal/server/http.go:155` | one NDJSON record per event |
| Client decoder | `internal/client/api.go:117` | `make(chan FollowChunk, 64)` |
| TUI drain | `internal/tui/follow.go:144` | only on the editor idle tick |

The TUI drains the stream exclusively from `followSession.Idle`, which the editor
calls on its 50 ms poll timeout (`internal/tui/terminal_editor.go:408` via
`applyWatch` at `:246`). The stream is started before the read begins
(`internal/tui/follow.go:195`), so the first drain happens about 50 ms after the
provider has already emitted the whole tail.

Backpressure therefore propagates the wrong way: the client decoder blocks on its
full 64-slot channel, the HTTP handler blocks on the socket write, the server
stops draining `events`, and `deliverFollow`
(`internal/channel/server.go:293`) finds the 64-slot queue full. It releases the
follow and reports `consumer_overflow` (`:328`).

`consumer_overflow` is documented as "the consumer is too slow to keep up with the
provider". That is not what happens here: the consumer is polled at a coarser
cadence than the burst, and the buffer bound is smaller than the requested tail.
A 300-line tail against 64 slots per stage has no relationship that could ever
hold, so the defect is structural rather than a matter of a slow reader.

## Secondary defect

`deliverFollowEnd` (`internal/channel/server.go:339`) discards queued chunks to
force the terminal frame through, so the tail the operator asked for is lost even
though the end event declares the loss. The operator sees neither the tail nor the
new output.

## Impact

- Every `send` in session scope loses its automatic follow, because the intent is
  consumed by `startFollow` and never re-armed.
- Explicit `logs -f` fails the same way on a long tail, because both routes share
  `armFollowStream`.
- The operator must recover manually with a second `logs -f`, and that second
  attempt fails identically while the tail is still long.
- The failure is reported as a consumer problem, which points the operator at the
  network instead of at the burst.

## Proposed resolution

The consumer must keep draining while the terminal write is throttled, so the
network read is never gated by the editor tick:

- Drain the client record channel continuously in `followSession` into a bounded
  internal buffer, and let `Idle` flush that buffer to the terminal. This keeps
  the documented "one record is one chunk" contract and the per-record byte
  budget unchanged.
- Alternatively, size the follow buffer from the requested `max_lines` instead of
  a fixed 64, so the buffer can hold the tail the caller asked for.
- Do not simply raise `followChunkBuffer`: the same overflow returns as soon as
  the tail grows, and an unbounded queue would let one reader exhaust Server
  memory.
- Keep `consumer_overflow` for a genuinely stalled consumer, not for a burst.

## Verification

- A test drives a tail-sized burst (at least `max_lines` records) through the
  follow path with a consumer that drains only on a tick, and asserts the stream
  survives and every record is rendered.
- A test asserts a genuinely stalled consumer still receives exactly one
  `consumer_overflow` end event.
- A test asserts the initial tail content is not discarded on a normal end.
- The fix must be reverse-verified: with the drain removed, the burst test must
  fail with `consumer_overflow`.

## Resolution

Fixed on 2026-11-09 by draining the consumer continuously instead of once per
editor poll. The change is confined to `internal/tui/follow.go`; the adapter,
Endpoint, Server and channel layers are untouched, so the documented contract
"one record is one chunk" and the per-record `max_bytes` budget are unchanged.

`followSession` now owns a pump goroutine that is the only reader of the record
stream. It renders each record as it arrives and holds the bytes in a bounded
pending buffer (`followPendingBytes = 4 MiB`), and `Idle` became a pure flush of
that buffer. The transport is therefore drained while the editor is between
polls, so a 300-record burst is absorbed locally instead of filling the 64-slot
transport queues.

Design points that the fix had to respect:

- `Idle` must never block, because the editor calls it between keypresses. It
  only swaps the buffer out and signals the pump.
- The pending bound applies backpressure rather than dropping data, so a
  genuinely stalled consumer is still reported by the transport as
  `consumer_overflow` instead of being shown a partial stream.
- A single record larger than the bound is accepted once the buffer is empty,
  because waiting for room that can never be freed would deadlock the pump.
- `Stop` marks the session ended, broadcasts the condition variable and closes a
  `done` channel before cancelling the context, so a pump blocked on the pending
  bound or on a record that never arrives exits instead of leaking the goroutine.
- `newFollowSessionWithRecords` is the single construction path, so a session can
  never exist without a reader.

## Secondary defect status

`deliverFollowEnd` (`internal/channel/server.go:339`) still discards queued chunks
to force the terminal frame through. That behaviour was deliberately not changed:
it is the correct last resort for a consumer that really cannot keep up, and
changing it would weaken the guarantee that a terminal frame is always delivered.
With the consumer draining continuously the queue no longer fills during a burst,
so the discard is no longer reachable in this scenario. It remains a latent
behaviour for a genuinely stalled consumer, which is the case it exists for.

## Verification evidence

| Check | Command | Result |
|---|---|---|
| Build | `go build ./...` | pass |
| Vet | `go vet ./internal/tui/` | pass |
| CLI component unit tests | `make test-unit-cli` | pass (`internal/tui` 74.8s) |
| Full unit suite | `make test-unit` | pass, all components |
| Race detector on the follow path | `go test -race -run 'TestFollowSession\|TestFollowLogs\|TestStartFollow\|TestUnitSendAutoFollow\|TestInteractiveLogsFollow' ./internal/tui/` | pass |
| BDD suite | `make test-bdd` | pass, 298.3s, including `interactive_follow_streams_records_until_a_keypress_stops_it` and `any_key_stops_the_interactive_follow_stream` |

Reverse verification, performed as required: with `go session.pump()` removed,
`TestFollowSessionDrainsBurstWithoutAnEditorPoll` failed with
`the burst was not drained without an editor poll` after the 5-second deadline.
The break was reverted and the test passed again in 0.008s. The test therefore
detects the defect rather than merely describing the fixed code.

The new regression test uses a one-slot record channel and a producer goroutine,
so a reader that only drained on the editor tick would block the producer. It
asserts the whole `DefaultInteractiveMaxLines` burst is consumed with no `Idle`
call at all, which is exactly the property the defect violated.

## Tests migrated

The pump made `Idle` asynchronous, so two tests that assumed one poll observes a
record handed over moments earlier were migrated rather than left racy:

- `TestFollowSessionIdleDrainsAvailableRecords` now waits for the terminal state
  with `waitEnded` before its single poll, preserving the original intent that one
  poll returns the whole accumulated burst.
- `TestFollowSessionIdleReportsRenderFailure` constructed `followSession`
  directly, bypassing the constructor and therefore the pump. It now uses
  `newFollowSessionWithRecords` and polls with `idleUntil`.
