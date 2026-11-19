---
maintainer: AI
author: DawsonLin
status: resolved
severity: medium
created: 2026-11-19
platform: linux
---

# A large `file.read` costs 2.4x the file on the wire and is CPU-bound, not memory-bound

## Symptom

Reading a large file through `file.read -o` is slow in a way the design documents
do not explain, and the cost is CPU rather than memory. Measured on Linux with the
real Server and Node from `tests/e2e/start.sh`, one CLI process, one file inside a
scope, content verified byte-identical with `cmp`:

| File size | Wall time | Server peak RSS | Node peak RSS | Server CPU | Node CPU |
|---|---|---|---|---|---|
| 5 bytes | 9 ms | 14.6 MB | 13.0 MB | 0.00 s | 0.00 s |
| 16 MiB | 1.34 s | 28.5 MB | 24.7 MB | 0.84 s | 0.27 s |
| 64 MiB | 5.11 s | 28.6 MB | 26.0 MB | 4.30 s | 1.29 s |
| 256 MiB | 20.8 s | 29.7 MB | 27.1 MB | 18.52 s | 5.53 s |

CPU ticks are `CLK_TCK=100`, so 1852 ticks is 18.5 s of Server CPU for 20.8 s of
wall time: the Server is busy for essentially the whole read. Throughput is about
12 MB/s.

Peak RSS is flat: 28.5 MB at 16 MiB and 29.7 MB at 256 MiB, a 4% rise for a 16x
larger file. Memory does not grow with file size, which is the property the design
intends and the measurement confirms.

## Cause

The file content is base64-encoded twice on the way to the caller, and both layers
are decoded and re-encoded by the Server.

1. `internal/node/dispatch.go:229` marshals `readResult{Content []byte}`. A `[]byte`
   field is base64 in JSON, so 256 KiB of content becomes 349,573 bytes of payload
   (x1.33).
2. `internal/protocol/frame.go:39` carries that payload in `Frame.Payload []byte`,
   which is base64 again. The frame becomes 466,153 bytes (x1.78).
3. `internal/server/channel.go:262` unmarshals the frame, decoding base64 layer two.
4. `internal/server/channel.go:277` unmarshals `frame.Payload` into the response,
   decoding base64 layer one.
5. The Server then re-marshals the envelope for the HTTP response.

Measured cost of one 256 KiB round trip in isolation, 200 iterations each:

```
payload json bytes 349573 (x1.33)
frame   json bytes 466153 (x1.78)
marshal readResult   310 us
marshal frame        428 us
unmarshal frame      3.86 ms
unmarshal readResult 2.43 ms
base64 encode 256KiB 439 us
sum of one round trip 7.04 ms
```

7 ms of pure JSON work per 256 KiB chunk, on the Server side alone, is 28 ms per
MiB, which is the same order as the measured 12 MB/s. The dominant term is
`unmarshal frame` at 3.86 ms, because decoding base64 into a `[]byte` allocates and
copies the whole payload.

## Why it matters

- A 1 GiB file takes about 83 s and burns about 74 s of Server CPU. A Server
  serving several Nodes is CPU-saturated by one large read.
- The 2.4x wire expansion is what forces `MaxResponseBytes = 256 KiB`
  (`internal/node/fence.go:20`). The frame limit is 1 MiB
  (`internal/server/channel.go:28`, `internal/node/session.go:21`), and one chunk
  already occupies 466 KB of it. Raising the response cap to 512 KiB would produce
  a 932 KB frame, leaving no headroom for the envelope, so the cap cannot be raised
  without changing the frame limit or the encoding.
- The double encoding buys nothing. The payload is already a JSON document; wrapping
  it in a `[]byte` field base64-encodes a document that is already text.

## What is not a problem

- Memory. Peak RSS is flat across a 16x size range, and the CLI holds one chunk at a
  time (`internal/server/cli/output.go:59`, `fetchWholeFile` writes each chunk
  before requesting the next). A 256 MiB read peaked at 15.6 MB of CLI RSS.
- Concurrency. Eight parallel 16 MiB reads completed with zero failures and
  byte-identical output, at 32.7 MB Server peak RSS and 27.4 MB Node peak RSS, in
  5.0 s. Concurrency is bounded by `maxInFlight = 64`
  (`internal/server/channel.go:50`).
- Correctness. Every size produced byte-identical output, including the 256 MiB
  case.

## Decided direction

The accepted fix is a versioned `binary-v1` file transport. Control and error
messages remain structured, while file bytes travel outside JSON without base64
or default compression. The Server selects the first version in its preference
order that the Node offered; malformed or disjoint offers fail closed instead of
silently falling back.

The negotiation contract lands before live activation, but neither peer advertises
or selects `binary-v1` until its binary frame behavior exists on both sides. Live
negotiation and framing activate atomically so an intermediate build cannot claim
a transport it does not implement. Chunk size remains 256 KiB until measurement
shows that a different bounded value improves the complete workflow.

## Detection gap

