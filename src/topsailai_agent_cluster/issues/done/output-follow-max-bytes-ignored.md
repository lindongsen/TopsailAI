---
maintainer: AI
author: DawsonLin
---

# Output follow ignored the byte budget and ended the stream on an oversized record

## Trigger

Human question (verbatim):

> 那个MaxBytes的具体问题是什么？

followed by the instruction to fix it directly:

> 直接修，你打算怎么修？

The finding was raised while analysing `output-follow-single-provider-verified.md`, which the human
dismissed (`这个issue不理会`). Only the byte-budget defect was pursued.

## Observed behavior

Three defects shared one root cause.

1. `max_bytes` was accepted and then ignored. A caller asking for a 1024-byte budget silently received
   the default 64 KiB, with no error and no diagnostic.
2. The enforced bound was per line, not per chunk, contradicting the protocol comment
   `MaxBytes bounds one chunk`. It only coincided because the TopsailAI provider emits one line per
   chunk, so a provider that emitted several lines per chunk would have had no byte bound at all.
3. A record longer than the bound ended the whole stream. `bufio.Scanner` returned `ErrTooLong`,
   `scanFollowLines` wrapped it, and `runFollow` classified the result as `provider_error`. The
   operator saw an opaque provider failure and lost every record written after the long one.

The code comment claimed an oversized record was "truncated and labelled", which was false, and
`Truncated` was never set on the follow path at all. `docs/API.md` repeated the false claim that
follow used "the same defaults and clamps as the snapshot route".

## Root cause

The follow path's byte budget was never implemented. A hardcoded constant
`followMaxLineBytes = 64 << 10` was substituted for it, and the comment and documentation described
the intended behaviour rather than the real one. `FollowOutput` read only `MaxLines`, so
`request.MaxBytes` had no consumer anywhere on the follow path, while the snapshot path
(`ReadOutput`) honoured it correctly.

## Resolution

- `bufio.Scanner` was replaced with `bufio.Reader` and a new `readFollowRecord`, because a scanner
  cannot skip an oversized token and continue. An oversized record is now truncated on a UTF-8
  boundary, labelled `Truncated`, and the rest of that record is discarded up to the next newline so
  the stream continues.
- Constants were renamed to state their real role: `followDefaultRecordBytes` (64 KiB, the default)
  and `followMaxRecordBytes` (1 MiB, the absolute ceiling matching the Server clamp). The ceiling is
  1 MiB rather than 64 KiB because the Server already clamps to 1 MiB, so a lower adapter ceiling
  would silently override the caller's request.
- `FollowOutput` now resolves the budget from `request.MaxBytes` with the default and the clamp, and
  passes it to the runner. One record is one chunk, so the record budget is the chunk budget, which
  makes the protocol comment true.
- Records are deliberately not accumulated into a full chunk before emitting, because that would turn
  a live stream into "wait until enough data", so a provider emitting one line every ten seconds would
  show nothing.
- `followRecord{Line, Truncated}` carries truncation evidence through the runner interface, and
  `OutputChunk.Truncated` is set from it.
- The false comment in `follow.go` and the false sentence in `docs/API.md` were corrected, and
  `docs/agent-cluster-protocol.md` gained an "Implemented output follow byte budget" section.

Endpoint `runFollow`, the Server follow handler and the TUI renderer were not modified: they already
forward and render `Truncated`, and keeping the change in the adapter preserves the boundary that the
Server never interprets provider behaviour.

## Prevention

Regression tests assert the requested budget reaches the runner for an explicit, absent, negative and
oversized value; assert an oversized record is truncated and labelled while the following record is
still delivered; assert truncation lands on a rune boundary; assert a blank line is still a record;
assert a record longer than the internal read buffer is delivered intact when it fits the budget;
assert a record spanning several buffer reads is truncated to the budget; assert a genuine read error
is reported rather than mistaken for a clean end of stream; and assert the defensive clamp holds even
when a caller bypasses the adapter normalization.

Reverse verification was performed twice. Reinstating the old "stream dies on an oversized record"
behaviour made the truncation tests fail with `bufio.Scanner: token too long`. Passing a literal `0`
instead of the normalized budget made all four budget sub-cases fail.

## Known limitation

`execFollowRunner.Follow` remains at 0% coverage because it needs a real subprocess. It was already 0%
before this change. The process-group kill, `WaitDelay` and `PYTHONUNBUFFERED` wiring are therefore
covered only indirectly.
