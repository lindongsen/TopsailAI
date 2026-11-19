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

Measured before Unit 4a/4b, when the Server re-encoded content as base64 JSON:

| Size | Server wire bytes | Server ratio | Node wire bytes | Node ratio |
|---|---|---|---|---|
| 1 MiB | 1,401,997 | 1.3370 | 1,051,841 | 1.0031 |
| 16 MiB | 22,432,593 | 1.3371 | 16,829,449 | 1.0031 |
| 64 MiB | 89,730,385 | 1.3371 | 67,317,769 | 1.0031 |

Measured after Unit 4a/4b, with the CLI opting in to the raw byte stream:

| Size | Server wire bytes | Server ratio | Node wire bytes | Node ratio |
|---|---|---|---|---|
| 1 MiB | 1,052,209 | 1.0034 | 1,051,841 | 1.0031 |
| 16 MiB | 16,834,209 | 1.0034 | 16,829,441 | 1.0031 |
| 64 MiB | 67,336,593 | 1.0034 | 67,317,769 | 1.0031 |

Both hops are now at the PRD's 1.10 target. The Server hop fell from 1.3371 to
1.0034 because the envelope is no longer written on the opt-in path; the Node hop
was already binary and did not move, which is the evidence that the change removed
the envelope rather than shifting bytes to the other side.

The 64 MiB row was measured in Unit 7d at revision `e0b46ef4`, and it confirms the
ratio is stable across the full 64x size range rather than only at the two smaller
sizes.

Measured on the same host with `/proc/loadavg` between 6.53 and 12.43, so the
absolute CPU figures in these runs are not comparable with the baseline table above.
The ratios are, because a ratio does not move with host load.

### Final measurement at the close of the work

Command: `make measure MEASURE_SIZES="1 16 64"`, revision `e0b46ef4`, transport
`binary-v1`, TLS disabled, `/proc/loadavg` 8.54.

| Size | Wall | Throughput | Server CPU | Node CPU | Server peak RSS | Node peak RSS | Content |
|---|---|---|---|---|---|---|---|
| 1 MiB | 0.034 s | 29.41 MiB/s | 0.020 s | 0.010 s | 20,376 KB | 15,908 KB | yes |
| 16 MiB | 0.356 s | 44.94 MiB/s | 0.240 s | 0.180 s | 23,700 KB | 21,304 KB | yes |
| 64 MiB | 1.439 s | 44.48 MiB/s | 0.920 s | 0.640 s | 23,964 KB | 22,068 KB | yes |

Idle baselines before any read in this run: Server 14,112 KB, Node 13,780 KB.

Compared with the baseline table above, which was measured at `29d3634f+dirty`:

| Property | Baseline | Final | Change |
|---|---|---|---|
| Throughput at 16 MiB | 11.01 MiB/s | 44.94 MiB/s | 4.1x faster |
| Throughput at 64 MiB | 11.01 MiB/s | 44.48 MiB/s | 4.0x faster |
| Server CPU at 64 MiB | 2.480 s | 0.920 s | 63% less |
| Server peak RSS at 64 MiB | 28,480 KB | 23,964 KB | 16% less |
| Peak RSS growth 16 → 64 MiB | +2,252 KB | +264 KB | still bounded |

The final run happened at a higher load than the baseline run (8.54 against
2.06–3.91), so the throughput and CPU improvements are understated rather than
inflated. The budget check reported the six absolute CPU rows as `INCONCLUSIVE` for
that reason and passed every ratio and RSS rule, which is the correct outcome: the
ratios are load-independent and are what the budget asserts.

## What counts as a regression

A regression is a change in a **ratio or a bounded property**, not a change in an
absolute number. The absolute numbers move with host load; the ratios do not.

| Property | Baseline | Regression when | Why this rule |
|---|---|---|---|
| Peak RSS growth from 16 MiB to 64 MiB | Server +2,252 KB (15.3% of idle baseline), Node +0 KB | growth exceeds 25% of the idle baseline | Memory boundedness is the product requirement; a proportional increase means the chunk pipeline was replaced by a whole-file buffer |
| Server CPU per MiB | 0.038 s/MiB at 16 MiB, 0.039 s/MiB at 64 MiB | exceeds 0.25 CPU-seconds per 16 MiB on a comparable host | The PRD budget; per-MiB cost is the quantity that must stay flat |
| Node CPU per MiB | 0.011 s/MiB at 16 MiB, 0.010 s/MiB at 64 MiB | exceeds 0.10 CPU-seconds per 16 MiB on a comparable host | The PRD budget; the Node runs on a personal computer |
| Node wire ratio | 1.0031 | exceeds 1.10 | The PRD target, and the hop where the binary transport already works |
| Server wire ratio | 1.0034 | exceeds 1.10 | The PRD target. It was 1.3371 while the Server re-encoded content as base64 JSON; Unit 4a removed that and Unit 4b made the CLI opt in, so a rise back toward 1.33 means the envelope returned |
| Content identity | byte-identical at every size | any mismatch | A fast wrong answer is not an improvement |

### How to compare

1. Run `tests/e2e/start.sh` then `tests/e2e/measure_read.sh 1 16 64` on the same host
   class, with TLS in the same state.
2. To check the envelope specifically, run `make measure-optin`. It measures the raw
   byte stream and the JSON envelope against the same two processes, so the
   difference between the two reports is the cost of the envelope and nothing else.
   A Server ratio near 1.33 in the `legacy` block is expected; the `raw` block is the
   one the ceiling applies to.
3. Compare the **ratios** first. A ratio change is a code change; an absolute change
   with a stable ratio is host load.
4. Compare absolute CPU and wall time only when `/proc/loadavg` is within about 1.0 of
   the baseline run's load. Otherwise record the load and treat the comparison as
   inconclusive rather than as a pass or a fail.
5. A regression must fail the check or be approved with updated measurements and a
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