No test measures resource behaviour. The largest fixture anywhere is
`4*capBytes` = 1 MiB (`internal/server/cli/output_test.go:316`), and
`internal/node/fence_test.go:400` uses `MaxResponseBytes+1024`. No test asserts a
wall-time, CPU or RSS bound, and no BDD scenario mentions a large file
(`grep -rn "large\|MiB" tests/bdd/features/*.feature` returns nothing). The suite
therefore cannot observe a throughput regression, which is the class of defect this
issue describes.

## Resolution

Resolved on 2026-11-19 by Units 2, 3, 4a and 4b of the resource-efficient read
plan (`.task/plan_20261119T123000-resource-efficient-read.md`). The double base64
encoding is gone from both hops, and the detection gap is closed by a measurement
harness that runs from a maintained Make target.

### What changed

| Unit | Commit | Change |
|---|---|---|
| 2 | `645314db` | Versioned file transport negotiation, fail-closed on a disjoint offer |
| 3 | `8d4c6fc9` | `binary-v1` content frame: magic, bounded JSON header, raw bytes |
| 4a | `298e0484` | The Server writes the bytes to the HTTP response without re-encoding |
| 4b | `e0b46ef4` | The CLI opts in with `Accept: application/octet-stream` and consumes the raw body |

The Node hop was already binary, so it did not move. The Server hop was the one
that decoded and re-encoded, and it is the one that changed.

### Measured after the fix

Same host, same command (`make measure MEASURE_SIZES="1 16 64"`), revision
`e0b46ef4`, transport `binary-v1`, TLS disabled:

| Size | Wall | Throughput | Server CPU | Node CPU | Server peak RSS | Node peak RSS | Content |
|---|---|---|---|---|---|---|---|
| 1 MiB | 0.034 s | 29.41 MiB/s | 0.020 s | 0.010 s | 20,376 KB | 15,908 KB | yes |
| 16 MiB | 0.356 s | 44.94 MiB/s | 0.240 s | 0.180 s | 23,700 KB | 21,304 KB | yes |
| 64 MiB | 1.439 s | 44.48 MiB/s | 0.920 s | 0.640 s | 23,964 KB | 22,068 KB | yes |

Protocol bytes:

| Size | Server ratio | Node ratio |
|---|---|---|
| 1 MiB | 1.0034 | 1.0031 |
| 16 MiB | 1.0034 | 1.0031 |
| 64 MiB | 1.0034 | 1.0031 |

### Before and after

| Property | Before | After | Change |
|---|---|---|---|
| Server wire ratio | 1.3371 | 1.0034 | base64 expansion removed |
| Node wire ratio | 1.0031 | 1.0031 | unchanged, which proves the bytes were not moved to the other hop |
| Throughput at 16 MiB | 11.01 MiB/s | 44.94 MiB/s | 4.1x |
| Throughput at 64 MiB | 11.01 MiB/s | 44.48 MiB/s | 4.0x |
| Server CPU at 64 MiB | 2.480 s | 0.920 s | 63% less |
| Server peak RSS at 64 MiB | 28,480 KB | 23,964 KB | 16% less |
| Peak RSS growth 16 → 64 MiB | +2,252 KB | +264 KB | still bounded |

The after-run happened at `/proc/loadavg` 8.54, higher than the baseline run's
2.06–3.91, so the throughput and CPU improvements are understated rather than
inflated. The ratios are load-independent and are the numbers the budget asserts.

### The frame-headroom argument above is now obsolete

The "Why it matters" section argued that `MaxResponseBytes = 256 KiB` could not be
raised, because one chunk occupied 466 KB of the 1 MiB frame. That was true of the
double-encoded frame and is no longer true: a 256 KiB chunk now costs about 800
bytes of overhead, so a 512 KiB chunk would occupy roughly 513 KB of the 1 MiB
frame and leave ample headroom.

The cap is therefore raisable on technical grounds. It is **not** raised here,
because the chunk size is a separate decision with its own trade-offs (per-request
memory, small-request latency, cancellation responsiveness, retry cost on a weak
link) and the PRD defers it to measurement. Recorded so the next reader does not
inherit a constraint that no longer exists.

### Detection gap closed

- `tests/e2e/measure_read.sh` reports CPU, peak RSS, protocol bytes, wall time,
  throughput, platform, Go version and revision for both sides.
- `tests/e2e/check_budget.sh` asserts the ratios, the RSS growth bound and the CPU
  budget, and reports absolute CPU rows as `INCONCLUSIVE` when host load makes them
  incomparable rather than passing them.
- `make measure` runs both, so the check is reachable from a maintained target
  rather than from a script nobody invokes.
- `docs/resource-baseline.md` records the numbers and the regression rule.

### What remains open

- The chunk size is still 256 KiB. Raising it is now possible and is a separate
  measured decision.
- The per-caller admission default of 2 is an unresolved product decision; eight
  concurrent 16 MiB reads serialize into about four waves.
- Absolute CPU figures are only comparable on a host with similar load; the budget
  enforces ratios and bounded properties for that reason.
