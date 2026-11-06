---
maintainer: AI
author: DawsonLin
---

# `logs` latency is dominated by a redundant full provider discovery

## Trigger

Human report (verbatim):

> 我发现cli的logs指令执行很慢，有办法优化吗？

## Observed behavior

`agent-cluster-cli logs <endpoint> <session>` takes 2.1-2.7 s against a healthy local Endpoint, and
`GET /api/v1/output` alone takes 1.9-3.7 s. Reading the log file itself is not the cost.

## Measured breakdown (2026-11-06)

Live cluster: Server `127.0.0.1:53680`, channel `127.0.0.1:53943`, Endpoint `ai-dev` running inside
container `ai-dev`.

| Stage | Elapsed |
|---|---|
| `agent-cluster-cli -json logs ai-dev <res>` end-to-end | 2413 / 2130 / 2727 ms |
| `GET /api/v1/output` (curl, same target) | 2119 / 3717 / 2176 ms |
| `topsailai workspace --format json` (in `ai-dev`) | 1698 / 1660 / 1703 ms |
| `topsailai runtime logs -s SESSION -n 20 --json` (in `ai-dev`) | 691 / 424 / 397 ms |
| Python import of `cli_topsailai.runtime_logs` | 282 ms |
| `resolve_log_target` over 4521 directory entries | 62 ms |
| `read_log_tail(n=20)` on a 6.38 MB stdout | 1 ms |
| `GET /api/v1/endpoints/ai-dev/session-state` | 1.9 ms |

The two provider invocations sum to the observed API latency (1.7 s + 0.4 s = 2.1 s), so channel and
Server overhead are small.

## Root cause

`Executor.ReadOutput` (`internal/endpoint/executor.go`) calls `Adapter.Inspect` before every read to
revalidate the target generation. The TopsailAI adapter implements `Inspect`
(`internal/adapter/topsailai/adapter.go`) by running a full `Discover`, i.e.
`topsailai workspace --format json`, and then scanning the returned sessions for the target.

That discovery is a complete provider history scan. It is 1.7 s in the container and 6.5 s on the
host, and it is executed purely to compare one generation string that the Endpoint already holds in
its own `source_cache` table. Every `logs` request therefore launches two provider CLI subprocesses
where one is sufficient.

## Proposed resolution

Revalidate the generation from the Endpoint's own latest accepted source snapshot instead of a live
discovery:

1. Add a targeted store read (for example `SourceSnapshot(ctx, adapterID)`) that returns the single
   `source_cache` row for the mapped adapter.
2. In `ReadOutput`, look up the resource in that snapshot and compare `Generation`.
3. Fall back to a live `Inspect` only when the cache cannot answer: unknown data, resource absent
   from the snapshot, or a stale snapshot. A cache miss must never be reported as a match.
4. Keep rejecting a genuine mismatch with `generation_mismatch`.

Expected result: one provider CLI launch per read, roughly 0.5-0.9 s end-to-end, inside the 1 s
budget. No periodic stdout polling is introduced, Endpoint stays a controller that only invokes the
adapter CLI, and Server gains no adapter knowledge.

## Prevention

Add a regression test that asserts `ReadOutput` performs no discovery when the cached snapshot
already carries the requested generation, and that it still performs one when the cache is unknown
or the generation differs.

## Resolution (2026-11-06T23:50)

Implemented as proposed. `Store.SourceSnapshot(ctx, adapterID)` was added to
`internal/storage/endpoint/cache.go`, and `Executor.ReadOutput` now calls `revalidateGeneration`,
which trusts only a found, `DataKnown`, non-`Stale` snapshot containing the resource and otherwise
falls back to exactly one live `Inspect`. `generation_mismatch` is unchanged.

Measured on the live local cluster for the same target:

- cache hit: **0.89 s** end-to-end for `agent-cluster-cli -json --lines 20 logs ...`
- forced cache miss (`stale=1`): **18.87 s** for the identical command

The 21x difference is the redundant full discovery that this change removes. The miss path is now
slow because the host `topsailai workspace --format json` grew to 18-34 s as history accumulated,
which is precisely why a read must not run it.

Regression test `TestReadOutputSkipsDiscoveryWhenSnapshotAnswers` covers six cases and counts live
inspections: 0 when the snapshot answers (match and mismatch), 1 when it cannot (stale, unknown data,
resource absent, no row). A negative control confirmed the test fails on the intended assertion when
the fix is reverted.

Related environment defect: the running Server binary predated `parseMaxLines`, so `max_lines` was
dropped and every snapshot returned the adapter's 20-line default. Rebuilding and restarting the
Server made `--lines 5/20/100` return 5/20/100 lines. This was a stale local binary, not a source
defect, and it is worth checking binary freshness before trusting a limit-related measurement.
