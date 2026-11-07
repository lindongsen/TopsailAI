---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# `refresh` latency is dominated by provider discovery cost and a serial Endpoint fan-out

## Trigger

Human report (verbatim):

> cli 执行 refresh 指令的时候我觉得慢，请分析根因

## Observed behavior

`agent-cluster-cli refresh` in the workspace scope takes 10.5-15.6 s against a healthy cluster, and
`--endpoint ai-dev refresh` takes 3.1-6.6 s. `agent-cluster-cli endpoints`, which performs no forced
collection, takes 8-9 ms, so CLI startup, TLS, authentication and Server reads are not the cost.

## Measured breakdown (2026-11-07)

Live local cluster, Endpoint `ai-dev` local, `local-endpoint` and `topsailai-dev` remote. Provider
history: 4,653 files / 428 MB under `~/.topsailai/workspace/task`.

| Stage | Elapsed |
|---|---|
| `refresh` (workspace scope, 3 Endpoints) | 10493 / 10754 / 11509 ms (earlier 13530-15600 ms) |
| `--endpoint ai-dev refresh` | 3151-6626 ms |
| `--endpoint local-endpoint refresh` | 5839 / 7220 ms |
| `--endpoint topsailai-dev refresh` | 790 / 924 ms |
| `endpoints` (no forced collection) | 8 / 9 / 9 ms |
| `topsailai workspace --format json` (host, 15 items) | 3030 / 3640 / 4500 ms |

Per-Endpoint sums equal the workspace-scope total (3.4 + 5.8 + 0.9 = 10.1 s), so the fan-out is
additive.

`cProfile` of `_print_workspace_json` (3.303 s): `subprocess.communicate` 2.995 s across 17 calls,
`is_process_holding_file` 1.708 s, `is_file_in_use` 1.678 s across 8 calls, `_run_lookup_command`
1.354 s. Stage timings: `discover_workspace_log_files` 0.047 s, `enrich_files_with_session_names`
1.362 s, `_workspace_json_item` loop 1.571 s, `uv` + import 0.53-0.62 s.

Dead-PID liveness probing was the dominant provider defect when this issue was first
measured: 8 dead rows cost **1.413 s** while 7 alive rows cost **0.007 s**, a 200x
difference, and one `refresh` spawned **14 `lsof` + 7 `fuser` = 21 subprocesses**.

**This layer is already fixed.** Commit `6427f977 fix: resolve file holders from the
process table before external tools` (2026-11-07 11:15:50) added `_proc_available` and
`_proc_holds_file` and made `is_file_in_use` consult the process table first. It is an
ancestor of HEAD. Re-measured on 2026-11-07: 20 dead PIDs spawn **0** subprocesses, and
one dead-PID probe costs mean **0.0417 s** (max 0.0520 s over 10 runs, 80 `/proc`
entries). Full discovery is now **1.79-1.91 s** for 10 rows, not 5.42 s.

## Root cause

Two additive layers remain:

1. **Serial Endpoint fan-out.** `forceCollection` (`internal/tui/refresh.go`) awaits each
   `RefreshInventory` before starting the next Endpoint, so workspace scope costs the sum instead of the
   maximum. Endpoints are independent.
2. **Inline collection on the channel read loop.** `publishRefresh`
   (`internal/endpoint/service.go:304`) calls `Collect` inline in `channelLoop`, blocking command,
   receipt, launch, output and heartbeat frames for the whole collection. `Collector.Collect` also has no
   cycle-level mutex (only `apply`/`compose` are guarded), so the 10 s `collectionLoop` and a forced
   refresh can run duplicate provider discovery. The protocol document requires coalescing and cycle
   serialization; the implementation does not provide it.

This is not a timeout: Endpoint collection 30 s, Server `refreshTimeout` 30 s, TUI
`refreshCommandTimeout` 35 s are all above the observed latency. The 409 `not_committed` freshness guard
is not involved; refreshes returned HTTP 200 with fresh `DATA_STATUS` timestamps.

Unlike `issues/done/logs-latency-redundant-discovery.md` and `issues/done/send-latency-redundant-discovery.md`,
`refresh` cannot skip discovery: it exists to produce a new observation, so returning cached data would
make the command a lie.

## Proposed resolution

Ordered by measured benefit and risk:

1. Provider: skip the `lsof`/`fuser` fallback when `/proc/<pid>` is absent on a `/proc`-capable host.
   **DONE** in `6427f977`, which resolves holders from the process table before any external tool.
2. Cluster: parallelize `forceCollection` with a bounded worker pool, preserving per-Endpoint error
   isolation. Not implemented; deferred by the human on 2026-11-07.
3. Cluster: move `publishRefresh` off the channel read loop. Not implemented; same deferral.
4. Cluster: serialize and coalesce `Collect` cycles as the protocol already requires. Not implemented;
   same deferral.
5. Provider: batch liveness probing into one pass. Not implemented. The residual cost is a full `/proc`
   scan per dead row (mean 0.0417 s), which is negligible at the measured scale, so this is not
   recommended without a larger process count.

## Prevention

- Regression test asserting no external tool is spawned when the process table can answer. **DONE** in
  `6427f977`: `test_no_holder_does_not_spawn_a_tool` in
  `cli/tests/unit/topsailai/test_log_file_use.py` asserts `subprocess.Popen` is never called.
- Regression test asserting workspace-scope refresh latency tracks the slowest Endpoint, not the sum.
- Regression test asserting two overlapping refresh requests produce one provider discovery.
- Regression test asserting command and heartbeat frames are served during a forced collection.
- Keep the 409 freshness guard reachable so a "fast" refresh can never silently return cached data.

## Cluster-side design

The cluster-side change details (items 2, 3, 4) are analysed in
`.task/plan_20261107T100228_refresh-cluster-side-change-design.md`, including the verified concurrency
facts, the protocol-permitted single-flight option and why it is unbounded, the arrival-aware coalescing
rule, the `W = 4` bound and its honest scale limitation, the test impact on `refreshStub`, and the
interaction with the in-flight `watch --force` work. That document also records that the 409 guard is
reachable only through a storage commit failure, not through the ordering drop, and that the human
deferred the coalescing change on 2026-11-07.

## Limitations

- The periodic-loop versus forced-refresh overlap is established from code structure, not a reproducible
  process-count measurement; sampling was inconclusive because the provider CLI is a bash → `uv` →
  `python3` chain with a short process lifetime.
- Remote Endpoint numbers include network and remote host load.
- Provider absolute numbers are host-dependent; the earlier container measurement was 1.7 s.

Full analysis: `.task/plan_20261107T092715_refresh-latency-root-cause.md`.
