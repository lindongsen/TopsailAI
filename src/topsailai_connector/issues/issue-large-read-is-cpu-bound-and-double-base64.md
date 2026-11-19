---
maintainer: AI
author: DawsonLin
status: open
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

## Suggested direction

Not decided here, because each option changes the wire contract:

- Carry the payload as `json.RawMessage` instead of `[]byte`, which removes one
  base64 layer and the 1.33x expansion.
- Send the content as a raw binary frame rather than inside JSON, which removes
  both layers.
- Raise `MaxResponseBytes` together with the frame limit, which reduces the number
  of round trips but not the per-byte cost.

## Detection gap

No test measures resource behaviour. The largest fixture anywhere is
`4*capBytes` = 1 MiB (`internal/server/cli/output_test.go:316`), and
`internal/node/fence_test.go:400` uses `MaxResponseBytes+1024`. No test asserts a
wall-time, CPU or RSS bound, and no BDD scenario mentions a large file
(`grep -rn "large\|MiB" tests/bdd/features/*.feature` returns nothing). The suite
therefore cannot observe a throughput regression, which is the class of defect this
issue describes.
