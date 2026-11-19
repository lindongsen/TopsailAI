---
maintainer: AI
author: DawsonLin
status: measured
created: 2026-11-19
updated: 2026-11-19
---

# Resource Baseline and Regression Rule

This document records what one `file.read` actually costs, on a named environment, at
a named revision. It exists so a later run can be compared with this one instead of
with an opinion.

A baseline is not a promise. It is a measurement with its environment attached, and
the environment is part of the number: the same binary on a busier host is slower, and
that difference is not a regression.

## Reference environment

| Property | Value |
|---|---|
| CPU | 11th Gen Intel Core i5-1135G7 @ 2.40 GHz, 8 logical cores |
| Memory | 15.4 GiB |
| Kernel | Linux 5.14.0-1052-oem |
| Go | go1.25.0 linux/amd64 |
| TLS | disabled (`tls=false` on the Server's ready line) |
| Transport | `binary-v1` |
| Revision | `29d3634f+dirty` |

The host is shared. During these measurements `/proc/loadavg` read between 2.06 and
3.91, and an unrelated `qemu-system-x86` process held roughly half of one core. Two
runs of the identical binary differed by 2.3x in throughput. Absolute figures below
are therefore a record of this host at this time, not a portable budget.

## Measured baseline

Command: `tests/e2e/start.sh` then `tests/e2e/measure_read.sh 1 16 64`.

| Size | Wall | Throughput | Server CPU | Node CPU | Server peak RSS | Node peak RSS | Content |
|---|---|---|---|---|---|---|---|
| 1 MiB | 0.157 s | 6.37 MiB/s | 0.070 s | 0.010 s | 22,272 KB | 16,100 KB | yes |
| 16 MiB | 1.453 s | 11.01 MiB/s | 0.610 s | 0.170 s | 26,228 KB | 21,180 KB | yes |
| 64 MiB | 5.812 s | 11.01 MiB/s | 2.480 s | 0.630 s | 28,480 KB | 21,180 KB | yes |

Idle baselines before any read: Server 14,676 KB, Node 13,276 KB.

### Protocol bytes

| Size | Server wire bytes | Server ratio | Node wire bytes | Node ratio |
|---|---|---|---|---|
| 1 MiB | 1,401,997 | 1.3370 | 1,051,841 | 1.0031 |
| 16 MiB | 22,432,593 | 1.3371 | 16,829,449 | 1.0031 |
| 64 MiB | 89,730,385 | 1.3371 | 67,317,769 | 1.0031 |

The Node hop is at the PRD's 1.10 target. The Server hop is not: 1.3371 is the base64
expansion ratio, because the Server still re-encodes content as base64 JSON before
writing the HTTP response. Closing that is Unit 4a, which is deferred behind another
agent's uncommitted changes in `internal/server/cli/`.

## What counts as a regression

A regression is a change in a **ratio or a bounded property**, not a change in an
absolute number. The absolute numbers move with host load; the ratios do not.

| Property | Baseline | Regression when | Why this rule |
|---|---|---|---|
| Peak RSS growth from 16 MiB to 64 MiB | Server +2,252 KB (15.3% of idle baseline), Node +0 KB | growth exceeds 25% of the idle baseline | Memory boundedness is the product requirement; a proportional increase means the chunk pipeline was replaced by a whole-file buffer |
| Server CPU per MiB | 0.038 s/MiB at 16 MiB, 0.039 s/MiB at 64 MiB | exceeds 0.25 CPU-seconds per 16 MiB on a comparable host | The PRD budget; per-MiB cost is the quantity that must stay flat |
| Node CPU per MiB | 0.011 s/MiB at 16 MiB, 0.010 s/MiB at 64 MiB | exceeds 0.10 CPU-seconds per 16 MiB on a comparable host | The PRD budget; the Node runs on a personal computer |
| Node wire ratio | 1.0031 | exceeds 1.10 | The PRD target, and the hop where the binary transport already works |
| Server wire ratio | 1.3371 | exceeds 1.3371 | Recorded as the current known state, not as a target. It must fall to about 1.003 when Unit 4a lands; a rise above 1.3371 is a regression today |
| Content identity | byte-identical at every size | any mismatch | A fast wrong answer is not an improvement |

### How to compare

1. Run `tests/e2e/start.sh` then `tests/e2e/measure_read.sh 1 16 64` on the same host
   class, with TLS in the same state.
2. Compare the **ratios** first. A ratio change is a code change; an absolute change
   with a stable ratio is host load.
3. Compare absolute CPU and wall time only when `/proc/loadavg` is within about 1.0 of
   the baseline run's load. Otherwise record the load and treat the comparison as
   inconclusive rather than as a pass or a fail.
4. A regression must fail the check or be approved with updated measurements and a
   written reason. It must not pass silently because the output was still correct.

## Known gaps in this baseline

- **256 MiB was not measured here.** The PRD's success measure names 256 MiB; this
  baseline stops at 64 MiB because the host is shared and a 256 MiB run takes minutes
  of contended CPU. The 64 MiB figure already shows flat peak RSS across a 64x range,
  which is the property the 256 MiB case is meant to test, but the exact 256 MiB
  number is not recorded and must not be claimed.
- **Windows is not measured.** The harness reads `/proc`, which does not exist there.
  Unit 7a covers the Windows build; a Windows resource baseline needs a different
  measurement source and is not claimed here.
- **TLS is disabled.** TLS adds CPU and bytes on both hops. A TLS baseline is a
  separate measurement.
- **Concurrency is measured separately** and recorded in the Unit 6a evidence file:
  8 concurrent 16 MiB reads took 2.16 s against 0.69 s at 2, because the per-caller
  default of 2 serializes them into about four waves.

## Open decision carried into the next unit

The per-caller default of 2 is a single-caller throughput ceiling. Whether that is the
intended product behaviour or a value to raise is not decided by this document. The
measurement is recorded; the decision needs the product owner.
